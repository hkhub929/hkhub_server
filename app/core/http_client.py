import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Shared upstream connection pool, owned by the application lifespan."""
    return request.app.state.http_client
