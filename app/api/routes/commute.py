import logging

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.http_client import get_http_client
from app.core.i18n import request_language
from app.modules.commute.schemas import (
    Audience, Border, BordersResponse, HistoryResponse, PortCode, TransitResponse,
)
from app.modules.commute.service import read_borders, read_history
from app.modules.commute.transit import read_transit

router = APIRouter()
logger = logging.getLogger(__name__)


def headers(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Accept-Language'


@router.get('/borders', response_model=BordersResponse)
def borders(request: Request, response: Response, session: Session = Depends(get_db)):
    headers(response)
    try:
        return read_borders(session, request_language(request))
    except SQLAlchemyError as error:
        logger.warning('Border lookup unavailable type=%s', type(error).__name__)
        raise AppError('http_503', 'Commute data unavailable', 503) from error


@router.get('/borders/{port_code}', response_model=Border)
def border(port_code: PortCode, request: Request, response: Response,
           session: Session = Depends(get_db)):
    data = borders(request, response, session)
    return next(item for item in data.items if item.code == port_code)


@router.get('/borders/{port_code}/history', response_model=HistoryResponse)
def history(port_code: PortCode, audience: Audience, response: Response,
            session: Session = Depends(get_db)):
    headers(response)
    try:
        return read_history(session, port_code, audience)
    except SQLAlchemyError as error:
        logger.warning('History lookup unavailable type=%s', type(error).__name__)
        raise AppError('http_503', 'History unavailable', 503) from error


@router.get('/borders/{port_code}/transit', response_model=TransitResponse)
async def transit(port_code: PortCode, request: Request, response: Response,
                  client: httpx.AsyncClient = Depends(get_http_client)):
    headers(response)
    if not hasattr(request.app.state, 'commute_transit_cache'):
        request.app.state.commute_transit_cache = {}
    return await read_transit(client, port_code, request_language(request),
                              request.app.state.commute_transit_cache)
