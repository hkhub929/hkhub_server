from datetime import date, datetime
from zoneinfo import ZoneInfo

HK = ZoneInfo('Asia/Hong_Kong')
QUEUE_CODES = {0, 1, 2, 4, 99}
STALE_SECONDS = 1800
SOURCE_PAGE = 'https://data.gov.hk/en-data/dataset/hk-immd-set28-land-boundary-control-points-waiting-time'
QUEUE_URLS = {
    audience: f'https://secure1.info.gov.hk/immd/mobileapps/2bb9ae17/data/CPQueueTime{suffix}.json'
    for audience, suffix in (('resident', 'R'), ('visitor', 'V'))
}
PORTS = {
    'LWS': {
        'name': ('罗湖口岸', '羅湖口岸', 'Luohu'),
        'counterpart': ('罗湖管制站', '羅湖管制站', 'Lo Wu'),
        'modes': ['mtr'],
    },
    'LSC': {
        'name': ('福田口岸', '福田口岸', 'Futian'),
        'counterpart': ('落马洲支线管制站', '落馬洲支線管制站', 'Lok Ma Chau Spur Line'),
        'modes': ['mtr', 'bus'],
    },
    'SBC': {
        'name': ('深圳湾口岸', '深圳灣口岸', 'Shenzhen Bay'),
        'counterpart': ('深圳湾管制站', '深圳灣管制站', 'Shenzhen Bay Control Point'),
        'modes': ['bus'],
    },
}


def copy_text(values: tuple[str, str, str], language: str) -> str:
    return values[2] if language == 'en' else values[0 if language == 'zh-Hans' else 1]


def slot_at(moment: datetime) -> tuple[date, int]:
    local = moment.astimezone(HK)
    return local.date(), (local.hour * 60 + local.minute) // 15
