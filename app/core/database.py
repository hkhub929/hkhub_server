from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import settings


class Base(DeclarativeBase):
    """ORM mapping base. Schema changes belong exclusively in db/migrations SQL."""


def database_url() -> str:
    value = settings.database_url.get_secret_value()
    if not value:
        raise RuntimeError("DATABASE_URL is required. Copy .env.example to .env first.")
    url = make_url(value)
    if url.drivername not in {"postgresql", "postgresql+psycopg2"}:
        raise ValueError("DATABASE_URL must use postgresql+psycopg2://")
    return url.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args={
            "connect_timeout": 5,
            "options": "-c timezone=UTC -c statement_timeout=15000",
        },
    )


def get_db() -> Generator[Session, None, None]:
    """One session per request; writes commit explicitly in the application layer."""
    with Session(get_engine(), autoflush=False, expire_on_commit=False) as session:
        yield session


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()
