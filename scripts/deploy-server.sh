#!/usr/bin/env bash
# Runs on Ubuntu. Secret JSON is received only over SSH stdin, never as shell code.
# Usage: bash scripts/deploy-server.sh <release-id> <migrate:true|false>
set -Eeuo pipefail
umask 077

RELEASE_ID="${1:?Release ID is required}"
APPLY_MIGRATIONS="${2:-false}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="/srv/apps/hkhub/prod/server/api"
DATA_DIR="/srv/data/hkhub/prod/server/api"
SERVER_ENV_FILE="$DATA_DIR/server.env"
POSTGRES_DIR="/srv/data/hkhub/prod/shared/postgresql"
POSTGRES_ENV_FILE="$POSTGRES_DIR/postgres.env"
COMPOSE_PROJECT="hkhub-prod-api"

fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ "$RELEASE_ID" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || fail 'Invalid release ID.'
[[ "$APPLY_MIGRATIONS" == true || "$APPLY_MIGRATIONS" == false ]] || fail 'Invalid migration choice.'
[[ -f "$SOURCE_DIR/.env.prod" && -f "$SOURCE_DIR/Dockerfile" && -f "$SOURCE_DIR/docker-compose.prod.yml" ]] || fail 'Source archive is incomplete.'
# Only committed public configuration is sourced. Secrets are parsed as JSON below.
set -a
. "$SOURCE_DIR/.env.prod"
set +a
# Let each release.env control its own port/image, including when restoring an older release.
export -n API_HOST_PORT SERVER_IMAGE SERVER_ENV_FILE POSTGRES_ENV_FILE
[[ -z "${DATABASE_URL:-}" ]] || fail 'DATABASE_URL must come from GitHub Secrets, not public configuration or the host environment.'
[[ -z "${DEEPSEEK_API_KEY:-}" ]] || fail 'DEEPSEEK_API_KEY must come from GitHub Secrets, not public configuration or the host environment.'
[[ -z "${POSTGRES_PASSWORD:-}" ]] || fail 'POSTGRES_PASSWORD must come from GitHub Secrets, not public configuration or the host environment.'
[[ "$API_HOST_PORT" =~ ^[0-9]{2,5}$ ]] || fail 'Invalid host port.'
(( 10#$API_HOST_PORT >= 1024 && 10#$API_HOST_PORT <= 65535 )) || fail 'Host port must be between 1024 and 65535.'
[[ "$SERVER_IMAGE_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || fail 'Invalid local image name.'
[[ "$ENVIRONMENT" == production && "$DEBUG" == false ]] || fail 'Unsafe production runtime configuration.'
for program in docker flock realpath python3; do command -v "$program" >/dev/null || fail "Missing program: $program"; done
docker compose version >/dev/null
docker buildx version </dev/null >/dev/null 2>&1 || fail 'Docker buildx is required. Install the buildx plugin on this host before deployment.'

# Consume stdin before any Docker command can consume it. Values are never logged or sourced.
SECRET_PAYLOAD=""
IFS= read -r SECRET_PAYLOAD || [[ -n "$SECRET_PAYLOAD" ]] || fail 'Secret payload is missing.'
mkdir -p "$APP_DIR/releases" "$DATA_DIR" "$POSTGRES_DIR/data"
exec 9>"$APP_DIR/deploy.lock"
flock -w 600 9 || fail 'Another HK Hub deployment is still running.'
RELEASE_DIR="$APP_DIR/releases/$RELEASE_ID"
[[ ! -e "$RELEASE_DIR" ]] || fail 'This release already exists; use a new workflow attempt.'

previous_release=""
previous_image=""
if [[ -e "$APP_DIR/current" && ! -L "$APP_DIR/current" ]]; then
  fail 'current exists but is not a release symlink.'
fi
if [[ -L "$APP_DIR/current" ]]; then
  previous_release="$(realpath -e "$APP_DIR/current")"
  [[ "$previous_release" == "$APP_DIR/releases/"* ]] || fail 'Current release is outside the expected directory.'
  [[ -f "$previous_release/release.env" ]] || fail 'Previous release metadata is missing.'
  previous_id="$(docker compose --project-name "$COMPOSE_PROJECT" \
    --env-file "$previous_release/release.env" -f "$previous_release/docker-compose.prod.yml" \
    ps --all --quiet server)"
  if [[ -n "$previous_id" ]]; then
    previous_image="$(docker inspect --format '{{.Image}}' "$previous_id")"
  fi
fi

staged_env="$DATA_DIR/.server-env-$RELEASE_ID"
backup_env="$DATA_DIR/.server-env-backup-$RELEASE_ID"
staged_postgres_env="$POSTGRES_DIR/.postgres-env-$RELEASE_ID"
bootstrap_sql="$POSTGRES_DIR/.bootstrap-$RELEASE_ID.sql"
trap 'rm -f "$staged_env" "$backup_env" "$staged_postgres_env" "$bootstrap_sql"' EXIT
# Emit only known runtime settings, without deployment target variables or shell expansion.
printf '%s' "$SECRET_PAYLOAD" | python3 -c '
import json, os, sys
from urllib.parse import unquote, urlsplit

def invalid(message):
    sys.exit("Invalid production configuration: " + message + " (values redacted).")

try:
    secrets = json.load(sys.stdin)
except (ValueError, TypeError):
    invalid("Secret payload must be valid JSON")
if not isinstance(secrets, dict) or set(secrets) != {"DATABASE_URL", "POSTGRES_PASSWORD", "DEEPSEEK_API_KEY"}:
    invalid("Secret payload must contain DATABASE_URL, POSTGRES_PASSWORD and DEEPSEEK_API_KEY")
for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "DEEPSEEK_API_KEY"):
    if not isinstance(secrets[key], str):
        invalid(key + " must be a string")
    if any(character in secrets[key] for character in ("\r", "\n", "\x00")):
        invalid(key + " must not contain newlines or NUL; paste only the value")
database_url = secrets["DATABASE_URL"]
if not database_url.startswith(("postgresql+psycopg2://", "postgresql://")):
    invalid("DATABASE_URL must start with postgresql+psycopg2:// or postgresql://; do not include quotes or DATABASE_URL=")
try:
    url = urlsplit(database_url)
    host, port = url.hostname, url.port
except ValueError:
    invalid("DATABASE_URL cannot be parsed; check its port and URL-encode reserved password characters")
if host != "postgres":
    invalid("DATABASE_URL host must be postgres, not localhost, 127.0.0.1 or the server IP")
if port not in (None, 5432):
    invalid("DATABASE_URL port must be 5432")
if unquote(url.username or "") != "hkhub":
    invalid("DATABASE_URL username must be hkhub")
if url.path != "/hkhub":
    invalid("DATABASE_URL database must be hkhub; do not include surrounding quotes")
if url.query or url.fragment:
    invalid("DATABASE_URL must not contain query parameters or a fragment; URL-encode reserved password characters")
app_password = unquote(url.password or "")
admin_password = secrets["POSTGRES_PASSWORD"]
if not app_password.strip():
    invalid("DATABASE_URL must contain a non-empty application password")
if not admin_password.strip():
    invalid("POSTGRES_PASSWORD must be non-empty")
if app_password == admin_password:
    invalid("POSTGRES_PASSWORD must differ from the application password in DATABASE_URL")
if any(character in app_password for character in ("\r", "\n", "\x00")):
    invalid("DATABASE_URL decoded application password must not contain newlines or NUL")
keys = ("APP_NAME", "VERSION", "ENVIRONMENT", "API_PREFIX", "DEBUG", "LOG_LEVEL",
        "CORS_ORIGINS", "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW", "UPSTREAM_TIMEOUT_SECONDS", "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS",
        "COMPANY_OBSERVATION_ENABLED", "COMPANY_OBSERVATION_AI_ENABLED",
        "COMPANY_OBSERVATION_POLL_SECONDS", "COMPANY_OBSERVATION_SOURCE_TIMEOUT_SECONDS",
        "COMPANY_OBSERVATION_MAX_DOWNLOAD_BYTES", "COMPANY_OBSERVATION_MAX_SOURCE_ROWS",
        "COMPANY_OBSERVATION_BATCH_SIZE", "COMPANY_OBSERVATION_DAILY_CALL_LIMIT",
        "COMPANY_OBSERVATION_REPORT_CALL_LIMIT", "COMPANY_OBSERVATION_MAX_ANALYSIS_ATTEMPTS")
for key in keys:
    if key not in os.environ:
        invalid(key + " must be set in .env.prod")
values = {key: os.environ[key] for key in keys}
values.update({key: secrets[key] for key in ("DATABASE_URL", "DEEPSEEK_API_KEY")})
postgres_values = {"POSTGRES_USER": "postgres", "POSTGRES_DB": "postgres",
                   "POSTGRES_PASSWORD": admin_password,
                   "POSTGRES_HOST_AUTH_METHOD": "scram-sha-256"}
for key, value in (*values.items(), *postgres_values.items()):
    if any(character in value for character in ("\r", "\n", "\x00")):
        invalid(key + " must not contain newlines or NUL")
quote = chr(39)
def dotenv(values):
    return "".join(key + "=" + quote + value.replace(quote, chr(92) + quote)
                   + quote + "\n" for key, value in values.items())
print(dotenv(values), end="")
with open(sys.argv[1], "w", encoding="utf-8") as file:
    file.write(dotenv(postgres_values))
# Execute as the container-local postgres OS user; no admin secret enters the API.
# Existing roles/passwords are untouched. Credential rotation is a separate operation.
literal = quote + app_password.replace(quote, quote + quote) + quote
statement = "CREATE ROLE hkhub LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD " + literal
with open(sys.argv[2], "w", encoding="utf-8") as file:
    file.write("SET standard_conforming_strings = on;\n")
    file.write("SELECT " + quote + statement.replace(quote, quote + quote) + quote
               + " WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
               + quote + "hkhub" + quote + ")\\gexec\n")
    file.write("SELECT " + quote + "CREATE DATABASE hkhub OWNER hkhub" + quote
               + " WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = "
               + quote + "hkhub" + quote + ")\\gexec\n")
' "$staged_postgres_env" "$bootstrap_sql" > "$staged_env"
unset SECRET_PAYLOAD
chmod 600 "$staged_env" "$staged_postgres_env" "$bootstrap_sql"
# PostgreSQL image env applies only at initialization. Do not silently rotate it.
if [[ -f "$POSTGRES_ENV_FILE" ]]; then
  cmp -s "$staged_postgres_env" "$POSTGRES_ENV_FILE" || fail 'PostgreSQL initialization settings changed. Rotate database credentials separately before deployment.'
else
  [[ -z "$(find "$POSTGRES_DIR/data" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail 'Existing PostgreSQL data has no initialization metadata. Review it before deployment.'
  mv "$staged_postgres_env" "$POSTGRES_ENV_FILE"
fi

# Build from this exact source release while the existing API keeps serving.
mkdir "$RELEASE_DIR"
cp -a "$SOURCE_DIR/." "$RELEASE_DIR/"
SERVER_IMAGE="$SERVER_IMAGE_NAME:$RELEASE_ID"
# BuildKit retains dependency layers and the pip download cache across releases.
DOCKER_BUILDKIT=1 docker build --progress=plain --file "$RELEASE_DIR/Dockerfile" --tag "$SERVER_IMAGE" "$RELEASE_DIR"
# Pin the local content; deployment and rollback never need a registry.
SERVER_IMAGE="$(docker image inspect --format '{{.Id}}' "$SERVER_IMAGE")"
printf 'SERVER_IMAGE=%s\nSERVER_ENV_FILE=%s\nAPI_HOST_PORT=%s\nPOSTGRES_ENV_FILE=%s\n' \
  "$SERVER_IMAGE" "$SERVER_ENV_FILE" "$API_HOST_PORT" "$POSTGRES_ENV_FILE" > "$RELEASE_DIR/release.env"
chmod 600 "$RELEASE_DIR/release.env"

compose_release() {
  docker compose --project-name "$COMPOSE_PROJECT" --env-file "$RELEASE_DIR/release.env" \
    -f "$RELEASE_DIR/docker-compose.prod.yml" "$@"
}

background_services() {
  local directory="$1" services worker
  services="$(docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
    -f "$directory/docker-compose.prod.yml" config --services)" || return 1
  # Old release definitions are supported only for deployment handover and rollback.
  for worker in worker commute-worker rent-worker company-worker; do
    if grep -qx "$worker" <<< "$services"; then
      printf '%s\n' "$worker"
    fi
  done
  return 0
}

remove_background_containers() {
  local directory="$1" services
  local -a workers
  services="$(background_services "$directory")" || return 1
  [[ -n "$services" ]] || return 0
  mapfile -t workers <<< "$services"
  docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
    -f "$directory/docker-compose.prod.yml" stop "${workers[@]}" || return 1
  # Remove only stopped background containers. Never remove PostgreSQL or its data.
  docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
    -f "$directory/docker-compose.prod.yml" rm --force "${workers[@]}"
}

wait_until_ready() {
  local directory="$1" id status attempt worker_id worker_status services worker workers_ready
  for ((attempt = 0; attempt < 30; attempt++)); do
    id="$(docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
      -f "$directory/docker-compose.prod.yml" ps --all --quiet server)" || return 1
    if [[ -n "$id" ]]; then
      status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")" || return 1
      if [[ "$status" == 'running healthy' ]]; then
        # Check only workers present in this release, retaining old-release rollback support.
        services="$(docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
          -f "$directory/docker-compose.prod.yml" config --services)" || return 1
        workers_ready=true
        for worker in worker commute-worker rent-worker company-worker; do
          grep -qx "$worker" <<< "$services" || continue
          worker_id="$(docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
            -f "$directory/docker-compose.prod.yml" ps --all --quiet "$worker")" || return 1
          if [[ -z "$worker_id" ]]; then
            workers_ready=false
            continue
          fi
          worker_status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}} {{end}}{{.RestartCount}}' "$worker_id")" || return 1
          [[ "$worker_status" != exited* && "$worker_status" != dead* ]] || return 1
          if [[ "$worker" == worker ]]; then
            [[ "$worker_status" == 'running healthy 0' ]] || workers_ready=false
          else
            [[ "$worker_status" == 'running 0' ]] || workers_ready=false
          fi
        done
        [[ "$workers_ready" != true ]] || return 0
      fi
      [[ "$status" != exited* && "$status" != dead* ]] || return 1
    fi
    sleep 5
  done
  return 1
}

