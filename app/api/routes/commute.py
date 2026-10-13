"""Read-only cross-border commute endpoints.

Every response is served from this service: current status from stored observations,
onward connections through the shared upstream client. Clients never call an official
open-data host directly, so endpoints and credentials stay under server control.
"""

import httpx
from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.http_client import get_http_client
from app.modules.commute import service
from app.modules.commute.ports import SUPPORTED_PORT_CODES
from app.modules.commute.schemas import (
    Audience,
    BordersResponse,
    HistoryResponse,
    PortQueueStatus,
    TransitResponse,
)

router = APIRouter()


def _require_port(port_code: str) -> str:
    """Reject unsupported control points instead of returning an empty queue state."""
    if port_code not in SUPPORTED_PORT_CODES:
        raise AppError("commute_unknown_port", "Unknown control point", 404)
    return port_code


@router.get("/borders", response_model=BordersResponse)
def borders(response: Response, session: Session = Depends(get_db)) -> BordersResponse:
    """Current Hong Kong inbound queue status for every supported control point."""
    response.headers["Cache-Control"] = "no-store"
    return service.read_borders(session)


@router.get("/borders/{port_code}", response_model=PortQueueStatus)
def border_detail(
    response: Response,
    port_code: str = Path(max_length=8),
    session: Session = Depends(get_db),
) -> PortQueueStatus:
    response.headers["Cache-Control"] = "no-store"
    return service.read_port(session, _require_port(port_code))


@router.get("/borders/{port_code}/history", response_model=HistoryResponse)
def border_history(
    audience: Audience,
    response: Response,
    port_code: str = Path(max_length=8),
    session: Session = Depends(get_db),
) -> HistoryResponse:
    """Same local 15-minute window on previous days; never a prediction or an average."""
    response.headers["Cache-Control"] = "no-store"
    return service.read_history(session, _require_port(port_code), audience)


@router.get("/borders/{port_code}/transit", response_model=TransitResponse)
async def border_transit(
    response: Response,
    port_code: str = Path(max_length=8),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> TransitResponse:
    """Verified Hong Kong-side onward connections; an upstream failure stays local."""
    response.headers["Cache-Control"] = "no-store"
    return await service.read_transit(client, _require_port(port_code))
