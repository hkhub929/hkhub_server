#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"

usage() {
  cat <<'EOF'
Usage: ./cmd.sh [command] [args]

  init                 Install dependencies; start local MySQL and create database if needed
  api, dev (default)   Apply migrations and start API at http://localhost:8000
  serve                Start API without reload or automatic migrations
  db:up                Ensure native local MySQL on 3307 and configured database exist
  db:down              Stop only project-owned MySQL; preserve its data
  db:check             Verify actual database connection, port and MySQL version
  db:migrate           Apply pending SQL files from db/migrations
  db:status            List applied and pending SQL migrations
  db:rollback --confirm  Roll back the latest migration (may delete data)
  image:build [args]   Build the backend image (requires IMAGE)
  image:push          Push the backend image (requires IMAGE and registry login)
  image:publish [args]  Build and then push the backend image
  test [args]          Run pytest
  lint                 Run Ruff
  help                 Show this help

Local API runs directly in .venv; local MySQL is native, never containerized.
init auto-starts/provisions only ENVIRONMENT=local + localhost:3307 targets.
Managed data and private admin credentials live in .local/mysql (excluded from Git/images).
Install native MySQL first if mysqld is unavailable, or configure MYSQLD_BIN.
Existing instances need valid DATABASE_URL or LOCAL_DATABASE_ADMIN_URL credentials.
Set LOCAL_DATABASE_AUTOSTART=false to use an independently managed local database.
Production databases are never started or created by init.
Only image:* commands use containers, for packaging and publishing the API.
IMAGE must specify your registry/repository:version; registry login is handled separately.
IMAGE_PLATFORM defaults to linux/amd64; set linux/arm64 for ARM servers.
CONTAINER_RUNTIME defaults to docker; set podman to use Podman.
The image listens on port 8000. Inject DATABASE_URL/CORS_ORIGINS at deployment time.
Apply migrations separately with: python -m app.core.migrations apply
API_HOST and API_PORT override the local API bind address (defaults: 0.0.0.0:8000).
EOF
}

require_venv() {
  if [[ ! -x "$PYTHON" ]]; then
    printf 'Missing virtual environment. Run ./cmd.sh init first.\n' >&2
    exit 1
  fi
}

require_env() {
  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    printf 'Missing .env. Run ./cmd.sh init and configure DATABASE_URL.\n' >&2
    exit 1
  fi
}

migrate() {
  require_venv
  require_env
  "$PYTHON" -m app.core.migrations "$@"
}

local_database() {
  require_venv
  require_env
  "$PYTHON" -m app.core.local_database "$@"
}

require_image() {
  if [[ -z "${IMAGE:-}" ]]; then
    printf 'Set IMAGE to your registry/repository:version before using image commands.\n' >&2
    exit 1
  fi
  command -v "$CONTAINER_RUNTIME" >/dev/null || {
    printf 'Container runtime not found: %s\n' "$CONTAINER_RUNTIME" >&2
    exit 1
  }
}

build_image() {
  require_image
  "$CONTAINER_RUNTIME" build \
    --platform "${IMAGE_PLATFORM:-linux/amd64}" \
    --file "$PROJECT_ROOT/Dockerfile" --tag "$IMAGE" "$@" "$PROJECT_ROOT"
}

push_image() {
  require_image
  "$CONTAINER_RUNTIME" push "$IMAGE"
}

command="${1:-api}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command" in
  init)
    if [[ ! -f .env ]]; then cp .env.example .env; fi
    if [[ ! -x "$PYTHON" ]]; then "${PYTHON_BIN:-python3}" -m venv .venv; fi
    "$PYTHON" -m pip install -e '.[dev]'
    local_database init
    printf 'Initialization complete. Run ./cmd.sh api to apply migrations and start the API.\n'
    ;;
  api|dev)
    local_database init
    migrate apply
    exec "$PYTHON" -m uvicorn app.main:app --reload \
      --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" "$@"
    ;;
  serve)
    require_venv
    require_env
    exec "$PYTHON" -m uvicorn app.main:app \
      --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" "$@"
    ;;
  db:up)
    local_database up
    ;;
  db:down)
    local_database down
    ;;
  db:check)
    local_database check
    ;;
  db:migrate)
    migrate apply "$@"
    ;;
  db:status)
    migrate list "$@"
    ;;
  db:rollback)
    migrate rollback "$@"
    ;;
  image:build)
    build_image "$@"
    ;;
  image:push)
    push_image
    ;;
  image:publish)
    build_image "$@"
    push_image
    ;;
  test)
    require_venv
    exec "$PYTHON" -m pytest "$@"
    ;;
  lint)
    require_venv
    exec "$PYTHON" -m ruff check app tests
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    printf 'Unknown command: %s\n' "$command" >&2
    usage >&2
    exit 1
    ;;
esac
