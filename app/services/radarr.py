from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from app.db import get_connection, upsert_job_state
from app.services.qbittorrent import normalize_path


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()


class StopRequested(Exception):
    pass


@dataclass(slots=True)
class RadarrEntry:
    source: str
    movie_id: int
    title: str
    year: int | None
    status: str
    movie_path: str
    file_path: str
    queue_id: int | None = None
    tracked_download_status: str = ""
    tracked_download_state: str = ""
    status_messages: list[str] | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": self.source,
            "movie_id": self.movie_id,
            "title": self.title,
            "year": self.year,
            "status": self.status,
            "movie_path": self.movie_path,
            "file_path": self.file_path,
            "tracked_download_status": self.tracked_download_status,
            "tracked_download_state": self.tracked_download_state,
            "status_messages": self.status_messages or [],
        }
        if self.queue_id is not None:
            payload["queue_id"] = self.queue_id
        return payload


def run_radarr_sync(
    database_path: str,
    radarr_url: str,
    radarr_api_key: str,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    job_key = "radarr-sync"
    started_at = _now_iso()
    if not radarr_url or not radarr_api_key:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Radarr sync",
                state="idle",
                progress=100,
                message="Radarr is not configured",
                started_at=started_at,
                preserve_started_at=False,
            )
        return {"matches": 0, "imported": 0, "queue": 0}

    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key=job_key,
            label="Radarr sync",
            state="running",
            progress=5,
            message="Connecting to Radarr",
            started_at=started_at,
            preserve_started_at=False,
        )

    try:
        entries = fetch_radarr_entries(
            radarr_url=radarr_url,
            radarr_api_key=radarr_api_key,
            progress=lambda progress, message: _update_radarr_progress(database_path, progress, message, started_at),
            should_stop=should_stop,
        )
    except StopRequested:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Radarr sync",
                state="cancelled",
                progress=100,
                message="Stopped during Radarr sync",
                started_at=started_at,
            )
        return {"matches": 0, "imported": 0, "queue": 0}

    if should_stop is not None and should_stop():
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Radarr sync",
                state="cancelled",
                progress=100,
                message="Stopped before saving Radarr data",
                started_at=started_at,
            )
        return {"matches": 0, "imported": len([entry for entry in entries if entry.source == "movie"]), "queue": len([entry for entry in entries if entry.source == "queue"])}

    with get_connection(database_path) as connection:
        reset_radarr_data(connection)
        matches = persist_radarr_data(connection, entries)
        imported = len([entry for entry in entries if entry.source == "movie"])
        queued = len([entry for entry in entries if entry.source == "queue"])
        upsert_job_state(
            connection,
            job_key=job_key,
            label="Radarr sync",
            state="done",
            progress=100,
            message=f"Synced {imported} Radarr files, {queued} queue items, matched {matches} files",
            started_at=started_at,
        )
    return {"matches": matches, "imported": imported, "queue": queued}


def fetch_radarr_entries(
    *,
    radarr_url: str,
    radarr_api_key: str,
    progress: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[RadarrEntry]:
    base_url = radarr_url.rstrip("/")
    headers = {"X-Api-Key": radarr_api_key}
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True, headers=headers) as client:
        _raise_if_stop_requested(should_stop)

        if progress is not None:
            progress(15, "Fetching Radarr movies")
        movie_response = client.get("/api/v3/movie")
        movie_response.raise_for_status()
        movie_rows = movie_response.json()

        _raise_if_stop_requested(should_stop)
        if progress is not None:
            progress(55, "Fetching Radarr queue")
        queue_rows = _fetch_radarr_queue_rows(client, should_stop=should_stop)

    entries: list[RadarrEntry] = []
    for movie in movie_rows:
        _raise_if_stop_requested(should_stop)
        entry = _movie_entry_from_payload(dict(movie))
        if entry is not None:
            entries.append(entry)

    for queue_item in queue_rows:
        _raise_if_stop_requested(should_stop)
        entries.extend(_queue_entries_from_payload(dict(queue_item)))

    if progress is not None:
        progress(90, f"Prepared {len(entries)} Radarr file entries")
    return entries


def persist_radarr_data(connection, entries: list[RadarrEntry]) -> int:
    matches_by_location: dict[int, list[dict[str, object]]] = {}
    locations = connection.execute("SELECT id, path FROM file_locations").fetchall()
    location_by_path = {normalize_path(str(row["path"])): int(row["id"]) for row in locations}

    for entry in entries:
        location_id = location_by_path.get(normalize_path(entry.file_path))
        if location_id is None:
            continue
        matches_by_location.setdefault(location_id, []).append(entry.as_payload())

    for location_id, items in matches_by_location.items():
        connection.execute(
            "UPDATE file_locations SET radarr_json = ? WHERE id = ?",
            (json.dumps({"items": items}), location_id),
        )

    return len(matches_by_location)


