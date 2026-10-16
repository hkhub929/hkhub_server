from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.rent.calculations import build_series, change, months_between, shift_month
from app.modules.rent.catalog import DICTIONARY_URL, SOURCE_PAGE, SOURCES, TERMS_URL, catalog, notes


def active_sources(session: Session) -> list:
    # Pointer, snapshot and sync state are read together in one MVCC statement.
    return session.execute(text('''
        SELECT state.*, snapshot.id AS snapshot_id, snapshot.catalog, snapshot.series_data,
               snapshot.accepted_at, snapshot.source_updated_at, snapshot.parser_version,
               snapshot.coverage_start_month, snapshot.coverage_end_month
        FROM rent_source_state state LEFT JOIN rent_snapshots snapshot
            ON snapshot.id=state.active_snapshot_id AND snapshot.source_id=state.source_id
        ORDER BY state.source_id
    ''')).mappings().all()


def dataset(row) -> dict:
    return {key: str(row[key]) if key == 'snapshot_id' and row[key] else row[key]
            for key in ('source_id', 'snapshot_id', 'accepted_at', 'source_updated_at',
                        'last_attempt_at', 'last_checked_at', 'last_changed_at',
                        'last_attempt_status', 'last_error_code', 'parser_version',
                        'coverage_start_month', 'coverage_end_month')} | {
        'source_url': SOURCES[row['source_id']]['url'], 'source_page': SOURCE_PAGE,
        'dictionary_url': DICTIONARY_URL, 'terms_url': TERMS_URL,
        'notes': notes(row['source_id']),
    }


def read_catalog(session: Session) -> dict:
    rows = active_sources(session)
    metrics = [{
        'metric': row['source_id'], 'available': row['snapshot_id'] is not None,
        'default_series_id': SOURCES[row['source_id']]['default'] if row['snapshot_id'] else None,
        'dataset': dataset(row), 'series': row['catalog'] or [],
    } for row in rows]
    return {'schema_version': 1, 'metrics': metrics}


def read_trends(session: Session, identities: list[str], years: int, view: str) -> dict:
    if len(set(identities)) != len(identities):
        raise AppError('validation_error', 'Duplicate rental series', 422)
    rows = active_sources(session)
    available = {item['series_id']: (item, row) for row in rows for item in row['catalog'] or []}
    selected = []
    for identity in identities:
        if identity not in available:
            known = {item['series_id'] for source_id in SOURCES for item in catalog(source_id)}
            if identity in known:
                raise AppError('data_unavailable', 'Rental data unavailable', 503)
            raise AppError('series_not_available', 'Rental series unavailable', 404)
        selected.append(available[identity])
    definition, row = selected[0]
    if any(meta['metric'] != definition['metric'] or
           meta['comparison_group'] != definition['comparison_group'] or
           meta['unit'] != definition['unit'] or meta['base_period'] != definition['base_period']
           for meta, _ in selected):
        raise AppError('incompatible_series', 'Series cannot be compared', 422)
    end = row['coverage_end_month']
    start = shift_month(end, -12 * years)
    months = months_between(start, end)
    if view == 'relative':
        for meta, _ in selected:
            points = {point['month']: point for point in row['series_data'][meta['series_id']]}
            baseline = change(points, start, start)
            if baseline['percent'] is None:
                raise AppError('relative_baseline_unavailable', 'Common baseline unavailable', 422)
            if any(point.get('comparability_break') for month, point in points.items() if start < month <= end):
                raise AppError('incompatible_series', 'Methodology changes within the interval', 422)
    series = [build_series(meta, row['series_data'][meta['series_id']], months, view == 'relative')
              for meta, _ in selected]
    return {'schema_version': 1, 'dataset': dataset(row),
            'range': {'years': years, 'start_month': start, 'end_month': end,
                      'coverage_start_month': row['coverage_start_month'],
                      'actual_start_month': max(start, row['coverage_start_month']),
                      'complete': all(item['complete'] for item in series)},
            'view': view, 'relative_baseline_month': start if view == 'relative' else None,
            'series': series}
