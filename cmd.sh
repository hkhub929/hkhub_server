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
                       api, dev and serve stop any process already listening on API_PORT first
  worker               Apply migrations and supervise all background collectors
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
init, API and worker commands never start the database. Run db:up separately first.
Run worker in one terminal alongside the API; Ctrl+C stops all background collectors.
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

# List PIDs listening on a TCP port. Falls back when lsof is unavailable.
listening_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null | tr -s ' \t' '\n' || true
  else
    pgrep -f "python.*-m uvicorn" 2>/dev/null || true
  fi
}

# Recursively list child PIDs, deepest first.
descendant_pids() {
  local parent="$1" child
  for child in $(pgrep -P "$parent" 2>/dev/null || true); do
    descendant_pids "$child"
    printf '%s\n' "$child"
  done
}

# Listening PIDs plus their descendants; uvicorn --reload keeps both a reloader
# and a worker process bound to the same socket, so removing only one is not enough.
port_process_tree() {
  local port="$1" pid tree=""
  while IFS= read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    # Never target this script or its parent shell.
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    tree+="$pid"$'\n'
    tree+="$(descendant_pids "$pid")"$'\n'
  done < <(listening_pids "$port")
  printf '%s' "$tree" | sort -u | grep -v '^$' || true
}

stop_port() {
  local port="$1" pids remaining waited=0
  pids="$(port_process_tree "$port")"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  printf 'Stopping existing process(es) on port %s: %s\n' "$port" "$(printf '%s ' $pids)"
  kill $pids 2>/dev/null || true
  while [[ $waited -lt 20 ]]; do
    remaining="$(port_process_tree "$port")"
    if [[ -z "$remaining" ]]; then
      printf 'Port %s is free.\n' "$port"
      return 0
    fi
    sleep 0.25
    waited=$((waited + 1))
  done
  printf 'Graceful stop timed out; force killing: %s\n' "$(printf '%s ' $remaining)" >&2
  kill -9 $remaining 2>/dev/null || true
  sleep 0.5
}

# Restarting the API always reclaims its port so a stale server can never hold it.
restart_api() {
  stop_port "${API_PORT:-8000}"
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
    restart_api
    exec "$PYTHON" -m uvicorn app.main:app --reload \
      --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" "$@"
    ;;
  serve)
    require_venv
    require_env
    restart_api
    exec "$PYTHON" -m uvicorn app.main:app \
      --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" "$@"
    ;;
  worker)
    migrate apply
    exec "$PYTHON" -m app.worker "$@"
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
