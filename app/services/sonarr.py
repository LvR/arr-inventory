from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from app.db import get_connection, upsert_job_state
from app.services.qbittorrent import normalize_path
from app.services.radarr import StopRequested, _extract_status_messages, _raise_if_stop_requested, _to_optional_int


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(slots=True)
class SonarrEntry:
    source: str
    series_id: int
    series_title: str
    season_number: int | None
    episode_numbers: list[int]
    status: str
    series_path: str
    file_path: str
    queue_id: int | None = None
    tracked_download_status: str = ""
    tracked_download_state: str = ""
    status_messages: list[str] | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source": self.source,
            "series_id": self.series_id,
            "series_title": self.series_title,
            "season_number": self.season_number,
            "episode_numbers": self.episode_numbers,
            "status": self.status,
            "series_path": self.series_path,
            "file_path": self.file_path,
            "tracked_download_status": self.tracked_download_status,
            "tracked_download_state": self.tracked_download_state,
            "status_messages": self.status_messages or [],
        }
        if self.queue_id is not None:
            payload["queue_id"] = self.queue_id
        return payload


def run_sonarr_sync(
    database_path: str,
    sonarr_url: str,
    sonarr_api_key: str,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    job_key = "sonarr-sync"
    started_at = _now_iso()
    if not sonarr_url or not sonarr_api_key:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Sonarr sync",
                state="idle",
                progress=100,
                message="Sonarr is not configured",
                started_at=started_at,
                preserve_started_at=False,
            )
        return {"matches": 0, "imported": 0, "queue": 0}

    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key=job_key,
            label="Sonarr sync",
            state="running",
            progress=5,
            message="Connecting to Sonarr",
            started_at=started_at,
            preserve_started_at=False,
        )

    try:
        entries = fetch_sonarr_entries(
            sonarr_url=sonarr_url,
            sonarr_api_key=sonarr_api_key,
            progress=lambda progress, message: _update_sonarr_progress(database_path, progress, message, started_at),
            should_stop=should_stop,
        )
    except StopRequested:
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Sonarr sync",
                state="cancelled",
                progress=100,
                message="Stopped during Sonarr sync",
                started_at=started_at,
            )
        return {"matches": 0, "imported": 0, "queue": 0}

    imported = len([entry for entry in entries if entry.source == "episode"])
    queued = len([entry for entry in entries if entry.source == "queue"])
    if should_stop is not None and should_stop():
        with get_connection(database_path) as connection:
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Sonarr sync",
                state="cancelled",
                progress=100,
                message="Stopped before saving Sonarr data",
                started_at=started_at,
            )
        return {"matches": 0, "imported": imported, "queue": queued}

    with get_connection(database_path) as connection:
        reset_sonarr_data(connection)
        matches = persist_sonarr_data(connection, entries)
        upsert_job_state(
            connection,
            job_key=job_key,
            label="Sonarr sync",
            state="done",
            progress=100,
            message=f"Synced {imported} Sonarr files, {queued} queue items, matched {matches} files",
            started_at=started_at,
        )
    return {"matches": matches, "imported": imported, "queue": queued}


def fetch_sonarr_entries(
    *,
    sonarr_url: str,
    sonarr_api_key: str,
    progress: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> list[SonarrEntry]:
    base_url = sonarr_url.rstrip("/")
    headers = {"X-Api-Key": sonarr_api_key}
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True, headers=headers) as client:
        _raise_if_stop_requested(should_stop)
        if progress is not None:
            progress(15, "Fetching Sonarr series")
        series_response = client.get("/api/v3/series")
        series_response.raise_for_status()
        series_rows = series_response.json()

        entries: list[SonarrEntry] = []
        for series in series_rows:
            _raise_if_stop_requested(should_stop)
            series_id = int(series.get("id") or 0)
            series_path = str(series.get("path") or "")
            series_title = str(series.get("title") or "")
            episode_files_response = client.get("/api/v3/episodefile", params={"seriesId": series_id})
            episode_files_response.raise_for_status()
            episode_files = episode_files_response.json()
            episode_map = _fetch_episode_map(client, series_id)
            for episode_file in episode_files:
                entry = _episode_entry_from_payload(series_title, series_path, dict(episode_file), episode_map)
                if entry is not None:
                    entries.append(entry)

        _raise_if_stop_requested(should_stop)
        if progress is not None:
            progress(60, "Fetching Sonarr queue")
        queue_rows = _fetch_sonarr_queue_rows(client, should_stop=should_stop)

    for queue_item in queue_rows:
        _raise_if_stop_requested(should_stop)
        entries.extend(_queue_entries_from_payload(dict(queue_item)))

    if progress is not None:
        progress(90, f"Prepared {len(entries)} Sonarr file entries")
    return entries


def persist_sonarr_data(connection, entries: list[SonarrEntry]) -> int:
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
            "UPDATE file_locations SET sonarr_json = ? WHERE id = ?",
            (json.dumps({"items": items}), location_id),
        )

    return len(matches_by_location)