switch_current() {
  local directory="$1" link="$APP_DIR/.current-$RELEASE_ID"
  ln -sfn "$directory" "$link"
  mv -Tf "$link" "$APP_DIR/current"
}

activation_attempted=false
configuration_installed=false
rollback_on_error() {
  local result=$? rollback_status=0 previous_workers
  local -a workers
  trap - ERR
  set +e
  if [[ "$configuration_installed" == true ]]; then
    if [[ -f "$backup_env" ]]; then
      mv -f "$backup_env" "$SERVER_ENV_FILE"
    fi
  fi
  if [[ "$activation_attempted" == true ]]; then
    printf 'API activation failed. Attempting application rollback; SQL migrations are NOT rolled back.\n' >&2
    remove_background_containers "$RELEASE_DIR"
    rollback_status=$?
    if [[ -n "$previous_release" && -n "$previous_image" ]]; then
      if [[ $rollback_status == 0 ]]; then
        previous_workers="$(background_services "$previous_release")"
        rollback_status=$?
      fi
      if [[ $rollback_status == 0 ]]; then
        workers=()
        if [[ -n "$previous_workers" ]]; then
          mapfile -t workers <<< "$previous_workers"
        fi
        SERVER_IMAGE="$previous_image" docker compose --project-name "$COMPOSE_PROJECT" \
          --env-file "$previous_release/release.env" -f "$previous_release/docker-compose.prod.yml" \
          up -d --no-build --pull never --no-deps server "${workers[@]}"
        rollback_status=$?
      fi
      if [[ $rollback_status == 0 ]] && wait_until_ready "$previous_release"; then
        switch_current "$previous_release"
        printf 'Previous API image and configuration restored and ready.\n' >&2
      else
        printf 'Rollback did not become ready; manual intervention is required.\n' >&2
      fi
    else
      docker compose --project-name "$COMPOSE_PROJECT" --env-file "$RELEASE_DIR/release.env" \
        -f "$RELEASE_DIR/docker-compose.prod.yml" stop server worker
      printf 'No previous running release. Manual cleanup may be needed; database untouched.\n' >&2
    fi
  fi
  exit "$result"
}
trap rollback_on_error ERR

