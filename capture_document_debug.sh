#!/usr/bin/env bash
# ============================================================
# DOCUMENT_DISPLAY_DEBUG_MASTER.log capture script
# Run BEFORE uploading a document.
# ============================================================
set -euo pipefail

LOG="/home/shiyu/Documents/surfsense/DOCUMENT_DISPLAY_DEBUG_MASTER.log"
: > "$LOG"   # truncate / create

log()   { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }
sep()   { echo "" | tee -a "$LOG"; echo "================================================================" | tee -a "$LOG"; echo "  $*" | tee -a "$LOG"; echo "================================================================" | tee -a "$LOG"; echo "" | tee -a "$LOG"; }
dbq()   { docker exec surfsense-db-1 psql -U surfsense -d surfsense -c "$1" 2>&1 | tee -a "$LOG"; }
apicall() {
  local label="$1" path="$2"
  echo "--- API: $label ---" >> "$LOG"
  curl -s "http://localhost:8929${path}" \
    -H "Authorization: Bearer ${TOKEN}" \
    2>&1 | python3 -m json.tool 2>&1 >> "$LOG" || true
  echo "" >> "$LOG"
}

# ─── 0. Get auth token ──────────────────────────────────────
sep "SECTION 0: AUTHENTICATION"
log "Logging in..."
RAW_TOKEN=$(curl -s -X POST http://localhost:8929/auth/jwt/login \
  -d 'username=shi.yu%40broadridge.com&password=Lexar1357%21%21' \
  -H 'Content-Type: application/x-www-form-urlencoded')
TOKEN=$(echo "$RAW_TOKEN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
if [[ -z "$TOKEN" ]]; then
  log "ERROR: Login failed. Raw response: $RAW_TOKEN"
  exit 1
fi
log "Login OK. Token starts with: ${TOKEN:0:30}..."

# ─── 1. Snapshot: DB baseline ───────────────────────────────
sep "SECTION 1: DB BASELINE (before upload)"
log "Documents table:"
dbq "SELECT id, title, status, search_space_id, created_at, updated_at FROM documents ORDER BY id DESC LIMIT 10;"
log "Chunks count per document:"
dbq "SELECT document_id, count(*) AS chunk_count FROM chunks GROUP BY document_id ORDER BY document_id DESC;"
log "zero_publication tables:"
dbq "SELECT tablename, attnames FROM pg_publication_tables WHERE pubname='zero_publication' ORDER BY tablename;"
log "Search spaces:"
dbq "SELECT id, name, user_id FROM searchspaces ORDER BY id;"

# ─── 2. Snapshot: API baseline ──────────────────────────────
sep "SECTION 2: API BASELINE (before upload)"
apicall "GET /api/v1/documents" "/api/v1/documents"
apicall "GET /api/v1/documents?search_space_id=1" "/api/v1/documents?search_space_id=1"
apicall "GET /api/v1/search-spaces" "/api/v1/search-spaces"

# ─── 3. Clear old background logs, start live capture ───────
sep "SECTION 3: STARTING LIVE LOG STREAMS"
: > /tmp/zc_live.log
: > /tmp/backend_live.log
: > /tmp/celery_live.log
: > /tmp/celery_beat_live.log

docker logs surfsense-zero-cache-1  -f --tail 0 >> /tmp/zc_live.log      2>&1 &  ZC_PID=$!
docker logs surfsense-backend-1     -f --tail 0 >> /tmp/backend_live.log  2>&1 &  BE_PID=$!
docker logs surfsense-celery_worker-1 -f --tail 0 >> /tmp/celery_live.log 2>&1 &  CW_PID=$!
docker logs surfsense-celery_beat-1 -f --tail 0 >> /tmp/celery_beat_live.log 2>&1 & CB_PID=$!

log "Live log PIDs — zero-cache:$ZC_PID  backend:$BE_PID  celery-worker:$CW_PID  celery-beat:$CB_PID"
echo "ZC_PID=$ZC_PID BE_PID=$BE_PID CW_PID=$CW_PID CB_PID=$CB_PID" > /tmp/debug_pids.env

log ""
log "============================================================"
log "  ✅ Monitoring ready. NOW UPLOAD A DOCUMENT IN THE BROWSER."
log "  After upload completes (or if skeleton appears), run:"
log "     bash /home/shiyu/Documents/surfsense/capture_after_upload.sh"
log "============================================================"
