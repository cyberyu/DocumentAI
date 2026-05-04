#!/usr/bin/env bash
# ============================================================
# Run AFTER the upload (or as soon as skeleton appears).
# Appends post-upload snapshot to DOCUMENT_DISPLAY_DEBUG_MASTER.log
# ============================================================
set -euo pipefail

LOG="/home/shiyu/Documents/surfsense/DOCUMENT_DISPLAY_DEBUG_MASTER.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }
sep() { echo "" | tee -a "$LOG"; echo "================================================================" | tee -a "$LOG"; echo "  $*" | tee -a "$LOG"; echo "================================================================" | tee -a "$LOG"; echo "" | tee -a "$LOG"; }
dbq() { docker exec surfsense-db-1 psql -U surfsense -d surfsense -c "$1" 2>&1 | tee -a "$LOG"; }
apicall() {
  local label="$1" path="$2"
  echo "--- API: $label ---" >> "$LOG"
  curl -s "http://localhost:8929${path}" \
    -H "Authorization: Bearer ${TOKEN}" \
    2>&1 | python3 -m json.tool 2>&1 >> "$LOG" || true
  echo "" >> "$LOG"
}

# Auth
RAW_TOKEN=$(curl -s -X POST http://localhost:8929/auth/jwt/login \
  -d 'username=shi.yu%40broadridge.com&password=Lexar1357%21%21' \
  -H 'Content-Type: application/x-www-form-urlencoded')
TOKEN=$(echo "$RAW_TOKEN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
log "Post-upload capture started. Token: ${TOKEN:0:20}..."

# ─── A. DB snapshot after upload ────────────────────────────
sep "SECTION A: DB STATE (after upload)"
log "Documents:"
dbq "SELECT id, title, status, search_space_id, created_by_id, created_at, updated_at FROM documents ORDER BY id DESC LIMIT 10;"
log "Chunks per document:"
dbq "SELECT document_id, count(*) AS chunk_count FROM chunks GROUP BY document_id ORDER BY document_id DESC;"
log "Most recent 5 document status values (raw JSON):"
dbq "SELECT id, title, status::text, updated_at FROM documents ORDER BY updated_at DESC NULLS LAST LIMIT 5;"
log "Recent notifications:"
dbq "SELECT id, type, title, message, read, created_at FROM notifications ORDER BY created_at DESC LIMIT 5;"

# ─── B. API state after upload ──────────────────────────────
sep "SECTION B: API RESPONSES (after upload)"
apicall "GET /api/v1/documents" "/api/v1/documents"
apicall "GET /api/v1/documents?search_space_id=1" "/api/v1/documents?search_space_id=1"
apicall "GET /api/v1/documents?search_space_id=1&page_size=-1" "/api/v1/documents?search_space_id=1&page_size=-1"

# ─── C. Zero-cache state ────────────────────────────────────
sep "SECTION C: ZERO-CACHE STATE"
log "Zero-cache health:"
curl -s "http://localhost:5929/api/v1/status" 2>&1 | python3 -m json.tool 2>&1 | tee -a "$LOG" || \
  log "(no /api/v1/status endpoint — checking /health)"
curl -s "http://localhost:5929/health" 2>&1 | tee -a "$LOG" || true
echo "" | tee -a "$LOG"

# Check if the documents table is in zero replication
log "zero_publication documents column list:"
dbq "SELECT attnames FROM pg_publication_tables WHERE pubname='zero_publication' AND tablename='documents';"

# ─── D. Stop live streams and append logs ───────────────────
sep "SECTION D: LIVE LOG CAPTURE"
if [[ -f /tmp/debug_pids.env ]]; then
  source /tmp/debug_pids.env
  for pid in $ZC_PID $BE_PID $CW_PID $CB_PID; do
    kill "$pid" 2>/dev/null || true
  done
  log "Stopped live log streams."
fi

echo "" | tee -a "$LOG"
echo "------- zero-cache live log (/tmp/zc_live.log) --------" | tee -a "$LOG"
cat /tmp/zc_live.log | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "------- backend live log (/tmp/backend_live.log) --------" | tee -a "$LOG"
cat /tmp/backend_live.log | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "------- celery-worker live log (/tmp/celery_live.log) --------" | tee -a "$LOG"
cat /tmp/celery_live.log | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "------- celery-beat live log (/tmp/celery_beat_live.log) --------" | tee -a "$LOG"
cat /tmp/celery_beat_live.log | tee -a "$LOG"

# ─── E. Backend error extraction ────────────────────────────
sep "SECTION E: ERROR EXTRACTION"
log "Backend errors (from live stream):"
grep -i "error\|exception\|traceback\|fail" /tmp/backend_live.log 2>/dev/null | tee -a "$LOG" || log "(none)"
log "Celery errors (from live stream):"
grep -i "error\|exception\|traceback\|fail" /tmp/celery_live.log 2>/dev/null | tee -a "$LOG" || log "(none)"
log "Zero-cache errors (from live stream):"
grep -i "error\|warning\|WARN\|ERR" /tmp/zc_live.log 2>/dev/null | tee -a "$LOG" || log "(none)"

# ─── F. PostgreSQL replication / WAL debug ──────────────────
sep "SECTION F: REPLICATION / WAL DEBUG"
log "Replication slots:"
dbq "SELECT slot_name, plugin, slot_type, active, restart_lsn, confirmed_flush_lsn FROM pg_replication_slots;"
log "WAL sender processes:"
dbq "SELECT pid, state, sent_lsn, write_lsn, flush_lsn, replay_lsn, client_addr FROM pg_stat_replication;"
log "Publication rows:"
dbq "SELECT * FROM pg_publication WHERE pubname='zero_publication';"

sep "SECTION G: SUMMARY"
DOC_COUNT=$(docker exec surfsense-db-1 psql -U surfsense -d surfsense -t -c "SELECT count(*) FROM documents;" 2>&1 | tr -d ' ')
CHUNK_COUNT=$(docker exec surfsense-db-1 psql -U surfsense -d surfsense -t -c "SELECT count(*) FROM chunks;" 2>&1 | tr -d ' ')
API_COUNT=$(curl -s "http://localhost:8929/api/v1/documents?search_space_id=1" -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total', len(d) if isinstance(d,list) else '?'))" 2>/dev/null)
log "DB documents:   $DOC_COUNT"
log "DB chunks:      $CHUNK_COUNT"
log "API total:      $API_COUNT"
log ""
log "Log file: $LOG"
log "Capture complete."
