#!/bin/bash
# Run the SurfSense Celery worker locally
# Requires: conda activate documentai

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONPATH="$SCRIPT_DIR"
export SERVICE_ROLE=worker

# Load .env if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

exec celery -A celery_worker worker \
    --queues=surfsense \
    --concurrency=2 \
    --loglevel=INFO
