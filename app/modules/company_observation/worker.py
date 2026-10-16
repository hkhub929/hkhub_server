"""Independent process: python -m app.modules.company_observation.worker [--once]."""
import argparse
import asyncio
import hashlib
import json
import logging
import signal

import httpx
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import dispose_engine, get_engine
from app.modules.company_observation.analysis import analyse_report
from app.modules.company_observation.analysis_jobs import BudgetExceeded, claim_report, fail_report
from app.modules.company_observation.calendar import period_end
from app.modules.company_observation.sources import (
    LIQUIDATIONS, Resource, discover, download, parse_companies, parse_liquidations,
)
from app.modules.company_observation.storage import (
    build_snapshots, claim_collection, finish_collection, renew_collection, save_source,
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
        for resource in resources:
            if stop.is_set():
                error_code = 'collection_interrupted'
                return
            renew_collection(token)
            try:
                body = await download(client, resource.url)
                try:
                    records, diagnostics, status = parse_companies(body, resource)
                except (ValueError, UnicodeError) as error:
                    records, diagnostics, status = [], {'reason_code': 'source_invalid'}, 'invalid'
                    logger.warning('Company source invalid resource=%s type=%s', resource.id, type(error).__name__)
                save_source(resource, body, records, diagnostics, status, token)
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


def analysis_failure(error: Exception) -> tuple[str, str]:
    """Keep diagnostics bounded and never log credentials, response bodies or AI input."""
    if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError)):
        return 'analysis_timeout', type(error).__name__
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        code = {401: 'analysis_auth_failed', 403: 'analysis_access_denied',
                402: 'analysis_balance_insufficient', 429: 'analysis_rate_limited',
                400: 'analysis_request_invalid', 404: 'analysis_model_unavailable',
                422: 'analysis_request_invalid'}.get(status, 'analysis_upstream_failed')
        return code, f'http_status={status}'
    if isinstance(error, httpx.HTTPError):
        return 'analysis_connection_failed', type(error).__name__
    if isinstance(error, ValidationError):
        # Error types and count are safe; validation inputs and messages may contain AI text.
        kinds = sorted({item['type'] for item in error.errors(include_input=False,
                                                               include_context=False, include_url=False)})
        return 'analysis_schema_invalid', f'validation_count={error.error_count()} types={",".join(kinds)}'
    known = {'analysis_response_too_large', 'analysis_truncated', 'analysis_merge_limit',
             'analysis_metric_invalid', 'analysis_population_invalid', 'analysis_batch_incomplete',
             'analysis_evidence_invalid', 'analysis_merge_invalid', 'analysis_lease_lost', 'analysis_invalid'}
    if type(error) is ValueError and str(error) in known:
        return str(error), type(error).__name__
    return 'analysis_invalid', type(error).__name__


async def process_analysis(client: httpx.AsyncClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        report = claim_report()
        if report is None:
            return
        try:
            await analyse_report(client, report)
            logger.info('Company analysis published report=%s', report['id'])
        except BudgetExceeded as error:
            code = 'analysis_daily_budget_exceeded' if error.daily else 'analysis_report_budget_exceeded'
            logger.warning('Company analysis paused report=%s code=%s', report['id'], code)
            fail_report(report, code, budget=error.daily)
            if error.daily:
                return
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as error:
            code, detail = analysis_failure(error)
            logger.warning('Company analysis failed report=%s code=%s detail=%s', report['id'], code, detail)
            fail_report(report, code)


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
                if settings.company_observation_enabled:
                    if loop.time() >= next_collection:
                        await collect_sources(client, stop)
                        next_collection = loop.time() + settings.company_observation_poll_seconds
                    await process_analysis(client, stop)
            except SQLAlchemyError as error:
                logger.error('Company worker database failure type=%s', type(error).__name__)
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description='Collect official company sources and analyse full periods')
    parser.add_argument('--once', action='store_true', help='One collection and bounded analysis pass')
    args = parser.parse_args()
    logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run(args.once))
    finally:
        dispose_engine()


if __name__ == '__main__':
    main()
