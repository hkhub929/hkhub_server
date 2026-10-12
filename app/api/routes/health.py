import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import get_engine
from app.core.errors import error_response
from app.core.i18n import translate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
def health(request: Request) -> dict[str, str]:
    """Liveness probe; status is machine-readable, message is localized."""
    return {"status": "ok", "message": translate(request, "service_alive")}


@router.get("/ready", response_model=None)
def readiness(request: Request) -> dict[str, str] | JSONResponse:
    """Readiness includes database reachability and the initial schema migration."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT `key` FROM app_settings LIMIT 1"))
    except Exception as error:
        logger.warning("Readiness check failed type=%s", type(error).__name__)
        return error_response(
            request, 503, "not_ready", "Database unavailable or migrations not applied"
        )
    return {"status": "ok", "database": "ok", "message": translate(request, "service_ready")}
