# Working vs Broken System Comparison

## Context

- **Working Machine**: Documents display correctly (log captured in DOCUMENT_DISPLAY_DEBUG_MASTER.log)
- **Broken Machine**: Shows skeleton loaders instead of documents
- **Issue**: Same system, different behavior

---

## What the Working System Shows (from log)

### Backend (Both Should Be Same)
- ✅ API endpoint: `GET /api/v1/documents` returns:
  ```json
  {
    "items": [{"id": 27, "title": "...", "status": {"state": "ready"}}],
    "total": 1,
    "page": 0,
    "page_size": 50
  }
  ```
- ✅ Document status in DB: `{"state": "ready"}`
- ✅ Zero-cache replication: Active, streaming

### Key Infrastructure (Working System)
- Zero-cache service: Running on 172.19.0.8
- Replication slot: `zero_0_1777926735448` (active)
- WAL sender: Streaming to 172.19.0.8
- Publication: `zero_publication` (includes documents table)

---

## Critical Comparison Checklist

### 1. Frontend Version/Build
**Working machine might have different frontend code**

```bash
# On your broken machine, check:
docker ps | grep frontend
docker inspect <frontend-container-id> | grep -i image

# Check frontend image tag/version
docker images | grep frontend
```

**Questions:**
- Are both using same frontend Docker image?
- Same frontend build/version?
- Did working machine get custom frontend patches?

---

### 2. Zero-Cache Service Status

**The log shows zero-cache is CRITICAL - it syncs DB changes to frontend**

```bash
# Check if zero-cache is running
docker ps | grep zero-cache

# Check zero-cache logs
docker logs zero-cache --tail 100

# Check if replication is active
docker exec postgres psql -U user -d dbname -c \
  "SELECT * FROM pg_replication_slots WHERE active = true;"
```

**Expected (from working system):**
```
slot_name: zero_0_XXXXXXXXX
plugin: pgoutput
slot_type: logical
active: t (true)
```

**If `active = f` (false) → Zero-cache not connected → Frontend won't update!**

---

### 3. PostgreSQL Replication Publication

**Working system has `zero_publication` publishing documents table**

```bash
# Check publication exists
docker exec postgres psql -U user -d dbname -c \
  "SELECT * FROM pg_publication WHERE pubname = 'zero_publication';"

# Check which tables are published
docker exec postgres psql -U user -d dbname -c \
  "SELECT tablename FROM pg_publication_tables WHERE pubname = 'zero_publication';"
```

**Expected output should include:**
- `documents`
- `folders`
- `new_chat_messages`
- etc.

**If `documents` table NOT in publication → Frontend won't receive updates!**

---

### 4. Frontend Environment Variables

**Broken machine might have wrong API endpoint or zero-cache URL**

```bash
# Check frontend environment
docker exec <frontend-container> env | grep -E "API|BACKEND|ZERO|CACHE"

# Compare with working machine if possible
```

**Key variables to check:**
- `NEXT_PUBLIC_API_URL` or `REACT_APP_API_URL`
- `ZERO_CACHE_URL` or similar
- `WS_URL` (WebSocket for real-time updates)

---

### 5. Network Connectivity

**Frontend needs to reach both backend API AND zero-cache**

```bash
# From frontend container, test backend
docker exec <frontend-container> wget -O- http://backend:8080/health 2>&1

# Check Docker network
docker network inspect <network-name> | grep -A 5 "frontend\|backend\|zero-cache"
```

**All three should be on same Docker network.**

---

### 6. Browser Cache/Session

**Your browser might have old cached frontend code**

```
1. Hard refresh: Ctrl + Shift + R
2. Clear cache: F12 → Application → Clear storage
3. Try incognito/private window
4. Try different browser
```

---

### 7. Authentication/Authorization

**Working machine might have different user permissions**

```bash
# Check your user ID in database
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, email FROM \"user\" ORDER BY id;"

# Check if documents are owned by your user
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, title, created_by_id FROM documents;"
```

**If `created_by_id` doesn't match your user ID → You won't see documents!**

---

## Most Likely Root Causes (Ranked)

### 1. Zero-Cache Not Running or Not Connected (50%)

**Symptoms:**
- Replication slot exists but `active = false`
- Or zero-cache container not running at all

**Fix:**
```bash
# Restart zero-cache
docker restart zero-cache

# Check connection
docker logs zero-cache | grep -i "connected\|error"
```

---

### 2. Frontend Using Old/Different Image (25%)

**Symptoms:**
- Your broken machine has different frontend version
- Working machine has patched frontend

**Fix:**
```bash
# Pull the exact same frontend image as working machine
docker pull <same-image-tag>

# Or rebuild with same source
docker-compose build frontend --no-cache
docker-compose up -d frontend
```

