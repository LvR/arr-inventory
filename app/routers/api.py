from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from threading import Thread
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.services.auth import (
    authenticate_admin,
    build_session_response,
    clear_login_throttle,
    clear_authenticated_cookie,
    enforce_login_rate_limit,
    register_failed_login_attempt,
    require_authenticated_admin,
    set_authenticated_cookie,
)
from app.services.dashboard import (
    get_dashboard_data,
    get_group_detail,
    get_inventory_meta,
    get_job_state,
    get_summary,
    list_inventory,
    list_job_states,
)
from app.services.scanner import purge_inventory, request_stop, run_inventory_pipeline

router = APIRouter(prefix="/api")


class LoginPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str
    password: str


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/auth/session")
def session_status(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, str | bool]:
    return build_session_response(request, settings)


@router.post("/auth/login")
def login(payload: LoginPayload, request: Request, response: Response, settings: Settings = Depends(get_settings)) -> dict[str, str | bool]:
    enforce_login_rate_limit(request)
    if not authenticate_admin(payload.username, payload.password, settings):
        register_failed_login_attempt(request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    clear_login_throttle(request)
    set_authenticated_cookie(response, settings)
    return {"authenticated": True, "username": settings.admin_username}


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_authenticated_cookie(response)
    return {"authenticated": False}


@router.get("/summary")
def summary(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, int]:
    return get_summary(settings.database_path)


@router.get("/jobs")
def jobs(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    return list_job_states(settings.database_path)


@router.get("/inventory")
def inventory(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    return list_inventory(settings.database_path)


@router.get("/meta")
def meta(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, str | float]:
    return get_inventory_meta(settings.database_path)


@router.get("/dashboard")
def dashboard(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, object]:
    dashboard_data = get_dashboard_data(settings.database_path)
    dashboard_data["settings"] = {
        "app_name": settings.app_name,
        "data_root": settings.data_root,
    }
    return dashboard_data


@router.get("/jobs/{job_key}")
def job(job_key: str, _: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, object] | None:
    return get_job_state(settings.database_path, job_key)


@router.get("/groups/{group_id}")
def group_detail(group_id: int, _: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, object] | None:
    return get_group_detail(settings.database_path, group_id)


@router.post("/scan/filesystem")
def scan_filesystem(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, str]:
    start_time = datetime.now(tz=timezone.utc).isoformat()
    from app.db import get_connection, upsert_job_state

    with get_connection(settings.database_path) as connection:
        upsert_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="queued",
            progress=0,
            message="Scan requested",
            started_at=start_time,
        )
        upsert_job_state(
            connection,
            job_key="filesystem-scan",
            label="Filesystem scan",
            state="running",
            progress=1,
            message="Scan starting...",
            started_at=start_time,
        )

    thread = Thread(
        target=run_inventory_pipeline,
        args=(
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
        ),
        daemon=True,
    )
    thread.start()
    return {"status": "started"}


@router.post("/inventory/purge")
def purge(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, str]:
    purge_inventory(settings.database_path)
    return {"status": "purged"}


@router.post("/scan/stop")
def stop_scan(_: str = Depends(require_authenticated_admin), settings: Settings = Depends(get_settings)) -> dict[str, str]:
    request_stop(settings.database_path)
    return {"status": "stopping"}
