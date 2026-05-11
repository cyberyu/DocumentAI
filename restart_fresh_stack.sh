#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

WIPE_DATA=false
AUTO_CONFIRM=false

for arg in "$@"; do
  case "$arg" in
    --wipe-data)
      WIPE_DATA=true
      ;;
    --yes|-y)
      AUTO_CONFIRM=true
      ;;
    --help|-h)
      echo "Usage: ./restart_fresh_stack.sh [--wipe-data] [--yes]"
      echo "  --wipe-data   Remove Docker volumes before restart (destructive)"
      echo "  --yes, -y     Skip confirmation prompt when used with --wipe-data"
      exit 0
      ;;
    *)
      echo "❌ Unknown argument: $arg"
      echo "Run ./restart_fresh_stack.sh --help for usage"
      exit 1
      ;;
  esac
done

DEFAULT_COMPOSE_FILE="docker-compose-adaptable-rag.yml"
FALLBACK_COMPOSE_FILE="docker-compose.yml"

if [[ -f "$DEFAULT_COMPOSE_FILE" ]]; then
  COMPOSE_FILE="$DEFAULT_COMPOSE_FILE"
elif [[ -f "$FALLBACK_COMPOSE_FILE" ]]; then
  COMPOSE_FILE="$FALLBACK_COMPOSE_FILE"
else
  echo "❌ No compose file found. Expected $DEFAULT_COMPOSE_FILE or $FALLBACK_COMPOSE_FILE"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker is not installed or not in PATH"
  exit 1
fi

echo "📦 Using compose file: $COMPOSE_FILE"

SERVICES=(db redis opensearch backend celery_worker celery_beat frontend)

FRONTEND_PORT_DEFAULT="${FRONTEND_PORT:-3000}"
BACKEND_PORT_DEFAULT="${BACKEND_PORT:-8929}"
PORTS_TO_FREE=("$FRONTEND_PORT_DEFAULT" "$BACKEND_PORT_DEFAULT" 5432 6379 9200)

kill_port_users() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" || true)"
  if [[ -n "$pids" ]]; then
    echo "⚠️  Releasing port $port (PIDs: $pids)"
    kill $pids || true
    sleep 1
    pids="$(lsof -ti tcp:"$port" || true)"
    if [[ -n "$pids" ]]; then
      echo "⚠️  Force killing remaining PIDs on port $port: $pids"
      kill -9 $pids || true
    fi
  fi
}

echo "🧹 Clearing possible local port conflicts..."
for port in "${PORTS_TO_FREE[@]}"; do
  kill_port_users "$port"
done

echo "🛑 Stopping existing stack..."
if [[ "$WIPE_DATA" == "true" ]]; then
  echo "⚠️  --wipe-data selected: this will DELETE Docker volumes for this stack (Postgres, OpenSearch, Redis data)."
  if [[ "$AUTO_CONFIRM" != "true" ]]; then
    read -r -p "Type WIPE to continue: " confirm
    if [[ "$confirm" != "WIPE" ]]; then
      echo "Aborted wipe."
      exit 1
    fi
  fi
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
else
  docker compose -f "$COMPOSE_FILE" down --remove-orphans
fi

echo "🚀 Starting fresh containers (force recreate + build)..."
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate "${SERVICES[@]}"

wait_for_service() {
  local service="$1"
  local timeout_seconds="$2"
  local started_at
  started_at="$(date +%s)"

  while true; do
    local cid
    cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$service" || true)"

    if [[ -z "$cid" ]]; then
      if (( $(date +%s) - started_at > timeout_seconds )); then
        echo "❌ Timeout waiting for container id for service '$service'"
        return 1
      fi
      sleep 2
      continue
    fi

    local state
    state="$(docker inspect -f '{{.State.Status}}' "$cid")"
    local health
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"

    if [[ "$state" == "running" ]]; then
      if [[ "$health" == "none" || "$health" == "healthy" ]]; then
        echo "✅ $service is running${health:+ (health: $health)}"
        return 0
      fi
    fi

    if (( $(date +%s) - started_at > timeout_seconds )); then
      echo "❌ Timeout waiting for service '$service' (state=$state, health=$health)"
      return 1
    fi

    sleep 3
  done
}

echo "⏳ Waiting for services to be ready..."
for service in "${SERVICES[@]}"; do
  wait_for_service "$service" 300
done

BACKEND_PORT="$(docker compose -f "$COMPOSE_FILE" port backend 8000 | sed -E 's/.*:([0-9]+)$/\1/' || true)"
FRONTEND_PORT="$(docker compose -f "$COMPOSE_FILE" port frontend 3000 | sed -E 's/.*:([0-9]+)$/\1/' || true)"

if [[ -n "$BACKEND_PORT" ]]; then
  echo "🔎 Checking backend health endpoint on :$BACKEND_PORT"
  curl -fsS "http://localhost:$BACKEND_PORT/health" >/dev/null
  echo "✅ Backend health check passed"
fi

if [[ -n "$FRONTEND_PORT" ]]; then
  echo "🔎 Checking frontend endpoint on :$FRONTEND_PORT"
  curl -fsS "http://localhost:$FRONTEND_PORT" >/dev/null
  echo "✅ Frontend endpoint check passed"
fi

echo ""
echo "🎉 Fresh restart complete"
if [[ "$WIPE_DATA" == "true" ]]; then
  echo "Mode: WIPE DATA (volumes recreated)"
else
  echo "Mode: Normal restart (data preserved)"
fi
echo "Compose file: $COMPOSE_FILE"
echo "Frontend: http://localhost:${FRONTEND_PORT:-3000}"
echo "Backend:  http://localhost:${BACKEND_PORT:-8929}/health"
echo ""
echo "Service status:"
docker compose -f "$COMPOSE_FILE" ps
