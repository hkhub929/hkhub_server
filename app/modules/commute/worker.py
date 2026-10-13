"""Independent collection process: python -m app.modules.commute.worker."""
import asyncio
import json
import logging
import signal
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import dispose_engine, get_engine
from app.modules.commute.catalog import PORTS, QUEUE_CODES, QUEUE_URLS, slot_at

logger = logging.getLogger('hkhub.commute.worker')
MAX_BYTES = 65536
LOCK_ID = 72419201


def normalize(payload: dict) -> dict:
    result = {}
    for port in PORTS:
        values = payload.get(port)
        result[port] = {}
        for direction, field in (('arrival', 'arrQueue'), ('departure', 'depQueue')):
            code = values.get(field) if isinstance(values, dict) else None
            reason = 'missing' if code is None else 'invalid'
            if type(code) is int and code in QUEUE_CODES:
                reason = 'maintenance' if code == 4 else 'closed' if code == 99 else 'available'
            else:
                code = None
            result[port][direction] = {'code': code, 'reason': reason}
    return result


async def fetch(client: httpx.AsyncClient, url: str) -> dict:
    async with client.stream('GET', url) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError('Upstream response too large')
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError('Invalid upstream object')
    return normalize(payload)


async def collect(client: httpx.AsyncClient) -> None:
    # All collectors cooperate on one transaction-scoped database lock.
    with get_engine().begin() as connection:
        locked = connection.execute(text('SELECT pg_try_advisory_xact_lock(:key)'),
                                    {'key': LOCK_ID}).scalar()
        if not locked:
            return
        for audience, url in QUEUE_URLS.items():
            day, slot = slot_at(datetime.now(timezone.utc))
            existing = connection.execute(text('''
                SELECT fetched_at, attempt_count, attempted_at FROM commute_observations
                WHERE audience=:audience AND hk_date=:day AND hk_slot=:slot
            '''), {'audience': audience, 'day': day, 'slot': slot}).first()
            if existing is not None:
                if existing.fetched_at is not None or existing.attempt_count >= 3:
                    continue
                if (datetime.now(timezone.utc) - existing.attempted_at).total_seconds() < 60:
                    continue
            payload, error_code = None, None
            try:
                payload = await asyncio.wait_for(fetch(client, url),
                                                 timeout=settings.upstream_timeout_seconds)
            except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as error:
                error_code = 'upstream_unavailable'
                logger.warning('Collection failed audience=%s type=%s', audience, type(error).__name__)
            moment = datetime.now(timezone.utc)
            day, slot = slot_at(moment)  # Never backfill the slot in which a request started.
            connection.execute(text('''
                INSERT INTO commute_observations
                    (audience, hk_date, hk_slot, attempted_at, fetched_at, payload, error_code)
                VALUES (:audience, :day, :slot, :moment, :fetched, CAST(:payload AS jsonb), :error)
                ON CONFLICT (audience, hk_date, hk_slot) DO UPDATE SET
                    attempted_at=EXCLUDED.attempted_at, fetched_at=EXCLUDED.fetched_at,
                    payload=EXCLUDED.payload, error_code=EXCLUDED.error_code,
                    attempt_count=commute_observations.attempt_count + 1
                WHERE commute_observations.fetched_at IS NULL
                  AND commute_observations.attempt_count < 3
            '''), {'audience': audience, 'day': day, 'slot': slot, 'moment': moment,
                  'fetched': moment if payload is not None else None,
                  'payload': json.dumps(payload) if payload is not None else None,
                  'error': error_code})
            logger.info('Collection stored audience=%s date=%s slot=%s success=%s',
                        audience, day, slot, payload is not None)
        connection.execute(text('DELETE FROM commute_observations WHERE attempted_at < :cutoff'),
                           {'cutoff': datetime.now(timezone.utc) - timedelta(days=30)})


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds, follow_redirects=False,
        headers={'User-Agent': f'HKHub/{settings.version}'},
    ) as client:
        while not stop.is_set():
            try:
                await collect(client)
            except SQLAlchemyError as error:
                logger.error('Collection database failure type=%s', type(error).__name__)
            now = datetime.now(timezone.utc)
            # Successful slots are skipped; failures retry at most twice, one minute apart.
            next_slot = 900 - (now.minute % 15 * 60 + now.second)
            try:
                await asyncio.wait_for(stop.wait(), timeout=min(60, max(1, next_slot)))
            except asyncio.TimeoutError:
                pass


def main() -> None:
    logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run())
    finally:
        dispose_engine()


if __name__ == '__main__':
    main()
