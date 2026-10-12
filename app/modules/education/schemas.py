"""Education contract: school ranges are derived from programme estimates."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchoolId = Literal["hku", "cuhk", "hkust", "cityu", "polyu", "hkbu", "lingnan", "eduhk", "hkmu", "hsuhk"]
Tier = Literal["reach", "match", "safer"]
ShortText = Annotated[str, Field(min_length=1, max_length=350)]

SCHOOLS: dict[str, tuple[str, str, str]] = {
    "hku": ("香港大学", "香港大學", "The University of Hong Kong"),
    "cuhk": ("香港中文大学", "香港中文大學", "The Chinese University of Hong Kong"),
    "hkust": ("香港科技大学", "香港科技大學", "The Hong Kong University of Science and Technology"),
    "cityu": ("香港城市大学", "香港城市大學", "City University of Hong Kong"),
    "polyu": ("香港理工大学", "香港理工大學", "The Hong Kong Polytechnic University"),
    "hkbu": ("香港浸会大学", "香港浸會大學", "Hong Kong Baptist University"),
    "lingnan": ("岭南大学", "嶺南大學", "Lingnan University"),
    "eduhk": ("香港教育大学", "香港教育大學", "The Education University of Hong Kong"),
    "hkmu": ("香港都会大学", "香港都會大學", "Hong Kong Metropolitan University"),
    "hsuhk": ("香港恒生大学", "香港恒生大學", "The Hang Seng University of Hong Kong"),
}


class Applicant(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    institution: str = Field(min_length=1, max_length=120)
    major: str = Field(min_length=1, max_length=120)
    grade_scale: Literal["100", "4", "5"]
    grade: float = Field(ge=0, le=100)
    direction: str = Field(min_length=1, max_length=150)
    intake_year: int
    institution_tier: Literal["985", "211", "other", "unknown"] = "unknown"
    language_test: Literal["not_provided", "not_taken", "ielts", "toefl"] = "not_provided"
    language_score: float | None = None
    experience: str = Field(default="", max_length=1200)
    preferences: str = Field(default="", max_length=600)
    consent: Literal[True]

    @model_validator(mode="after")
    def validate_scores(self) -> "Applicant":
        if self.grade > float(self.grade_scale):
            raise ValueError("Grade exceeds its original scale")
        year = datetime.now(timezone.utc).year
        if not year - 1 <= self.intake_year <= year + 8:
            raise ValueError("Invalid intake year")
        maximum = {"ielts": 9, "toefl": 120}.get(self.language_test)
        if maximum is None:
            if self.language_score is not None:
                raise ValueError("A score requires a language test")
        elif self.language_score is None or not 0 <= self.language_score <= maximum:
            raise ValueError("Invalid language score")
        return self


class ProgrammeEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    probability: int = Field(ge=0, le=100)
    relevance: ShortText
    strengths: list[ShortText] = Field(min_length=1, max_length=2)
    weaknesses: list[ShortText] = Field(min_length=1, max_length=2)
    next_steps: list[ShortText] = Field(min_length=1, max_length=2)


def probability_tier(probability: int) -> Tier:
    if probability < 30:
        return "reach"
    if probability < 60:
        return "match"
    return "safer"


class SchoolEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    school_id: SchoolId
    programmes: list[ProgrammeEstimate] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_programmes(self) -> "SchoolEstimate":
        names = [item.name_en.strip().casefold() for item in self.programmes]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate programmes")
        return self


class ModelReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=1000)
    assumptions: list[ShortText] = Field(max_length=6)
    schools: list[SchoolEstimate] = Field(max_length=10)

    @model_validator(mode="after")
    def unique_schools(self) -> "ModelReport":
        ids = [school.school_id for school in self.schools]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate schools")
        return self


class ProgrammeResult(ProgrammeEstimate):
    tier: Tier


class SchoolResult(BaseModel):
    school_id: SchoolId
    name: str
    name_en: str
    probability_min: int
    probability_max: int
    tier: Tier
    programmes: list[ProgrammeResult]


class EducationReport(BaseModel):
    schema_version: Literal[1] = 1
    language: str
    generated_at: str
    source: Literal["ai_estimate"] = "ai_estimate"
    summary: str
    assumptions: list[str]
    schools: list[SchoolResult]


def build_report(model: ModelReport, language: str, applicant: Applicant) -> EducationReport:
    assumptions = list(model.assumptions)
    if applicant.language_test in ("not_provided", "not_taken"):
        language_note = {
            "zh-Hans": "未提供语言成绩：以下估算以入学前满足相关项目语言要求为前提。",
            "en": "Language scores are not provided: estimates assume meeting applicable "
                  "programme language requirements before admission.",
        }.get(language, "未提供語言成績：以下估算以入學前符合相關課程語言要求為前提。")
        assumptions = [language_note, *assumptions[:5]]
    schools = []
    name_index = 2 if language == "en" else 0 if language == "zh-Hans" else 1
    for school in model.schools:
        programmes = sorted(school.programmes, key=lambda item: item.probability, reverse=True)
        probabilities = [item.probability for item in programmes]
        schools.append(SchoolResult(
            school_id=school.school_id,
            name=SCHOOLS[school.school_id][name_index],
            name_en=SCHOOLS[school.school_id][2],
            probability_min=min(probabilities),
            probability_max=max(probabilities),
            tier=probability_tier(max(probabilities)),
            programmes=[ProgrammeResult(**item.model_dump(), tier=probability_tier(item.probability))
                        for item in programmes],
        ))
    tier_order = {"reach": 0, "match": 1, "safer": 2}
    schools.sort(key=lambda item: (tier_order[item.tier], -item.probability_max))
    return EducationReport(
        language=language,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        summary=model.summary,
        assumptions=assumptions,
        schools=schools,
    )
