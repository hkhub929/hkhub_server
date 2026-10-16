from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.company_observation.calendar import PeriodType

DataStatus = Literal['complete', 'partial', 'unavailable']
AnalysisStatus = Literal['pending', 'running', 'published', 'failed', 'not_configured',
                         'not_needed', 'superseded']


class MissingResource(BaseModel):
    start_date: date
    reason_code: str


class Source(BaseModel):
    resource_id: str
    source_url: str
    coverage_start: date
    coverage_end_exclusive: date
    fetched_at: datetime
    published_date: date | None = None
    status: str


class Period(BaseModel):
    report_id: UUID
    period_type: PeriodType
    start_date: date
    end_date_exclusive: date
    timezone: str = 'Asia/Hong_Kong'
    calendar_ended: bool = True
    data_status: DataStatus
    analysis_status: AnalysisStatus
    error_code: str | None = None


class PeriodsResponse(BaseModel):
    items: list[Period]
    default_start_date: date | None
    latest_ended_start_date: date
    last_success_at: datetime | None = None
    source_error_code: str | None = None


class Topic(BaseModel):
    topic_id: str
    report_id: UUID
    title: str
    explanation: str
    company_count: int
    content_language: str
    language_fallback: bool
    terms: list[str] = Field(default_factory=list)


class Overview(Period):
    dataset_fingerprint: str
    analysis_version: str
    analysis_attempt_count: int = 0
    analysis_max_attempts: int = 3
    analysis_retry_after: datetime | None = None
    analysis_retry_allowed: bool = False
    observed_company_count: int
    total_company_count: int | None
    identified_company_count: int | None = None
    unknown_company_count: int | None = None
    unknown_company_ratio: float | None = None
    summary: str | None = None
    findings: list[str] = Field(default_factory=list)
    content_language: str | None = None
    language_fallback: bool = False
    generated_at: datetime | None = None
    sources: list[Source]
    missing_resources: list[MissingResource]
    topics: list[Topic]


class Company(BaseModel):
    company_key: str
    identifier_type: str
    identifier_value: str
    name_en: str
    name_zh: str
    incorporation_date: date
    evidence: list[dict[str, str]]
    source: Source


class CompaniesResponse(BaseModel):
    report_id: UUID
    items: list[Company]
    next_cursor: str | None = None


class LiquidationMonth(BaseModel):
    month_start: date
    members_commenced: int
    creditors_commenced: int
    members_in_progress: int
    creditors_in_progress: int
    source_url: str
    fetched_at: datetime


class LiquidationsResponse(BaseModel):
    data_status: DataStatus
    period_type: str = 'month'
    scope: str = 'members_and_creditors_voluntary_winding_up'
    commenced_stage: str = 'cases_commenced_during_month'
    in_progress_stage: str = 'cases_in_progress'
    unit: str = 'cases'
    items: list[LiquidationMonth]
    error_code: str | None = None
    last_success_at: datetime | None = None
