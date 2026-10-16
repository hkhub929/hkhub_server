import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.modules.rent.catalog import SOURCES, catalog


def parse_point(raw: str, flag: str, month: str) -> dict:
    if flag not in {'', 'P', 'Z', 'PZ'}:
        raise ValueError('Unknown source remark')
    if raw == '-':
        value, missing = None, 'no_transactions'
    else:
        try:
            number = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError('Invalid source number') from error
        if (not number.is_finite() or number <= 0 or number.adjusted() > 6
                or number.adjusted() < -6 or len(number.as_tuple().digits) > 12):
            raise ValueError('Invalid rental value or source precision changed')
        value, missing = str(number), None
    return {'month': month, 'value': value, 'source_flag': flag,
            'quality_status': 'provisional' if 'P' in flag else 'published',
            'small_sample': 'Z' in flag, 'missing_reason': missing,
            'comparability_break': False}


def parse_csv(source_id: str, body: bytes) -> dict:
    text = body.decode('utf-8-sig', errors='strict')
    if '<html' in text.lower() or '\x00' in text:
        raise ValueError('Not a CSV document')
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as error:
        raise ValueError('Malformed source CSV') from error
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    definitions = catalog(source_id)
    header = ['Month']
    # CSV column order differs from our display order (All Classes first).
    source_columns = ([f'Class {code}' for code in 'ABCDE'] +
                      ['Classes A, B & C', 'Classes D & E', 'All Classes']
                      if source_id == 'rental_index' else
                      [item['source_column'] for item in definitions])
    for column in source_columns:
        header.extend([column, f'{column} - Remarks'])
    if len(rows) < 63 or ' '.join(rows[0][0].split()) != SOURCES[source_id]['title']:
        raise ValueError('Unexpected CSV title or insufficient history')
    if rows[1] != header:
        raise ValueError('Source columns changed; review mapping before publication')
    positions = {name: index for index, name in enumerate(header)}
    data = {item['series_id']: [] for item in definitions}
    months = []
    current = datetime.now(timezone.utc).strftime('%Y-%m')
    for row in rows[2:]:
        if len(row) != len(header) or not re.fullmatch(r'(0[1-9]|1[0-2])-\d{4}', row[0]):
            raise ValueError('Invalid CSV row or month')
        month = f'{row[0][3:]}-{row[0][:2]}'
        if month > current or (months and month <= months[-1]):
            raise ValueError('Future, duplicate or unordered source month')
        months.append(month)
        for item in definitions:
            position = positions[item['source_column']]
            data[item['series_id']].append(parse_point(row[position].strip(),
                                                       row[position + 1].strip(), month))
    if months[0] != SOURCES[source_id]['start']:
        raise ValueError('Source history start changed')
    if not any(points[-1]['value'] is not None for points in data.values()):
        raise ValueError('No values at source anchor month')
    return {'catalog': definitions, 'series_data': data, 'months': months,
            'coverage_start_month': months[0], 'coverage_end_month': months[-1]}