if [[ -f "$SERVER_ENV_FILE" ]]; then
  cp -p "$SERVER_ENV_FILE" "$backup_env"
  chmod 600 "$backup_env"
fi
mv -f "$staged_env" "$SERVER_ENV_FILE"
configuration_installed=true
# Bootstrap once, then start/reuse the existing DB without recreating or upgrading it.
compose_release up -d --no-recreate --wait --wait-timeout 150 postgres
if ! compose_release exec -T --user postgres postgres psql --set ON_ERROR_STOP=on --dbname=postgres \
  < "$bootstrap_sql" > /dev/null 2>&1; then
  printf 'Database bootstrap failed (credentials redacted). PostgreSQL data is preserved.\n' >&2
  false
fi
rm -f "$bootstrap_sql"
# Migrations need explicit approval and must remain compatible with the previous API.
if [[ "$APPLY_MIGRATIONS" == true ]]; then
  compose_release run --rm --no-deps server python -m app.core.migrations apply
fi
# Refuse activation before all collector schemas are migrated.
compose_release run --rm --no-deps server python -c \
  "from app.core.database import get_engine; from sqlalchemy import text; connection = get_engine().connect(); connection.execute(text('SELECT audience, hk_slot, attempt_count, payload FROM commute_observations LIMIT 0')); connection.execute(text('SELECT source_id, active_snapshot_id, attempt_count FROM rent_source_state LIMIT 0')); connection.execute(text('SELECT id, catalog, series_data FROM rent_snapshots LIMIT 0')); connection.execute(text('SELECT id, dataset_fingerprint, analysis_status FROM company_period_reports LIMIT 0')); connection.execute(text('SELECT name, claim_token, lease_until FROM company_worker_state LIMIT 0')); connection.close()"
activation_attempted=true
# Drain and remove the previous topology before starting new collectors, avoiding duplicates.
if [[ -n "$previous_release" ]]; then
  remove_background_containers "$previous_release"
fi
compose_release up -d --no-build --pull never --no-deps server worker
if ! wait_until_ready "$RELEASE_DIR"; then
  printf 'New API or background worker did not pass readiness checks.\n' >&2
  false
fi
switch_current "$RELEASE_DIR"
trap - ERR
printf 'HK Hub API deployed: release=%s port=%s image=%s\n' "$RELEASE_ID" "$API_HOST_PORT" "$SERVER_IMAGE"
# Keep previous releases/images for application rollback. Never clean /srv/data,
# remove/recreate PostgreSQL, run compose down, or manage host PostgreSQL/Nginx.
