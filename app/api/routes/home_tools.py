import hashlib
import json
import logging
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import JSON, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, request_language

router = APIRouter()
logger = logging.getLogger(__name__)
HOME_TOOLS_KEY = "home.tools"


class ToolCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    badge: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=500)


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["none", "route", "url"] = "none"
    target: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_target(self) -> "ToolAction":
        target = self.target or ""
        if self.type == "none":
            if target:
                raise ValueError("Inactive actions must not have a target")
            return self
        if any(character.isspace() or ord(character) < 32 for character in target):
            raise ValueError("Invalid action target")
        if "\\" in target:
            raise ValueError("Invalid action target")
        uri = urlsplit(target)
        if self.type == "url":
            if uri.scheme != "https" or not uri.hostname or uri.username or uri.password:
                raise ValueError("External tools require a public HTTPS URL")
            uri.port  # Validate the port without connecting to the configured URL.
        elif not target.startswith("/") or target.startswith("//") or uri.scheme or uri.netloc:
            raise ValueError("Native tools require an absolute in-app route")
        return self


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    icon: str = Field(default="apps", max_length=64)
    enabled: bool = True
    sort_order: int = 0
    action: ToolAction = Field(default_factory=ToolAction)
    translations: dict[str, ToolCopy]

    @model_validator(mode="after")
    def validate_translations(self) -> "ToolDefinition":
        if DEFAULT_LANGUAGE not in self.translations:
            raise ValueError("Traditional Chinese copy is required as a fallback")
        if set(self.translations) - set(SUPPORTED_LANGUAGES):
            raise ValueError("Unsupported translation language")
        return self


class HomeToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[ToolDefinition] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_ids(self) -> "HomeToolsConfig":
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Tool IDs must be unique")
        return self


class HomeTool(ToolCopy):
    id: str
    icon: str
    action: ToolAction


class HomeToolsResponse(BaseModel):
    version: str
    language: str
    items: list[HomeTool]


def load_home_tools(session: Session) -> HomeToolsConfig:
    statement = text("SELECT value FROM app_settings WHERE key = :key").columns(value=JSON)
    try:
        value = session.execute(statement, {"key": HOME_TOOLS_KEY}).scalar_one_or_none()
    except SQLAlchemyError as error:
        logger.warning("Home tools lookup failed type=%s", type(error).__name__)
        raise AppError("home_tools_unavailable", "Home tools unavailable", 503) from error
    if value is None:
        raise AppError("home_tools_unavailable", "Home tools configuration missing", 503)
    try:
        return HomeToolsConfig.model_validate(value)
    except ValidationError as error:
        # Never echo database configuration or rejected values to the client/logs.
        logger.warning("Home tools configuration is invalid")
        raise AppError("home_tools_unavailable", "Invalid home tools configuration", 503) from error


@router.get("/home-tools", response_model=HomeToolsResponse)
def home_tools(
    request: Request, response: Response, session: Session = Depends(get_db)
) -> HomeToolsResponse:
    """Read current database configuration on every request; no deploy/restart needed."""
    config = load_home_tools(session)
    language = request_language(request)
    items = []
    for item in sorted(config.items, key=lambda entry: (entry.sort_order, entry.id)):
        if not item.enabled:
            continue
        copy = item.translations.get(language, item.translations[DEFAULT_LANGUAGE])
        items.append(HomeTool(id=item.id, icon=item.icon, action=item.action, **copy.model_dump()))
    payload = json.dumps(
        [item.model_dump() for item in items], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    response.headers["Cache-Control"] = "no-store"
    return HomeToolsResponse(
        version=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        language=language,
        items=items,
    )


class GroupCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=80)


class CatalogToolCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=30)


def validate_copy_languages(translations: dict) -> None:
    if DEFAULT_LANGUAGE not in translations:
        raise ValueError("Traditional Chinese copy is required as a fallback")
    if set(translations) - set(SUPPORTED_LANGUAGES):
        raise ValueError("Unsupported translation language")


class CatalogGroupDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    sort_order: int = 0
    translations: dict[str, GroupCopy]

    @model_validator(mode="after")
    def validate_copy(self) -> "CatalogGroupDefinition":
        validate_copy_languages(self.translations)
        return self


class CatalogToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    group_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,95}$")
    icon: str = Field(default="apps", max_length=64)
    visible: bool = True
    sort_order: int = 0
    translations: dict[str, CatalogToolCopy]

    @model_validator(mode="after")
    def validate_copy(self) -> "CatalogToolDefinition":
        validate_copy_languages(self.translations)
        return self


class ToolCatalogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    groups: list[CatalogGroupDefinition] = Field(max_length=30)
    items: list[CatalogToolDefinition] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_relationships(self) -> "ToolCatalogConfig":
        group_ids = {group.id for group in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError("Group IDs must be unique")
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Tool IDs must be unique")
        if any(item.group_id not in group_ids for item in self.items):
            raise ValueError("Every tool must reference an existing group")
        return self


class CatalogTool(CatalogToolCopy):
    id: str
    feature_id: str
    icon: str
    visible: bool


class CatalogGroup(GroupCopy):
    id: str
    items: list[CatalogTool]


class ToolCatalogResponse(BaseModel):
    version: str
    language: str
    groups: list[CatalogGroup]


def load_tool_catalog(session: Session) -> ToolCatalogConfig:
    statement = text("SELECT value FROM app_settings WHERE key = :key").columns(value=JSON)
    try:
        value = session.execute(statement, {"key": "home.tools.v2"}).scalar_one_or_none()
    except SQLAlchemyError as error:
        logger.warning("Tool catalog lookup failed type=%s", type(error).__name__)
        raise AppError("home_tools_unavailable", "Tool catalog unavailable", 503) from error
    if value is None:
        raise AppError("home_tools_unavailable", "Tool catalog configuration missing", 503)
    try:
        return ToolCatalogConfig.model_validate(value)
    except ValidationError as error:
        # Report schema locations/types only, never configuration values or validator context.
        issues = [
            {"loc": issue["loc"], "type": issue["type"]}
            for issue in error.errors(include_input=False, include_context=False, include_url=False)
        ]
        logger.warning("Tool catalog configuration is invalid issues=%s", issues)
        raise AppError("home_tools_unavailable", "Invalid tool catalog configuration", 503) from error


@router.get("/tool-catalog", response_model=ToolCatalogResponse)
def tool_catalog(
    request: Request, response: Response, session: Session = Depends(get_db)
) -> ToolCatalogResponse:
    """Grouped native tools. visible is presentation, never authorization."""
    config = load_tool_catalog(session)
    language = request_language(request)
    grouped: dict[str, list[CatalogTool]] = {group.id: [] for group in config.groups}
    for item in sorted(config.items, key=lambda entry: (entry.sort_order, entry.id)):
        if not item.visible:
            continue
        copy = item.translations.get(language, item.translations[DEFAULT_LANGUAGE])
        grouped[item.group_id].append(CatalogTool(
            id=item.id, feature_id=item.feature_id, icon=item.icon,
            visible=item.visible, **copy.model_dump(),
        ))
    groups = []
    for group in sorted(config.groups, key=lambda entry: (entry.sort_order, entry.id)):
        if not grouped[group.id]:
            continue
        copy = group.translations.get(language, group.translations[DEFAULT_LANGUAGE])
        groups.append(CatalogGroup(id=group.id, items=grouped[group.id], **copy.model_dump()))
    payload = json.dumps(
        [group.model_dump() for group in groups], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    )
    response.headers["Cache-Control"] = "no-store"
    return ToolCatalogResponse(
        version=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        language=language, groups=groups,
    )
