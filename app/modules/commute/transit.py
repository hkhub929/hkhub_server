import asyncio
import json
import logging
from datetime import datetime, timezone
from time import monotonic

import httpx

from app.modules.commute.catalog import HK, copy_text
from app.modules.commute.schemas import Departure, TransitResponse, TransitRoute

logger = logging.getLogger(__name__)
MTR_URL = 'https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php'
# Verified official route-stop and stop responses, 2026-10-13. Only HK-bound departures.
BUS_ROUTES = {
    'LSC': [('KMB', 'B1', '81567ACCCF40DD4B',
             ('落马洲站 · 福田口岸', '落馬洲站 · 福田口岸', 'Lok Ma Chau Station / Futian Port'),
             ('天慈', '天慈', 'Tin Tsz'), '22.515533,114.066508')],
    'SBC': [('CTB', route, '003208', ('深圳湾口岸', '深圳灣口岸', 'Shenzhen Bay Port'),
             destination, '22.501662252091,113.94518812053')
            for route, destination in (
                ('B3', ('屯门码头', '屯門碼頭', 'Tuen Mun Ferry Pier')),
                ('B3X', ('屯门市中心', '屯門市中心', 'Tuen Mun Town Centre')),
            )],
}
MTR_STATIONS = {
    'ADM': ('金钟', '金鐘', 'Admiralty'),
    'HUH': ('红磡', '紅磡', 'Hung Hom'),
    'SHT': ('沙田', '沙田', 'Sha Tin'),
    'TAW': ('大围', '大圍', 'Tai Wai'),
    'SHS': ('上水', '上水', 'Sheung Shui'),
}


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.replace(tzinfo=HK) if result.tzinfo is None else result
    except ValueError:
        return None


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict:
    async with client.stream('GET', url, timeout=8, follow_redirects=False) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 262144:
                raise ValueError('Transit response too large')
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError('Invalid transit object')
    return payload


def fresh(value: datetime | None, now: datetime) -> bool:
    return value is not None and -60 <= (now - value).total_seconds() < 120


async def mtr(client: httpx.AsyncClient, port: str, language: str) -> TransitRoute:
    station = 'LOW' if port == 'LWS' else 'LMC'
    url = f'{MTR_URL}?line=EAL&sta={station}'
    route = TransitRoute(
        id=f'mtr-EAL-{station}-DOWN', mode='mtr', operator='MTR',
        route=copy_text(('东铁线', '東鐵綫', 'East Rail Line'), language),
        stop=copy_text(('罗湖站', '羅湖站', 'Lo Wu') if station == 'LOW'
                       else ('落马洲站', '落馬洲站', 'Lok Ma Chau'), language),
        destination=copy_text(MTR_STATIONS['ADM'], language), source_url=url,
        map_url=('https://www.google.com/maps/search/?api=1&query='
                 + ('Lo+Wu+MTR+Station+Hong+Kong' if station == 'LOW'
                    else 'Lok+Ma+Chau+MTR+Station+Hong+Kong')),
    )
    try:
        payload = await asyncio.wait_for(fetch_json(client, url), timeout=8)
        now = datetime.now(timezone.utc)
        route.fetched_at = now
        if payload.get('status') != 1:
            return route
        data = payload.get('data', {}).get(f'EAL-{station}')
        if not isinstance(data, dict) or not fresh(timestamp(data.get('curr_time')), now):
            return route
        route.delayed = payload.get('isdelay') == 'Y'
        for entry in data.get('DOWN', []):
            if not isinstance(entry, dict) or entry.get('valid') != 'Y' or entry.get('timeType') != 'D':
                continue
            when = timestamp(entry.get('time'))
            if when is None or when < now:
                continue
            dest = entry.get('dest', '')
            destination = copy_text(MTR_STATIONS[dest], language) if dest in MTR_STATIONS else str(dest)
            route.departures.append(Departure(
                time=when, kind='departure', platform=str(entry.get('plat', '')),
                destination=destination, data_time=timestamp(data.get('curr_time')),
            ))
        route.departures = sorted(route.departures, key=lambda item: item.time)[:3]
        route.state = 'available' if route.departures else 'no_departures'
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, asyncio.TimeoutError) as error:
        logger.warning('MTR unavailable station=%s type=%s', station, type(error).__name__)
    return route


async def bus(client: httpx.AsyncClient, definition: tuple, language: str) -> TransitRoute:
    operator, number, stop, stop_name, destination, coordinates = definition
    url = (f'https://data.etabus.gov.hk/v1/transport/kmb/eta/{stop}/{number}/1'
           if operator == 'KMB' else
           f'https://rt.data.gov.hk/v2/transport/citybus/eta/CTB/{stop}/{number}')
    route = TransitRoute(
        id=f'{operator}-{number}-{stop}-I', mode='bus', operator=operator, route=number,
        stop=copy_text(stop_name, language), destination=copy_text(destination, language),
        map_url=f'https://www.google.com/maps/search/?api=1&query={coordinates}', source_url=url,
    )
    try:
        payload = await asyncio.wait_for(fetch_json(client, url), timeout=8)
        now = datetime.now(timezone.utc)
        route.fetched_at = now
        if not fresh(timestamp(payload.get('generated_timestamp')), now):
            return route
        entries = payload.get('data')
        if not isinstance(entries, list):
            return route
        matched = [entry for entry in entries if isinstance(entry, dict)
                   and entry.get('co') == operator and entry.get('route') == number
                   and entry.get('dir') == 'I' and str(entry.get('seq')) == '1'
                   and (operator != 'KMB' or str(entry.get('service_type')) == '1')]
        # Empty ETA never means the route has stopped operating.
        if matched and not any(fresh(timestamp(entry.get('data_timestamp')), now) for entry in matched):
            return route
        suffix = 'en' if language == 'en' else 'sc' if language == 'zh-Hans' else 'tc'
        seen = set()
        for entry in matched:
            when = timestamp(entry.get('eta'))
            if when is None or when < now or when in seen:
                continue
            if not fresh(timestamp(entry.get('data_timestamp')), now):
                continue
            seen.add(when)
            scheduled = ('scheduled' in str(entry.get('rmk_en', '')).lower()
                         or '原定班次' in str(entry.get('rmk_tc', '')))
            route.departures.append(Departure(
                time=when, kind='scheduled_arrival' if scheduled else 'estimated_arrival',
                destination=str(entry.get(f'dest_{suffix}') or route.destination),
                remark=str(entry.get(f'rmk_{suffix}') or ''),
                data_time=timestamp(entry.get('data_timestamp')),
            ))
        route.departures = sorted(route.departures, key=lambda item: item.time)[:3]
        route.state = 'available' if route.departures else 'no_departures'
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, asyncio.TimeoutError) as error:
        logger.warning('Bus unavailable operator=%s route=%s type=%s', operator, number, type(error).__name__)
    return route


async def read_transit(client: httpx.AsyncClient, port: str, language: str, cache: dict) -> TransitResponse:
    key = (port, language)
    entry = cache.setdefault(key, {'lock': asyncio.Lock(), 'expires': 0, 'items': []})
    async with entry['lock']:
        if monotonic() >= entry['expires']:
            jobs = [bus(client, definition, language) for definition in BUS_ROUTES.get(port, [])]
            if port in ('LWS', 'LSC'):
                jobs.insert(0, mtr(client, port, language))
            entry['items'] = await asyncio.gather(*jobs)
            entry['expires'] = monotonic() + 60
    return TransitResponse(server_time=datetime.now(timezone.utc), items=entry['items'])
