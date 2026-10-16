"""Independent process: python -m app.modules.company_observation.worker [--once]."""
import argparse
import asyncio
import hashlib
import json
import logging
import signal

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import dispose_engine, get_engine
from app.modules.company_observation.calendar import period_end
from app.modules.company_observation.sources import (
    LIQUIDATIONS, Resource, discover, download, parse_companies, parse_liquidations,
)
from app.modules.company_observation.storage import (
    build_snapshots, claim_collection, finish_collection, renew_collection, save_source,
    stored_source, stored_source_ids,
)

logger = logging.getLogger('hkhub.company.worker')


async def collect_liquidations(client: httpx.AsyncClient, token: str) -> None:
    try:
        renew_collection(token)
        body = await download(client, LIQUIDATIONS)
        records = parse_liquidations(body)
        digest = hashlib.sha256(body).hexdigest()
        resource = Resource('cr-liquidations', LIQUIDATIONS, min(row['month_start'] for row in records),
                            period_end('month', max(row['month_start'] for row in records)), None)
        save_source(resource, body, [], {'valid_rows': len(records)}, 'complete', token)
        with get_engine().begin() as conn:
            owner = conn.execute(text('''SELECT name FROM company_worker_state WHERE name='sources'
                AND claim_token=:token AND lease_until>now() FOR UPDATE'''), {'token': token}).first()
            if not owner:
                raise ValueError('collection_lease_lost')
            conn.execute(text('''INSERT INTO company_liquidation_statistics(source_sha256, month_start,
                members_commenced, creditors_commenced, members_in_progress, creditors_in_progress,
                source_url, fetched_at) VALUES (:sha, :month_start, :members_commenced,
                :creditors_commenced, :members_in_progress, :creditors_in_progress, :url, now())
                ON CONFLICT DO NOTHING'''), [{'sha': digest, 'url': LIQUIDATIONS, **row} for row in records])
            conn.execute(text('''INSERT INTO company_worker_state(name, last_success_at, last_attempt_at, payload)
                VALUES ('liquidations', now(), now(), CAST(:payload AS jsonb))
                ON CONFLICT(name) DO UPDATE SET last_success_at=now(), last_attempt_at=now(),
                    error_code=NULL, payload=EXCLUDED.payload
            '''), {'payload': json.dumps({'sha256': digest})})
    except (httpx.HTTPError, ValueError, KeyError, UnicodeError) as error:
        logger.warning('Liquidation collection failed type=%s', type(error).__name__)
        with get_engine().begin() as conn:
            conn.execute(text('''INSERT INTO company_worker_state(name, last_attempt_at, error_code)
                VALUES ('liquidations', now(), 'source_unavailable')
                ON CONFLICT(name) DO UPDATE SET last_attempt_at=now(), error_code='source_unavailable'
            '''))


async def collect_sources(client: httpx.AsyncClient, stop: asyncio.Event) -> None:
    token = claim_collection()
    if token is None:
        return
    resources, error_code = None, None
    try:
        # Liquidations are independent and must not wait for historical company backfill.
        await collect_liquidations(client, token)
        resources = await discover(client)
        stored = stored_source_ids()
        skipped = sum(resource.id in stored for resource in resources)
        logger.info('Company sources checked resources=%s stored=%s missing=%s',
                    len(resources), skipped, len(resources) - skipped)
        for resource in resources:
            if stop.is_set():
                error_code = 'collection_interrupted'
                return
            if resource.id in stored:
                continue
            renew_collection(token)
            try:
                saved = stored_source(resource.id)
                if saved is None:
                    body = await download(client, resource.url)
                else:
                    resource, body = saved['resource'], saved['body']
                    logger.info('Company source reparsing stored CSV resource=%s', resource.id)
                try:
                    records, diagnostics, status = parse_companies(body, resource)
                except (ValueError, UnicodeError) as error:
                    records, diagnostics, status = [], {'reason_code': 'source_invalid'}, 'invalid'
                    logger.warning('Company source invalid resource=%s type=%s', resource.id, type(error).__name__)
                save_source(resource, body, records, diagnostics, status, token,
                            fetched_at=saved['fetched_at'] if saved else None)
            except (httpx.HTTPError, ValueError) as error:
                error_code = 'source_unavailable'
                logger.warning('Company collection failed resource=%s type=%s', resource.id, type(error).__name__)
        build_snapshots(resources, token)
        logger.info('Company snapshots refreshed resources=%s', len(resources))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        error_code = 'source_unavailable'
        logger.warning('Company catalog unavailable type=%s', type(error).__name__)
    finally:
        finish_collection(token, resources, error_code)


async def run(once: bool) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    next_collection = 0.0
    async with httpx.AsyncClient(timeout=settings.company_observation_source_timeout_seconds,
        follow_redirects=False, headers={'User-Agent': f'HKHub/{settings.version}'}) as client:
        while not stop.is_set():
            try:
                if settings.company_observation_enabled and loop.time() >= next_collection:
                    await collect_sources(client, stop)
                    next_collection = loop.time() + settings.company_observation_poll_seconds
            except SQLAlchemyError as error:
                logger.error('Company worker database failure type=%s', type(error).__name__)
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description='Collect official company sources and build period snapshots')
    parser.add_argument('--once', action='store_true', help='One collection pass')
    args = parser.parse_args()
    logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run(args.once))
    finally:
        dispose_engine()


if __name__ == '__main__':
    main()
