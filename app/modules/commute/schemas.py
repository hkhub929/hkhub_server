from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Audience = Literal['resident', 'visitor']
PortCode = Literal['LWS', 'LSC', 'SBC']
QueueReason = Literal[
    'available', 'maintenance', 'closed', 'missing', 'invalid',
    'fetch_failed', 'stale', 'not_collected',
]


class QueueStatus(BaseModel):
    code: int | None = None
    reason: QueueReason = 'not_collected'
    fetched_at: datetime | None = None
    attempted_at: datetime | None = None


class Border(BaseModel):
    code: PortCode
    name: str
    counterpart: str
    modes: list[Literal['mtr', 'bus']]
    queues: dict[Audience, QueueStatus]
    source_url: str


class BordersResponse(BaseModel):
    server_time: datetime
    timezone: str = 'Asia/Hong_Kong'
    direction: str = 'arrival'
    source_update_seconds: int = 900
    stale_after_seconds: int = 1800
    items: list[Border]


class HistoryDay(BaseModel):
    date: date
    queue: QueueStatus


class Comparison(BaseModel):
    lower: int
    same: int
    higher: int
    whole_week: bool
    position: Literal['lowest', 'joint_lowest', 'highest', 'joint_highest', 'same', 'mixed']


class HistoryResponse(BaseModel):
    server_time: datetime
    port_code: PortCode
    audience: Audience
    direction: str = 'arrival'
    timezone: str = 'Asia/Hong_Kong'
    slot_start: str
    slot_end: str
    current: QueueStatus
    days: list[HistoryDay]
    valid_count: int
    expected_count: int = 7
    comparison: Comparison | None = None


class Departure(BaseModel):
    time: datetime
    kind: Literal['departure', 'estimated_arrival', 'scheduled_arrival']
    platform: str = ''
    destination: str
    remark: str = ''
    data_time: datetime | None = None


class TransitRoute(BaseModel):
    id: str
    mode: Literal['mtr', 'bus']
    operator: str
    route: str
    stop: str
    destination: str
    map_url: str | None = None
    source_url: str
    fetched_at: datetime | None = None
    state: Literal['available', 'no_departures', 'unavailable'] = 'unavailable'
    delayed: bool = False
    departures: list[Departure] = Field(default_factory=list)


class TransitResponse(BaseModel):
    server_time: datetime
    stale_after_seconds: int = 120
    items: list[TransitRoute]
