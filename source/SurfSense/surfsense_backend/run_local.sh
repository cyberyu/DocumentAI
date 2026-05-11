#!/bin/bash
# Run the SurfSense backend locally (FastAPI / uvicorn)
# Requires: conda activate documentai

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONPATH="$SCRIPT_DIR"
export SERVICE_ROLE=api
export UVICORN_LOOP=asyncio

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Local frontend dev server default is 3000.
# Override FRONTEND_PORT if you intentionally use Docker frontend (e.g., 3929).
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
FRONTEND_URL="${NEXT_FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
BACKEND_URL="http://localhost:8930"

echo "[SurfSense] Backend URL:       ${BACKEND_URL}"
echo "[SurfSense] Frontend Login URL: ${FRONTEND_URL}/login"

exec uvicorn app.app:app --host 0.0.0.0 --port 8930 --reload
