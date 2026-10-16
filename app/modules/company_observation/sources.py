"""Allowlisted CKAN discovery and strict official UTF-8 CSV parsing."""
import calendar
import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from app.core.config import settings

CATALOG = 'https://data.gov.hk/en-data/api/3/action/package_show'
DATASET = 'hk-cr-crdata-list-newly-registered-companies-2526'
LIQUIDATIONS = 'https://www.cr.gov.hk/datagovhk/psi/statistics_05.csv'
PARSER_VERSION = 'cr-utf8-registration-v2'
COMMON_COLUMNS = ['Seq', 'Current Company Name in English', 'Current Company Name in Chinese',
                  'BR Number']
COMBINED_COLUMN = 'Date of Incorporation / Re-domiciliation Date'


@dataclass(frozen=True)
class Resource:
    id: str
    url: str
    start: date
    end: date
    published_date: date | None


def safe_url(url: str) -> None:
    uri = urlsplit(url)
    allowed = (uri.hostname == 'data.gov.hk' and uri.path == '/en-data/api/3/action/package_show')
    allowed |= (uri.hostname == 'www.cr.gov.hk' and
                (re.fullmatch(r'/docs/wrpt/RNC063/RNC063L_\d{8}\.csv', uri.path) is not None
                 or uri.path == '/datagovhk/psi/statistics_05.csv'))
    if (not allowed or uri.scheme != 'https' or uri.port not in (None, 443)
            or uri.username or uri.password or uri.fragment or uri.query):
        raise ValueError('source_url_invalid')


async def download(client: httpx.AsyncClient, url: str, params: dict | None = None) -> bytes:
    safe_url(url)
    body = bytearray()
    async with client.stream('GET', url, params=params,
                             timeout=settings.company_observation_source_timeout_seconds) as response:
        response.raise_for_status()
        if 'text/html' in response.headers.get('content-type', '').lower():
            raise ValueError('source_invalid')
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > settings.company_observation_max_download_bytes:
                raise ValueError('source_too_large')
    if not body:
        raise ValueError('source_empty')
    return bytes(body)


async def discover(client: httpx.AsyncClient) -> list[Resource]:
    payload = json.loads(await download(client, CATALOG, {'id': DATASET}))
    if payload.get('success') is not True:
        raise ValueError('catalog_invalid')
    resources = []
    for item in payload['result']['resources']:
        if item.get('format', '').upper() != 'CSV' or item.get('state') != 'active':
            continue
        if 'RNC063L_' not in item.get('url', ''):
            continue
        safe_url(item['url'])
        match = re.search(r'\((\d{1,2} [A-Za-z]+ \d{4}) to (\d{1,2} [A-Za-z]+ \d{4})\)',
                          item.get('name', ''))
        if not match:
            raise ValueError('coverage_invalid')
        start, last = (datetime.strptime(value, '%d %B %Y').date() for value in match.groups())
        if start.weekday() != 0 or last - start != timedelta(days=6):
            raise ValueError('coverage_invalid')
        publication = date.fromisoformat(item['datePublished']) if item.get('datePublished') else None
        resources.append(Resource(item['id'], item['url'], start, last + timedelta(days=1), publication))
    if not resources or len({item.start for item in resources}) != len(resources):
        raise ValueError('catalog_invalid')
    return sorted(resources, key=lambda item: item.start, reverse=True)


def csv_rows(body: bytes) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(body.decode('utf-8-sig')), strict=True))
    if not rows or len(rows) > settings.company_observation_max_source_rows:
        raise ValueError('source_invalid')
    return rows


