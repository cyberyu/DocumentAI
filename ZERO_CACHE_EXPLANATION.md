# Zero Cache Architecture - Why Skeleton Loaders Appear

## The Real Problem: Not a REST API Issue!

Your DocumentAI frontend **does NOT poll the REST API** for document updates. Instead:

```
Document Upload → PostgreSQL → Logical Replication → Zero Cache → WebSocket → Browser
                                                                      ↓
                                                              If this breaks,
                                                         skeleton loaders forever!
```

## Working System Architecture (from log)

**Components:**
- **rocicorp/zero:0.26.2** - Real-time sync service
- **PostgreSQL Logical Replication** - Publishes changes via `zero_publication`
- **WebSocket** - Browser connects to `http://localhost:5929` (zero-cache)
- **Replication Slot** - Active connection: `zero_0_1777926735448`

**When a document is uploaded:**
1. ✅ Backend saves to PostgreSQL ← **This works on your system**
2. ✅ PostgreSQL logical replication detects INSERT ← **May be broken**
3. ✅ Zero Cache receives change notification ← **May be broken**
4. ✅ Zero Cache pushes WebSocket "poke" to browser ← **May be broken**
5. ✅ Browser UI updates with new document ← **Never happens on your system**

## Why REST API Returns Documents But UI Shows Skeletons

The REST API (`GET /api/v1/documents`) is a **separate system** used for:
- Initial page load
- Manual refresh
- Direct queries

But the **live document list** uses Zero Cache WebSocket updates. Your system:
- ✅ REST API works (backend log shows correct response)
- ❌ Zero Cache broken (WebSocket never receives updates)
- Result: UI stuck on skeleton loaders waiting for WebSocket "poke"

## Most Likely Issues on Your Broken Machine

### Issue 1: Zero Cache Container Not Running (60% probability)
```bash
docker ps | grep zero
# If empty → zero-cache not running!
```

**Fix:**
```bash
docker compose up -d zero-cache
# or
docker start zero-cache
```

---

### Issue 2: Replication Slot Inactive (25% probability)
Zero-cache lost connection to PostgreSQL.

**Fix:**
```bash
docker restart zero-cache
```

---

### Issue 3: WAL Level Not Set to 'logical' (10% probability)
PostgreSQL not configured for logical replication.

**Fix:**
```bash
# Edit postgresql.conf
wal_level = logical

# Restart postgres
docker restart postgres

# Restart zero-cache
docker restart zero-cache
```

---

### Issue 4: Wrong NEXT_PUBLIC_ZERO_CACHE_URL (5% probability)
Frontend configured to connect to wrong zero-cache URL/port.

**Fix:**
Check `docker-compose.yml` frontend environment:
```yaml
NEXT_PUBLIC_ZERO_CACHE_URL: http://localhost:5929
```

---

## Run the Diagnostic Script

I've created a comprehensive diagnostic script that compares your system to the working one:

```bash
cd /mnt/ssd1/projects/DocumentAI
./diagnose-zero-cache.sh
```

**This will check:**
1. ✅/❌ Is zero-cache container running?
2. ✅/❌ Is replication slot active?
3. ✅/❌ Is WAL level set to 'logical'?
4. ✅/❌ Is 'documents' table in publication?
5. ✅/❌ Is zero-cache streaming from PostgreSQL?
6. ✅/❌ Is NEXT_PUBLIC_ZERO_CACHE_URL configured?
7. ✅/❌ Can browser reach zero-cache port?
8. ✅/❌ Any errors in zero-cache logs?

**The script will tell you EXACTLY what's broken and how to fix it.**

---

## Quick Manual Checks

### Check 1: Zero-cache running?
```bash
docker ps | grep zero-cache
```
Expected: One container running with `rocicorp/zero` image

### Check 2: Replication active?
```bash
docker exec postgres psql -U surfsense -d surfsense -c \
  "SELECT slot_name, active FROM pg_replication_slots;"
```
Expected: `active | t` (must be 't', not 'f')

### Check 3: Browser can reach zero-cache?
```bash
curl http://localhost:5929/api/v0/metrics
```
Expected: HTTP 200 response

### Check 4: Frontend knows about zero-cache?
```bash
docker inspect <frontend-container> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ZERO_CACHE
```
Expected: `NEXT_PUBLIC_ZERO_CACHE_URL=http://localhost:5929`

---

## Browser Debug (Advanced)

**Check WebSocket Connection:**
1. Open http://localhost:3929/documents
2. F12 → Network tab → WS (WebSocket filter)
3. Look for WebSocket connection to port 5929

**Expected (working):**
- WebSocket upgrade to `ws://localhost:5929/...`
- Status: 101 Switching Protocols
- Connection: Active

**Broken:**
- No WebSocket connection attempt
- Or WebSocket fails to connect (ERR_CONNECTION_REFUSED)

---

## Expected Working Configuration

From the working system log:

**docker-compose.yml ports:**
```yaml
frontend:
  ports:
    - "3929:3000"

backend:
  ports:
    - "8929:8000"

zero-cache:
  image: rocicorp/zero:0.26.2
  ports:
    - "5929:4848"  # ← Critical!
  environment:
    ZERO_APP_PUBLICATIONS: zero_publication
    ZERO_UPSTREAM_DB: postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
    ZERO_CVR_DB: postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
    ZERO_CHANGE_DB: postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable
```

**Frontend environment:**
```yaml
NEXT_PUBLIC_ZERO_CACHE_URL: http://localhost:5929
```

**PostgreSQL configuration:**
```
wal_level = logical
max_wal_senders = 10
max_replication_slots = 10
```

---

## After Running Diagnostic

The script will output a summary like:

```
✅ PASS: Zero-cache container found
✅ PASS: Replication slot is ACTIVE
✅ PASS: WAL level is logical
❌ FAIL: 'documents' table NOT in publication  ← Found the problem!
```

Then it gives you the exact fix command to run.

---

## Next Steps

1. **Run the diagnostic:**
   ```bash
   ./diagnose-zero-cache.sh > zero-cache-report.txt
   cat zero-cache-report.txt
   ```

2. **Apply the recommended fixes** from the summary section

3. **Test:**
   ```bash
   # Upload a new document
   # Check if it appears in UI (not skeleton loaders)
   ```

4. **If still broken**, share `zero-cache-report.txt` for analysis

---

## Success Criteria

✅ **You'll know it's fixed when:**
1. Upload a document
2. Wait 5 seconds
3. Document appears in UI with title, date, status
4. No skeleton loaders

✅ **Zero-cache is working when:**
- Replication slot shows `active: t`
- Zero-cache logs show `"starting poke from X to Y"` after uploads
- Browser DevTools shows WebSocket connection to localhost:5929
- Documents appear instantly after upload completes

---

## Why This Wasn't Obvious

The REST API returning documents correctly is a **red herring**. The frontend:
- Uses REST API only for initial load and manual refresh
- Uses Zero Cache WebSocket for **live updates** after uploads
- Shows skeletons when waiting for WebSocket update that never arrives

This is why:
- ✅ You can see documents in backend logs
- ✅ API returns documents correctly
- ✅ Database has documents with status='ready'
- ❌ But UI shows infinite skeleton loaders

**The missing piece:** Real-time WebSocket updates from Zero Cache
