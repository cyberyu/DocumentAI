#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f docker-compose-adaptable-rag.yml ]]; then
  COMPOSE_FILE="docker-compose-adaptable-rag.yml"
elif [[ -f docker-compose.yml ]]; then
  COMPOSE_FILE="docker-compose.yml"
else
  echo "No compose file found. Expected docker-compose-adaptable-rag.yml or docker-compose.yml"
  exit 1
fi

APP_SERVICES=(backend celery_worker celery_beat searxng)
APP_CONTAINERS=(
  surfsense-adaptable-rag-backend-1
  surfsense-adaptable-rag-celery_worker-1
  surfsense-adaptable-rag-celery_beat-1
  surfsense-adaptable-rag-searxng-1
)

echo "Using compose file: $COMPOSE_FILE"
echo "Stopping app services..."
for svc in "${APP_SERVICES[@]}"; do
  docker compose -f "$COMPOSE_FILE" stop "$svc" >/dev/null 2>&1 || true
done

echo "Disabling auto-restart for app containers..."
for container in "${APP_CONTAINERS[@]}"; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
    docker update --restart=no "$container" >/dev/null
    echo "locked: $container"
  fi
done

echo "Current compose status:"
docker compose -f "$COMPOSE_FILE" ps

echo "Done. Local mode is locked (Docker app containers disabled)."
