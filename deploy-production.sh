#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_NAME="rn-ota-production"
REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$REPOSITORY_ROOT/compose.production.yaml"
ENV_FILE="${ENV_FILE:-$REPOSITORY_ROOT/.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Production environment file not found: %s\n' "$ENV_FILE" >&2
  exit 1
fi

if [[ -n "$(git -C "$REPOSITORY_ROOT" status --porcelain)" ]]; then
  printf 'Refusing to deploy: the repository has local changes. Commit/push intended changes and keep EC2 checkout clean.\n' >&2
  exit 1
fi

git -C "$REPOSITORY_ROOT" pull --ff-only

COMPOSE=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  --file "$COMPOSE_FILE"
)

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach db
"${COMPOSE[@]}" up --detach --build --force-recreate api nginx

api_container=""
api_health="starting"
for attempt in {1..60}; do
  api_container="$("${COMPOSE[@]}" ps --quiet api)"
  if [[ -n "$api_container" ]]; then
    api_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$api_container" 2>/dev/null || true)"
    if [[ "$api_health" == "healthy" ]]; then
      nginx_container="$("${COMPOSE[@]}" ps --quiet nginx)"
      nginx_state="$(docker inspect --format '{{.State.Status}}' "$nginx_container" 2>/dev/null || true)"
      if [[ "$nginx_state" != "running" ]]; then
        printf 'Production Nginx is not running (state: %s). Recent Nginx logs:\n' "${nginx_state:-missing}" >&2
        "${COMPOSE[@]}" logs --tail=100 nginx >&2 || true
        exit 1
      fi
      printf 'Production deployment complete; API is healthy.\n'
      exit 0
    fi
    if [[ "$api_health" == "unhealthy" || "$api_health" == "missing" ]]; then
      break
    fi
  fi
  sleep 2
done

printf 'Production API did not become healthy (state: %s). Recent API logs:\n' "$api_health" >&2
"${COMPOSE[@]}" logs --tail=100 api >&2 || true
exit 1
