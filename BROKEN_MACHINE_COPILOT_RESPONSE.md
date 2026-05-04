# Broken Machine Skeleton Loader Debug — Working System Ground Truth

This document contains exact values from the **working** Docker (documents display correctly) for
side-by-side comparison. Paste this into the broken machine's Copilot session.

---

## BACKGROUND

**Architecture recap:** The frontend uses **Zero Cache** (`rocicorp/zero`) for real-time data sync,
NOT polling the REST API. When a document is saved to PostgreSQL, Zero Cache detects the change
via logical replication (`zero_publication`) and pushes a WebSocket poke to the browser.
If that poke never arrives, the UI stays on skeleton loaders — even if the REST API returns the
document correctly.

**Symptom pattern:**
- `GET /api/v1/documents` returns documents ✅
- UI shows skeleton loaders instead ❌
→ Root cause is almost always in the Zero Cache / logical replication path.

---

## STEP 1: RUN THESE DIAGNOSTIC COMMANDS ON THE BROKEN MACHINE

Replace `<db>`, `<frontend>`, `<zero>` with actual container names from `docker ps`.

### 1a. Check replication slot ← MOST CRITICAL CHECK

```bash
docker exec <db-container> psql -U surfsense -d surfsense -c \
  "SELECT slot_name, plugin, slot_type, active FROM pg_replication_slots;"
```

**Working machine output:**
```
          slot_name           | plugin  | slot_type | active
------------------------------+---------+-----------+--------
 zero_0_1777926735448         | pgoutput| logical   | t
```

**CRITICAL:** `active` MUST be `t`. If it is `f`, zero-cache is not connected to postgres —
documents will never appear in the UI.

---

### 1b. Check WAL level ← SECOND MOST CRITICAL

```bash
docker exec <db-container> psql -U surfsense -d surfsense -c "SHOW wal_level;"
```

**Working machine output:**
```
 wal_level
-----------
 logical
```

**CRITICAL:** Must be `logical`. If it is `replica` or `minimal`, logical replication is
impossible — zero-cache cannot receive change events regardless of other settings.

---

### 1c. Check the publication includes `documents` table

```bash
docker exec <db-container> psql -U surfsense -d surfsense -c \
  "SELECT tablename FROM pg_publication_tables WHERE pubname='zero_publication' ORDER BY tablename;"
```

**Working machine output:**
```
         tablename
---------------------------
 chat_comments
 chat_session_state
 documents              ← MUST be present
 folders
 new_chat_messages
 notifications
 search_source_connectors
 user
```

If `documents` is missing from this list, document updates are invisible to zero-cache.

---

### 1d. Check WAL sender (is zero-cache actively streaming?)

```bash
docker exec <db-container> psql -U surfsense -d surfsense -c \
  "SELECT application_name, state, client_addr, sent_lsn, write_lsn, flush_lsn \
   FROM pg_stat_replication;"
```

**Working machine output:**
```
 application_name | state     | client_addr | sent_lsn  | write_lsn | flush_lsn
------------------+-----------+-------------+-----------+-----------+-----------
 zero-replicator  | streaming | 172.19.0.8  | 0/...     | 0/...     | 0/...
```

`state` must be `streaming`. `application_name` must be `zero-replicator`.
If the row is missing entirely, zero-cache never established a replication connection.

---

### 1e. Check zero-cache environment variables

```bash
docker inspect <zero-cache-container> --format '{{range .Config.Env}}{{println .}}{{end}}' | sort
```

**Working machine values (exact):**
```
ZERO_UPSTREAM_DB=postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
ZERO_CVR_DB=postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
ZERO_CHANGE_DB=postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
ZERO_APP_PUBLICATIONS=zero_publication
ZERO_MUTATE_URL=http://frontend:3000/api/zero/mutate
ZERO_QUERY_URL=http://frontend:3000/api/zero/query
ZERO_REPLICA_FILE=/data/zero.db
ZERO_NUM_SYNC_WORKERS=4
ZERO_CVR_MAX_CONNS=30
ZERO_UPSTREAM_MAX_CONNS=20
ZERO_ADMIN_PASSWORD=surfsense-zero-admin
ZERO_LOG_FORMAT=json
```

Key things to verify:
- `ZERO_APP_PUBLICATIONS=zero_publication` — must match the publication name exactly
- `ZERO_UPSTREAM_DB` hostname `db` — must resolve to the postgres container
- `ZERO_MUTATE_URL` / `ZERO_QUERY_URL` hostname `frontend` — must resolve to frontend container

---

### 1f. Check frontend environment variables

```bash
docker inspect <frontend-container> --format '{{range .Config.Env}}{{println .}}{{end}}' | sort
```

**Working machine values (exact):**
```
NEXT_PUBLIC_ZERO_CACHE_URL=http://localhost:5929
NEXT_PUBLIC_FASTAPI_BACKEND_URL=http://localhost:8929
NEXT_PUBLIC_FASTAPI_BACKEND_AUTH_TYPE=LOCAL
NEXT_PUBLIC_ETL_SERVICE=DOCLING
NEXT_PUBLIC_DEPLOYMENT_MODE=self-hosted
FASTAPI_BACKEND_INTERNAL_URL=http://backend:8000
NODE_ENV=production
PORT=3000
```

**CRITICAL:** `NEXT_PUBLIC_ZERO_CACHE_URL=http://localhost:5929`
- The `localhost` here is correct because the browser (running on the host) connects to zero-cache
  via the host-mapped port. If the broken machine uses a different port mapping or a different
  hostname, update this.