---

### 3. Documents Table Not in Publication (15%)

**Symptoms:**
- Publication exists but excludes `documents` table
- Zero-cache connected but not receiving document updates

**Fix:**
```bash
# Add documents to publication
docker exec postgres psql -U user -d dbname -c \
  "ALTER PUBLICATION zero_publication ADD TABLE documents;"

# Restart zero-cache to re-sync
docker restart zero-cache
```

---

### 4. Browser Cached Old Frontend (10%)

**Symptoms:**
- Same containers, same config
- But browser has old JS bundle

**Fix:**
- Hard refresh: Ctrl + Shift + R
- Clear all cache
- Try incognito mode

---

## Diagnostic Commands (Run on Broken Machine)

### Quick Health Check

```bash
# 1. All services running?
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "frontend|backend|postgres|zero"

# 2. Replication healthy?
docker exec postgres psql -U user -d dbname -c \
  "SELECT slot_name, active, confirmed_flush_lsn FROM pg_replication_slots;"

# 3. Zero-cache connected?
docker logs zero-cache --tail 50 | grep -i "connected\|streaming\|error"

# 4. Frontend can reach backend?
docker exec <frontend-container> curl -s http://backend:8080/health

# 5. Documents exist in DB?
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, title, status FROM documents ORDER BY created_at DESC LIMIT 5;"
```

---

## Side-by-Side Comparison Template

| Component | Working Machine | Your Machine | Status |
|-----------|-----------------|--------------|--------|
| Frontend Image | ? | ? | ❓ |
| Frontend Port | 3929 (assumed) | ? | ❓ |
| Backend Port | 8929 | ? | ❓ |
| Zero-cache Running | ✅ Yes | ? | ❓ |
| Replication Active | ✅ true | ? | ❓ |
| Publication Tables | ✅ documents included | ? | ❓ |
| User ID | d4f30b0e-... | ? | ❓ |
| Documents in DB | ✅ 1 document | ? | ❓ |
| API Returns Docs | ✅ Yes | ? | ❓ |

**Fill in "Your Machine" column to identify differences.**

---

## Next Steps

1. **Verify zero-cache is running and connected:**
   ```bash
   docker ps | grep zero
   docker logs zero-cache --tail 100
   ```

2. **Check replication slot is active:**
   ```bash
   docker exec postgres psql -U user -d dbname -c \
     "SELECT slot_name, active FROM pg_replication_slots;"
   ```

3. **Verify documents table in publication:**
   ```bash
   docker exec postgres psql -U user -d dbname -c \
     "SELECT tablename FROM pg_publication_tables WHERE pubname = 'zero_publication';"
   ```

4. **Compare frontend images:**
   ```bash
   docker images | grep frontend
   ```

5. **Test API from browser console:**
   ```javascript
   fetch('/api/v1/documents', {
     headers: {'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)?.[1]}
   }).then(r => r.json()).then(console.log)
   ```

---

## Expected Results (Should Match Working System)

### Replication Slot
```
slot_name: zero_0_XXXXXXXXX
active: t
```

### Publication Tables (should include)
```
chat_comments
documents          ← CRITICAL
folders
new_chat_messages
notifications
search_source_connectors
user
```

### Zero-cache Logs (should show)
```
"level":"INFO","message":"connected..."
"message":"flushed cvr@..."
"message":"streaming..."
```

### API Response (from browser)
```json
{
  "items": [{...}],
  "total": 1
}
```

---

## If Still Stuck

Capture on **your broken machine**:

```bash
# Create comparison report
cat > /tmp/broken_system_report.txt <<'EOF'
=== BROKEN SYSTEM REPORT ===

1. Docker Containers:
EOF

docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" >> /tmp/broken_system_report.txt

echo -e "\n2. Replication Slots:" >> /tmp/broken_system_report.txt
docker exec postgres psql -U user -d dbname -c \
  "SELECT * FROM pg_replication_slots;" >> /tmp/broken_system_report.txt

echo -e "\n3. Publication Tables:" >> /tmp/broken_system_report.txt
docker exec postgres psql -U user -d dbname -c \
  "SELECT tablename FROM pg_publication_tables WHERE pubname = 'zero_publication';" \
  >> /tmp/broken_system_report.txt

echo -e "\n4. Zero-cache Logs:" >> /tmp/broken_system_report.txt
docker logs zero-cache --tail 50 >> /tmp/broken_system_report.txt 2>&1

echo -e "\n5. Documents in DB:" >> /tmp/broken_system_report.txt
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, title, status, created_by_id FROM documents LIMIT 5;" \
  >> /tmp/broken_system_report.txt

cat /tmp/broken_system_report.txt
```

**Share this report to compare with working system.**
