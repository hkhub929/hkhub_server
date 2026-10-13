"""SQL access for commute queue observations.

The table and its constraints live in db/migrations. Reads raise AppError so the API
degrades with a localized message; writes let the collector own its own error handling.
"""

import logging
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError

logger = logging.getLogger(__name__)

_INSERT_OBSERVATION = text(
    """
    INSERT INTO commute_queue_observations
        (port_code, audience, direction, status_code, hk_date, hk_slot, observed_at, source)
    VALUES
        (:port_code, :audience, :direction, :status_code, :hk_date, :hk_slot, :observed_at, :source)
    ON CONFLICT (port_code, audience, direction, hk_date, hk_slot) DO NOTHING
    """
)

# DISTINCT ON keeps the newest sampled window for each control point and audience.
_LATEST_ARRIVAL_STATUS = text(
    """
    SELECT DISTINCT ON (port_code, audience)
           port_code, audience, status_code, observed_at, hk_date, hk_slot
    FROM commute_queue_observations
    WHERE direction = 'arrival' AND port_code IN :port_codes
    ORDER BY port_code, audience, hk_date DESC, hk_slot DESC
    """
).bindparams(bindparam("port_codes", expanding=True))

_WINDOW_STATUS = text(
    """
    SELECT hk_date, status_code, observed_at
    FROM commute_queue_observations
    WHERE port_code = :port_code
      AND audience = :audience
      AND direction = 'arrival'
      AND hk_slot = :hk_slot
      AND hk_date BETWEEN :start_date AND :end_date
    """
)

_DELETE_EXPIRED = text(
    "DELETE FROM commute_queue_observations WHERE hk_date < :cutoff_date"
)


def save_observations(session: Session, rows: Iterable[dict[str, Any]]) -> int:
    """Insert one window's samples, ignoring duplicates, and return the stored count."""
    parameters = list(rows)
    if not parameters:
        return 0
    result = session.execute(_INSERT_OBSERVATION, parameters)
    return result.rowcount or 0


def latest_arrival_statuses(
    session: Session, port_codes: Iterable[str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Latest stored Hong Kong inbound status per control point and audience."""
    try:
        rows = session.execute(
            _LATEST_ARRIVAL_STATUS, {"port_codes": list(port_codes)}
        ).all()
    except SQLAlchemyError as error:
        logger.warning("Commute queue lookup failed type=%s", type(error).__name__)
        raise AppError("commute_unavailable", "Queue observations unavailable", 503) from error
    return {
        (row.port_code, row.audience): {
            "status_code": row.status_code,
            "observed_at": row.observed_at,
        }
        for row in rows
    }


def window_statuses(
    session: Session,
    port_code: str,
    audience: str,
    hk_slot: int,
    start_date: date,
    end_date: date,
) -> dict[date, dict[str, Any]]:
    """Stored status for one audience in the same local window across several days."""
    try:
        rows = session.execute(
            _WINDOW_STATUS,
            {
                "port_code": port_code,
                "audience": audience,
                "hk_slot": hk_slot,
                "start_date": start_date,
                "end_date": end_date,
            },
        ).all()
    except SQLAlchemyError as error:
        logger.warning("Commute window lookup failed type=%s", type(error).__name__)
        raise AppError("commute_unavailable", "Queue observations unavailable", 503) from error
    return {
        row.hk_date: {"status_code": row.status_code, "observed_at": row.observed_at}
        for row in rows
    }


def delete_expired(session: Session, cutoff_date: date) -> int:
    """Drop observations older than the retention window; returns the deleted count."""
    result = session.execute(_DELETE_EXPIRED, {"cutoff_date": cutoff_date})
    return result.rowcount or 0


def observation_row(
    port_code: str,
    audience: str,
    direction: str,
    status_code: int,
    hk_date: date,
    hk_slot: int,
    observed_at: datetime,
    source: str,
) -> dict[str, Any]:
    return {
        "port_code": port_code,
        "audience": audience,
        "direction": direction,
        "status_code": status_code,
        "hk_date": hk_date,
        "hk_slot": hk_slot,
        "observed_at": observed_at,
        "source": source,
    }
