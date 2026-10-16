"""Supervise all background collectors: python -m app.worker [--check]."""
import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger('hkhub.worker')
WORKERS = (
    'app.modules.commute.worker',
    'app.modules.rent.worker',
    'app.modules.company_observation.worker',
)
HEALTH_ADDRESS = ('127.0.0.1', 8001)
STARTUP_SECONDS = 10
STABLE_SECONDS = 300
SHUTDOWN_SECONDS = 160


@dataclass
class Child:
    module: str
    process: asyncio.subprocess.Process | None = None
    started_at: float = 0.0
    retry_at: float = 0.0
    failures: int = 0


def signal_child(child: Child, sig: signal.Signals) -> None:
    if child.process is None or child.process.returncode is not None:
        return
    try:
        # Separate sessions avoid duplicate terminal signals and include descendants.
        os.killpg(child.process.pid, sig)
    except ProcessLookupError:
        pass


async def stop_children(children: list[Child]) -> None:
    for child in children:
        signal_child(child, signal.SIGTERM)
    processes = [child.process for child in children if child.process is not None]
    if not processes:
        return
    waiting = asyncio.gather(*(process.wait() for process in processes))
    try:
        await asyncio.wait_for(asyncio.shield(waiting), timeout=SHUTDOWN_SECONDS)
    except asyncio.TimeoutError:
        logger.warning('Worker shutdown timed out; terminating remaining children')
        for child in children:
            signal_child(child, signal.SIGKILL)
        await waiting


async def monitor(children: list[Child], stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        for child in children:
            if stop.is_set():
                break
            now = loop.time()
            if child.process is not None:
                if child.process.returncode is None:
                    if now - child.started_at >= STABLE_SECONDS:
                        child.failures = 0
                    continue
                child.failures += 1
                delay = min(60, 2 ** min(child.failures, 6))
                logger.error('Worker exited module=%s code=%s retry_seconds=%s',
                             child.module, child.process.returncode, delay)
                child.process = None
                child.retry_at = now + delay
            if now < child.retry_at:
                continue
            child.process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', child.module,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
            child.started_at = loop.time()
            logger.info('Worker started module=%s pid=%s', child.module, child.process.pid)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass


async def health_connection(writer: asyncio.StreamWriter, children: list[Child],
                            stop: asyncio.Event) -> None:
    now = asyncio.get_running_loop().time()
    healthy = not stop.is_set() and all(
        child.process is not None and child.process.returncode is None
        and now - child.started_at >= STARTUP_SECONDS for child in children
    )
    try:
        writer.write(b'healthy\n' if healthy else b'unhealthy\n')
        await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def run() -> None:
    children = [Child(module) for module in WORKERS]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def handle_health(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await health_connection(writer, children, stop)

    # Loopback only; Compose does not publish this process-health port.
    server = await asyncio.start_server(handle_health, *HEALTH_ADDRESS)
    try:
        async with server:
            await monitor(children, stop)
    finally:
        stop.set()
        await stop_children(children)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def check_health() -> bool:
    try:
        with socket.create_connection(HEALTH_ADDRESS, timeout=3) as connection:
            with connection.makefile('rb') as stream:
                return stream.readline(32) == b'healthy\n'
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description='Run and supervise all HK Hub background workers')
    parser.add_argument('--check', action='store_true', help='Check supervised child processes and exit')
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if check_health() else 1)
    logging.basicConfig(level=settings.log_level,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    try:
        asyncio.run(run())
    except (OSError, RuntimeError):
        logger.exception('Worker supervisor failed')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
