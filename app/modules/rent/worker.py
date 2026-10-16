"""Daily independent collector: python -m app.modules.rent.worker [--once]."""
import argparse
import asyncio
import logging
import signal

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import dispose_engine
from app.modules.rent.catalog import SOURCES
from app.modules.rent.parser import parse_csv
from app.modules.rent.store import claim, fail, publish

logger = logging.getLogger('hkhub.rent.worker')
MAX_BYTES = 2 * 1024 * 1024


async def download(client: httpx.AsyncClient, source_id: str) -> bytes:
    # Fixed HTTPS origins; redirects are deliberately rejected rather than followed.
    async with client.stream('GET', SOURCES[source_id]['url']) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected upstream status')
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError('Source response exceeds size limit')
    return bytes(body)


async def collect(client: httpx.AsyncClient) -> bool:
    success = True
    for source_id in SOURCES:
        try:
            attempt = claim(source_id)
            if attempt is None:
                continue
            try:
                body = await asyncio.wait_for(download(client, source_id), timeout=45)
                payload = parse_csv(source_id, body)
                publish(source_id, attempt, payload)
                logger.info('Rental source checked source=%s through=%s', source_id,
                            payload['coverage_end_month'])
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError, UnicodeError) as error:
                code = 'invalid_source' if isinstance(error, ValueError) else 'upstream_unavailable'
                fail(source_id, attempt, code)
                success = False
                logger.warning('Rental collection failed source=%s type=%s', source_id, type(error).__name__)
        except SQLAlchemyError as error:
            success = False
            logger.error('Rental database failure source=%s type=%s', source_id, type(error).__name__)
    return success


async def run(once: bool) -> bool:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds, follow_redirects=False,
                                 headers={'User-Agent': f'HKHub/{settings.version}'}) as client:
        while not stop.is_set():
            success = await collect(client)
            if once:
                return success
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description='Collect RVD monthly rental statistics')
    parser.add_argument('--once', action='store_true', help='Check due sources once and exit')
    args = parser.parse_args()
    logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(message)s')
    try:
        if not asyncio.run(run(args.once)):
            raise SystemExit(1)
    finally:
        dispose_engine()


if __name__ == '__main__':
    main()
