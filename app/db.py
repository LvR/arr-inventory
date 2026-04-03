from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS job_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    state TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_key TEXT NOT NULL UNIQUE,
    device INTEGER NOT NULL,
    inode INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    hardlink_count INTEGER NOT NULL DEFAULT 1,
    consistency_status TEXT NOT NULL DEFAULT 'pending',
    consistency_issue_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES file_groups(id) ON DELETE CASCADE,
    root_bucket TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    torrent_name TEXT NOT NULL DEFAULT '',
    qbittorrent_json TEXT NOT NULL DEFAULT '{}',
    radarr_json TEXT NOT NULL DEFAULT '{}',
    sonarr_json TEXT NOT NULL DEFAULT '{}',
    tmdb_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qb_torrents (
    hash TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    total_uploaded INTEGER NOT NULL DEFAULT 0,
    total_downloaded INTEGER NOT NULL DEFAULT 0,
    ratio REAL NOT NULL DEFAULT 0,
    seed_time INTEGER NOT NULL DEFAULT 0,
    save_path TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qb_torrent_trackers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    torrent_hash TEXT NOT NULL REFERENCES qb_torrents(hash) ON DELETE CASCADE,
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qb_torrent_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    torrent_hash TEXT NOT NULL REFERENCES qb_torrents(hash) ON DELETE CASCADE,
    file_index INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(torrent_hash, file_index)
);

CREATE TABLE IF NOT EXISTS qb_file_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL REFERENCES file_locations(id) ON DELETE CASCADE,
    torrent_hash TEXT NOT NULL REFERENCES qb_torrents(hash) ON DELETE CASCADE,
    torrent_file_id INTEGER NOT NULL REFERENCES qb_torrent_files(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, torrent_hash, torrent_file_id)
);

CREATE TABLE IF NOT EXISTS group_check_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES file_groups(id) ON DELETE CASCADE,
    check_key TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    summary TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_id, check_key)
);

CREATE INDEX IF NOT EXISTS idx_file_locations_root_bucket ON file_locations(root_bucket);
CREATE INDEX IF NOT EXISTS idx_file_locations_group_id ON file_locations(group_id);
CREATE INDEX IF NOT EXISTS idx_file_groups_device_inode ON file_groups(device, inode);
CREATE INDEX IF NOT EXISTS idx_qb_torrent_files_hash ON qb_torrent_files(torrent_hash);
CREATE INDEX IF NOT EXISTS idx_qb_torrent_files_path ON qb_torrent_files(file_path);
CREATE INDEX IF NOT EXISTS idx_qb_file_matches_location_id ON qb_file_matches(location_id);
CREATE INDEX IF NOT EXISTS idx_qb_file_matches_hash ON qb_file_matches(torrent_hash);
CREATE INDEX IF NOT EXISTS idx_group_check_results_group_id ON group_check_results(group_id);
"""


def _connect(database_path: str) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(database_path: str) -> None:
    with _connect(database_path) as connection:
        connection.executescript(SCHEMA)
        _migrate_schema(connection)
        connection.commit()


def _migrate_schema(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(
        connection,
        table_name="file_groups",
        column_name="consistency_status",
        column_sql="TEXT NOT NULL DEFAULT 'pending'",
    )
    _add_column_if_missing(
        connection,
        table_name="file_groups",
        column_name="consistency_issue_count",
        column_sql="INTEGER NOT NULL DEFAULT 0",
    )


def _add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row["name"] == column_name for row in rows):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def reset_inventory(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM group_check_results")
    connection.execute("DELETE FROM qb_file_matches")
    connection.execute("DELETE FROM qb_torrent_files")
    connection.execute("DELETE FROM qb_torrent_trackers")
    connection.execute("DELETE FROM qb_torrents")
    connection.execute("DELETE FROM file_locations")
    connection.execute("DELETE FROM file_groups")


def reset_job_states(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM job_states")


def set_inventory_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO inventory_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_inventory_meta(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT key, value FROM inventory_meta").fetchall()
    return {row["key"]: row["value"] for row in rows}


def upsert_job_state(
    connection: sqlite3.Connection,
    *,
    job_key: str,
    label: str,
    state: str,
    progress: int,
    message: str,
    started_at: str | None = None,
    preserve_started_at: bool = True,
) -> None:
    reset_started_at = started_at if not preserve_started_at else None
    connection.execute(
        """
        INSERT INTO job_states (job_key, label, state, progress, message, started_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(job_key) DO UPDATE SET
            label = excluded.label,
            state = excluded.state,
            progress = excluded.progress,
            message = excluded.message,
            started_at = COALESCE(?, excluded.started_at, job_states.started_at),
            updated_at = CURRENT_TIMESTAMP
        """,
        (job_key, label, state, progress, message, started_at, reset_started_at),
    )


def ensure_job_state(
    connection: sqlite3.Connection,
    *,
    job_key: str,
    label: str,
    state: str = "idle",
    progress: int = 0,
    message: str = "",
) -> None:
    row = connection.execute("SELECT 1 FROM job_states WHERE job_key = ?", (job_key,)).fetchone()
    if row is None:
        upsert_job_state(
            connection,
            job_key=job_key,
            label=label,
            state=state,
            progress=progress,
            message=message,
        )


def fetch_job_state(connection: sqlite3.Connection, job_key: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM job_states WHERE job_key = ?", (job_key,)).fetchone()


@contextmanager
def get_connection(database_path: str) -> Iterator[sqlite3.Connection]:
    connection = _connect(database_path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()
