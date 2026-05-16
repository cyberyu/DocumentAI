#!/bin/bash
# =============================================================================
# start_local_bundle.sh — Start all SurfSense services locally
#
# Starts:  Docker infra → Backend → Celery → Frontend
# Usage:   ./start_local_bundle.sh
# Stop:    Press Ctrl+C to gracefully shut down all services
#
# ── Docker services (managed by docker-compose-adaptable-rag.yml) ──────────
#     All are separate containers, started together as a Compose group.
#
#     docker-compose-adaptable-rag.yml  →  Project: surfsense-adaptable-rag
#       │
#       ├── 🐘 db          (pgvector/pgvector:pg17)      Port: 5432
#       ├── 🔍 opensearch  (opensearchproject/opensearch:2.11.1)  Port: 9200
#       ├── 🟥 redis       (redis:8-alpine)              Port: 6379
#       └── 🔄 zero-cache  (rocicorp/zero:0.26.2)        Port: 5929 → 4848
#
# ── Local processes ────────────────────────────────────────────────────────
#     Backend  → uvicorn (FastAPI)   Port: 8930
#     Worker   → celery              — (background tasks)
#     Frontend → next dev (Next.js)  Port: 3000
# =============================================================================

set -e
shopt -s expand_aliases

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/source/SurfSense/surfsense_backend"
FRONTEND_DIR="$REPO_ROOT/source/SurfSense/surfsense_web"
COMPOSE_FILE="$REPO_ROOT/docker-compose-adaptable-rag.yml"

PIDS=()        # Track background process PIDs
trap cleanup SIGINT SIGTERM EXIT

cleanup() {
    echo ""
    echo "[stop] Shutting down all services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    for pid in "${PIDS[@]}"; do
        wait "$pid" 2>/dev/null || true
    done
    echo "[stop] All services stopped."
    exit 0
}

# ── Helper: wait for HTTP 200 ────────────────────────────────────────────────
wait_for_http() {
    local url="$1" service="$2" max=45
    echo -n "  Waiting for $service at $url..."
    for i in $(seq 1 "$max"); do
        if curl -sf "$url" >/dev/null 2>&1; then
            echo " ready ($i s)"
            return 0
        fi
        sleep 2
        echo -n "."
    done
    echo ""
    echo "  ⚠  $service not ready after $max s, continuing..."
    return 0
}

# =============================================================================
# Conda environment
# =============================================================================
echo "  Activating conda env 'documentai'..."
eval "$(conda shell.bash hook)"
if conda activate documentai 2>/dev/null; then
    echo "   ✓ conda env 'documentai' activated"
else
    echo "   ⚠  Failed to activate 'documentai'. Create it: conda create -n documentai python=3.12"
fi

# =============================================================================
# STEP 1 — Start Docker infrastructure
# =============================================================================
echo "══════════════════════════════════════════════════════════════════"
echo "  SurfSense — Local Start"
echo "  Repo: $REPO_ROOT"
echo "══════════════════════════════════════════════════════════════════"
echo ""

echo "[1/5] Starting Docker infrastructure (db, opensearch, redis, zero-cache)..."
cd "$REPO_ROOT"
docker compose -f "$COMPOSE_FILE" up -d db opensearch redis zero-cache 2>&1 | sed 's/^/   /'

# Wait for PostgreSQL
echo -n "  Waiting for PostgreSQL (localhost:5432)..."
for i in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U surfsense -d surfsense >/dev/null 2>&1; then
        echo " ready ($i s)"
        break
    fi
    sleep 1
    echo -n "."
done

# Wait for OpenSearch
echo -n "  Waiting for OpenSearch (localhost:9200)..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:9200/_cluster/health >/dev/null 2>&1; then
        echo " ready ($i s)"
        break
    fi
    sleep 2
    echo -n "."
done

# Wait for Redis
echo -n "  Waiting for Redis (localhost:6379)..."
for i in $(seq 1 20); do
    if docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        echo " ready ($i s)"
        break
    fi
    sleep 1
    echo -n "."
done
echo ""

# =============================================================================
# STEP 2 — Verify backend .env
# =============================================================================
echo "[2/5] Backend .env..."
if [ -f "$BACKEND_DIR/.env" ]; then
    echo "   ✓ Found $BACKEND_DIR/.env"
else
    echo "   Creating $BACKEND_DIR/.env from example..."
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "   ⚠  Edit $BACKEND_DIR/.env and add your API keys / secrets."
fi

# Ensure frontend .env.local has ZeroCache URL
if ! grep -q "NEXT_PUBLIC_ZERO_CACHE_URL" "$FRONTEND_DIR/.env.local" 2>/dev/null; then
    echo "   Adding NEXT_PUBLIC_ZERO_CACHE_URL to frontend .env.local..."
    echo "NEXT_PUBLIC_ZERO_CACHE_URL=http://localhost:5929" >> "$FRONTEND_DIR/.env.local"
fi

# =============================================================================
# STEP 3 — Start FastAPI backend
# =============================================================================
echo "[3/5] Starting FastAPI backend..."
cd "$BACKEND_DIR"
export PYTHONPATH="$BACKEND_DIR"
export SERVICE_ROLE=api
export UVICORN_LOOP=asyncio
if [ -f "$BACKEND_DIR/.env" ]; then
    set -a
    source "$BACKEND_DIR/.env"
    set +a
fi

uvicorn app.app:app --host 0.0.0.0 --port 8930 --reload &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")
echo "   PID $BACKEND_PID — http://localhost:8930"

# Wait for backend health endpoint
wait_for_http "http://localhost:8930/health" "Backend"

# =============================================================================
# STEP 4 — Start Celery worker
# =============================================================================
echo "[4/5] Starting Celery worker..."
cd "$BACKEND_DIR"
export SERVICE_ROLE=worker
celery -A celery_worker worker \
    --queues=surfsense \
    --concurrency=2 \
    --loglevel=INFO &
CELERY_PID=$!
PIDS+=("$CELERY_PID")
echo "   PID $CELERY_PID — queues=surfsense, concurrency=2"
sleep 2  # brief wait for worker to register

# =============================================================================
# STEP 5 — Start Next.js frontend
# =============================================================================
echo "[5/5] Starting Next.js frontend..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")
echo "   PID $FRONTEND_PID — http://localhost:3000"

# Frontend dev server opens the port early (compilation starts on first request)
echo -n "  Waiting for Frontend (localhost:3000)..."
for i in $(seq 1 30); do
    if ss -tlnp 2>/dev/null | grep -q ':3000 '; then
        echo " ready ($i s)"
        break
    fi
    sleep 2
    echo -n "."
done

# =============================================================================
# Done — print summary
# =============================================================================
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  All services running! Press Ctrl+C to stop."
echo "══════════════════════════════════════════════════════════════════"
echo ""
echo "  Backend  → http://localhost:8930  (PID $BACKEND_PID)"
echo "  Docs     → http://localhost:8930/docs"
echo "  Frontend → http://localhost:3000  (PID $FRONTEND_PID)"
echo "  Celery   → PID $CELERY_PID"
echo ""
echo "  PostgreSQL  → localhost:5432"
echo "  Redis       → localhost:6379"
echo "  OpenSearch  → localhost:9200"
echo ""

# Wait for any foreground signal
wait
