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

exec uvicorn app.app:app --host 0.0.0.0 --port 8930 --reload
