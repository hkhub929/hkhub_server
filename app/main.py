from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
