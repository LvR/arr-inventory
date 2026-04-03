from __future__ import annotations

import os
from threading import Event
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from datetime import datetime, timezone

from app.db import ensure_job_state, get_connection, reset_inventory, reset_job_states, set_inventory_meta, upsert_job_state
from app.services.consistency import run_consistency_checks_with_stop
from app.services.qbittorrent import run_qbittorrent_sync
from app.services.radarr import run_radarr_sync
from app.services.sonarr import run_sonarr_sync


ROOT_BUCKETS = {
    "downloads": "downloads",
    "movies": "movies",
    "tv": "tv",
    "music": "music",
}

STOP_EVENTS: dict[str, Event] = {}


@dataclass(slots=True)
class FileRecord:
    root_bucket: str
    path: str
    filename: str
    device: int
    inode: int
    size_bytes: int
    hardlink_count: int

    @property
    def group_key(self) -> str:
        return f"{self.device}:{self.inode}"


@dataclass(slots=True)
class ScanRoots:
    downloads: Path
    movies: Path
    tv: Path
    music: Path


def _iter_files(root: Path) -> Iterable[Path]:
    for current_root, _, filenames in os.walk(root):
        base = Path(current_root)
        for filename in filenames:
            yield base / filename


def _resolve_scan_root(data_root: Path, configured_path: str) -> Path:
    candidate = Path(configured_path)
    if candidate.is_absolute():
        return candidate
    return data_root / candidate


def _build_scan_roots(data_root: Path, downloads_path: str, movies_path: str, tv_path: str) -> ScanRoots:
    return ScanRoots(
        downloads=_resolve_scan_root(data_root, downloads_path),
        movies=_resolve_scan_root(data_root, movies_path),
        tv=_resolve_scan_root(data_root, tv_path),
        music=data_root / "media" / "music",
    )


def _bucket_for_path(path: Path, scan_roots: ScanRoots) -> str | None:
    for bucket, root in (
        (ROOT_BUCKETS["downloads"], scan_roots.downloads),
        (ROOT_BUCKETS["movies"], scan_roots.movies),
        (ROOT_BUCKETS["tv"], scan_roots.tv),
        (ROOT_BUCKETS["music"], scan_roots.music),
    ):
        try:
            path.relative_to(root)
            return bucket
        except ValueError:
            continue
    return None


