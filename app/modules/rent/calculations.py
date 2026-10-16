from decimal import Decimal


def shift_month(month: str, offset: int) -> str:
    year, number = map(int, month.split('-'))
    year, number = divmod(year * 12 + number - 1 + offset, 12)
    return f'{year:04d}-{number + 1:02d}'


def months_between(start: str, end: str) -> list[str]:
    months, current = [], start
    while current <= end:
        months.append(current)
        current = shift_month(current, 1)
    return months


def point_at(points: dict, month: str) -> dict:
    return points.get(month, {'month': month, 'value': None, 'source_flag': '',
                             'quality_status': 'missing', 'small_sample': False,
                             'missing_reason': 'month_missing', 'comparability_break': False})


def change(points: dict, start: str, end: str) -> dict:
    first, last = point_at(points, start), point_at(points, end)
    reason = None
    if first['value'] is None or last['value'] is None:
        reason = 'endpoint_missing'
    elif Decimal(first['value']) <= 0:
        reason = 'invalid_denominator'
    elif any(point.get('comparability_break') for month, point in points.items() if start < month <= end):
        reason = 'methodology_break'
    percent = None if reason else float((Decimal(last['value']) / Decimal(first['value']) - 1) * 100)
    return {'start_month': start, 'end_month': end,
            'start_value': numeric(first['value']), 'end_value': numeric(last['value']),
            'percent': percent, 'reason': reason}


def numeric(value) -> float | None:
    return float(Decimal(value)) if value is not None else None


def build_series(definition: dict, stored: list[dict], months: list[str], relative: bool) -> dict:
    points = {point['month']: point for point in stored}
    start, end = months[0], months[-1]
    output = []
    baseline = point_at(points, start)['value']
    for month in months:
        point = point_at(points, month)
        transformed = (float(Decimal(point['value']) / Decimal(baseline) * 100)
                       if relative and point['value'] is not None else None)
        output.append({**point, 'value': numeric(point['value']), 'relative_value': transformed})
    latest = point_at(points, end)
    mom, yoy = change(points, shift_month(end, -1), end), change(points, shift_month(end, -12), end)
    return {'definition': definition, 'points': output,
            'latest': {'month': end, 'value': numeric(latest['value']),
                       'source_flag': latest['source_flag'], 'mom': mom, 'yoy': yoy},
            'period_change': change(points, start, end),
            'insight': {'code': 'year_on_year' if yoy['percent'] is not None else 'coverage_only',
                        'month': end, 'percent': yoy['percent']},
            'complete': all(point['value'] is not None for point in output)}
