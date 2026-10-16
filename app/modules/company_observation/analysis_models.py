"""Finite AI output shapes, literal evidence matching and publication checks."""
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Copy(StrictModel):
    title: str = Field(min_length=1, max_length=60)
    explanation: str = Field(min_length=1, max_length=400)


class TranslatedCopy(StrictModel):
    zh_hant: Copy
    zh_hans: Copy
    en: Copy

    def display(self) -> dict:
        return {'zh-Hant': self.zh_hant.model_dump(), 'zh-Hans': self.zh_hans.model_dump(),
                'en': self.en.model_dump()}


class Evidence(StrictModel):
    company_key: str = Field(max_length=64)
    field: str = Field(pattern=r'^name_(en|zh)$')
    term: str = Field(min_length=2, max_length=60)


class Candidate(StrictModel):
    label: str = Field(min_length=1, max_length=60)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)


class Candidates(StrictModel):
    processed_company_keys: list[str] = Field(max_length=150)
    topics: list[Candidate] = Field(max_length=60)


class MergedTopic(StrictModel):
    copy: TranslatedCopy
    terms: list[str] = Field(min_length=1, max_length=30)


class MergedTopics(StrictModel):
    topics: list[MergedTopic] = Field(max_length=60)


class SummaryCopy(StrictModel):
    summary: str = Field(min_length=1, max_length=500)
    findings: list[str] = Field(max_length=3)


class Summary(StrictModel):
    zh_hant: SummaryCopy
    zh_hans: SummaryCopy
    en: SummaryCopy

    def display(self) -> dict:
        return {'zh-Hant': self.zh_hant.model_dump(), 'zh-Hans': self.zh_hans.model_dump(),
                'en': self.en.model_dump()}


GENERIC = {'香港', '香港公司', '國際', '国际', '集團', '集团', '有限公司', '有限',
           'limited', 'ltd', 'company', 'co', 'hk', 'hong kong', 'group', 'international', 'holdings'}
FORBIDDEN = re.compile(
    r'升溫|升温|降溫|降温|爆發|爆发|值得入場|值得入场|倒閉率|倒闭率|'
    r'需求(?:上升|上涨|增長|增长)|官方(?:行業|行业|分類|分类)|'
    r'\b(?:boom(?:ing)?|surging|fastest.growing|investment opportunity|bankruptcy rate|'
    r'official classification|demand growth|hotter|cooling)\b', re.IGNORECASE)


def fold(value: str) -> str:
    return unicodedata.normalize('NFKC', value).casefold()


def literal_evidence(name: str, term: str) -> str | None:
    """Map normalized offsets back to the exact legal-name substring."""
    normalized, offsets = '', []
    for index, character in enumerate(name):
        fragment = fold(character)
        normalized += fragment
        offsets.extend([index] * len(fragment))
    needle = fold(term)
    if needle in GENERIC:
        return None
    pattern = re.escape(needle)
    if needle and needle[0].isascii() and needle[0].isalnum():
        pattern = r'(?<![a-z0-9])' + pattern
    if needle and needle[-1].isascii() and needle[-1].isalnum():
        pattern += r'(?![a-z0-9])'
    match = re.search(pattern, normalized)
    if not match:
        return None
    return name[offsets[match.start()]:offsets[match.end() - 1] + 1]


def safe_copy(value: str, *, numerical: bool = False) -> None:
    if len(value) > 600 or FORBIDDEN.search(value) or any(character in value for character in '<>'):
        raise ValueError('analysis_invalid')
    if not numerical and re.search(r'[0-9０-９%％]|百分|\bpercent\b', value, re.IGNORECASE):
        raise ValueError('analysis_invalid')


def validate_candidates(result: Candidates, companies: list[dict]) -> dict:
    lookup = {company['company_key']: company for company in companies}
    if (len(result.processed_company_keys) != len(lookup)
            or set(result.processed_company_keys) != set(lookup)):
        raise ValueError('analysis_batch_incomplete')
    candidates = []
    for topic in result.topics:
        safe_copy(topic.label, numerical=True)
        terms = []
        for evidence in topic.evidence:
            company = lookup.get(evidence.company_key)
            if not company or not literal_evidence(company[evidence.field], evidence.term):
                raise ValueError('analysis_evidence_invalid')
            if evidence.term not in terms:
                terms.append(evidence.term)
        candidates.append({'label': topic.label, 'terms': terms})
    return {'topics': candidates}


def validate_merged(result: MergedTopics, candidates: list[dict]) -> list[dict]:
    allowed = {fold(term) for candidate in candidates for term in candidate['terms']}
    used, labels, output = set(), set(), []
    for topic in result.topics:
        terms = list(dict.fromkeys(topic.terms))
        folded = {fold(term) for term in terms}
        label = fold(topic.copy.zh_hant.title)
        if not folded <= allowed or folded & used or folded & GENERIC or label in labels:
            raise ValueError('analysis_merge_invalid')
        for copy in topic.copy.display().values():
            safe_copy(copy['title'], numerical=True)
            safe_copy(copy['explanation'])
        used.update(folded)
        labels.add(label)
        output.append({'display': topic.copy.display(), 'terms': terms})
    return output
