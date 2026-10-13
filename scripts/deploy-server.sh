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
COMPOSE_PROJECT="hkhub-prod-api"

fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ "$RELEASE_ID" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || fail 'Invalid release ID.'
[[ "$APPLY_MIGRATIONS" == true || "$APPLY_MIGRATIONS" == false ]] || fail 'Invalid migration choice.'
[[ -f "$SOURCE_DIR/.envprod" && -f "$SOURCE_DIR/Dockerfile" && -f "$SOURCE_DIR/docker-compose.prod.yml" ]] || fail 'Source archive is incomplete.'
# Only committed public configuration is sourced. Secrets are parsed as JSON below.
set -a
. "$SOURCE_DIR/.envprod"
set +a
# Let each release.env control its own port/image, including when restoring an older release.
export -n API_HOST_PORT SERVER_IMAGE SERVER_ENV_FILE
[[ -z "${DATABASE_URL:-}" ]] || fail 'DATABASE_URL must come from GitHub Secrets, not public configuration or the host environment.'
[[ -z "${DEEPSEEK_API_KEY:-}" ]] || fail 'DEEPSEEK_API_KEY must come from GitHub Secrets, not public configuration or the host environment.'
[[ "$API_HOST_PORT" =~ ^[0-9]{2,5}$ ]] || fail 'Invalid host port.'
(( 10#$API_HOST_PORT >= 1024 && 10#$API_HOST_PORT <= 65535 )) || fail 'Host port must be between 1024 and 65535.'
[[ "$SERVER_IMAGE_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || fail 'Invalid local image name.'
[[ "$ENVIRONMENT" == production && "$DEBUG" == false ]] || fail 'Unsafe production runtime configuration.'
for program in docker flock realpath python3; do command -v "$program" >/dev/null || fail "Missing program: $program"; done
docker compose version >/dev/null

# Consume stdin before any Docker command can consume it. Values are never logged or sourced.
SECRET_PAYLOAD=""
IFS= read -r SECRET_PAYLOAD || [[ -n "$SECRET_PAYLOAD" ]] || fail 'Secret payload is missing.'
mkdir -p "$APP_DIR/releases" "$DATA_DIR"
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
trap 'rm -f "$staged_env" "$backup_env"' EXIT
# Emit only known runtime settings, without deployment target variables or shell expansion.
printf '%s' "$SECRET_PAYLOAD" | python3 -c '
import json, os, sys
try:
    secrets = json.load(sys.stdin)
    if set(secrets) != {"DATABASE_URL", "DEEPSEEK_API_KEY"}:
        raise ValueError()
    if not isinstance(secrets["DEEPSEEK_API_KEY"], str):
        raise ValueError()
    database_url = secrets["DATABASE_URL"]
    if not isinstance(database_url, str) or not database_url.startswith(("postgresql+psycopg2://", "postgresql://")):
        raise ValueError()
    keys = ("APP_NAME", "VERSION", "ENVIRONMENT", "API_PREFIX", "DEBUG", "LOG_LEVEL",
            "CORS_ORIGINS", "DATABASE_POOL_SIZE",
            "DATABASE_MAX_OVERFLOW", "UPSTREAM_TIMEOUT_SECONDS", "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS")
    values = {key: os.environ[key] for key in keys}
    values.update(secrets)
    if any(any(character in value for character in ("\r", "\n", "\x00")) for value in values.values()):
        raise ValueError()
except (ValueError, KeyError, TypeError):
    sys.exit("Invalid production configuration or secrets (values redacted).")
quote = chr(39)
for key, value in values.items():
    # Compose dotenv single quotes prevent dollar interpolation in credentials.
    escaped = value.replace(quote, chr(92) + quote)
    print(key + "=" + quote + escaped + quote)
' > "$staged_env"
unset SECRET_PAYLOAD
chmod 600 "$staged_env"

# Build from this exact source release while the existing API keeps serving.
mkdir "$RELEASE_DIR"
cp -a "$SOURCE_DIR/." "$RELEASE_DIR/"
SERVER_IMAGE="$SERVER_IMAGE_NAME:$RELEASE_ID"
docker build --file "$RELEASE_DIR/Dockerfile" --tag "$SERVER_IMAGE" "$RELEASE_DIR"
# Pin the local content; deployment and rollback never need a registry.
SERVER_IMAGE="$(docker image inspect --format '{{.Id}}' "$SERVER_IMAGE")"
printf 'SERVER_IMAGE=%s\nSERVER_ENV_FILE=%s\nAPI_HOST_PORT=%s\n' \
  "$SERVER_IMAGE" "$SERVER_ENV_FILE" "$API_HOST_PORT" > "$RELEASE_DIR/release.env"
chmod 600 "$RELEASE_DIR/release.env"

compose_release() {
  docker compose --project-name "$COMPOSE_PROJECT" --env-file "$RELEASE_DIR/release.env" \
    -f "$RELEASE_DIR/docker-compose.prod.yml" "$@"
}

wait_until_ready() {
  local directory="$1" id status attempt
  for ((attempt = 0; attempt < 30; attempt++)); do
    id="$(docker compose --project-name "$COMPOSE_PROJECT" --env-file "$directory/release.env" \
      -f "$directory/docker-compose.prod.yml" ps --all --quiet server)" || return 1
    if [[ -n "$id" ]]; then
      status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")" || return 1
      [[ "$status" != 'running healthy' ]] || return 0
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
  local result=$?
  trap - ERR
  set +e
  if [[ "$configuration_installed" == true ]]; then
    if [[ -f "$backup_env" ]]; then
      mv -f "$backup_env" "$SERVER_ENV_FILE"
    fi
  fi
  if [[ "$activation_attempted" == true ]]; then
    printf 'API activation failed. Attempting application rollback; SQL migrations are NOT rolled back.\n' >&2
    if [[ -n "$previous_release" && -n "$previous_image" ]]; then
      SERVER_IMAGE="$previous_image" docker compose --project-name "$COMPOSE_PROJECT" \
        --env-file "$previous_release/release.env" -f "$previous_release/docker-compose.prod.yml" \
        up -d --no-build --pull never --no-deps server
      if [[ $? == 0 ]] && wait_until_ready "$previous_release"; then
        switch_current "$previous_release"
        printf 'Previous API image and configuration restored and ready.\n' >&2
      else
        printf 'Rollback did not become ready; manual intervention is required.\n' >&2
      fi
    else
      docker compose --project-name "$COMPOSE_PROJECT" --env-file "$RELEASE_DIR/release.env" \
        -f "$RELEASE_DIR/docker-compose.prod.yml" stop server
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
# Migrations need explicit approval and must remain compatible with the previous API.
if [[ "$APPLY_MIGRATIONS" == true ]]; then
  compose_release run --rm --no-deps server python -m app.core.migrations apply
fi
activation_attempted=true
compose_release up -d --no-build --pull never --no-deps server
if ! wait_until_ready "$RELEASE_DIR"; then
  printf 'New API did not pass the database-aware readiness check.\n' >&2
  false
fi
switch_current "$RELEASE_DIR"
trap - ERR
printf 'HK Hub API deployed: release=%s port=%s image=%s\n' "$RELEASE_ID" "$API_HOST_PORT" "$SERVER_IMAGE"
# Keep previous releases/images for application rollback. Never clean /srv/data or manage PostgreSQL/Nginx.
