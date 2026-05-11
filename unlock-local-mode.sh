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

START_APP_SERVICES="${1:-}"

echo "Using compose file: $COMPOSE_FILE"
echo "Restoring auto-restart for app containers..."
for container in "${APP_CONTAINERS[@]}"; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
    docker update --restart=unless-stopped "$container" >/dev/null
    echo "unlocked: $container"
  fi
done

if [[ "$START_APP_SERVICES" == "--start" ]]; then
  echo "Starting app services..."
  docker compose -f "$COMPOSE_FILE" up -d "${APP_SERVICES[@]}"
fi

echo "Current compose status:"
docker compose -f "$COMPOSE_FILE" ps

echo "Done. Local mode lock is removed."
