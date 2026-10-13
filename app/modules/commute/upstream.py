"""Upstream access for Immigration Department queue status and MTR next train.

Only the two fixed official hosts below are ever requested, so no client input can
influence a target URL. Functions in this module never decide what to display: they
either return validated values or raise.
"""

from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.modules.commute.ports import (
    DIRECTION_FIELDS,
    HONG_KONG_TZ,
    MTR_LINE,
)

QUEUE_BASE_URL = "https://secure1.info.gov.hk/immd/mobileapps/2bb9ae17/data"
QUEUE_URLS = {
    "resident": f"{QUEUE_BASE_URL}/CPQueueTimeR.json",
    "visitor": f"{QUEUE_BASE_URL}/CPQueueTimeV.json",
}
MTR_SCHEDULE_URL = "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"

# Both payloads are a few kilobytes; anything larger is not the official response.
MAX_PAYLOAD_BYTES = 65536
# The schedule endpoint returns four upcoming trains per direction.
MTR_DEPARTURE_LIMIT = 4
MTR_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _headers() -> dict[str, str]:
    return {"User-Agent": f"HKHub/{settings.version}", "Accept": "application/json"}


def _read_json(response: httpx.Response) -> Any:
    if response.status_code != 200:
        raise ValueError(f"upstream status {response.status_code}")
    if len(response.content) > MAX_PAYLOAD_BYTES:
        raise ValueError("upstream payload too large")
    return response.json()


def fetch_queue_status(audience: str) -> dict[str, dict[str, int]]:
    """Blocking read used by the collector process, never by a request handler."""
    url = QUEUE_URLS[audience]
    with httpx.Client(
        timeout=settings.upstream_timeout_seconds,
        headers=_headers(),
        follow_redirects=False,
    ) as client:
        return parse_queue_status(_read_json(client.get(url)))


def parse_queue_status(payload: Any) -> dict[str, dict[str, int]]:
    """Extract {control point: {direction: status code}} from an official payload.

    A control point or direction that is missing or malformed is omitted, and the
    caller must treat omission as unknown. Official responses have been observed
    without every documented key, so absence is never an error.
    """
    if not isinstance(payload, dict):
        raise ValueError("queue payload is not an object")
    result: dict[str, dict[str, int]] = {}
    for port_code, value in payload.items():
        if not isinstance(port_code, str) or not isinstance(value, dict):
            continue
        directions = {}
        for field, direction in DIRECTION_FIELDS:
            code = value.get(field)
            # bool is an int subclass and is never a valid status code.
            if isinstance(code, int) and not isinstance(code, bool):
                directions[direction] = code
        if directions:
            result[port_code] = directions
    return result


async def fetch_mtr_schedule(client: httpx.AsyncClient, station: str) -> Any:
    """Read the next-train schedule for one MTR station using the shared client."""
    response = await client.get(
        MTR_SCHEDULE_URL,
        params={"line": MTR_LINE, "sta": station},
        timeout=settings.upstream_timeout_seconds,
    )
    return _read_json(response)


def parse_mtr_schedule(payload: Any) -> tuple[list[dict[str, Any]], datetime | None]:
    """Return upcoming departures and the schedule's own Hong Kong local timestamp.

    The reported time type is passed through unchanged, because only some values
    have a verified meaning; callers must not assume every entry is a departure.
    """
    if not isinstance(payload, dict) or payload.get("status") != 1:
        raise ValueError("mtr schedule unavailable")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("mtr schedule payload is not an object")
    departures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    observed_at: datetime | None = None
    for schedule in data.values():
        if not isinstance(schedule, dict):
            continue
        observed_at = observed_at or _local_timestamp(schedule.get("curr_time"))
        for direction, trains in schedule.items():
            if not isinstance(trains, list):
                continue
            for train in trains:
                entry = _departure(train, direction)
                if entry is None:
                    continue
                key = (entry["time"], entry["destination"], entry["platform"])
                if key not in seen:
                    seen.add(key)
                    departures.append(entry)
    departures.sort(key=lambda item: item["time"])
    return departures[:MTR_DEPARTURE_LIMIT], observed_at


def _departure(train: Any, direction: Any) -> dict[str, Any] | None:
    if not isinstance(train, dict) or train.get("valid") != "Y":
        return None
    reported_time = train.get("time")
    if not isinstance(reported_time, str) or not reported_time.strip():
        return None
    minutes = train.get("ttnt")
    return {
        "line": MTR_LINE,
        "direction": direction if isinstance(direction, str) else "",
        "destination": _text(train.get("dest")),
        "platform": _text(train.get("plat")),
        "time": reported_time.strip(),
        "minutes": minutes if isinstance(minutes, int) and not isinstance(minutes, bool) else None,
        "time_type": _text(train.get("timeType")),
    }


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _local_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), MTR_TIMESTAMP_FORMAT).replace(tzinfo=HONG_KONG_TZ)
    except ValueError:
        return None
