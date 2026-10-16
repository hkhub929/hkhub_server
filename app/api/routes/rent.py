import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.modules.rent.service import read_catalog, read_trends

router = APIRouter()
logger = logging.getLogger(__name__)


def headers(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Accept-Language'


@router.get('/catalog')
def catalog(response: Response, session: Session = Depends(get_db)):
    headers(response)
    try:
        return read_catalog(session)
    except SQLAlchemyError as error:
        logger.warning('Rental catalog unavailable type=%s', type(error).__name__)
        raise AppError('http_503', 'Rental data unavailable', 503) from error


@router.get('/trends')
def trends(response: Response, series_id: list[str] = Query(min_length=1, max_length=3),
           years: int = Query(default=1, ge=1, le=5),
           view: Literal['original', 'relative'] = 'original',
           session: Session = Depends(get_db)):
    headers(response)
    if years not in {1, 3, 5}:
        raise AppError('validation_error', 'Unsupported rental interval', 422)
    try:
        return read_trends(session, series_id, years, view)
    except SQLAlchemyError as error:
        logger.warning('Rental trends unavailable type=%s', type(error).__name__)
        raise AppError('http_503', 'Rental data unavailable', 503) from error
