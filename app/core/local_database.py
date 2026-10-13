"""Explicit local PostgreSQL commands; init and API startup never provision a database."""

import argparse
import fcntl
import os
import re
import secrets
from contextlib import closing

import psycopg2
from dotenv import set_key
from psycopg2 import sql
from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url

from app.core.config import PROJECT_ROOT, settings
from app.core.database import database_url
from app.core.local_postgres import (
    ADMIN_USER,
    INSTANCE_DIR,
    admin_connection,
    assert_owned,
    start_instance,
    stop_instance,
)


def connect(url: URL):
    return psycopg2.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        connect_timeout=3, options="-c timezone=UTC -c statement_timeout=5000",
    )


def print_database_status(url: URL) -> None:
    with closing(connect(url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('port'), version()")
            name, port, version = cursor.fetchone()
    print(f"Connected: {url.host}:{port} database={name} version={version}")


def persist_generated_password(url: URL) -> URL:
    if "DATABASE_URL" in os.environ:
        raise RuntimeError("Set a non-placeholder password in the DATABASE_URL environment override.")
    url = url.set(password=secrets.token_urlsafe(32))
    value = url.render_as_string(hide_password=False)
    set_key(str(PROJECT_ROOT / ".env"), "DATABASE_URL", value, quote_mode="always")
    (PROJECT_ROOT / ".env").chmod(0o600)
    settings.database_url = SecretStr(value)
    print("Generated local application credentials and saved them to .env (not printed).")
    return url


def validate_local_account(url: URL) -> None:
    if not url.database or not re.fullmatch(r"[A-Za-z0-9_]{1,63}", url.database):
        raise RuntimeError("Local database name must contain 1-63 letters, digits or underscores.")
    if url.database in {"postgres", "template0", "template1"}:
        raise RuntimeError("Use a dedicated application database, not a PostgreSQL system database.")
    if not url.username or not re.fullmatch(r"[A-Za-z0-9_]{1,63}", url.username):
        raise RuntimeError("Local username must contain 1-63 letters, digits or underscores.")
    if url.username in {ADMIN_USER, "postgres"}:
        raise RuntimeError("Use a dedicated application account, not a PostgreSQL admin account.")


def provision_database(url: URL) -> None:
    with closing(admin_connection()) as connection:
        assert_owned(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (url.username,))
            role_exists = cursor.fetchone() is not None
            if role_exists:
                # Never change passwords, permissions or ownership of an existing role.
                if not url.password or url.password == "change_me":
                    raise RuntimeError("Existing local account needs its original DATABASE_URL password.")
            else:
                if not url.password or url.password == "change_me":
                    url = persist_generated_password(url)
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(url.username), sql.Literal(url.password),
                ))
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                    sql.Identifier(url.database), sql.Identifier(url.username),
                ))
    print_database_status(url)


def require_managed_local_target(url: URL) -> None:
    if settings.environment != "local":
        raise RuntimeError("Local PostgreSQL management requires ENVIRONMENT=local.")
    if url.host not in {"localhost", "127.0.0.1"} or url.port != 5433:
        raise RuntimeError("Local PostgreSQL management is restricted to localhost:5433.")
    if url.query:
        raise RuntimeError("Managed local DATABASE_URL must not override connection query parameters.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly manage native local PostgreSQL")
    parser.add_argument("command", choices=["up", "down", "check"])
    command = parser.parse_args().command
    try:
        url = make_url(database_url())
        if command == "check":
            print_database_status(url)
            return
        require_managed_local_target(url)
        if command == "up":
            validate_local_account(url)
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        INSTANCE_DIR.chmod(0o700)
        with (INSTANCE_DIR / "bootstrap.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if command == "down":
                stop_instance()
            else:
                start_instance()
                provision_database(url)
    except psycopg2.Error as error:
        parser.exit(1, f"PostgreSQL operation failed (code={error.pgcode or 'connection'}); "
                       "check credentials, port ownership and permissions.\n")
    except (RuntimeError, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
