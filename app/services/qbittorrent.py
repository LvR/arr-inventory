from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from app.db import get_connection, upsert_job_state


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()


class StopRequested(Exception):
    pass


@dataclass(slots=True)
class TorrentFile:
    file_index: int
    file_path: str
    file_name: str
    size_bytes: int
    priority: int
    progress: float
    raw_json: dict[str, object]


@dataclass(slots=True)
class TorrentTracker:
    url: str
    status: str
    message: str


@dataclass(slots=True)
class TorrentRecord:
    torrent_hash: str
    name: str
    status: str
    category: str
    tags: str
    total_uploaded: int
    total_downloaded: int
    ratio: float
    seed_time: int
    save_path: str
    files: list[TorrentFile]
    trackers: list[TorrentTracker]
    raw_json: dict[str, object]


def run_qbittorrent_sync(
    database_path: str,
    qbittorrent_url: str,
    qbittorrent_username: str,
    qbittorrent_password: str,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    job_key = "qbittorrent-sync"
    started_at = _now_iso()
    if not qbittorrent_url:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="qBittorrent sync",
                state="idle",
                progress=100,
                message="qBittorrent is not configured",
                started_at=started_at,
                preserve_started_at=False,
            )
        return {"torrents": 0, "matches": 0}

    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key=job_key,
            label="qBittorrent sync",
            state="running",
            progress=5,
            message="Connecting to qBittorrent",
            started_at=started_at,
            preserve_started_at=False,
        )

    try:
        torrents = fetch_qbittorrent_data(
            qbittorrent_url=qbittorrent_url,
            qbittorrent_username=qbittorrent_username,
            qbittorrent_password=qbittorrent_password,
            progress=lambda progress, message: _update_qb_progress(database_path, progress, message, started_at),
            should_stop=should_stop,
        )
    except StopRequested:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="qBittorrent sync",
                state="cancelled",
                progress=100,
                message="Stopped during qBittorrent sync",
                started_at=started_at,
            )
        return {"torrents": 0, "matches": 0}

    if should_stop is not None and should_stop():
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="qBittorrent sync",
                state="cancelled",
                progress=100,
                message="Stopped before saving qBittorrent data",
                started_at=started_at,
            )
        return {"torrents": 0, "matches": 0}

    with get_connection(database_path) as connection:
        reset_qbittorrent_data(connection)
        matches = persist_qbittorrent_data(connection, torrents)
        upsert_job_state(
            connection,
            job_key=job_key,
            label="qBittorrent sync",
            state="done",
            progress=100,
            message=f"Synced {len(torrents)} torrents and matched {matches} files",
            started_at=started_at,
        )
    return {"torrents": len(torrents), "matches": matches}


def fetch_qbittorrent_data(
    *,
    qbittorrent_url: str,
    qbittorrent_username: str,
    qbittorrent_password: str,
    progress: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[TorrentRecord]:
    base_url = qbittorrent_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True) as client:
        _raise_if_stop_requested(should_stop)
        response = client.post(
            "/api/v2/auth/login",
            data={"username": qbittorrent_username, "password": qbittorrent_password},
        )
        response.raise_for_status()
        if response.text.strip() != "Ok.":
            raise RuntimeError("Unable to authenticate with qBittorrent")

        torrents_response = client.get("/api/v2/torrents/info")
        torrents_response.raise_for_status()
        torrent_rows = torrents_response.json()

        records: list[TorrentRecord] = []
        total = len(torrent_rows)
        for index, row in enumerate(torrent_rows, start=1):
            _raise_if_stop_requested(should_stop)
            torrent_hash = str(row.get("hash", ""))
            if progress is not None:
                progress(max(10, min(85, 10 + int((index / max(total, 1)) * 70))), f"Fetching qBittorrent metadata {index}/{total}")

            files_response = client.get("/api/v2/torrents/files", params={"hash": torrent_hash})
            files_response.raise_for_status()
            tracker_response = client.get("/api/v2/torrents/trackers", params={"hash": torrent_hash})
            tracker_response.raise_for_status()

            save_path = str(row.get("save_path", ""))
            content_path = str(row.get("content_path", ""))
            base_path = _resolve_torrent_base_path(save_path, content_path, str(row.get("name", "")))

            files = [
                TorrentFile(
                    file_index=index_value,
                    file_path=_build_torrent_file_path(base_path, str(file_row.get("name", ""))),
                    file_name=Path(str(file_row.get("name", ""))).name,
                    size_bytes=int(file_row.get("size", 0) or 0),
                    priority=int(file_row.get("priority", 0) or 0),
                    progress=float(file_row.get("progress", 0) or 0),
                    raw_json=dict(file_row),
                )
                for index_value, file_row in enumerate(files_response.json())
            ]
            trackers = [
                TorrentTracker(
                    url=str(tracker.get("url", "")),
                    status=str(tracker.get("status", "")),
                    message=str(tracker.get("msg", "")),
                )
                for tracker in tracker_response.json()
            ]

            records.append(
                TorrentRecord(
                    torrent_hash=torrent_hash,
                    name=str(row.get("name", "")),
                    status=str(row.get("state", "")),
                    category=str(row.get("category", "")),
                    tags=str(row.get("tags", "")),
                    total_uploaded=int(row.get("uploaded", 0) or 0),
                    total_downloaded=int(row.get("downloaded", 0) or 0),
                    ratio=float(row.get("ratio", 0) or 0),
                    seed_time=int(row.get("seeding_time", 0) or 0),
                    save_path=save_path,
                    files=files,
                    trackers=trackers,
                    raw_json=dict(row),
                )
            )
            _raise_if_stop_requested(should_stop)
        return records


