from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ARR Inventory"
    data_root: str = "/data"
    database_path: str = "./app.db"
    frontend_dist_path: str = "./frontend/dist/frontend/browser"
    admin_username: str = "admin"
    admin_password: str = "admin"

    qbittorrent_url: str = ""
    qbittorrent_username: str = ""
    qbittorrent_password: str = ""

    radarr_url: str = ""
    radarr_api_key: str = ""

    sonarr_url: str = ""
    sonarr_api_key: str = ""

    torrent_min_seed_time_days: float = 0.0
    torrent_min_ratio: float = 0.0

    tmdb_api_key: str = ""
    scan_interval_seconds: int = 60


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
