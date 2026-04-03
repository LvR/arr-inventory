from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

from app.db import get_connection, upsert_job_state
from app.services.inventory_utils import classify_file_type, extract_tracker_name, tracker_is_disabled


CHECK_STATUS_OK = "ok"
CHECK_STATUS_KO = "ko"
CHECK_STATUS_PENDING = "pending"
CHECK_STATUS_NA = "na"


@dataclass(slots=True)
class GroupCheckResult:
    check_key: str
    label: str
    status: str
    summary: str
    details: list[str]


@dataclass(slots=True)
class GroupContext:
    group_id: int
    locations: list[dict[str, object]]
    matched_location_ids: set[int]
    trackers: list[dict[str, object]]
    torrents: list[dict[str, object]]


def run_consistency_checks(database_path: str) -> dict[str, int]:
    return run_consistency_checks_with_stop(database_path)


def run_consistency_checks_with_stop(
    database_path: str,
    should_stop: Callable[[], bool] | None = None,
    torrent_min_seed_time_days: float = 0.0,
    torrent_min_ratio: float = 0.0,
) -> dict[str, int]:
    job_key = "consistency-check"
    started_at = datetime.now(tz=timezone.utc).isoformat()
    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key=job_key,
            label="Consistency check",
            state="running",
            progress=5,
            message="Evaluating group consistency rules",
            started_at=started_at,
            preserve_started_at=False,
        )

        connection.execute("DELETE FROM group_check_results")
        connection.execute(
            "UPDATE file_groups SET consistency_status = 'pending', consistency_issue_count = 0, updated_at = CURRENT_TIMESTAMP"
        )

        groups = _load_group_contexts(connection)
        total = max(len(groups), 1)
        groups_with_issues = 0

        for index, group in enumerate(groups, start=1):
            if should_stop is not None and should_stop():
                upsert_job_state(
                    connection,
                    job_key=job_key,
                    label="Consistency check",
                    state="cancelled",
                    progress=100,
                    message=f"Stopped after checking {index - 1} groups",
                    started_at=started_at,
                )
                return {"groups": len(groups), "groups_with_issues": groups_with_issues}

            results = evaluate_group(
                group,
                torrent_min_seed_time_days=torrent_min_seed_time_days,
                torrent_min_ratio=torrent_min_ratio,
            )
            issue_count = sum(1 for result in results if result.status == CHECK_STATUS_KO)
            if issue_count:
                groups_with_issues += 1

            applicable_results = [result for result in results if result.status != CHECK_STATUS_NA]
            global_status = CHECK_STATUS_PENDING
            if applicable_results:
                global_status = CHECK_STATUS_KO if issue_count else CHECK_STATUS_OK

            for result in results:
                connection.execute(
                    """
                    INSERT INTO group_check_results (group_id, check_key, label, status, summary, details_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        group.group_id,
                        result.check_key,
                        result.label,
                        result.status,
                        result.summary,
                        json.dumps(result.details),
                    ),
                )

            connection.execute(
                """
                UPDATE file_groups
                SET consistency_status = ?, consistency_issue_count = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (global_status, issue_count, group.group_id),
            )

            progress = min(95, 5 + int((index / total) * 90))
            upsert_job_state(
                connection,
                job_key=job_key,
                label="Consistency check",
                state="running",
                progress=progress,
                message=f"Checked {index}/{len(groups)} groups",
                started_at=started_at,
            )

        upsert_job_state(
            connection,
            job_key=job_key,
            label="Consistency check",
            state="done",
            progress=100,
            message=f"Checked {len(groups)} groups, {groups_with_issues} with issues",
            started_at=started_at,
        )

    return {"groups": len(groups), "groups_with_issues": groups_with_issues}


def evaluate_group(
    group: GroupContext,
    *,
    torrent_min_seed_time_days: float = 0.0,
    torrent_min_ratio: float = 0.0,
) -> list[GroupCheckResult]:
    checks: list[GroupCheckResult] = [
        check_downloads_are_matched_to_torrents(group),
        check_movies_have_single_video_per_directory(group),
        check_movies_match_radarr(group),
        check_tv_match_sonarr(group),
        check_download_torrents_are_still_useful(
            group,
            torrent_min_seed_time_days=torrent_min_seed_time_days,
            torrent_min_ratio=torrent_min_ratio,
        ),
        check_trackers_are_healthy(group),
    ]
    return checks


