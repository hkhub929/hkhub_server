"""Lifecycle of a project-owned native PostgreSQL instance, started only by db:up."""

import os
import shlex
import shutil
import socket
import subprocess
from contextlib import closing
from pathlib import Path

import psycopg2

from app.core.config import PROJECT_ROOT, settings

INSTANCE_DIR = PROJECT_ROOT / ".local" / "postgresql"
DATA_DIR = INSTANCE_DIR / "data"
LOG_PATH = INSTANCE_DIR / "postgresql.log"
ADMIN_USER = "hkhub_admin"


def binary_directory() -> Path:
    if settings.postgres_bin_dir:
        directory = Path(settings.postgres_bin_dir).expanduser().resolve()
        if all(os.access(directory / name, os.X_OK) for name in ("initdb", "pg_ctl")):
            return directory
        raise RuntimeError("POSTGRES_BIN_DIR must contain executable initdb and pg_ctl.")
    candidates = []
    found = shutil.which("pg_ctl")
    if found:
        candidates.append(Path(found).resolve().parent)
    for prefix in ("/opt/homebrew/opt", "/usr/local/opt"):
        for formula in ("postgresql@18", "postgresql@17", "postgresql@16", "postgresql"):
            candidates.append(Path(prefix) / formula / "bin")
    for directory in candidates:
        if all(os.access(directory / name, os.X_OK) for name in ("initdb", "pg_ctl")):
            return directory.resolve()
    raise RuntimeError("PostgreSQL binaries not found. Install PostgreSQL or set POSTGRES_BIN_DIR.")


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def admin_connection():
    # initdb enables trust only on Unix sockets in this private, mode-0700 directory.
    # TCP connections require SCRAM; the administrative role has no TCP password.
    connection = psycopg2.connect(
        host=str(INSTANCE_DIR), port=5433, user=ADMIN_USER, dbname="postgres",
        connect_timeout=3, options="-c timezone=UTC -c statement_timeout=5000",
    )
    connection.autocommit = True
    return connection


def assert_owned(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SHOW data_directory")
        actual = Path(cursor.fetchone()[0]).resolve()
        cursor.execute("SHOW port")
        port = int(cursor.fetchone()[0])
    if actual != DATA_DIR.resolve() or port != 5433:
        raise RuntimeError("Refusing to manage PostgreSQL with a different data directory or port.")


def run_postgres(arguments: list[str], *, timeout: int = 120) -> None:
    try:
        result = subprocess.run(
            arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"PostgreSQL command timed out. Inspect {LOG_PATH}.") from error
    if result.returncode:
        raise RuntimeError(f"PostgreSQL command failed. Inspect {LOG_PATH} and POSTGRES_BIN_DIR.")


def start_instance() -> None:
    if port_is_open(5433):
        with closing(admin_connection()) as connection:
            assert_owned(connection)
        print("Project-owned PostgreSQL is already running at 127.0.0.1:5433.")
        return
    directory = binary_directory()
    if not (DATA_DIR / "PG_VERSION").is_file():
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            raise RuntimeError("Existing PostgreSQL data is incomplete; refusing to reinitialize.")
        print(f"Initializing native PostgreSQL data at {DATA_DIR}", flush=True)
        # No unauthenticated TCP is exposed. Socket access is restricted by directory permissions.
        with LOG_PATH.open("ab") as log:
            try:
                result = subprocess.run(
                    [str(directory / "initdb"), "-D", str(DATA_DIR), "-U", ADMIN_USER,
                     "--encoding=UTF8", "--locale=C", "--auth-local=trust",
                     "--auth-host=scram-sha-256"],
                    stdout=log, stderr=log, timeout=120,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"PostgreSQL initialization timed out. Inspect {LOG_PATH}.") from error
        if result.returncode:
            raise RuntimeError(f"PostgreSQL initialization failed. Inspect {LOG_PATH}.")
    print("Starting native PostgreSQL at 127.0.0.1:5433", flush=True)
    options = shlex.join([
        "-h", "127.0.0.1", "-p", "5433", "-k", str(INSTANCE_DIR),
        "-c", "timezone=UTC", "-c", "password_encryption=scram-sha-256",
    ])
    run_postgres([
        str(directory / "pg_ctl"), "-D", str(DATA_DIR), "-l", str(LOG_PATH),
        "-o", options, "-w", "-t", "30", "start",
    ])
    with closing(admin_connection()) as connection:
        assert_owned(connection)


def stop_instance() -> None:
    if not (DATA_DIR / "PG_VERSION").is_file():
        raise RuntimeError("No project-owned PostgreSQL instance; refusing to stop an external server.")
    if not (DATA_DIR / "postmaster.pid").exists():
        print("Project-owned PostgreSQL is already stopped. Data is preserved.")
        return
    with closing(admin_connection()) as connection:
        assert_owned(connection)
    run_postgres([
        str(binary_directory() / "pg_ctl"), "-D", str(DATA_DIR),
        "-m", "fast", "-w", "-t", "30", "stop",
    ])
    print("Project-owned PostgreSQL stopped. Data is preserved.")
