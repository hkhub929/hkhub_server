"""Lifecycle of a project-owned native MySQL instance; never uses containers."""

import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pymysql

from app.core.config import PROJECT_ROOT, settings

INSTANCE_DIR = PROJECT_ROOT / ".local" / "mysql"
DATA_DIR = INSTANCE_DIR / "data"
SOCKET_PATH = INSTANCE_DIR / "mysql.sock"
CREDENTIALS_PATH = INSTANCE_DIR / "admin.json"
LOG_PATH = INSTANCE_DIR / "mysql.log"


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def admin_connection(credentials: dict, port: int):
    return pymysql.connect(
        user="root",
        password=credentials["password"],
        unix_socket=str(SOCKET_PATH),
        connect_timeout=3,
        read_timeout=5,
        write_timeout=5,
        charset="utf8mb4",
        autocommit=True,
    )


def save_credentials(credentials: dict) -> None:
    temporary = CREDENTIALS_PATH.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(credentials, handle)
    temporary.replace(CREDENTIALS_PATH)


def load_credentials() -> dict:
    return json.loads(CREDENTIALS_PATH.read_text())


def mysql_binary() -> Path:
    found = settings.mysqld_bin or shutil.which("mysqld")
    if not found:
        for prefix in ("/opt/homebrew/opt", "/usr/local/opt"):
            for formula in ("mysql@8.4", "mysql@8.0", "mysql"):
                candidate = Path(prefix) / formula / "bin" / "mysqld"
                if candidate.is_file():
                    found = str(candidate)
                    break
            if found:
                break
    if not found:
        raise RuntimeError("mysqld not found. Install native MySQL or configure MYSQLD_BIN.")
    binary = Path(found).resolve()
    if not os.access(binary, os.X_OK):
        raise RuntimeError("MYSQLD_BIN is not executable.")
    return binary


def server_arguments(binary: Path, port: int) -> list[str]:
    return [
        str(binary),
        "--no-defaults",
        f"--basedir={binary.parent.parent}",
        f"--datadir={DATA_DIR}",
        f"--socket={SOCKET_PATH}",
        f"--pid-file={INSTANCE_DIR / 'mysql.pid'}",
        f"--log-error={LOG_PATH}",
        f"--port={port}",
        "--bind-address=127.0.0.1",
        "--mysqlx=OFF",
    ]


def run_server(arguments: list[str], timeout: int = 120) -> None:
    try:
        result = subprocess.run(
            arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"MySQL startup timed out. Inspect {LOG_PATH}.") from error
    if result.returncode:
        raise RuntimeError(f"MySQL startup failed. Inspect {LOG_PATH}.")


def wait_for_admin(credentials: dict, port: int) -> None:
    for _ in range(60):
        try:
            with admin_connection(credentials, port):
                return
        except pymysql.MySQLError:
            time.sleep(0.5)
    raise RuntimeError(f"MySQL did not become ready. Inspect {LOG_PATH}.")


def assert_owned(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@datadir")
        actual = Path(cursor.fetchone()[0]).resolve()
    if actual != DATA_DIR.resolve():
        raise RuntimeError("Refusing to manage a MySQL instance with a different data directory.")


def secure_initial_instance(arguments: list[str], credentials: dict, port: int) -> None:
    # Empty-password root is never exposed to TCP, even during first initialization.
    if not SOCKET_PATH.exists():
        run_server([*arguments, "--skip-networking", "--daemonize"])
    try:
        connection = admin_connection(credentials, port)
    except pymysql.MySQLError:
        bootstrap_credentials = {**credentials, "password": ""}
        wait_for_admin(bootstrap_credentials, port)
        connection = admin_connection(bootstrap_credentials, port)
    with connection:
        assert_owned(connection)
        with connection.cursor() as cursor:
            cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY %s", (credentials["password"],))
        credentials["secured"] = True
        save_credentials(credentials)
        with connection.cursor() as cursor:
            cursor.execute("SHUTDOWN")
    wait_for_stop()


def start_instance(port: int) -> None:
    binary = mysql_binary()
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    INSTANCE_DIR.chmod(0o700)
    if not CREDENTIALS_PATH.exists():
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            raise RuntimeError("Existing data has no ownership credentials; refusing to reinitialize.")
        save_credentials({"password": secrets.token_urlsafe(32), "secured": False, "port": port})
    credentials = load_credentials()
    if credentials["port"] != port:
        raise RuntimeError("Managed MySQL port differs from DATABASE_URL; refusing to change it.")
    arguments = server_arguments(binary, port)
    if not (DATA_DIR / "mysql").is_dir():
        if DATA_DIR.exists() and any(DATA_DIR.iterdir()):
            raise RuntimeError("Incomplete MySQL data directory; inspect it manually before retrying.")
        print(f"Initializing native MySQL data at {DATA_DIR}", flush=True)
        run_server([*arguments, "--initialize-insecure"])
    if not credentials["secured"]:
        secure_initial_instance(arguments, credentials, port)
    print(f"Starting native MySQL at 127.0.0.1:{port}", flush=True)
    run_server([*arguments, "--daemonize"])
    wait_for_admin(credentials, port)
    if not port_is_open(port):
        raise RuntimeError("MySQL socket is ready but the configured TCP port is unavailable.")


def wait_for_stop() -> None:
    for _ in range(60):
        if not SOCKET_PATH.exists():
            return
        time.sleep(0.5)
    raise RuntimeError("MySQL shutdown timed out; data has not been removed.")


def stop_instance(port: int) -> None:
    if not CREDENTIALS_PATH.exists():
        raise RuntimeError("No project-owned MySQL instance; refusing to stop an external server.")
    if not SOCKET_PATH.exists():
        print("Project-owned MySQL is already stopped. Data is preserved.")
        return
    with admin_connection(load_credentials(), port) as connection:
        assert_owned(connection)
        with connection.cursor() as cursor:
            cursor.execute("SHUTDOWN")
    wait_for_stop()
    print("Project-owned MySQL stopped. Data is preserved.")