def check_downloads_are_matched_to_torrents(group: GroupContext) -> GroupCheckResult:
    download_location_ids = {
        int(str(location["id"]))
        for location in group.locations
        if str(location["root_bucket"]) == "downloads"
    }
    missing_paths = [
        str(location["path"])
        for location in group.locations
        if str(location["root_bucket"]) == "downloads" and int(str(location["id"])) not in group.matched_location_ids
    ]
    if not download_location_ids:
        return GroupCheckResult(
            check_key="downloads_matched",
            label="Downloads in torrents",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no file in downloads.",
            details=[],
        )
    if not missing_paths:
        return GroupCheckResult(
            check_key="downloads_matched",
            label="Downloads in torrents",
            status=CHECK_STATUS_OK,
            summary="Every downloads file is matched to a torrent.",
            details=[],
        )
    return GroupCheckResult(
        check_key="downloads_matched",
        label="Downloads in torrents",
        status=CHECK_STATUS_KO,
        summary="Some downloads files are not matched to any torrent.",
        details=missing_paths,
    )


def check_movies_have_single_video_per_directory(group: GroupContext) -> GroupCheckResult:
    movie_video_paths = [
        str(location["path"])
        for location in group.locations
        if str(location["root_bucket"]) == "movies" and classify_file_type(str(location["filename"])) == "video"
    ]
    if not movie_video_paths:
        return GroupCheckResult(
            check_key="movies_single_video_dir",
            label="Movies single video directory",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no video file in movies.",
            details=[],
        )
    directory_map: dict[str, list[str]] = {}
    for path in movie_video_paths:
        parent = str(PurePosixPath(path).parent)
        directory_map.setdefault(parent, []).append(path)
    conflicting_directories = [
        f"{directory}: {', '.join(sorted(paths))}"
        for directory, paths in sorted(directory_map.items())
        if len(paths) > 1
    ]
    if not conflicting_directories:
        return GroupCheckResult(
            check_key="movies_single_video_dir",
            label="Movies single video directory",
            status=CHECK_STATUS_OK,
            summary="Each movies directory contains at most one video file for this group.",
            details=[],
        )
    return GroupCheckResult(
        check_key="movies_single_video_dir",
        label="Movies single video directory",
        status=CHECK_STATUS_KO,
        summary="A movies directory contains more than one video file for this group.",
        details=conflicting_directories,
    )


def check_trackers_are_healthy(group: GroupContext) -> GroupCheckResult:
    tracker_errors = []
    for tracker in group.trackers:
        url = str(tracker["url"])
        status = str(tracker["status"])
        message = str(tracker["message"])
        if tracker_is_disabled(url, status):
            continue
        normalized_status = status.strip().lower()
        normalized_message = message.strip().lower()
        if normalized_status in {"working", "ok", "updating", "2", "3"} and normalized_message in {"", "ok"}:
            continue
        if normalized_status in {"working", "ok", "updating", "2", "3"} and not normalized_message:
            continue
        tracker_errors.append(f"{url} - {status} - {message or 'no message'}")

    if not group.trackers:
        return GroupCheckResult(
            check_key="trackers_healthy",
            label="Trackers healthy",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no matched torrent tracker.",
            details=[],
        )

    if not tracker_errors:
        return GroupCheckResult(
            check_key="trackers_healthy",
            label="Trackers healthy",
            status=CHECK_STATUS_OK,
            summary="No active tracker reports an error.",
            details=[],
        )
    return GroupCheckResult(
        check_key="trackers_healthy",
        label="Trackers healthy",
        status=CHECK_STATUS_KO,
        summary="At least one active tracker reports an error.",
        details=tracker_errors,
    )


def check_movies_match_radarr(group: GroupContext) -> GroupCheckResult:
    movie_locations = [
        location
        for location in group.locations
        if str(location["root_bucket"]) == "movies" and classify_file_type(str(location["filename"])) == "video"
    ]
    imported_radarr_locations = [
        location
        for location in group.locations
        if classify_file_type(str(location["filename"])) == "video"
        and any(str(item.get("source") or "") == "movie" for item in _parse_media_items(location.get("radarr_json")))
    ]
    if not movie_locations and not imported_radarr_locations:
        return GroupCheckResult(
            check_key="movies_radarr_consistent",
            label="Movies match Radarr",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no video file in movies or imported Radarr video entry.",
            details=[],
        )

    missing_in_radarr = [
        str(location["path"])
        for location in movie_locations
        if not any(str(item.get("source") or "") == "movie" for item in _parse_media_items(location.get("radarr_json")))
    ]
    imported_outside_movies = [
        str(location["path"])
        for location in imported_radarr_locations
        if str(location["root_bucket"]) != "movies"
    ]
    if not missing_in_radarr and not imported_outside_movies:
        return GroupCheckResult(
            check_key="movies_radarr_consistent",
            label="Movies match Radarr",
            status=CHECK_STATUS_OK,
            summary="Movies files and imported Radarr entries match each other.",
            details=[],
        )

    details = [f"Missing in Radarr: {path}" for path in missing_in_radarr]
    details.extend(f"Imported in Radarr but not in movies: {path}" for path in imported_outside_movies)
    return GroupCheckResult(
        check_key="movies_radarr_consistent",
        label="Movies match Radarr",
        status=CHECK_STATUS_KO,
        summary="Movies files and imported Radarr entries are not aligned.",
        details=details,
    )


