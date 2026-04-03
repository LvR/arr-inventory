from __future__ import annotations

from datetime import datetime, timezone
import json

from app.db import get_connection
from app.services.inventory_utils import classify_file_type, extract_tracker_name, pick_file_type, tracker_is_disabled


def get_summary(database_path: str) -> dict[str, int]:
    summary = {
        "files": 0,
        "downloads": 0,
        "movies": 0,
        "tv": 0,
        "music": 0,
        "groups": 0,
        "locations": 0,
        "torrents": 0,
        "checks_ok": 0,
        "checks_ko": 0,
    }

    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT root_bucket, COUNT(*) AS count
            FROM file_locations
            GROUP BY root_bucket
            """
        ).fetchall()
        for row in rows:
            bucket = row["root_bucket"]
            if bucket in summary:
                summary[bucket] = int(row["count"])

        summary["groups"] = int(connection.execute("SELECT COUNT(*) FROM file_groups").fetchone()[0])
        summary["locations"] = int(connection.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0])
        summary["files"] = summary["locations"]
        summary["torrents"] = int(connection.execute("SELECT COUNT(*) FROM qb_torrents").fetchone()[0])
        summary["checks_ok"] = int(
            connection.execute("SELECT COUNT(*) FROM file_groups WHERE consistency_status = 'ok'").fetchone()[0]
        )
        summary["checks_ko"] = int(
            connection.execute("SELECT COUNT(*) FROM file_groups WHERE consistency_status = 'ko'").fetchone()[0]
        )

    return summary


def list_job_states(database_path: str) -> list[dict[str, object]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT job_key, label, state, progress, message, started_at, updated_at
            FROM job_states
            ORDER BY CASE job_key
                WHEN 'filesystem-scan' THEN 1
                WHEN 'qbittorrent-sync' THEN 2
                WHEN 'radarr-sync' THEN 3
                WHEN 'sonarr-sync' THEN 4
                WHEN 'consistency-check' THEN 5
                ELSE 99
            END ASC, updated_at DESC, job_key ASC
            """
        ).fetchall()

    jobs: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        for field in ("started_at", "updated_at"):
            value = item.get(field)
            item[f"{field}_display"] = smart_datetime(str(value)) if value else ""
        item["duration_seconds"] = calculate_duration_seconds(
            str(item.get("started_at") or ""),
            str(item.get("updated_at") or ""),
            str(item.get("state") or ""),
        )
        jobs.append(item)
    return jobs


def get_dashboard_data(database_path: str) -> dict[str, object]:
    jobs = list_job_states(database_path)
    inventory = list_inventory(database_path)
    return {
        "summary": get_summary(database_path),
        "jobs": jobs,
        "inventory": inventory,
        "meta": get_inventory_meta(database_path, jobs),
        "scan_job": get_job_state(database_path, "filesystem-scan"),
        "filters": {"trackers": list_tracker_filters(inventory)},
    }


