"""Standalone scheduler that records Immigration Department queue observations.

Run as `python -m app.modules.commute.collector` (or `./cmd.sh collector`), for example
from the collector service in docker-compose.prod.yml. The API only reads stored
observations, so this process must keep running for current status to stay available.

Sampling is a schedule, not proof that the department published a new assessment: a
repeated request can legitimately return the same code. Observations are therefore
labelled with the moment they were received.
"""

import logging
import math
import signal
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import database_url, dispose_engine, get_engine
from app.modules.commute import repository, upstream
from app.modules.commute.ports import AUDIENCES, DIRECTIONS, HONG_KONG_TZ, hk_window

logger = logging.getLogger("hkhub.commute.collector")
SOURCE = "immd_opendata"


def collect_once() -> int:
    """Sample both audiences and store one row per control point, window and direction."""
    rows: list[dict[str, Any]] = []
    for audience in AUDIENCES:
        try:
            statuses = upstream.fetch_queue_status(audience)
        except Exception as error:
            # A failed audience leaves a gap in the history instead of fake data,
            # and must not stop the other audience from being recorded.
            logger.warning(
                "Queue fetch failed audience=%s type=%s", audience, type(error).__name__
            )
            continue
        observed_at = datetime.now(timezone.utc)
        hk_date, slot = hk_window(observed_at)
        for port_code, directions in statuses.items():
            for direction in DIRECTIONS:
                code = directions.get(direction)
                if code is None:
                    continue
                rows.append(
                    repository.observation_row(
                        port_code=port_code,
                        audience=audience,
                        direction=direction,
                        status_code=code,
                        hk_date=hk_date,
                        hk_slot=slot,
                        observed_at=observed_at,
                        source=SOURCE,
                    )
                )
    if not rows:
        logger.warning("No queue observations collected")
        return 0
    with Session(get_engine(), autoflush=False, expire_on_commit=False) as session:
        try:
            saved = repository.save_observations(session, rows)
            session.commit()
        except Exception:
            session.rollback()
            raise
    logger.info("Queue observations stored sampled=%s saved=%s", len(rows), saved)
    return saved


def cleanup_expired() -> int:
    """Delete observations past the retention window so the table cannot grow forever."""
    cutoff_date = datetime.now(HONG_KONG_TZ).date() - timedelta(
        days=settings.commute_retention_days
    )
    with Session(get_engine(), autoflush=False, expire_on_commit=False) as session:
        try:
            deleted = repository.delete_expired(session, cutoff_date)
            session.commit()
        except Exception:
            session.rollback()
            raise
    if deleted:
        logger.info("Queue observations pruned deleted=%s cutoff=%s", deleted, cutoff_date)
    return deleted


def seconds_until_next_slot() -> float:
    """Seconds until the next aligned boundary.

    UTC epoch alignment matches Hong Kong wall-clock alignment because the fixed
    UTC+8 offset is an exact multiple of every supported interval.
    """
    interval = max(1, settings.commute_collect_interval_minutes) * 60
    now = datetime.now(timezone.utc).timestamp()
    return (math.floor(now / interval) + 1) * interval - now


def run_forever() -> None:
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, lambda *_: stop.set())
    database_url()  # Fail fast rather than looping without a database.
    logger.info(
        "Commute collector started interval_minutes=%s retention_days=%s",
        settings.commute_collect_interval_minutes,
        settings.commute_retention_days,
    )
    last_cleanup_date: Any = None
    while not stop.is_set():
        try:
            collect_once()
        except Exception:
            logger.exception("Queue collection failed")
        today = datetime.now(HONG_KONG_TZ).date()
        if today != last_cleanup_date:
            try:
                cleanup_expired()
                last_cleanup_date = today
            except Exception:
                logger.exception("Queue retention cleanup failed")
        stop.wait(seconds_until_next_slot())
    dispose_engine()
    logger.info("Commute collector stopped")


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_forever()


if __name__ == "__main__":
    main()
