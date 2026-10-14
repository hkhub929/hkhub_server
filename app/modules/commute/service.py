from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.commute.catalog import PORTS, SOURCE_PAGE, STALE_SECONDS, copy_text, slot_at
from app.modules.commute.schemas import (
    Border, BordersResponse, Comparison, HistoryDay, HistoryResponse, QueueStatus,
)


# Never substitute an earlier successful observation for a newer failed fetch.
def queue_from_row(row, port: str, now: datetime | None = None,
                   direction: str = 'arrival') -> QueueStatus:
    if row is None:
        return QueueStatus()
    status = QueueStatus(fetched_at=row['fetched_at'], attempted_at=row['attempted_at'])
    if row['error_code'] is not None:
        return status.model_copy(update={'reason': 'fetch_failed'})
    if now is not None and (now - row['fetched_at']).total_seconds() >= STALE_SECONDS:
        return status.model_copy(update={'reason': 'stale'})
    value = (row['payload'] or {}).get(port, {}).get(direction, {})
    code = value.get('code')
    reason = value.get('reason', 'missing')
    return status.model_copy(update={'code': code, 'reason': reason})


def read_borders(session: Session, language: str) -> BordersResponse:
    now = datetime.now(timezone.utc)
    rows = session.execute(text('''
        SELECT DISTINCT ON (audience) audience, attempted_at, fetched_at, payload, error_code
        FROM commute_observations ORDER BY audience, attempted_at DESC
    ''')).mappings().all()
    recent = {row['audience']: row for row in rows}
    items = [Border(
        code=code, name=copy_text(meta['name'], language),
        counterpart=copy_text(meta['counterpart'], language), modes=meta['modes'],
        queues={audience: queue_from_row(recent.get(audience), code, now)
                for audience in ('resident', 'visitor')},
        departure_queues={audience: queue_from_row(
            recent.get(audience), code, now, 'departure')
            for audience in ('resident', 'visitor')},
        source_url=SOURCE_PAGE,
    ) for code, meta in PORTS.items()]
    return BordersResponse(server_time=now, items=items)


def compare(current: QueueStatus, days: list[HistoryDay]) -> tuple[int, Comparison | None]:
    valid = [day.queue.code for day in days if day.queue.reason == 'available']
    count = len(valid)
    if current.reason != 'available' or count == 0:
        return count, None
    lower = sum(current.code < code for code in valid)
    higher = sum(current.code > code for code in valid)
    same = count - lower - higher
    position = 'mixed'
    if same == count:
        position = 'same'
    elif higher == 0:
        position = 'joint_lowest' if same else 'lowest'
    elif lower == 0:
        position = 'joint_highest' if same else 'highest'
    return count, Comparison(
        lower=lower, same=same, higher=higher, whole_week=count == 7, position=position,
    )


def read_history(session: Session, port: str, audience: str, direction: str = 'arrival') -> HistoryResponse:
    now = datetime.now(timezone.utc)
    today, slot = slot_at(now)
    rows = session.execute(text('''
        SELECT hk_date, attempted_at, fetched_at, payload, error_code
        FROM commute_observations
        WHERE audience = :audience AND hk_slot = :slot
          AND hk_date BETWEEN :start AND :end
    '''), {'audience': audience, 'slot': slot, 'start': today - timedelta(days=7),
          'end': today}).mappings().all()
    by_date = {row['hk_date']: row for row in rows}
    current = queue_from_row(by_date.get(today), port, now, direction)
    # Historical observations are not stale simply because they were collected days ago.
    days = [HistoryDay(date=day, queue=queue_from_row(by_date.get(day), port, direction=direction))
            for day in (today - timedelta(days=offset) for offset in range(7, 0, -1))]
    valid_count, comparison = compare(current, days)
    start_minutes, end_minutes = slot * 15, (slot + 1) * 15
    return HistoryResponse(
        server_time=now, port_code=port, audience=audience, direction=direction,
        current=current, days=days,
        slot_start=f'{start_minutes // 60:02d}:{start_minutes % 60:02d}',
        slot_end=f'{end_minutes // 60:02d}:{end_minutes % 60:02d}',
        valid_count=valid_count, comparison=comparison,
    )
