from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.db import init_db
from app.routers.api import router as api_router
from app.routers.web import mount_frontend_routes


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title=(settings or get_settings()).app_name)

    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    current_settings = settings or get_settings()
    init_db(current_settings.database_path)

    app.include_router(api_router)
    mount_frontend_routes(app, current_settings)

    return app


app = create_app()
