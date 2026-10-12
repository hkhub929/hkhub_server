import logging
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import database_url, dispose_engine
from app.core.errors import register_error_handlers
from app.core.i18n import localized_headers, negotiate_language

logger = logging.getLogger("hkhub.requests")


@asynccontextmanager
async def lifespan(application: FastAPI):
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if settings.environment == "production":
        database_url()  # Fail fast on missing production configuration; never create tables.
    async with httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        headers={"User-Agent": f"HKHub/{settings.version}"},
        follow_redirects=False,
    ) as client:
        application.state.http_client = client
        try:
            yield
        finally:
            dispose_engine()


def create_app() -> FastAPI:
    """Compose platform infrastructure; business routers are mounted in api/router.py."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug and settings.environment != "production",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept-Language", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Language"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_id = request.headers.get("X-Request-ID", "")
        # Correlation only, never authentication. Restrict input to prevent log injection.
        request.state.request_id = supplied_id if re.fullmatch(r"[0-9a-f]{32}", supplied_id) else uuid4().hex
        request.state.language = negotiate_language(request.headers.get("Accept-Language"))
        started = time.monotonic()
        logger.info("%s %s started request_id=%s", request.method, request.url.path,
                    request.state.request_id)
        response = await call_next(request)
        language_headers = localized_headers(request, response.headers)
        response.headers["Content-Language"] = language_headers["Content-Language"]
        response.headers["Vary"] = language_headers["Vary"]
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "%s %s status=%s duration_ms=%.1f request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
            request.state.request_id,
        )
        return response

    register_error_handlers(application)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
