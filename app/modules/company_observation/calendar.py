from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PeriodType = Literal['week', 'month', 'year']
HK = ZoneInfo('Asia/Hong_Kong')


def today() -> date:
    return datetime.now(HK).date()


def period_start(kind: PeriodType, day: date) -> date:
    if kind == 'week':
        return day - timedelta(days=day.weekday())
    if kind == 'month':
        return day.replace(day=1)
    return day.replace(month=1, day=1)


def period_end(kind: PeriodType, start: date) -> date:
    if kind == 'week':
        return start + timedelta(days=7)
    if kind == 'month':
        return date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return date(start.year + 1, 1, 1)


def latest_ended(kind: PeriodType) -> date:
    return period_start(kind, period_start(kind, today()) - timedelta(days=1))


def expected_weeks(start: date, end: date) -> list[date]:
    result = []
    day = period_start('week', start)
    while day < end:
        result.append(day)
        day += timedelta(days=7)
    return result


def periods_since(first: date) -> list[tuple[PeriodType, date, date]]:
    result = []
    for kind in ('month', 'week', 'year'):
        start = period_start(kind, first)
        while period_end(kind, start) <= today():
            end = period_end(kind, start)
            result.append((kind, start, end))
            start = end
    return result