- Port `5929` must match the `ports:` mapping in `docker-compose.yml` for zero-cache.

---

### 1g. Check zero-cache logs for errors

```bash
docker logs <zero-cache-container> --tail 50 2>&1 | grep -E '"level":"(ERROR|WARN)"|error|ERR|failed|cannot'
```

**Working machine zero-cache logs show NO errors.** You should see only INFO-level entries like:
```json
{"level":"INFO","worker":"syncer","component":"view-syncer","message":"flushing 1 rows (1 inserts, 0 deletes)"}
{"level":"INFO","worker":"syncer","component":"view-syncer","message":"flushed cvr@... {\"rows\":1,...}"}
{"level":"INFO","worker":"syncer","component":"view-syncer","message":"starting poke from X to Y"}
{"level":"INFO","worker":"change-streamer","component":"change-streamer","message":"Purging changes before ..."}
```

If you see ERROR entries, or if there are NO "flushing" / "starting poke" messages after a
document upload, zero-cache is broken.

---

### 1h. Check zero-cache port is reachable from host

```bash
curl -v http://localhost:<zero-cache-port>/api/v0/metrics 2>&1 | head -20
```

On the working machine (port 5929):
```
* Connected to localhost (127.0.0.1) port 5929
< HTTP/1.1 200 OK
```

If you get `Connection refused`, zero-cache is not listening / port mapping is wrong.

---

### 1i. Check docker-compose port mappings

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

**Working machine output:**
```
surfsense-frontend-1      0.0.0.0:3929->3000/tcp
surfsense-backend-1       0.0.0.0:8929->8000/tcp
surfsense-zero-cache-1    0.0.0.0:5929->4848/tcp
surfsense-db-1            0.0.0.0:5437->5432/tcp
surfsense-redis-1         0.0.0.0:6389->6379/tcp
```

Zero-cache internal port is **4848** → mapped to **5929** on host.
`NEXT_PUBLIC_ZERO_CACHE_URL` must point to the host-mapped port (5929).

---

## STEP 2: DOCKER IMAGES (verify broken machine uses same versions)

**Working machine images:**
```
frontend:      shiyu688/surfsense-web:hybrid-patch-99pct
backend:       shiyu688/surfsense-backend:hybrid-patch-99pct
celery_worker: shiyu688/surfsense-backend:hybrid-patch-99pct-worker
celery_beat:   shiyu688/surfsense-backend:hybrid-patch-99pct-worker
zero-cache:    rocicorp/zero:0.26.2
db:            pgvector/pgvector:pg17
redis:         redis:8-alpine
searxng:       searxng/searxng:latest
```

---

## STEP 3: DECISION TREE — MOST LIKELY FIXES

```
Start here
│
├─ pg_replication_slots.active = 'f'?
│   → Restart zero-cache: docker compose restart zero-cache
│   → If slot stays inactive: docker compose down zero-cache && docker compose up -d zero-cache
│   → If still inactive: check zero-cache logs for connection error to postgres
│
├─ wal_level != 'logical'?
│   → Edit postgresql.conf: wal_level = logical
│   → Restart postgres (full restart, not reload)
│   → Then restart zero-cache (replication slot may need recreation)
│
├─ 'documents' missing from pg_publication_tables?
│   → docker exec <db> psql -U surfsense -d surfsense -c \
│       "ALTER PUBLICATION zero_publication ADD TABLE documents;"
│   → Then restart zero-cache
│
├─ NEXT_PUBLIC_ZERO_CACHE_URL wrong host/port?
│   → Fix in docker-compose.yml frontend environment section
│   → docker compose up -d --force-recreate frontend
│
├─ zero-cache logs show errors connecting to frontend (ZERO_MUTATE_URL)?
│   → Verify 'frontend' hostname resolves inside zero-cache container:
│       docker exec <zero-cache> nslookup frontend
│
└─ All DB / zero-cache checks pass, but browser never receives pokes?
    → Open browser DevTools → Network → WS tab
    → Connect to http://localhost:<frontend-port>/documents
    → Look for a WebSocket connection to <zero-cache-url>
    → If WebSocket is not upgrading, check NEXT_PUBLIC_ZERO_CACHE_URL
    → If WebSocket connects but no messages arrive, check zero-cache logs
        for "starting poke" messages after you upload a document
```

---

## STEP 4: POSTGRESQL CONFIGURATION REFERENCE

Working machine `postgresql.conf` (relevant settings):
```
wal_level = logical
max_wal_senders = 10
max_replication_slots = 10
```

These are the minimum required for zero-cache to work.

---

## STEP 5: DATABASE SCHEMA — `documents` table status column

The `status` column is JSONB with this shape (must match exactly):
```json
{"state": "ready", "reason": null}
```

Default value: `'{"state": "ready"}'::jsonb`

This is what zero-cache queries and what the frontend renders.
If the column type or default differs, zero-cache queries may return no rows.

Verify:
```bash
docker exec <db> psql -U surfsense -d surfsense -c \
  "\d documents" | grep status
```

Expected: `status | jsonb | not null | default '{"state": "ready"}'::jsonb`

---

## QUICK SUMMARY: MOST COMMON CAUSES (RANKED BY LIKELIHOOD)

1. **Replication slot inactive** (`active=f`) — zero-cache lost connection; restart it
2. **NEXT_PUBLIC_ZERO_CACHE_URL wrong** — browser can't reach zero-cache port
3. **wal_level not logical** — postgres config wrong; requires restart
4. **documents not in zero_publication** — publication was created before table existed
5. **Port mapping mismatch** — zero-cache internal port 4848 not exposed to host correctly
