"""Response contract for the cross-border commute module.

Field names are stable machine-readable values. "Usually under N minutes" wording
derived from the official dictionary is presentation copy and lives in the app, so a
threshold change needs no server contract change.
"""

from typing import Literal

from pydantic import BaseModel

StatusName = Literal["normal", "busy", "very_busy", "maintenance", "non_service", "unknown"]
Audience = Literal["resident", "visitor"]
Freshness = Literal["fresh", "stale", "missing"]


class QueueState(BaseModel):
    """One audience's Hong Kong inbound queue status for one control point."""

    status: StatusName
    status_code: int | None
    observed_at: str | None
    state: Freshness


class PortQueueStatus(BaseModel):
    port_code: str
    resident: QueueState
    visitor: QueueState


class BordersResponse(BaseModel):
    schema_version: Literal[1] = 1
    generated_at: str
    ports: list[PortQueueStatus]


class HistoryDay(BaseModel):
    hk_date: str
    status: StatusName
    status_code: int | None
    observed_at: str | None


class HistoryResponse(BaseModel):
    """Same local window comparison; counts describe ordered levels, not minutes."""

    schema_version: Literal[1] = 1
    port_code: str
    audience: Audience
    generated_at: str
    hk_date: str
    hk_slot: int
    current: QueueState
    days: list[HistoryDay]
    valid_days: int
    lower_days: int
    same_days: int
    higher_days: int
    conclusive: bool


class TransitDeparture(BaseModel):
    """One upcoming train; mode keeps room for a verified bus source later."""

    mode: Literal["mtr"] = "mtr"
    line: str
    direction: str
    destination: str
    platform: str
    time: str
    minutes: int | None
    time_type: str


class TransitSource(BaseModel):
    kind: str
    state: Literal["ok", "unavailable", "unverified"]
    observed_at: str | None = None
    reason: str | None = None


class TransitResponse(BaseModel):
    schema_version: Literal[1] = 1
    port_code: str
    generated_at: str
    sources: list[TransitSource]
    departures: list[TransitDeparture]
