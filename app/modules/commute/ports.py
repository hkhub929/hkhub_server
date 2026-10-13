"""Supported control points and the official queue status vocabulary.

Status codes and thresholds come from the Immigration Department data dictionary
for "Land Boundary Control Points Waiting Time".
"""

from datetime import date, datetime, timedelta, timezone

# Hong Kong has kept UTC+8 without daylight saving since 1979, so a fixed offset is
# exact and avoids depending on tzdata being present in the runtime image.
HONG_KONG_TZ = timezone(timedelta(hours=8))

RESIDENT = "resident"
VISITOR = "visitor"
AUDIENCES = (RESIDENT, VISITOR)

ARRIVAL = "arrival"
DEPARTURE = "departure"
DIRECTIONS = (ARRIVAL, DEPARTURE)

# Two directions are sampled for audit, but only the Hong Kong inbound direction
# backs the first release, which covers travelling from Shenzhen into Hong Kong.
DIRECTION_FIELDS = (("arrQueue", ARRIVAL), ("depQueue", DEPARTURE))

STATUS_NORMAL = 0
STATUS_BUSY = 1
STATUS_VERY_BUSY = 2
STATUS_MAINTENANCE = 4
STATUS_NON_SERVICE = 99

# Only these codes express a comparable queue level. Maintenance, non-service and
# unknown codes must never be ordered against each other or treated as normal.
COMPARABLE_CODES = (STATUS_NORMAL, STATUS_BUSY, STATUS_VERY_BUSY)

STATUS_NAMES = {
    STATUS_NORMAL: "normal",
    STATUS_BUSY: "busy",
    STATUS_VERY_BUSY: "very_busy",
    STATUS_MAINTENANCE: "maintenance",
    STATUS_NON_SERVICE: "non_service",
}
UNKNOWN_STATUS = "unknown"

# Control point code -> MTR East Rail station code reached after clearing Hong Kong
# immigration. None means no onward rail connection has been verified yet, which is
# reported as unavailable rather than guessed.
#
# Lok Ma Chau Spur Line (LSC) serves Futian Port; the station there is coded LMC by
# the MTR, which is a different naming system from the Immigration Department code
# LMC (Lok Ma Chau control point). The two must never be interchanged.
MTR_STATION_BY_PORT: dict[str, str | None] = {
    "LWS": "LOW",
    "LSC": "LMC",
    "SBC": None,
}

# Ordered as shown in the app: Lo Wu, Futian (Spur Line), Shenzhen Bay.
SUPPORTED_PORT_CODES = ("LWS", "LSC", "SBC")

SLOT_MINUTES = 15


def status_name(code: int | None) -> str:
    """Map a stored status code to a stable name; unknown codes stay unknown."""
    if code is None:
        return UNKNOWN_STATUS
    return STATUS_NAMES.get(code, UNKNOWN_STATUS)


def is_comparable(code: int | None) -> bool:
    return code in COMPARABLE_CODES


def hk_window(moment: datetime) -> tuple[date, int]:
    """Return the Hong Kong local date and 15-minute window index of an instant."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(HONG_KONG_TZ)
    slot = local.hour * (60 // SLOT_MINUTES) + local.minute // SLOT_MINUTES
    return local.date(), slot


def iso_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