def reset_radarr_data(connection) -> None:
    connection.execute("UPDATE file_locations SET radarr_json = '{}'")


def _fetch_radarr_queue_rows(client: httpx.Client, *, should_stop: Callable[[], bool] | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    page_size = 250
    while True:
        _raise_if_stop_requested(should_stop)
        response = client.get("/api/v3/queue/details", params={"page": page, "pageSize": page_size})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            page_rows = [dict(item) for item in payload.get("records", [])]
        else:
            page_rows = [dict(item) for item in payload]
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        page += 1
    return rows


def _movie_entry_from_payload(movie: dict[str, object]) -> RadarrEntry | None:
    movie_file = movie.get("movieFile")
    if not isinstance(movie_file, dict):
        return None
    movie_path = str(movie.get("path") or "")
    file_path = _extract_file_path(movie_file, base_path=movie_path)
    if not file_path:
        return None
    return RadarrEntry(
        source="movie",
        movie_id=int(movie.get("id") or 0),
        title=str(movie.get("title") or ""),
        year=_to_optional_int(movie.get("year")),
        status=str(movie.get("status") or ""),
        movie_path=movie_path,
        file_path=file_path,
    )


def _queue_entries_from_payload(queue_item: dict[str, object]) -> list[RadarrEntry]:
    movie = queue_item.get("movie") if isinstance(queue_item.get("movie"), dict) else {}
    movie_path = str(movie.get("path") or queue_item.get("moviePath") or "")
    file_paths = _queue_file_paths(queue_item, movie_path)
    if not file_paths:
        return []

    status_messages = _extract_status_messages(queue_item.get("statusMessages"))
    title = str(movie.get("title") or queue_item.get("title") or "")
    year = _to_optional_int(movie.get("year") or queue_item.get("year"))
    status = str(queue_item.get("status") or queue_item.get("trackedDownloadState") or queue_item.get("trackedDownloadStatus") or "")

    return [
        RadarrEntry(
            source="queue",
            movie_id=int(movie.get("id") or queue_item.get("movieId") or 0),
            title=title,
            year=year,
            status=status,
            movie_path=movie_path,
            file_path=file_path,
            queue_id=_to_optional_int(queue_item.get("id")),
            tracked_download_status=str(queue_item.get("trackedDownloadStatus") or ""),
            tracked_download_state=str(queue_item.get("trackedDownloadState") or ""),
            status_messages=status_messages,
        )
        for file_path in file_paths
    ]


def _queue_file_paths(queue_item: dict[str, object], movie_path: str) -> list[str]:
    candidates: list[str] = []
    for key in ("outputPath", "downloadPath", "path"):
        value = queue_item.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)

    movie_file = queue_item.get("movieFile") if isinstance(queue_item.get("movieFile"), dict) else None
    if movie_file:
        movie_file_path = _extract_file_path(movie_file, base_path=movie_path)
        if movie_file_path:
            candidates.append(movie_file_path)

    queue_files = queue_item.get("queueFiles")
    if isinstance(queue_files, list):
        for queue_file in queue_files:
            if not isinstance(queue_file, dict):
                continue
            queue_file_path = _extract_file_path(queue_file, base_path=movie_path)
            if queue_file_path:
                candidates.append(queue_file_path)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_path(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def _extract_file_path(payload: dict[str, object], *, base_path: str = "") -> str:
    direct_path = payload.get("path")
    if isinstance(direct_path, str) and direct_path.strip():
        return direct_path

    relative_path = payload.get("relativePath")
    if isinstance(relative_path, str) and relative_path.strip() and base_path:
        return str((Path(base_path) / relative_path).resolve(strict=False))
    return ""


def _extract_status_messages(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            messages.append(item)
            continue
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        text = str(item.get("messages") or item.get("message") or "").strip()
        combined = ": ".join(part for part in (title, text) if part)
        if combined:
            messages.append(combined)
    return messages


def _to_optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _update_radarr_progress(database_path: str, progress: int, message: str, started_at: str | None = None) -> None:
    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key="radarr-sync",
            label="Radarr sync",
            state="running",
            progress=progress,
            message=message,
            started_at=started_at,
        )


def _raise_if_stop_requested(should_stop: Callable[[], bool] | None) -> None:
    if should_stop is not None and should_stop():
        raise StopRequested()