def source_date(value: str) -> date:
    for pattern in ('%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError('date_invalid')


def parse_companies(body: bytes, resource: Resource) -> tuple[list[dict], dict, str]:
    rows = csv_rows(body)
    header = [value.strip() for value in rows[0]]
    if (len(header) != 6 or header[:4] != COMMON_COLUMNS
            or header[4] not in ('Date of Incorporation', COMBINED_COLUMN)
            or header[5] != 'Date of Change of name'):
        raise ValueError('schema_invalid')
    combined = header[4] == COMBINED_COLUMN
    records, stats = [], {'raw_rows': 0, 'valid_rows': 0, 'excluded_rows': 0,
                          'ambiguous_rows': 0, 'invalid_rows': 0, 'duplicate_rows': 0,
                          'date_semantics': 'incorporation_or_redomiciliation' if combined else 'incorporation',
                          'population_scope': 'incorporation_and_redomiciliation'}
    seen = set()
    for index, row in enumerate(rows[1:], 2):
        if not any(value.strip() for value in row):
            continue
        stats['raw_rows'] += 1
        record = parse_company_row(row, index, resource, combined)
        if record['error_code']:
            key = 'invalid_rows'
        elif record['event_type'] in ('incorporation', 'incorporation_or_redomiciliation'):
            key = 'valid_rows'
        else:
            key = 'excluded_rows'
        stats[key] += 1
        identity = (record['company_key'], record['incorporation_date'], record['name_en'], record['name_zh'])
        if key == 'valid_rows' and identity in seen:
            stats['duplicate_rows'] += 1
        seen.add(identity)
        records.append(record)
    # Combined dates establish the combined population, not separate incorporation counts.
    status = 'partial' if stats['invalid_rows'] else 'complete'
    stats['reason_code'] = 'source_invalid' if stats['invalid_rows'] else None
    return records, stats, status


def parse_company_row(row: list[str], index: int, resource: Resource, combined: bool) -> dict:
    record = {'row_locator': index, 'company_key': None, 'identifier_type': 'brn',
              'identifier_value': None, 'name_en': '', 'name_zh': '',
              'incorporation_date': None, 'event_type': 'invalid', 'error_code': None}
    try:
        if len(row) != 6:
            raise ValueError('row_invalid')
        _, english, chinese, identifier, incorporation, changed = row
        record.update(name_en=english, name_zh=chinese, identifier_value=identifier,
                      company_key=f'brn:{identifier}')
        if not re.fullmatch(r'[A-Za-z0-9]{1,32}', identifier) or not (english or chinese):
            raise ValueError('identity_invalid')
        for value in (incorporation, changed):
            if value and not resource.start <= source_date(value) < resource.end:
                raise ValueError('date_outside_coverage')
        if incorporation:
            # Legacy database column stores the official event date, not necessarily company creation.
            record.update(incorporation_date=source_date(incorporation),
                          event_type='incorporation_or_redomiciliation' if combined else 'incorporation')
        elif changed:
            record['event_type'] = 'name_change'
        else:
            raise ValueError('event_missing')
    except ValueError as error:
        record['error_code'] = str(error)
    return record


def parse_liquidations(body: bytes) -> list[dict]:
    rows = csv_rows(body)
    expected = ['Year', 'Month', 'In_Progress_Members', 'Commenced_Members',
                'In_Progress_Creditors', 'Commenced_Creditors']
    if rows[0] != expected:
        raise ValueError('liquidation_schema_invalid')
    months = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
    result, seen = [], set()
    for row in rows[1:]:
        if not any(value.strip() for value in row):
            continue
        if len(row) != 6:
            raise ValueError('liquidation_row_invalid')
        year, month, progress_m, commenced_m, progress_c, commenced_c = [value.strip() for value in row]
        start = date(int(year), months[month.lower()], 1)
        if start in seen:
            raise ValueError('liquidation_duplicate')
        seen.add(start)
        counts = [int(value) for value in (commenced_m, commenced_c, progress_m, progress_c)]
        if any(value < 0 for value in counts):
            raise ValueError('liquidation_count_invalid')
        result.append(dict(month_start=start, members_commenced=counts[0], creditors_commenced=counts[1],
                           members_in_progress=counts[2], creditors_in_progress=counts[3]))
    if not result:
        raise ValueError('liquidation_empty')
    return result