def persist_qbittorrent_data(connection, torrents: list[TorrentRecord]) -> int:
    matches = 0
    locations = connection.execute("SELECT id, path FROM file_locations").fetchall()
    location_by_path = {normalize_path(str(row["path"])): int(row["id"]) for row in locations}

    for torrent in torrents:
        connection.execute(
            """
            INSERT INTO qb_torrents (
                hash, name, status, category, tags, total_uploaded, total_downloaded, ratio, seed_time, save_path, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                torrent.torrent_hash,
                torrent.name,
                torrent.status,
                torrent.category,
                torrent.tags,
                torrent.total_uploaded,
                torrent.total_downloaded,
                torrent.ratio,
                torrent.seed_time,
                torrent.save_path,
                json.dumps(torrent.raw_json),
            ),
        )

        for tracker in torrent.trackers:
            connection.execute(
                """
                INSERT INTO qb_torrent_trackers (torrent_hash, url, status, message)
                VALUES (?, ?, ?, ?)
                """,
                (torrent.torrent_hash, tracker.url, tracker.status, tracker.message),
            )

        for torrent_file in torrent.files:
            cursor = connection.execute(
                """
                INSERT INTO qb_torrent_files (
                    torrent_hash, file_index, file_path, file_name, size_bytes, priority, progress, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    torrent.torrent_hash,
                    torrent_file.file_index,
                    torrent_file.file_path,
                    torrent_file.file_name,
                    torrent_file.size_bytes,
                    torrent_file.priority,
                    torrent_file.progress,
                    json.dumps(torrent_file.raw_json),
                ),
            )
            torrent_file_id = cursor.lastrowid
            location_id = location_by_path.get(normalize_path(torrent_file.file_path))
            if location_id is None:
                continue
            matches += 1
            connection.execute(
                """
                INSERT INTO qb_file_matches (location_id, torrent_hash, torrent_file_id)
                VALUES (?, ?, ?)
                """,
                (location_id, torrent.torrent_hash, torrent_file_id),
            )
            connection.execute(
                """
                UPDATE file_locations
                SET source = 'qbittorrent', torrent_name = ?, qbittorrent_json = ?
                WHERE id = ?
                """,
                (
                    torrent.name,
                    json.dumps(
                        {
                            "hash": torrent.torrent_hash,
                            "status": torrent.status,
                            "category": torrent.category,
                            "tags": torrent.tags,
                        }
                    ),
                    location_id,
                ),
            )

    return matches


def reset_qbittorrent_data(connection) -> None:
    connection.execute("DELETE FROM qb_file_matches")
    connection.execute("DELETE FROM qb_torrent_files")
    connection.execute("DELETE FROM qb_torrent_trackers")
    connection.execute("DELETE FROM qb_torrents")
    connection.execute(
        "UPDATE file_locations SET source = '', torrent_name = '', qbittorrent_json = '{}'"
    )


def _update_qb_progress(database_path: str, progress: int, message: str, started_at: str | None = None) -> None:
    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key="qbittorrent-sync",
            label="qBittorrent sync",
            state="running",
            progress=progress,
            message=message,
            started_at=started_at,
        )


def _resolve_torrent_base_path(save_path: str, content_path: str, torrent_name: str) -> str:
    if content_path:
        content = Path(content_path)
        if content.name == torrent_name:
            return str(content.parent)
        if content.suffix:
            return str(content.parent)
        if content.is_absolute():
            return str(content)
    return save_path.rstrip("/")


def _build_torrent_file_path(base_path: str, relative_path: str) -> str:
    if not relative_path:
        return base_path
    return str((Path(base_path) / relative_path).resolve(strict=False))


def normalize_path(value: str) -> str:
    normalized = os.path.normpath(value.strip())
    return normalized.rstrip("/") if normalized != "/" else normalized


def _raise_if_stop_requested(should_stop: Callable[[], bool] | None) -> None:
    if should_stop is not None and should_stop():
        raise StopRequested()