def check_tv_match_sonarr(group: GroupContext) -> GroupCheckResult:
    tv_locations = [
        location
        for location in group.locations
        if str(location["root_bucket"]) == "tv" and classify_file_type(str(location["filename"])) == "video"
    ]
    imported_sonarr_locations = [
        location
        for location in group.locations
        if classify_file_type(str(location["filename"])) == "video"
        and any(str(item.get("source") or "") == "episode" for item in _parse_media_items(location.get("sonarr_json")))
    ]
    if not tv_locations and not imported_sonarr_locations:
        return GroupCheckResult(
            check_key="tv_sonarr_consistent",
            label="TV match Sonarr",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no video file in TV or imported Sonarr video entry.",
            details=[],
        )

    missing_in_sonarr = [
        str(location["path"])
        for location in tv_locations
        if not any(str(item.get("source") or "") == "episode" for item in _parse_media_items(location.get("sonarr_json")))
    ]
    imported_outside_tv = [
        str(location["path"])
        for location in imported_sonarr_locations
        if str(location["root_bucket"]) != "tv"
    ]
    if not missing_in_sonarr and not imported_outside_tv:
        return GroupCheckResult(
            check_key="tv_sonarr_consistent",
            label="TV match Sonarr",
            status=CHECK_STATUS_OK,
            summary="TV files and imported Sonarr entries match each other.",
            details=[],
        )

    details = [f"Missing in Sonarr: {path}" for path in missing_in_sonarr]
    details.extend(f"Imported in Sonarr but not in TV: {path}" for path in imported_outside_tv)
    return GroupCheckResult(
        check_key="tv_sonarr_consistent",
        label="TV match Sonarr",
        status=CHECK_STATUS_KO,
        summary="TV files and imported Sonarr entries are not aligned.",
        details=details,
    )


def check_download_torrents_are_still_useful(
    group: GroupContext,
    *,
    torrent_min_seed_time_days: float,
    torrent_min_ratio: float,
) -> GroupCheckResult:
    download_locations = [location for location in group.locations if str(location["root_bucket"]) == "downloads"]
    media_locations = [
        location
        for location in group.locations
        if str(location["root_bucket"]) in {"movies", "tv", "music"}
        or any(str(item.get("source") or "") == "movie" for item in _parse_media_items(location.get("radarr_json")))
        or any(str(item.get("source") or "") == "episode" for item in _parse_media_items(location.get("sonarr_json")))
    ]
    if not download_locations:
        return GroupCheckResult(
            check_key="download_torrent_still_useful",
            label="Download torrent still useful",
            status=CHECK_STATUS_NA,
            summary="Not applicable because this group has no file in downloads.",
            details=[],
        )

    if media_locations:
        return GroupCheckResult(
            check_key="download_torrent_still_useful",
            label="Download torrent still useful",
            status=CHECK_STATUS_OK,
            summary="This download group is still useful because it is present in media or ARR apps.",
            details=[],
        )

    threshold_seed_time_seconds = max(0.0, torrent_min_seed_time_days) * 86400
    threshold_ratio = max(0.0, torrent_min_ratio)
    if not group.torrents:
        return GroupCheckResult(
            check_key="download_torrent_still_useful",
            label="Download torrent still useful",
            status=CHECK_STATUS_OK,
            summary="This downloads-only group has no matched torrent metadata to evaluate.",
            details=[],
        )

    over_threshold_torrents = [
        torrent
        for torrent in group.torrents
        if float(torrent.get("seed_time") or 0) > threshold_seed_time_seconds
        and float(torrent.get("ratio") or 0) > threshold_ratio
    ]
    if len(over_threshold_torrents) != len(group.torrents):
        return GroupCheckResult(
            check_key="download_torrent_still_useful",
            label="Download torrent still useful",
            status=CHECK_STATUS_OK,
            summary="At least one matched torrent is still below the configured ratio or seed time threshold.",
            details=[],
        )

    details = [
        (
            f"{_torrent_tracker_prefix(torrent)}{torrent.get('name', '')}: "
            f"ratio {float(torrent.get('ratio') or 0):.2f}, seed time {_human_seconds(int(torrent.get('seed_time') or 0))}"
        )
        for torrent in over_threshold_torrents
    ]
    return GroupCheckResult(
        check_key="download_torrent_still_useful",
        label="Download torrent still useful",
        status=CHECK_STATUS_KO,
        summary="All matched torrents in this downloads-only group exceed the configured ratio and seed time thresholds.",
        details=details,
    )