def list_inventory(database_path: str) -> list[dict[str, object]]:
    with get_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT g.id, g.group_key, g.device, g.inode, g.size_bytes, g.hardlink_count, g.updated_at
                , g.consistency_status, g.consistency_issue_count
            FROM file_groups g
            ORDER BY g.updated_at DESC, g.id DESC
            """
        ).fetchall()

        location_rows = connection.execute(
            """
            SELECT group_id, root_bucket, path, filename, radarr_json, sonarr_json
            FROM file_locations
            ORDER BY group_id ASC, filename COLLATE NOCASE ASC, path COLLATE NOCASE ASC
            """
        ).fetchall()

        torrent_rows = connection.execute(
            """
            SELECT fl.group_id, qt.hash, qt.name, qt.status, qt.category, qt.tags
            FROM qb_file_matches qfm
            JOIN file_locations fl ON fl.id = qfm.location_id
            JOIN qb_torrents qt ON qt.hash = qfm.torrent_hash
            ORDER BY fl.group_id ASC, qt.name COLLATE NOCASE ASC
            """
        ).fetchall()

        tracker_rows = connection.execute(
            """
            SELECT fl.group_id, qt.hash AS torrent_hash, qtt.url, qtt.status
            FROM qb_file_matches qfm
            JOIN file_locations fl ON fl.id = qfm.location_id
            JOIN qb_torrents qt ON qt.hash = qfm.torrent_hash
            JOIN qb_torrent_trackers qtt ON qtt.torrent_hash = qt.hash
            ORDER BY fl.group_id ASC, qt.name COLLATE NOCASE ASC, qtt.id ASC
            """
        ).fetchall()

        check_rows = connection.execute(
            """
            SELECT group_id, check_key, label, status
            FROM group_check_results
            ORDER BY group_id ASC, id ASC
            """
        ).fetchall()

    locations_by_group: dict[int, list[dict[str, object]]] = {}
    for row in location_rows:
        locations_by_group.setdefault(int(row["group_id"]), []).append(dict(row))

    torrents_by_group: dict[int, list[dict[str, object]]] = {}
    for row in torrent_rows:
        group_id = int(row["group_id"])
        entry = dict(row)
        if group_id not in torrents_by_group:
            torrents_by_group[group_id] = []
        if not any(existing["hash"] == entry["hash"] for existing in torrents_by_group[group_id]):
            torrents_by_group[group_id].append(entry)

    tracker_names_by_group: dict[int, set[str]] = {}
    for row in tracker_rows:
        tracker_name = extract_tracker_name(str(row["url"] or ""))
        if not tracker_name or tracker_is_disabled(str(row["url"]), str(row["status"] or "")):
            continue
        group_id = int(row["group_id"])
        tracker_names_by_group.setdefault(group_id, set()).add(tracker_name)

    checks_by_group: dict[int, list[dict[str, str]]] = {}
    for row in check_rows:
        checks_by_group.setdefault(int(row["group_id"]), []).append(
            {
                "check_key": str(row["check_key"]),
                "label": str(row["label"]),
                "status": str(row["status"]),
            }
        )

    inventory = []
    for row in rows:
        item = dict(row)
        group_id = int(item["id"])
        locations = locations_by_group[group_id] if group_id in locations_by_group else []
        filenames: list[str] = []
        paths: list[str] = []
        buckets = set()
        path_groups = {"downloads": [], "movies": [], "tv": [], "music": []}
        file_types = set()
        radarr_items: list[dict[str, object]] = []
        sonarr_items: list[dict[str, object]] = []
        for location in locations:
            filename = str(location["filename"])
            if filename not in filenames:
                filenames.append(filename)
            file_types.add(classify_file_type(filename))
            path = str(location["path"])
            bucket = str(location["root_bucket"])
            paths.append(path)
            buckets.add(bucket)

            if bucket == "downloads":
                path_groups["downloads"].append({"path": path, "source_label": "download"})
            elif bucket in path_groups:
                path_groups[bucket].append({"path": path, "source_label": bucket})

            radarr_payload = _parse_media_json(location.get("radarr_json"))
            radarr_items.extend(radarr_payload.get("items", []))
            sonarr_payload = _parse_media_json(location.get("sonarr_json"))
            sonarr_items.extend(sonarr_payload.get("items", []))

        item["location_count"] = len(locations)
        item["filenames_display"] = ", ".join(filenames)
        item["paths"] = paths
        item["paths_tooltip"] = "\n".join(paths)
        item["path_groups"] = [
            {"label": "Downloads", "entries": path_groups["downloads"]},
            {"label": "Movies", "entries": path_groups["movies"]},
            {"label": "TV", "entries": path_groups["tv"]},
            {"label": "Music", "entries": path_groups["music"]},
        ]
        item["size_bytes_display"] = format_bytes(int(item["size_bytes"]))
        item["has_downloads"] = int("downloads" in buckets)
        item["has_movies"] = int("movies" in buckets)
        item["has_radarr"] = int(bool(radarr_items))
        item["has_tv"] = int("tv" in buckets)
        item["has_sonarr"] = int(bool(sonarr_items))
        item["has_music"] = int("music" in buckets)
        item["file_type"] = pick_file_type(file_types)
        torrent_entries = torrents_by_group.get(group_id, [])
        item["torrent_count"] = len(torrent_entries)
        item["has_torrents"] = int(item["torrent_count"] > 0)
        item["tracker_names"] = sorted(tracker_names_by_group.get(group_id, set()))
        item["torrent_names"] = [str(entry["name"]) for entry in torrent_entries]
        item["torrents_tooltip"] = "\n".join(item["tracker_names"])
        item["check_results"] = checks_by_group.get(group_id, [])
        item["consistency_status"] = str(item.get("consistency_status") or "pending")
        item["consistency_issue_count"] = int(item.get("consistency_issue_count") or 0)
        inventory.append(item)
    return inventory


def get_group_detail(database_path: str, group_id: int) -> dict[str, object] | None:
    with get_connection(database_path) as connection:
        group_row = connection.execute(
            """
            SELECT id, group_key, device, inode, size_bytes, hardlink_count, updated_at
                , consistency_status, consistency_issue_count
            FROM file_groups
            WHERE id = ?
            """,
            (group_id,),
        ).fetchone()
        if group_row is None:
            return None

        location_rows = connection.execute(
            """
            SELECT id, root_bucket, path, filename, source, torrent_name, qbittorrent_json
                , radarr_json, sonarr_json
            FROM file_locations
            WHERE group_id = ?
            ORDER BY path COLLATE NOCASE ASC
            """,
            (group_id,),
        ).fetchall()

        torrent_rows = connection.execute(
            """
            SELECT DISTINCT qt.hash, qt.name, qt.status, qt.category, qt.tags, qt.total_uploaded, qt.total_downloaded,
                qt.ratio, qt.seed_time, qt.save_path, qt.raw_json
            FROM qb_file_matches qfm
            JOIN file_locations fl ON fl.id = qfm.location_id
            JOIN qb_torrents qt ON qt.hash = qfm.torrent_hash
            WHERE fl.group_id = ?
            ORDER BY qt.name COLLATE NOCASE ASC
            """,
            (group_id,),
        ).fetchall()

        check_rows = connection.execute(
            """
            SELECT check_key, label, status, summary, details_json
            FROM group_check_results
            WHERE group_id = ?
            ORDER BY id ASC
            """,
            (group_id,),
        ).fetchall()

    locations = []
    grouped_paths = {"downloads": [], "movies": [], "tv": [], "music": []}
    filenames: list[str] = []
    for row in location_rows:
        item = dict(row)
        try:
            item["qbittorrent"] = json.loads(str(item.get("qbittorrent_json") or "{}"))
        except json.JSONDecodeError:
            item["qbittorrent"] = {}
        item["radarr"] = _parse_media_json(item.get("radarr_json"))
        item["sonarr"] = _parse_media_json(item.get("sonarr_json"))
        locations.append(item)
        filename = str(item["filename"])
        if filename not in filenames:
            filenames.append(filename)
        bucket = str(item["root_bucket"])
        if bucket in grouped_paths:
            grouped_paths[bucket].append(str(item["path"]))

    torrent_details = []
    with get_connection(database_path) as connection:
        for row in torrent_rows:
            trackers = connection.execute(
                """
                SELECT url, status, message
                FROM qb_torrent_trackers
                WHERE torrent_hash = ?
                ORDER BY id ASC
                """,
                (row["hash"],),
            ).fetchall()
            files = connection.execute(
                """
                SELECT qtf.file_path, qtf.file_name, qtf.size_bytes, qtf.priority, qtf.progress,
                    CASE WHEN matched.id IS NULL THEN 0 ELSE 1 END AS is_matched
                FROM qb_torrent_files qtf
                LEFT JOIN (
                    SELECT qfm.id, qfm.torrent_file_id
                    FROM qb_file_matches qfm
                    JOIN file_locations fl ON fl.id = qfm.location_id
                    WHERE fl.group_id = ?
                ) AS matched ON matched.torrent_file_id = qtf.id
                WHERE qtf.torrent_hash = ?
                ORDER BY qtf.file_path COLLATE NOCASE ASC
                """,
                (group_id, row["hash"]),
            ).fetchall()
            item = dict(row)
            item["trackers"] = []
            tracker_names: set[str] = set()
            for tracker in trackers:
                tracker_item = dict(tracker)
                if tracker_is_disabled(str(tracker_item["url"]), str(tracker_item["status"])):
                    continue
                tracker_name = extract_tracker_name(str(tracker_item["url"]))
                tracker_item["tracker_name"] = tracker_name or "unknown"
                if tracker_name:
                    tracker_names.add(tracker_name)
                item["trackers"].append(tracker_item)
            item["tracker_names"] = sorted(tracker_names)
            item["files"] = [dict(file_row) for file_row in files]
            torrent_details.append(item)

    result = dict(group_row)
    result["size_bytes_display"] = format_bytes(int(result["size_bytes"]))
    result["filenames_display"] = ", ".join(filenames)
    result["path_groups"] = [
        {"label": "Downloads", "entries": grouped_paths["downloads"]},
        {"label": "Movies", "entries": grouped_paths["movies"]},
        {"label": "TV", "entries": grouped_paths["tv"]},
        {"label": "Music", "entries": grouped_paths["music"]},
    ]
    result["locations"] = locations
    result["radarr"] = _build_radarr_detail(locations)
    result["sonarr"] = _build_sonarr_detail(locations)
    result["torrents"] = torrent_details
    result["consistency_status"] = str(result.get("consistency_status") or "pending")
    result["consistency_issue_count"] = int(result.get("consistency_issue_count") or 0)
    result["checks"] = []
    for row in check_rows:
        details = []
        try:
            details = json.loads(str(row["details_json"] or "[]"))
        except json.JSONDecodeError:
            details = []
        result["checks"].append(
            {
                "check_key": row["check_key"],
                "label": row["label"],
                "status": row["status"],
                "summary": row["summary"],
                "details": details,
            }
        )
    return result


def list_tracker_filters(inventory: list[dict[str, object]]) -> list[str]:
    tracker_names: set[str] = set()
    for row in inventory:
        for tracker_name in row.get("tracker_names", []):
            tracker_names.add(str(tracker_name))
    return sorted(tracker_names)


def _parse_media_json(value: object) -> dict[str, list[dict[str, object]]]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {"items": []}
    if not isinstance(parsed, dict):
        return {"items": []}
    items = parsed.get("items")
    if not isinstance(items, list):
        return {"items": []}
    return {"items": [dict(item) for item in items if isinstance(item, dict)]}


def _build_radarr_detail(locations: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    imported: list[dict[str, object]] = []
    queued: list[dict[str, object]] = []
    seen: set[str] = set()
    for location in locations:
        for item in location.get("radarr", {}).get("items", []):
            signature = json.dumps(item, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            if str(item.get("source") or "") == "queue":
                queued.append(item)
            else:
                imported.append(item)
    imported.sort(key=lambda item: (str(item.get("title") or "").lower(), str(item.get("file_path") or "").lower()))
    queued.sort(key=lambda item: (str(item.get("title") or "").lower(), str(item.get("file_path") or "").lower()))
    return {"imported": imported, "queue": queued}


def _build_sonarr_detail(locations: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    imported: list[dict[str, object]] = []
    queued: list[dict[str, object]] = []
    seen: set[str] = set()
    for location in locations:
        for item in location.get("sonarr", {}).get("items", []):
            signature = json.dumps(item, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            if str(item.get("source") or "") == "queue":
                queued.append(item)
            else:
                imported.append(item)
    imported.sort(key=lambda item: (str(item.get("series_title") or "").lower(), str(item.get("file_path") or "").lower()))
    queued.sort(key=lambda item: (str(item.get("series_title") or "").lower(), str(item.get("file_path") or "").lower()))
    return {"imported": imported, "queue": queued}


def get_inventory_meta(database_path: str, jobs: list[dict[str, object]] | None = None) -> dict[str, str | float]:
    with get_connection(database_path) as connection:
        rows = connection.execute("SELECT key, value FROM inventory_meta").fetchall()
    meta = {row["key"]: row["value"] for row in rows}
    if meta.get("last_inventory_at"):
        meta["last_inventory_at_display"] = smart_datetime(meta["last_inventory_at"])
    else:
        meta["last_inventory_at_display"] = "never"
    if jobs is None:
        jobs = list_job_states(database_path)
    meta["total_duration_seconds"] = round(
        sum(float(job.get("duration_seconds") or 0) for job in jobs),
        1,
    )
    return meta


def get_job_state(database_path: str, job_key: str) -> dict[str, object] | None:
    with get_connection(database_path) as connection:
        row = connection.execute(
            """
            SELECT job_key, label, state, progress, message, started_at, updated_at
            FROM job_states
            WHERE job_key = ?
            """,
            (job_key,),
        ).fetchone()

    if not row:
        return None

    item = dict(row)
    state = str(item["state"])
    item["state_display"] = {
        "queued": "queued",
        "running": "running",
        "done": "done",
        "error": "error",
        "idle": "idle",
        "cancelled": "cancelled",
    }.get(state, state)
    for field in ("started_at", "updated_at"):
        value = item.get(field)
        item[f"{field}_display"] = smart_datetime(str(value)) if value else ""
    item["duration_seconds"] = calculate_duration_seconds(
        str(item.get("started_at") or ""),
        str(item.get("updated_at") or ""),
        str(item.get("state") or ""),
    )
    return item


def format_bytes(size_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size_bytes)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.1f} {units[index]}"


def smart_datetime(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value

    now = datetime.now(tz=timezone.utc)
    delta = now - dt.astimezone(timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"


def calculate_duration_seconds(started_at: str, updated_at: str, state: str) -> float:
    start = parse_iso_datetime(started_at)
    if start is None:
        return 0.0

    end = parse_iso_datetime(updated_at)
    if end is None or state == "running":
        end = datetime.now(tz=timezone.utc)

    duration = max(0.0, (end - start).total_seconds())
    return round(duration, 1)


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
