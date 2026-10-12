import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.i18n import localized_headers, translate, validation_message

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A safe, public error; never put credentials or upstream payloads in message."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", uuid4().hex)
    fallback = translate(request, "internal_error" if status_code >= 500 else "request_failed")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": translate(request, code, fallback), "details": details or []},
            "request_id": request_id,
        },
        headers={**localized_headers(request, headers), "X-Request-ID": request_id},
    )


def register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        return error_response(request, error.status_code, error.code, error.message)

    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException) -> JSONResponse:
        message = translate(request, "internal_error" if error.status_code >= 500 else "request_failed")
        return error_response(
            request, error.status_code, f"http_{error.status_code}", message, headers=error.headers
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # Do not echo rejected input: it can contain passwords or personal data.
        details = [
            {
                "location": list(item["loc"]),
                "message": validation_message(request, item["type"]),
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return error_response(request, 422, "validation_error", "Invalid request", details)

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        # Exception strings may include connection URLs or upstream payloads.
        logger.error(
            "Unhandled error request_id=%s type=%s",
            getattr(request.state, "request_id", "unknown"),
            type(error).__name__,
        )
        return error_response(request, 500, "internal_error", "Internal server error")