def _load_group_contexts(connection) -> list[GroupContext]:
    group_rows = connection.execute("SELECT id FROM file_groups ORDER BY id ASC").fetchall()
    location_rows = connection.execute(
        "SELECT id, group_id, root_bucket, path, filename, radarr_json, sonarr_json FROM file_locations ORDER BY group_id ASC, path ASC"
    ).fetchall()
    match_rows = connection.execute(
        "SELECT fl.group_id, qfm.location_id FROM qb_file_matches qfm JOIN file_locations fl ON fl.id = qfm.location_id"
    ).fetchall()
    tracker_rows = connection.execute(
        """
        SELECT fl.group_id, qtt.url, qtt.status, qtt.message
        FROM qb_file_matches qfm
        JOIN file_locations fl ON fl.id = qfm.location_id
        JOIN qb_torrent_trackers qtt ON qtt.torrent_hash = qfm.torrent_hash
        ORDER BY fl.group_id ASC, qtt.id ASC
        """
    ).fetchall()
    torrent_rows = connection.execute(
        """
        SELECT fl.group_id, qt.hash, qt.name, qt.ratio, qt.seed_time, qtt.url AS tracker_url
        FROM qb_file_matches qfm
        JOIN file_locations fl ON fl.id = qfm.location_id
        JOIN qb_torrents qt ON qt.hash = qfm.torrent_hash
        LEFT JOIN qb_torrent_trackers qtt ON qtt.torrent_hash = qt.hash
        ORDER BY fl.group_id ASC, qt.name COLLATE NOCASE ASC
        """
    ).fetchall()

    locations_by_group: dict[int, list[dict[str, object]]] = {}
    for row in location_rows:
        locations_by_group.setdefault(int(row["group_id"]), []).append(dict(row))

    matches_by_group: dict[int, set[int]] = {}
    for row in match_rows:
        matches_by_group.setdefault(int(row["group_id"]), set()).add(int(row["location_id"]))

    trackers_by_group: dict[int, list[dict[str, object]]] = {}
    for row in tracker_rows:
        group_id = int(row["group_id"])
        tracker = {"url": row["url"], "status": row["status"], "message": row["message"]}
        existing = trackers_by_group.setdefault(group_id, [])
        if tracker not in existing:
            existing.append(tracker)

    torrents_by_group: dict[int, list[dict[str, object]]] = {}
    for row in torrent_rows:
        group_id = int(row["group_id"])
        existing = torrents_by_group.setdefault(group_id, [])
        torrent_hash = str(row["hash"])
        tracker_url = str(row["tracker_url"] or "")
        current = next((item for item in existing if str(item.get("hash")) == torrent_hash), None)
        if current is None:
            current = {
                "hash": row["hash"],
                "name": row["name"],
                "ratio": row["ratio"],
                "seed_time": row["seed_time"],
                "tracker_url": "",
            }
            existing.append(current)
        if tracker_url and not tracker_is_disabled(tracker_url, "") and not current.get("tracker_url"):
            current["tracker_url"] = tracker_url

    return [
        GroupContext(
            group_id=int(row["id"]),
            locations=locations_by_group.get(int(row["id"]), []),
            matched_location_ids=matches_by_group.get(int(row["id"]), set()),
            trackers=trackers_by_group.get(int(row["id"]), []),
            torrents=torrents_by_group.get(int(row["id"]), []),
        )
        for row in group_rows
    ]


def _parse_media_items(value: object) -> list[dict[str, object]]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    items = parsed.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _human_seconds(value: int) -> str:
    total = max(0, int(value))
    days = total // 86400
    if days > 0:
        hours = (total % 86400) // 3600
        return f"{days}d {hours}h"
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _torrent_tracker_prefix(torrent: dict[str, object]) -> str:
    tracker_name = extract_tracker_name(str(torrent.get("tracker_url") or ""))
    return f"[{tracker_name}] " if tracker_name else "[no tracker] "
