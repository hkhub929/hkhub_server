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
    if url.drivername not in {"mysql", "mysql+pymysql"}:
        raise ValueError("DATABASE_URL must use mysql+pymysql://")
    return (
        url.set(drivername="mysql+pymysql")
        .update_query_dict({"charset": "utf8mb4"})
        .render_as_string(hide_password=False)
    )


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
            "read_timeout": 15,
            "write_timeout": 15,
            "init_command": "SET time_zone = '+00:00'",
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
