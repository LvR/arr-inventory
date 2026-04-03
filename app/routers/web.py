from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings


def mount_frontend_routes(app: FastAPI, settings: Settings) -> None:
    frontend_dist = Path(settings.frontend_dist_path)
    assets_dir = frontend_dist / "assets"
    index_file = frontend_dist / "index.html"

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_app(full_path: str = ""):
        reserved_prefixes = ("api/", "static/", "assets/")
        if full_path.startswith(reserved_prefixes):
            raise HTTPException(status_code=404, detail="Not Found")
        requested_path = frontend_dist / full_path
        if full_path and requested_path.is_file():
            return FileResponse(requested_path)
        if not index_file.is_file():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Frontend build not found. Build Angular with 'npm install && npm run build' in ./frontend "
                    f"and ensure FRONTEND_DIST_PATH points to {frontend_dist}."
                ),
            )
        return FileResponse(index_file)