def scan_filesystem(
    data_root: str,
    downloads_path: str | None = None,
    movies_path: str | None = None,
    tv_path: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[FileRecord]:
    root = Path(data_root)
    scan_roots = _build_scan_roots(
        root,
        downloads_path or str(root / "downloads"),
        movies_path or str(root / "media" / "movies"),
        tv_path or str(root / "media" / "tv"),
    )
    candidates = [path for path in _iter_files(root) if path.is_file()]
    total = len(candidates)
    records: list[FileRecord] = []

    for index, file_path in enumerate(candidates, start=1):
        if should_stop is not None and should_stop():
            break
        bucket = _bucket_for_path(file_path, scan_roots)
        if bucket is None:
            if progress is not None:
                progress(index, total, str(file_path))
            continue

        stat_result = file_path.stat()
        records.append(
            FileRecord(
                root_bucket=bucket,
                path=str(file_path),
                filename=file_path.name,
                device=stat_result.st_dev,
                inode=stat_result.st_ino,
                size_bytes=stat_result.st_size,
                hardlink_count=stat_result.st_nlink,
            )
        )
        if progress is not None:
            progress(index, total, str(file_path))

    return records


def persist_inventory(connection, records: list[FileRecord]) -> None:
    reset_inventory(connection)

    grouped: dict[str, list[FileRecord]] = {}
    for record in records:
        grouped.setdefault(record.group_key, []).append(record)

    for group_key, group_records in grouped.items():
        leader = group_records[0]
        cursor = connection.execute(
            """
            INSERT INTO file_groups (group_key, device, inode, size_bytes, hardlink_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(group_key) DO UPDATE SET
                device = excluded.device,
                inode = excluded.inode,
                size_bytes = excluded.size_bytes,
                hardlink_count = excluded.hardlink_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                group_key,
                leader.device,
                leader.inode,
                leader.size_bytes,
                leader.hardlink_count,
            ),
        )
        group_id = cursor.lastrowid or connection.execute(
            "SELECT id FROM file_groups WHERE group_key = ?", (group_key,)
        ).fetchone()[0]

        for record in group_records:
            connection.execute(
                """
                INSERT INTO file_locations (group_id, root_bucket, path, filename)
                VALUES (?, ?, ?, ?)
                """,
                (group_id, record.root_bucket, record.path, record.filename),
            )

    set_inventory_meta(connection, "last_inventory_at", datetime.now(tz=timezone.utc).isoformat())


def run_filesystem_scan(
    database_path: str,
    data_root: str,
    *,
    downloads_path: str | None = None,
    movies_path: str | None = None,
    tv_path: str | None = None,
) -> dict[str, int]:
    now = datetime.now(tz=timezone.utc).isoformat()
    with get_connection(database_path) as connection:
        ensure_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="queued",
            progress=0,
            message="Waiting to scan filesystem",
        )
        upsert_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="running",
            progress=5,
            message=f"Scanning {data_root}",
            started_at=now,
        )

        def report_progress(processed: int, total: int, current_path: str) -> None:
            percent = 5 if total == 0 else min(95, 5 + int((processed / total) * 90))
            upsert_job_state(
                connection,
                job_key="filesystem-scan",
                label="Filesystem scan",
                state="running",
                progress=percent,
                message=f"{processed}/{total} files - {current_path}",
                started_at=now,
            )

        stop_event = _get_stop_event(database_path)
        records = scan_filesystem(
            data_root,
            downloads_path=downloads_path,
            movies_path=movies_path,
            tv_path=tv_path,
            progress=report_progress,
            should_stop=stop_event.is_set,
        )
        persist_inventory(connection, records)

        if stop_event.is_set():
            upsert_job_state(
                connection,
                job_key="filesystem-scan",
                label="Filesystem scan",
                state="cancelled",
                progress=100,
                message=f"Stopped after indexing {len(records)} files",
                started_at=now,
            )
            return {
                "files": len(records),
                "groups": len({record.group_key for record in records}),
            }

        upsert_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="done",
            progress=100,
            message=f"Indexed {len(records)} files",
            started_at=now,
        )
    return {
        "files": len(records),
        "groups": len({record.group_key for record in records}),
    }


def run_inventory_pipeline(
    database_path: str,
    data_root: str,
    qbittorrent_url: str,
    qbittorrent_username: str,
    qbittorrent_password: str,
    radarr_url: str,
    radarr_api_key: str,
    sonarr_url: str,
    sonarr_api_key: str,
    torrent_min_seed_time_days: float,
    torrent_min_ratio: float,
    *,
    downloads_path: str | None = None,
    movies_path: str | None = None,
    tv_path: str | None = None,
) -> dict[str, int]:
    stop_event = _get_stop_event(database_path)
    stop_event.clear()

    try:
        with get_connection(database_path) as connection:
            ensure_job_state(
                connection,
                job_key="qbittorrent-sync",
                label="qBittorrent sync",
                state="queued",
                progress=0,
                message="Waiting for filesystem scan",
            )
            ensure_job_state(
                connection,
                job_key="sonarr-sync",
                label="Sonarr sync",
                state="queued",
                progress=0,
                message="Waiting for Radarr sync",
            )
            ensure_job_state(
                connection,
                job_key="consistency-check",
                label="Consistency check",
                state="queued",
                progress=0,
                message="Waiting for Sonarr sync",
            )
            ensure_job_state(
                connection,
                job_key="radarr-sync",
                label="Radarr sync",
                state="queued",
                progress=0,
                message="Waiting for qBittorrent sync",
            )

        fs_result = run_filesystem_scan(
            database_path,
            data_root,
            downloads_path=downloads_path,
            movies_path=movies_path,
            tv_path=tv_path,
        )

        with get_connection(database_path) as connection:
            if stop_event.is_set():
                upsert_job_state(
                    connection,
                    job_key="qbittorrent-sync",
                    label="qBittorrent sync",
                    state="cancelled",
                    progress=100,
                    message="Stopped before qBittorrent sync",
                    preserve_started_at=True,
                )
                upsert_job_state(
                    connection,
                    job_key="radarr-sync",
                    label="Radarr sync",
                    state="cancelled",
                    progress=100,
                    message="Stopped before Radarr sync",
                    preserve_started_at=True,
                )
                upsert_job_state(
                    connection,
                    job_key="sonarr-sync",
                    label="Sonarr sync",
                    state="cancelled",
                    progress=100,
                    message="Stopped before Sonarr sync",
                    preserve_started_at=True,
                )
                upsert_job_state(
                    connection,
                    job_key="consistency-check",
                    label="Consistency check",
                    state="cancelled",
                    progress=100,
                    message="Stopped before consistency check",
                    preserve_started_at=True,
                )
                return {
                    "files": fs_result["files"],
                    "groups": fs_result["groups"],
                    "torrents": 0,
                    "matches": 0,
                    "radarr_matches": 0,
                    "sonarr_matches": 0,
                    "groups_with_issues": 0,
                }

        qb_result = run_qbittorrent_sync(
            database_path,
            qbittorrent_url,
            qbittorrent_username,
            qbittorrent_password,
            should_stop=stop_event.is_set,
        )

        with get_connection(database_path) as connection:
            if stop_event.is_set():
                upsert_job_state(
                    connection,
                    job_key="radarr-sync",
                    label="Radarr sync",
                    state="cancelled",
                    progress=100,
                    message="Stopped before Radarr sync",
                    preserve_started_at=True,
                )
                upsert_job_state(
                    connection,
                    job_key="consistency-check",
                    label="Consistency check",
                    state="cancelled",
                    progress=100,
                    message="Stopped before consistency check",
                    preserve_started_at=True,
                )
                return {
                    "files": fs_result["files"],
                    "groups": fs_result["groups"],
                    "torrents": qb_result["torrents"],
                    "matches": qb_result["matches"],
                    "radarr_matches": 0,
                    "sonarr_matches": 0,
                    "groups_with_issues": 0,
                }

        radarr_result = run_radarr_sync(
            database_path,
            radarr_url,
            radarr_api_key,
            should_stop=stop_event.is_set,
        )

        with get_connection(database_path) as connection:
            if stop_event.is_set():
                upsert_job_state(
                    connection,
                    job_key="sonarr-sync",
                    label="Sonarr sync",
                    state="cancelled",
                    progress=100,
                    message="Stopped before Sonarr sync",
                    preserve_started_at=True,
                )
                upsert_job_state(
                    connection,
                    job_key="consistency-check",
                    label="Consistency check",
                    state="cancelled",
                    progress=100,
                    message="Stopped before consistency check",
                    preserve_started_at=True,
                )
                return {
                    "files": fs_result["files"],
                    "groups": fs_result["groups"],
                    "torrents": qb_result["torrents"],
                    "matches": qb_result["matches"],
                    "radarr_matches": radarr_result["matches"],
                    "sonarr_matches": 0,
                    "groups_with_issues": 0,
                }

        sonarr_result = run_sonarr_sync(
            database_path,
            sonarr_url,
            sonarr_api_key,
            should_stop=stop_event.is_set,
        )

        with get_connection(database_path) as connection:
            if stop_event.is_set():
                upsert_job_state(
                    connection,
                    job_key="consistency-check",
                    label="Consistency check",
                    state="cancelled",
                    progress=100,
                    message="Stopped before consistency check",
                    preserve_started_at=True,
                )
                return {
                    "files": fs_result["files"],
                    "groups": fs_result["groups"],
                    "torrents": qb_result["torrents"],
                    "matches": qb_result["matches"],
                    "radarr_matches": radarr_result["matches"],
                    "sonarr_matches": sonarr_result["matches"],
                    "groups_with_issues": 0,
                }

        consistency_result = run_consistency_checks_with_stop(
            database_path,
            should_stop=stop_event.is_set,
            torrent_min_seed_time_days=torrent_min_seed_time_days,
            torrent_min_ratio=torrent_min_ratio,
        )
        return {
            "files": fs_result["files"],
            "groups": fs_result["groups"],
            "torrents": qb_result["torrents"],
            "matches": qb_result["matches"],
            "radarr_matches": radarr_result["matches"],
            "sonarr_matches": sonarr_result["matches"],
            "groups_with_issues": consistency_result["groups_with_issues"],
        }
    finally:
        stop_event.clear()


def request_stop(database_path: str) -> None:
    _get_stop_event(database_path).set()
    with get_connection(database_path) as connection:
        for job_key, label in (("filesystem-scan", "Filesystem scan"), ("qbittorrent-sync", "qBittorrent sync"), ("radarr-sync", "Radarr sync"), ("sonarr-sync", "Sonarr sync"), ("consistency-check", "Consistency check")):
            row = connection.execute("SELECT state FROM job_states WHERE job_key = ?", (job_key,)).fetchone()
            if row and row["state"] in {"queued", "running"}:
                upsert_job_state(
                    connection,
                    job_key=job_key,
                    label=label,
                    state="running",
                    progress=99,
                    message="Stop requested...",
                    preserve_started_at=True,
                )


def purge_inventory(database_path: str) -> None:
    _get_stop_event(database_path).clear()
    with get_connection(database_path) as connection:
        reset_inventory(connection)
        reset_job_states(connection)
        set_inventory_meta(connection, "last_inventory_at", "")


def _get_stop_event(database_path: str) -> Event:
    if database_path not in STOP_EVENTS:
        STOP_EVENTS[database_path] = Event()
    return STOP_EVENTS[database_path]
