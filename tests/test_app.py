from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db import init_db
from app.main import create_app
from app.services.inventory_utils import extract_tracker_name, tracker_is_disabled


def test_health_endpoint(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_renders(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "ARR Inventory" in response.text


def test_dashboard_api_payload(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["app_name"] == "ARR Inventory"
    assert payload["settings"]["data_root"] == "/data"
    assert payload["summary"]["files"] == 0
    assert payload["summary"]["music"] == 0
    assert payload["summary"]["torrents"] == 0
    assert payload["meta"]["total_duration_seconds"] == 0
    assert "summary" in payload
    assert "inventory" in payload


def test_scan_qb_sync_and_group_detail(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads"
    movies = data_root / "media" / "movies" / "Movie Alpha"
    music = data_root / "media" / "music"
    downloads.mkdir(parents=True)
    movies.mkdir(parents=True)
    music.mkdir(parents=True)
    sample = downloads / "movie.mkv"
    movie_copy = movies / "movie.mkv"
    track = music / "song.mp3"
    sample.write_text("demo", encoding="utf-8")
    movie_copy.hardlink_to(sample)
    track.write_text("demo", encoding="utf-8")

    FakeQBClient.downloads_path = str(downloads)
    FakeQBClient.music_path = str(music)
    FakeRadarrImportedClient.movie_file_path = str(movie_copy)
    FakeRadarrImportedClient.movie_path = str(movies)

    def client_factory(*args, **kwargs):
        base_url = str(kwargs.get("base_url", ""))
        if "qb.local" in base_url:
            return FakeQBClient(*args, **kwargs)
        if "radarr.local" in base_url:
            return FakeRadarrImportedClient(*args, **kwargs)
        if "sonarr.local" in base_url:
            return FakeSonarrImportedClient(*args, **kwargs)
        raise AssertionError(base_url)

    monkeypatch.setattr(httpx, "Client", client_factory)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        qbittorrent_url="http://qb.local",
        qbittorrent_username="user",
        qbittorrent_password="pass",
        radarr_url="http://radarr.local",
        radarr_api_key="radarr-key",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_inventory_pipeline

    result = run_inventory_pipeline(
        settings.database_path,
        settings.data_root,
        settings.qbittorrent_url,
        settings.qbittorrent_username,
        settings.qbittorrent_password,
        settings.radarr_url,
        settings.radarr_api_key,
        settings.sonarr_url,
        settings.sonarr_api_key,
        settings.torrent_min_seed_time_days,
        settings.torrent_min_ratio,
    )
    assert result["torrents"] == 2
    assert result["groups_with_issues"] == 0

    payload = client.get("/api/dashboard").json()

    assert payload["summary"]["downloads"] == 1
    assert payload["summary"]["files"] == 3
    assert payload["summary"]["music"] == 1
    assert payload["summary"]["torrents"] == 2
    assert any(row["torrent_count"] == 1 for row in payload["inventory"])
    assert any(row["has_radarr"] == 1 for row in payload["inventory"])
    assert not any(row["has_sonarr"] == 1 for row in payload["inventory"])
    assert all(row["consistency_status"] == "ok" for row in payload["inventory"])
    assert payload["filters"]["trackers"] == ["example"]

    movie_group = next(row for row in payload["inventory"] if row["file_type"] == "video")
    assert movie_group["torrent_names"] == ["movie-pack"]
    assert movie_group["torrents_tooltip"] == "example"
    assert movie_group["tracker_names"] == ["example"]
    detail = client.get(f"/api/groups/{movie_group['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["group_key"] == movie_group["group_key"]
    assert len(detail_payload["locations"]) == 2
    assert len(detail_payload["torrents"]) == 1
    assert detail_payload["torrents"][0]["hash"] == "hash-video"
    assert detail_payload["torrents"][0]["trackers"][0]["url"] == "udp://tracker.example:80/announce"
    assert detail_payload["torrents"][0]["tracker_names"] == ["example"]
    assert len(detail_payload["radarr"]["imported"]) == 1
    assert detail_payload["radarr"]["queue"] == []
    assert detail_payload["consistency_status"] == "ok"
    assert len(detail_payload["checks"]) == 6
    assert any(check["status"] == "na" for check in detail_payload["checks"])


def test_consistency_checks_report_group_issues(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads" / "release"
    movies = data_root / "media" / "movies" / "MovieA"
    downloads.mkdir(parents=True)
    movies.mkdir(parents=True)
    source = downloads / "matched.mkv"
    source.write_text("demo", encoding="utf-8")
    (downloads / "missing.mkv").hardlink_to(source)
    (movies / "cut1.mkv").hardlink_to(source)
    (movies / "cut2.mp4").hardlink_to(source)

    BrokenQBClient.downloads_path = str(downloads)
    FakeRadarrImportedClient.movie_file_path = str(source)
    FakeRadarrImportedClient.movie_path = str(movies)

    def client_factory(*args, **kwargs):
        base_url = str(kwargs.get("base_url", ""))
        if "qb.local" in base_url:
            return BrokenQBClient(*args, **kwargs)
        if "radarr.local" in base_url:
            return FakeRadarrImportedClient(*args, **kwargs)
        if "sonarr.local" in base_url:
            return FakeSonarrImportedClient(*args, **kwargs)
        raise AssertionError(base_url)

    monkeypatch.setattr(httpx, "Client", client_factory)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        qbittorrent_url="http://qb.local",
        qbittorrent_username="user",
        qbittorrent_password="pass",
        radarr_url="http://radarr.local",
        radarr_api_key="radarr-key",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_inventory_pipeline

    result = run_inventory_pipeline(
        settings.database_path,
        settings.data_root,
        settings.qbittorrent_url,
        settings.qbittorrent_username,
        settings.qbittorrent_password,
        settings.radarr_url,
        settings.radarr_api_key,
        settings.sonarr_url,
        settings.sonarr_api_key,
        settings.torrent_min_seed_time_days,
        settings.torrent_min_ratio,
    )

    assert result["groups_with_issues"] >= 1

    payload = client.get("/api/dashboard").json()
    broken_group = next(row for row in payload["inventory"] if row["consistency_status"] == "ko")
    assert broken_group["consistency_issue_count"] == 4

    detail_payload = client.get(f"/api/groups/{broken_group['id']}").json()
    assert detail_payload["consistency_status"] == "ko"
    assert {check["check_key"] for check in detail_payload["checks"]} == {
        "downloads_matched",
        "movies_single_video_dir",
        "movies_radarr_consistent",
        "tv_sonarr_consistent",
        "download_torrent_still_useful",
        "trackers_healthy",
    }
    assert all(
        check["status"] == "ko"
        for check in detail_payload["checks"]
        if check["check_key"] not in {"tv_sonarr_consistent", "download_torrent_still_useful"}
    )
    assert next(check for check in detail_payload["checks"] if check["check_key"] == "tv_sonarr_consistent")["status"] == "na"
    assert next(check for check in detail_payload["checks"] if check["check_key"] == "download_torrent_still_useful")["status"] == "ok"


def test_consistency_checks_stay_pending_before_run(tmp_path):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads"
    downloads.mkdir(parents=True)
    (downloads / "movie.mkv").write_text("demo", encoding="utf-8")

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_filesystem_scan

    run_filesystem_scan(settings.database_path, settings.data_root)

    payload = client.get("/api/dashboard").json()
    row = payload["inventory"][0]
    assert row["consistency_status"] == "pending"

    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    assert detail_payload["consistency_status"] == "pending"
    assert detail_payload["checks"] == []


def test_radarr_queue_match_sets_group_flag_and_detail(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads" / "QueueMovie"
    downloads.mkdir(parents=True)
    queued_file = downloads / "QueueMovie.mkv"
    queued_file.write_text("demo", encoding="utf-8")

    FakeRadarrQueueClient.queue_file_path = str(queued_file)
    FakeRadarrQueueClient.movie_path = str(data_root / "media" / "movies" / "QueueMovie (2025)")
    monkeypatch.setattr(httpx, "Client", FakeRadarrQueueClient)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        radarr_url="http://radarr.local",
        radarr_api_key="radarr-key",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_filesystem_scan
    from app.services.radarr import run_radarr_sync

    run_filesystem_scan(settings.database_path, settings.data_root)
    result = run_radarr_sync(settings.database_path, settings.radarr_url, settings.radarr_api_key)

    assert result["matches"] == 1

    payload = client.get("/api/dashboard").json()
    row = payload["inventory"][0]
    assert row["has_radarr"] == 1

    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    assert detail_payload["radarr"]["imported"] == []
    assert len(detail_payload["radarr"]["queue"]) == 1
    assert detail_payload["radarr"]["queue"][0]["file_path"] == str(queued_file)


def test_sonarr_queue_match_sets_group_flag_and_detail(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    tv_dir = data_root / "media" / "tv" / "Queue Show" / "Season 01"
    tv_dir.mkdir(parents=True)
    queued_file = tv_dir / "Queue.Show.S01E01.mkv"
    queued_file.write_text("demo", encoding="utf-8")

    FakeSonarrQueueClient.queue_file_path = str(queued_file)
    FakeSonarrQueueClient.series_path = str(data_root / "media" / "tv" / "Queue Show")
    monkeypatch.setattr(httpx, "Client", FakeSonarrQueueClient)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        sonarr_url="http://sonarr.local",
        sonarr_api_key="sonarr-key",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_filesystem_scan
    from app.services.sonarr import run_sonarr_sync

    run_filesystem_scan(settings.database_path, settings.data_root)
    result = run_sonarr_sync(settings.database_path, settings.sonarr_url, settings.sonarr_api_key)

    assert result["matches"] == 1

    payload = client.get("/api/dashboard").json()
    row = payload["inventory"][0]
    assert row["has_sonarr"] == 1

    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    assert detail_payload["sonarr"]["imported"] == []
    assert len(detail_payload["sonarr"]["queue"]) == 1
    assert detail_payload["sonarr"]["queue"][0]["file_path"] == str(queued_file)


def test_consistency_checks_report_tv_sonarr_mismatch(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    tv_dir = data_root / "media" / "tv" / "Broken Show" / "Season 01"
    tv_dir.mkdir(parents=True)
    episode = tv_dir / "Broken.Show.S01E01.mkv"
    episode.write_text("demo", encoding="utf-8")

    monkeypatch.setattr(httpx, "Client", FakeSonarrClient)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        sonarr_url="http://sonarr.local",
        sonarr_api_key="sonarr-key",
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_filesystem_scan
    from app.services.consistency import run_consistency_checks

    run_filesystem_scan(settings.database_path, settings.data_root)
    run_consistency_checks(settings.database_path)

    payload = client.get("/api/dashboard").json()
    row = payload["inventory"][0]
    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    tv_check = next(check for check in detail_payload["checks"] if check["check_key"] == "tv_sonarr_consistent")
    assert tv_check["status"] == "ko"
    assert any("Missing in Sonarr" in detail for detail in tv_check["details"])


def test_consistency_checks_report_download_torrent_no_longer_useful(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads"
    downloads.mkdir(parents=True)
    sample = downloads / "movie.mkv"
    sample.write_text("demo", encoding="utf-8")

    FakeQBClient.downloads_path = str(downloads)
    FakeQBClient.music_path = str(data_root / "media" / "music")
    monkeypatch.setattr(httpx, "Client", FakeQBClient)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        qbittorrent_url="http://qb.local",
        qbittorrent_username="user",
        qbittorrent_password="pass",
        torrent_min_seed_time_days=0.001,
        torrent_min_ratio=1.0,
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_inventory_pipeline

    result = run_inventory_pipeline(
        settings.database_path,
        settings.data_root,
        settings.qbittorrent_url,
        settings.qbittorrent_username,
        settings.qbittorrent_password,
        settings.radarr_url,
        settings.radarr_api_key,
        settings.sonarr_url,
        settings.sonarr_api_key,
        settings.torrent_min_seed_time_days,
        settings.torrent_min_ratio,
    )

    assert result["groups_with_issues"] >= 1

    payload = client.get("/api/dashboard").json()
    row = next(item for item in payload["inventory"] if item["consistency_status"] == "ko")
    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    useful_check = next(check for check in detail_payload["checks"] if check["check_key"] == "download_torrent_still_useful")
    assert useful_check["status"] == "ko"
    assert any("movie-pack" in detail for detail in useful_check["details"])
    assert any("[example]" in detail for detail in useful_check["details"])
    assert not any("[** [dht] **]" in detail for detail in useful_check["details"])
    assert not any("[** [lsd] **]" in detail for detail in useful_check["details"])
    assert not any("[** [pex] **]" in detail for detail in useful_check["details"])
    assert any("seed time" in detail and "h" in detail for detail in useful_check["details"])


def test_consistency_checks_keep_download_torrent_useful_when_any_matched_torrent_is_below_thresholds(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads"
    downloads.mkdir(parents=True)
    sample = downloads / "movie.mkv"
    sample.write_text("demo", encoding="utf-8")

    class MixedThresholdQBClient(FakeQBClient):
        def get(self, path, params=None):
            if path == "/api/v2/torrents/info":
                return FakeQBResponse(
                    [
                        {
                            "hash": "hash-over",
                            "name": "movie-pack-over",
                            "state": "uploading",
                            "category": "movies",
                            "tags": "",
                            "uploaded": 1000,
                            "downloaded": 500,
                            "ratio": 2.0,
                            "seeding_time": 3600,
                            "save_path": "/tmp/unused",
                            "content_path": self.downloads_path,
                        },
                        {
                            "hash": "hash-under",
                            "name": "movie-pack-under",
                            "state": "uploading",
                            "category": "movies",
                            "tags": "",
                            "uploaded": 100,
                            "downloaded": 100,
                            "ratio": 1.0,
                            "seeding_time": 30,
                            "save_path": "/tmp/unused",
                            "content_path": self.downloads_path,
                        },
                    ]
                )
            if path == "/api/v2/torrents/files":
                return FakeQBResponse([{"name": "movie.mkv", "size": 4, "priority": 1, "progress": 1.0}])
            if path == "/api/v2/torrents/trackers":
                return FakeQBResponse([{"url": "udp://tracker.example:80/announce", "status": "working", "msg": "ok"}])
            return super().get(path, params=params)

    MixedThresholdQBClient.downloads_path = str(downloads)
    MixedThresholdQBClient.music_path = str(data_root / "media" / "music")
    monkeypatch.setattr(httpx, "Client", MixedThresholdQBClient)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        data_root=str(data_root),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
        qbittorrent_url="http://qb.local",
        qbittorrent_username="user",
        qbittorrent_password="pass",
        torrent_min_seed_time_days=0.001,
        torrent_min_ratio=1.0,
    )
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.services.scanner import run_inventory_pipeline

    run_inventory_pipeline(
        settings.database_path,
        settings.data_root,
        settings.qbittorrent_url,
        settings.qbittorrent_username,
        settings.qbittorrent_password,
        settings.radarr_url,
        settings.radarr_api_key,
        settings.sonarr_url,
        settings.sonarr_api_key,
        settings.torrent_min_seed_time_days,
        settings.torrent_min_ratio,
    )

    payload = client.get("/api/dashboard").json()
    row = payload["inventory"][0]
    detail_payload = client.get(f"/api/groups/{row['id']}").json()
    useful_check = next(check for check in detail_payload["checks"] if check["check_key"] == "download_torrent_still_useful")
    assert useful_check["status"] == "ok"
    assert useful_check["details"] == []


def test_stop_scan_sets_stopping_state(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200
    client.post("/api/scan/filesystem")
    response = client.post("/api/scan/stop")

    assert response.status_code == 200
    assert response.json() == {"status": "stopping"}


def test_job_duration_is_reported(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code == 200

    from app.db import get_connection, upsert_job_state

    with get_connection(settings.database_path) as connection:
        upsert_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="done",
            progress=100,
            message="done",
            started_at="2026-03-23T10:00:00+00:00",
        )
        connection.execute(
            "UPDATE job_states SET updated_at = ? WHERE job_key = ?",
            ("2026-03-23T10:00:05+00:00", "filesystem-scan"),
        )

    payload = client.get("/api/dashboard").json()
    job = next(job for job in payload["jobs"] if job["job_key"] == "filesystem-scan")
    assert job["duration_seconds"] == 5.0
    assert payload["meta"]["total_duration_seconds"] == 5.0


def test_upsert_job_state_can_reset_started_at(tmp_path):
    from app.db import get_connection, upsert_job_state

    database_path = str(tmp_path / "test.db")
    init_db(database_path)

    with get_connection(database_path) as connection:
        upsert_job_state(
            connection,
            job_key="qbittorrent-sync",
            label="qBittorrent sync",
            state="done",
            progress=100,
            message="old",
            started_at="2026-03-23T10:00:00+00:00",
            preserve_started_at=False,
        )
        upsert_job_state(
            connection,
            job_key="qbittorrent-sync",
            label="qBittorrent sync",
            state="running",
            progress=5,
            message="new",
            started_at="2026-03-23T10:10:00+00:00",
            preserve_started_at=False,
        )
        row = connection.execute(
            "SELECT started_at FROM job_states WHERE job_key = ?",
            ("qbittorrent-sync",),
        ).fetchone()

    assert row["started_at"] == "2026-03-23T10:10:00+00:00"


def test_stop_event_can_interrupt_scan(tmp_path):
    data_root = tmp_path / "data"
    downloads = data_root / "downloads"
    downloads.mkdir(parents=True)
    for index in range(5):
        (downloads / f"file-{index}.mkv").write_text("demo", encoding="utf-8")

    from app.services import scanner

    stop_event = scanner._get_stop_event(str(tmp_path / "test.db"))
    stop_event.set()
    records = scanner.scan_filesystem(str(data_root), should_stop=stop_event.is_set)

    assert records == []
    stop_event.clear()


def test_extract_tracker_name_uses_simple_domain_rule():
    assert extract_tracker_name("udp://tracker.blabla.org:80/announce") == "blabla"
    assert extract_tracker_name("https://open.stealth.si/announce") == "stealth"
    assert extract_tracker_name("tracker.local") == "local"
    assert tracker_is_disabled("** [dht] **", "") is True
    assert tracker_is_disabled("** [lsd] **", "") is True
    assert tracker_is_disabled("** [pex] **", "") is True


def test_dashboard_requires_login(tmp_path):
    from app.services.auth import reset_login_throttle_state

    reset_login_throttle_state()
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/api/dashboard")

    assert response.status_code == 401


def test_login_and_logout_flow(tmp_path):
    from app.services.auth import reset_login_throttle_state

    reset_login_throttle_state()
    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    session_before = client.get("/api/auth/session")
    assert session_before.status_code == 200
    assert session_before.json() == {"authenticated": False}

    denied = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert denied.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True, "username": "admin"}

    session_after = client.get("/api/auth/session")
    assert session_after.status_code == 200
    assert session_after.json() == {"authenticated": True, "username": "admin"}

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False}

    session_final = client.get("/api/auth/session")
    assert session_final.status_code == 200
    assert session_final.json() == {"authenticated": False}


def test_login_throttle_escalates_after_three_attempts(tmp_path, monkeypatch):
    from app.services import auth

    auth.reset_login_throttle_state()
    current_time = 1000.0

    monkeypatch.setattr(auth.time, "monotonic", lambda: current_time)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    for _ in range(3):
        denied = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert denied.status_code == 401

    throttled = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert throttled.status_code == 429
    assert "Try again in 2s" in throttled.json()["detail"]

    current_time += 2.1
    denied_again = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert denied_again.status_code == 401

    throttled_again = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert throttled_again.status_code == 429
    assert "Try again in 8s" in throttled_again.json()["detail"]


def test_successful_login_clears_throttle_for_ip(tmp_path, monkeypatch):
    from app.services import auth

    auth.reset_login_throttle_state()
    current_time = 2000.0

    monkeypatch.setattr(auth.time, "monotonic", lambda: current_time)

    settings = Settings(
        database_path=str(tmp_path / "test.db"),
        frontend_dist_path=str(_frontend_fixture_dir(tmp_path)),
        admin_username="admin",
        admin_password="secret",
    )
    app = create_app(settings)
    client = TestClient(app)

    for _ in range(2):
        denied = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert denied.status_code == 401

    allowed = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert allowed.status_code == 200

    denied_after_success = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert denied_after_success.status_code == 401


def _frontend_fixture_dir(tmp_path) -> Path:
    frontend_dir = tmp_path / "frontend-dist"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html><body>ARR Inventory</body></html>", encoding="utf-8")
    return frontend_dir


class FakeQBResponse:
    def __init__(self, json_data=None, text: str = "", status_code: int = 200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://qb.local")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


class FakeRadarrClient:
    def __init__(self, *args, **kwargs):
        self.base_url = kwargs.get("base_url", "")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, path, params=None):
        if path == "/api/v3/movie":
            return FakeQBResponse(
                [
                    {
                        "id": 101,
                        "title": "Movie Alpha",
                        "year": 2024,
                        "status": "released",
                        "path": self.base_url.replace("http://radarr.local", "") or "/data/media/movies/Movie Alpha (2024)",
                        "movieFile": {
                            "relativePath": "movie.mkv",
                            "path": "/tmp/unused",
                        },
                    }
                ]
            )
        if path == "/api/v3/queue/details":
            return FakeQBResponse({"records": []})
        raise AssertionError(path)


class FakeRadarrImportedClient(FakeRadarrClient):
    movie_file_path = ""
    movie_path = ""

    def get(self, path, params=None):
        if path == "/api/v3/movie":
            return FakeQBResponse(
                [
                    {
                        "id": 101,
                        "title": "Movie Alpha",
                        "year": 2024,
                        "status": "released",
                        "path": self.movie_path,
                        "movieFile": {
                            "path": self.movie_file_path,
                            "relativePath": Path(self.movie_file_path).name,
                        },
                    }
                ]
            )
        if path == "/api/v3/queue/details":
            return FakeQBResponse({"records": []})
        return super().get(path, params=params)


class FakeRadarrQueueClient(FakeRadarrClient):
    queue_file_path = ""
    movie_path = ""

    def get(self, path, params=None):
        if path == "/api/v3/movie":
            return FakeQBResponse([])
        if path == "/api/v3/queue/details":
            return FakeQBResponse(
                {
                    "records": [
                        {
                            "id": 501,
                            "status": "downloading",
                            "trackedDownloadStatus": "warning",
                            "trackedDownloadState": "importPending",
                            "statusMessages": [{"title": "Import", "messages": "Waiting for download"}],
                            "movie": {
                                "id": 301,
                                "title": "QueueMovie",
                                "year": 2025,
                                "path": self.movie_path,
                            },
                            "outputPath": self.queue_file_path,
                        }
                    ]
                }
            )
        return super().get(path, params=params)


class FakeSonarrClient:
    def __init__(self, *args, **kwargs):
        self.base_url = kwargs.get("base_url", "")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, path, params=None):
        if path == "/api/v3/series":
            return FakeQBResponse([])
        if path == "/api/v3/episodefile":
            return FakeQBResponse([])
        if path == "/api/v3/episode":
            return FakeQBResponse([])
        if path == "/api/v3/queue/details":
            return FakeQBResponse({"records": []})
        raise AssertionError(path)


class FakeSonarrImportedClient(FakeSonarrClient):
    series_path = ""
    file_path = ""

    def get(self, path, params=None):
        if path == "/api/v3/series":
            return FakeQBResponse([{"id": 11, "title": "Queue Show", "path": self.series_path}])
        if path == "/api/v3/episodefile":
            return FakeQBResponse([
                {"id": 21, "seriesId": 11, "path": self.file_path, "relativePath": Path(self.file_path).name, "episodes": [31]}
            ])
        if path == "/api/v3/episode":
            return FakeQBResponse([{"id": 31, "seasonNumber": 1, "episodeNumber": 1}])
        if path == "/api/v3/queue/details":
            return FakeQBResponse({"records": []})
        return super().get(path, params=params)


class FakeSonarrQueueClient(FakeSonarrClient):
    series_path = ""
    queue_file_path = ""

    def get(self, path, params=None):
        if path == "/api/v3/series":
            return FakeQBResponse([])
        if path == "/api/v3/queue/details":
            return FakeQBResponse(
                {
                    "records": [
                        {
                            "id": 901,
                            "status": "downloading",
                            "trackedDownloadStatus": "warning",
                            "trackedDownloadState": "importPending",
                            "statusMessages": [{"title": "Import", "messages": "Waiting for episode"}],
                            "series": {"id": 11, "title": "Queue Show", "path": self.series_path},
                            "seasonNumber": 1,
                            "episodeIds": [31],
                            "outputPath": self.queue_file_path,
                        }
                    ]
                }
            )
        return super().get(path, params=params)


class FakeQBClient:
    downloads_path = ""
    music_path = ""

    def __init__(self, *args, **kwargs):
        self.base_url = kwargs.get("base_url", "")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, path, data=None):
        if path == "/api/v2/auth/login":
            return FakeQBResponse(text="Ok.")
        raise AssertionError(path)

    def get(self, path, params=None):
        if path == "/api/v2/torrents/info":
            return FakeQBResponse(
                [
                    {
                        "hash": "hash-video",
                        "name": "movie-pack",
                        "state": "uploading",
                        "category": "movies",
                        "tags": "tag1,tag2",
                        "uploaded": 1000,
                        "downloaded": 500,
                        "ratio": 2.0,
                        "seeding_time": 3600,
                        "save_path": "/tmp/unused",
                        "content_path": self.downloads_path,
                    },
                    {
                        "hash": "hash-audio",
                        "name": "song-pack",
                        "state": "stalledUP",
                        "category": "music",
                        "tags": "",
                        "uploaded": 200,
                        "downloaded": 100,
                        "ratio": 2.0,
                        "seeding_time": 7200,
                        "save_path": "/tmp/unused",
                        "content_path": self.music_path,
                    },
                ]
            )
        if path == "/api/v2/torrents/files":
            assert params is not None
            torrent_hash = params["hash"]
            if torrent_hash == "hash-video":
                return FakeQBResponse([{"name": "movie.mkv", "size": 4, "priority": 1, "progress": 1.0}])
            if torrent_hash == "hash-audio":
                return FakeQBResponse([{"name": "song.mp3", "size": 4, "priority": 1, "progress": 1.0}])
        if path == "/api/v2/torrents/trackers":
            return FakeQBResponse([{"url": "udp://tracker.example:80/announce", "status": "working", "msg": "ok"}])
        raise AssertionError(path)


class BrokenQBClient(FakeQBClient):
    def get(self, path, params=None):
        if path == "/api/v2/torrents/info":
            return FakeQBResponse(
                [
                    {
                        "hash": "hash-broken",
                        "name": "broken-pack",
                        "state": "stalledUP",
                        "category": "movies",
                        "tags": "",
                        "uploaded": 0,
                        "downloaded": 0,
                        "ratio": 0,
                        "seeding_time": 0,
                        "save_path": "/tmp/unused",
                        "content_path": self.downloads_path,
                    }
                ]
            )
        if path == "/api/v2/torrents/files":
            return FakeQBResponse([{"name": "matched.mkv", "size": 4, "priority": 1, "progress": 1.0}])
        if path == "/api/v2/torrents/trackers":
            return FakeQBResponse([{"url": "udp://tracker.example:80/announce", "status": "not working", "msg": "timeout"}])
        return super().get(path, params=params)
