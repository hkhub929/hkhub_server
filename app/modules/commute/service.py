"""Assemble commute responses from stored observations and live upstream data.

Nothing here writes observations: the collector owns sampling, so a user request can
never create, refresh or backfill a recorded window.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.commute import repository, upstream
from app.modules.commute.ports import (
    MTR_STATION_BY_PORT,
    RESIDENT,
    SUPPORTED_PORT_CODES,
    UNKNOWN_STATUS,
    VISITOR,
    hk_window,
    is_comparable,
    iso_utc,
    status_name,
)
from app.modules.commute.schemas import (
    BordersResponse,
    HistoryDay,
    HistoryResponse,
    PortQueueStatus,
    QueueState,
    TransitDeparture,
    TransitResponse,
    TransitSource,
)

logger = logging.getLogger(__name__)

# The schedule endpoint refreshes every few seconds; this keeps one open screen from
# issuing a request per rebuild. Each worker process keeps its own small cache.
_TRANSIT_CACHE_SECONDS = 20
_transit_cache: dict[str, tuple[float, TransitResponse]] = {}


def _queue_state(row: dict[str, Any] | None, now: datetime) -> QueueState:
    if row is None:
        return QueueState(
            status=UNKNOWN_STATUS, status_code=None, observed_at=None, state="missing"
        )
    observed_at = row.get("observed_at")
    code = row.get("status_code")
    return QueueState(
        status=status_name(code),
        status_code=code,
        observed_at=iso_utc(observed_at) if observed_at else None,
        state=_freshness(observed_at, now),
    )


def _freshness(observed_at: datetime | None, now: datetime) -> str:
    """Stale means the sampler has not recorded this window recently; it is not an error."""
    if observed_at is None:
        return "missing"
    limit = timedelta(minutes=settings.commute_stale_after_minutes)
    return "fresh" if now - observed_at <= limit else "stale"


def _port_status(
    port_code: str, rows: dict[tuple[str, str], dict[str, Any]], now: datetime
) -> PortQueueStatus:
    return PortQueueStatus(
        port_code=port_code,
        resident=_queue_state(rows.get((port_code, RESIDENT)), now),
        visitor=_queue_state(rows.get((port_code, VISITOR)), now),
    )


def read_borders(session: Session) -> BordersResponse:
    """Current Hong Kong inbound status for every supported control point."""
    rows = repository.latest_arrival_statuses(session, SUPPORTED_PORT_CODES)
    now = datetime.now(timezone.utc)
    return BordersResponse(
        generated_at=iso_utc(now),
        ports=[_port_status(code, rows, now) for code in SUPPORTED_PORT_CODES],
    )


def read_port(session: Session, port_code: str) -> PortQueueStatus:
    rows = repository.latest_arrival_statuses(session, (port_code,))
    return _port_status(port_code, rows, datetime.now(timezone.utc))


def read_history(session: Session, port_code: str, audience: str) -> HistoryResponse:
    """Compare the current local window with the same window on previous days."""
    now = datetime.now(timezone.utc)
    hk_date, slot = hk_window(now)
    history_days = settings.commute_history_days
    rows = repository.window_statuses(
        session, port_code, audience, slot, hk_date - timedelta(days=history_days), hk_date
    )
    current = _queue_state(rows.get(hk_date), now)
    days = [
        _history_day(hk_date - timedelta(days=offset), rows)
        for offset in range(1, history_days + 1)
    ]
    lower, same, higher, valid = _compare(current.status_code, days)
    return HistoryResponse(
        port_code=port_code,
        audience=audience,
        generated_at=iso_utc(now),
        hk_date=hk_date.isoformat(),
        hk_slot=slot,
        current=current,
        days=days,
        valid_days=valid,
        lower_days=lower,
        same_days=same,
        higher_days=higher,
        # A full-week conclusion needs every day plus a comparable current level.
        conclusive=valid == history_days and is_comparable(current.status_code),
    )


def _history_day(day: date, rows: dict[date, dict[str, Any]]) -> HistoryDay:
    row = rows.get(day)
    code = row.get("status_code") if row else None
    observed_at = row.get("observed_at") if row else None
    return HistoryDay(
        hk_date=day.isoformat(),
        status=status_name(code),
        status_code=code,
        observed_at=iso_utc(observed_at) if observed_at else None,
    )


def _compare(current_code: int | None, days: list[HistoryDay]) -> tuple[int, int, int, int]:
    """Count lower/same/higher levels against past days and the comparable total."""
    if not is_comparable(current_code):
        return 0, 0, 0, 0
    lower = same = higher = 0
    for day in days:
        code = day.status_code
        if not is_comparable(code):
            continue
        if current_code > code:
            lower += 1
        elif current_code == code:
            same += 1
        else:
            higher += 1
    return lower, same, higher, lower + same + higher


async def read_transit(client: httpx.AsyncClient, port_code: str) -> TransitResponse:
    """Verified Hong Kong-side onward connections; failures stay local to this call."""
    station = MTR_STATION_BY_PORT.get(port_code)
    if station is None:
        return _transit_response(
            port_code, [_source("mtr", "unverified", reason="no_verified_connection")], []
        )
    cached = _cache_get(port_code)
    if cached is not None:
        return cached
    try:
        departures, observed_at = upstream.parse_mtr_schedule(
            await upstream.fetch_mtr_schedule(client, station)
        )
    except (httpx.HTTPError, ValueError) as error:
        logger.warning(
            "Commute transit failed port=%s station=%s type=%s",
            port_code, station, type(error).__name__,
        )
        return _transit_response(
            port_code, [_source("mtr", "unavailable", reason="upstream_unavailable")], []
        )
    response = _transit_response(
        port_code,
        [_source("mtr", "ok", observed_at=observed_at)],
        [TransitDeparture(**item) for item in departures],
    )
    _cache_put(port_code, response)
    return response


def _source(
    kind: str,
    state: str,
    *,
    observed_at: datetime | None = None,
    reason: str | None = None,
) -> TransitSource:
    return TransitSource(
        kind=kind,
        state=state,
        observed_at=iso_utc(observed_at) if observed_at else None,
        reason=reason,
    )


def _transit_response(
    port_code: str, sources: list[TransitSource], departures: list[TransitDeparture]
) -> TransitResponse:
    return TransitResponse(
        port_code=port_code,
        generated_at=iso_utc(datetime.now(timezone.utc)),
        sources=sources,
        departures=departures,
    )


def _cache_get(port_code: str) -> TransitResponse | None:
    entry = _transit_cache.get(port_code)
    if entry is None:
        return None
    stored_at, response = entry
    if monotonic() - stored_at > _TRANSIT_CACHE_SECONDS:
        _transit_cache.pop(port_code, None)
        return None
    return response


def _cache_put(port_code: str, response: TransitResponse) -> None:
    _transit_cache[port_code] = (monotonic(), response)
