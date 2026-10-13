#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"

usage() {
  cat <<'EOF'
Usage: ./cmd.sh [command] [args]

  init                 Install dependencies and prepare .env; never start a database
  api, dev (default)   Apply migrations and start API at http://localhost:8000
  serve                Start API without reload or automatic migrations
  db:up                Start project-owned PostgreSQL on 5433 and create database if needed
  db:down              Stop only project-owned PostgreSQL; preserve its data
  db:check             Verify configured PostgreSQL connection, port and version
  db:migrate           Apply pending SQL files from db/migrations
  db:status            List applied and pending SQL migrations
  db:rollback --confirm  Roll back the latest migration (may delete data)
  image:build [args]   Build the backend image (requires IMAGE)
  image:push          Push the backend image (requires IMAGE and registry login)
  image:publish [args]  Build and then push the backend image
  test [args]          Run pytest
  lint                 Run Ruff
  help                 Show this help

Local API runs directly in .venv; local PostgreSQL is native, never containerized.
init and API commands never start the database. Run db:up separately before api.
db:up/db:down manage only ENVIRONMENT=local + localhost:5433 project-owned targets.
Managed data lives in .local/postgresql (excluded from Git/images).
Install native PostgreSQL first, or configure POSTGRES_BIN_DIR.
For external instances, configure DATABASE_URL and start/manage them independently.
Production databases are never started or created by these commands.
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
    printf 'Dependencies ready. Run ./cmd.sh db:up separately, then ./cmd.sh api.\n'
    ;;
  api|dev)
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