def reset_sonarr_data(connection) -> None:
    connection.execute("UPDATE file_locations SET sonarr_json = '{}'")


def _fetch_episode_map(client: httpx.Client, series_id: int) -> dict[int, dict[str, object]]:
    response = client.get("/api/v3/episode", params={"seriesId": series_id})
    response.raise_for_status()
    return {int(item.get("id") or 0): dict(item) for item in response.json() if isinstance(item, dict)}


def _fetch_sonarr_queue_rows(client: httpx.Client, *, should_stop: Callable[[], bool] | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    page_size = 250
    while True:
        _raise_if_stop_requested(should_stop)
        response = client.get("/api/v3/queue/details", params={"page": page, "pageSize": page_size})
        response.raise_for_status()
        payload = response.json()
        page_rows = [dict(item) for item in payload.get("records", [])] if isinstance(payload, dict) else [dict(item) for item in payload]
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
        page += 1
    return rows


def _episode_entry_from_payload(
    series_title: str,
    series_path: str,
    episode_file: dict[str, object],
    episode_map: dict[int, dict[str, object]],
) -> SonarrEntry | None:
    file_path = _extract_file_path(episode_file, base_path=series_path)
    if not file_path:
        return None
    season_number, episode_numbers = _episode_numbers_for_file(episode_file, episode_map)
    return SonarrEntry(
        source="episode",
        series_id=int(episode_file.get("seriesId") or 0),
        series_title=series_title,
        season_number=season_number,
        episode_numbers=episode_numbers,
        status=str(episode_file.get("qualityCutoffNotMet") or "imported"),
        series_path=series_path,
        file_path=file_path,
    )


def _queue_entries_from_payload(queue_item: dict[str, object]) -> list[SonarrEntry]:
    series = queue_item.get("series") if isinstance(queue_item.get("series"), dict) else {}
    series_path = str(series.get("path") or queue_item.get("seriesPath") or "")
    file_paths = _queue_file_paths(queue_item, series_path)
    if not file_paths:
        return []
    season_number = _to_optional_int(queue_item.get("seasonNumber"))
    episode_numbers = _extract_episode_numbers(queue_item.get("episodeIds"), queue_item.get("episode"))
    status_messages = _extract_status_messages(queue_item.get("statusMessages"))
    status = str(queue_item.get("status") or queue_item.get("trackedDownloadState") or queue_item.get("trackedDownloadStatus") or "")
    return [
        SonarrEntry(
            source="queue",
            series_id=int(series.get("id") or queue_item.get("seriesId") or 0),
            series_title=str(series.get("title") or queue_item.get("title") or ""),
            season_number=season_number,
            episode_numbers=episode_numbers,
            status=status,
            series_path=series_path,
            file_path=file_path,
            queue_id=_to_optional_int(queue_item.get("id")),
            tracked_download_status=str(queue_item.get("trackedDownloadStatus") or ""),
            tracked_download_state=str(queue_item.get("trackedDownloadState") or ""),
            status_messages=status_messages,
        )
        for file_path in file_paths
    ]


def _queue_file_paths(queue_item: dict[str, object], series_path: str) -> list[str]:
    candidates: list[str] = []
    for key in ("outputPath", "downloadPath", "path"):
        value = queue_item.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    episode_file = queue_item.get("episodeFile") if isinstance(queue_item.get("episodeFile"), dict) else None
    if episode_file:
        episode_file_path = _extract_file_path(episode_file, base_path=series_path)
        if episode_file_path:
            candidates.append(episode_file_path)
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


def _episode_numbers_for_file(episode_file: dict[str, object], episode_map: dict[int, dict[str, object]]) -> tuple[int | None, list[int]]:
    episode_ids = episode_file.get("episodes") or episode_file.get("episodeIds") or []
    numbers = _extract_episode_numbers(episode_ids, None, episode_map)
    season_number = None
    for episode_id in episode_ids if isinstance(episode_ids, list) else []:
        episode = episode_map.get(int(episode_id or 0), {})
        season_number = _to_optional_int(episode.get("seasonNumber"))
        if season_number is not None:
            break
    return season_number, numbers


def _extract_episode_numbers(
    episode_ids: object,
    episode_payload: object = None,
    episode_map: dict[int, dict[str, object]] | None = None,
) -> list[int]:
    numbers: list[int] = []
    if isinstance(episode_ids, list) and episode_map is not None:
        for episode_id in episode_ids:
            episode = episode_map.get(int(episode_id or 0), {})
            number = _to_optional_int(episode.get("episodeNumber"))
            if number is not None:
                numbers.append(number)
    elif isinstance(episode_payload, dict):
        number = _to_optional_int(episode_payload.get("episodeNumber"))
        if number is not None:
            numbers.append(number)
    return numbers


def _update_sonarr_progress(database_path: str, progress: int, message: str, started_at: str | None = None) -> None:
    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key="sonarr-sync",
            label="Sonarr sync",
            state="running",
            progress=progress,
            message=message,
            started_at=started_at,
        )
