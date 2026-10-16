import logging
from contextlib import contextmanager
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.i18n import request_language
from app.modules.company_observation.calendar import PeriodType
from app.modules.company_observation.schemas import (
    CompaniesResponse, LiquidationsResponse, Overview, PeriodsResponse, Topic,
)
from app.modules.company_observation.service import (
    read_companies, read_liquidations, read_overview, read_periods, read_topic,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@contextmanager
def reading(response: Response):
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Vary'] = 'Accept-Language'
    try:
        yield
    except SQLAlchemyError as error:
        logger.warning('Company observation database unavailable type=%s', type(error).__name__)
        raise AppError('http_503', 'Company data unavailable', 503) from error


@router.get('/periods', response_model=PeriodsResponse)
def periods(response: Response, period_type: PeriodType = 'month', session: Session = Depends(get_db)):
    with reading(response):
        return read_periods(session, period_type)


@router.get('/overview', response_model=Overview)
def overview(request: Request, response: Response, period_type: PeriodType = 'month',
             start_date: date | None = None, session: Session = Depends(get_db)):
    with reading(response):
        return read_overview(session, period_type, start_date, request_language(request))


@router.get('/reports/{report_id}/topics/{topic_id}', response_model=Topic)
def topic(report_id: UUID, topic_id: str, request: Request, response: Response,
          session: Session = Depends(get_db)):
    with reading(response):
        return read_topic(session, report_id, topic_id, request_language(request))


@router.get('/reports/{report_id}/companies', response_model=CompaniesResponse)
def companies(report_id: UUID, response: Response, topic_id: str | None = Query(default=None, min_length=1, max_length=64),
              q: str = Query(default='', max_length=120), cursor: str | None = Query(default=None, max_length=1024),
              limit: int = Query(default=30, ge=1, le=100), session: Session = Depends(get_db)):
    with reading(response):
        return read_companies(session, report_id, topic_id, q, cursor, limit)


@router.get('/liquidations', response_model=LiquidationsResponse)
def liquidations(response: Response, limit: int = Query(default=12, ge=1, le=120),
                 session: Session = Depends(get_db)):
    with reading(response):
        return read_liquidations(session, limit)
