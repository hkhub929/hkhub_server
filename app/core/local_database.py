"""Local database provisioning entrypoint used by cmd.sh; production never provisions."""

import argparse
import fcntl
import os
import re
import secrets

import pymysql
from dotenv import set_key
from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url

from app.core.config import PROJECT_ROOT, settings
from app.core.database import database_url
from app.core.local_mysql import (
    CREDENTIALS_PATH,
    INSTANCE_DIR,
    admin_connection,
    assert_owned,
    load_credentials,
    port_is_open,
    start_instance,
    stop_instance,
)


def connect(url: URL, *, with_database: bool = True):
    return pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username,
        password=url.password or "",
        database=url.database if with_database else None,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
    )


def print_database_status(url: URL) -> None:
    with connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), @@port, @@version")
            name, port, version = cursor.fetchone()
    print(f"Connected: {url.host}:{port} database={name} MySQL={version}")


def get_admin(url: URL):
    if CREDENTIALS_PATH.exists():
        try:
            connection = admin_connection(load_credentials(), url.port or 3307)
        except pymysql.MySQLError:
            pass
        else:
            try:
                assert_owned(connection)
            except Exception:
                connection.close()
                raise
            return connection, True
    configured = settings.local_database_admin_url.get_secret_value()
    if configured:
        admin_url = make_url(configured)
        if admin_url.drivername not in {"mysql", "mysql+pymysql"}:
            raise RuntimeError("LOCAL_DATABASE_ADMIN_URL must use mysql+pymysql://.")
        if admin_url.host != url.host or admin_url.port != url.port:
            raise RuntimeError("LOCAL_DATABASE_ADMIN_URL must point to the configured local instance.")
        return connect(admin_url, with_database=False), False
    # Existing instances may grant this account permission to create its own database.
    try:
        return connect(url, with_database=False), False
    except pymysql.MySQLError as error:
        raise RuntimeError(
            "Existing local MySQL requires valid credentials. Configure DATABASE_URL or "
            "LOCAL_DATABASE_ADMIN_URL; no existing accounts have been changed."
        ) from error


def persist_generated_password(url: URL) -> URL:
    if "DATABASE_URL" in os.environ:
        raise RuntimeError(
            "Cannot replace placeholder credentials supplied by DATABASE_URL environment override."
        )
    url = url.set(password=secrets.token_urlsafe(32))
    value = url.render_as_string(hide_password=False)
    set_key(str(PROJECT_ROOT / ".env"), "DATABASE_URL", value, quote_mode="always")
    (PROJECT_ROOT / ".env").chmod(0o600)
    settings.database_url = SecretStr(value)
    print("Generated local application credentials and saved them to .env (not printed).")
    return url


def provision_database(url: URL) -> URL:
    try:
        print_database_status(url)
        return url
    except pymysql.MySQLError:
        pass
    if not url.database or not re.fullmatch(r"[A-Za-z0-9_]+", url.database):
        raise RuntimeError("Local database name must contain only letters, digits and underscores.")
    if not url.username or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", url.username):
        raise RuntimeError("Local username must contain 1-32 letters, digits or underscores.")
    if url.username == "root":
        raise RuntimeError("Use a dedicated application account, not root, in DATABASE_URL.")
    connection, owned = get_admin(url)
    with connection:
        if owned or settings.local_database_admin_url.get_secret_value():
            if not url.password or url.password == "change_me":
                url = persist_generated_password(url)
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            if owned or settings.local_database_admin_url.get_secret_value():
                for host in ("localhost", "127.0.0.1"):
                    # Never reset the password of an existing account.
                    cursor.execute(
                        "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
                        (url.username, host, url.password),
                    )
                    cursor.execute(
                        f"GRANT ALL PRIVILEGES ON `{url.database}`.* TO %s@%s",
                        (url.username, host),
                    )
    print_database_status(url)
    return url


def require_managed_local_target(url: URL) -> int:
    if settings.environment != "local" or not settings.local_database_autostart:
        raise RuntimeError("Local MySQL management requires ENVIRONMENT=local and autostart enabled.")
    if url.host not in {"localhost", "127.0.0.1"} or url.port != 3307:
        raise RuntimeError("Automatic MySQL management is restricted to localhost:3307.")
    return 3307


def initialize(url: URL) -> None:
    if settings.environment != "local" or not settings.local_database_autostart:
        print("Automatic database provisioning skipped; using an independently managed database.")
        return
    if url.host not in {"localhost", "127.0.0.1"} or url.port != 3307:
        print("Automatic provisioning skipped for non-local-3307 target.")
        return
    port = require_managed_local_target(url)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (INSTANCE_DIR / "bootstrap.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not port_is_open(port):
            start_instance(port)
        provision_database(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage native local MySQL without containers")
    parser.add_argument("command", choices=["init", "up", "down", "check"])
    command = parser.parse_args().command
    try:
        url = make_url(database_url())
        if command == "check":
            print_database_status(url)
        elif command == "down":
            stop_instance(require_managed_local_target(url))
        else:
            if command == "up":
                require_managed_local_target(url)
            initialize(url)
    except pymysql.MySQLError as error:
        code = error.args[0] if error.args else "unknown"
        parser.exit(1, f"MySQL operation failed (code={code}); check credentials and permissions.\n")
    except (RuntimeError, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
