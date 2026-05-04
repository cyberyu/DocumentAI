# Upload Log Capture Guide
**Purpose:** Capture all relevant logs during document upload to debug skeleton loader issue

## Pre-Upload Setup

### Terminal Setup (Open 5 terminals)

**Terminal 1 - Backend Logs:**
```bash
cd /mnt/ssd1/projects/DocumentAI
docker logs backend -f --tail 50 | tee upload-backend-$(date +%Y%m%d-%H%M%S).log
```

**Terminal 2 - Frontend Logs:**
```bash
cd /mnt/ssd1/projects/DocumentAI
docker logs documentai-frontend-1 -f --tail 50 | tee upload-frontend-$(date +%Y%m%d-%H%M%S).log
```

**Terminal 3 - PostgreSQL Logs:**
```bash
cd /mnt/ssd1/projects/DocumentAI
docker logs postgres -f --tail 50 | tee upload-postgres-$(date +%Y%m%d-%H%M%S).log
```

**Terminal 4 - Celery Worker (if exists):**
```bash
cd /mnt/ssd1/projects/DocumentAI
# Check if celery worker exists
docker ps | grep celery || docker ps | grep worker

# If exists:
docker logs <worker_container_name> -f --tail 50 | tee upload-worker-$(date +%Y%m%d-%H%M%S).log

# If no separate worker, skip this
```

**Terminal 5 - Database Queries (monitoring):**
```bash
cd /mnt/ssd1/projects/DocumentAI
watch -n 2 'docker exec postgres psql -U user -d dbname -c "SELECT id, file_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT 5;" 2>/dev/null'
```

---

## Browser DevTools Setup

### Before Upload:
1. **Open browser at http://localhost:3929**
2. **Press F12** to open DevTools
3. **Set up tabs:**
   - **Console tab** - Leave open to catch errors
   - **Network tab** - Enable "Preserve log" checkbox
   - **Network tab** - Clear existing entries

### Network Tab Configuration:
```
✓ Preserve log (checked)
✓ Disable cache (checked)
Filter: All (or XHR/Fetch)
```

---

## During Upload - Step by Step

### Step 1: Start Monitoring
1. All terminals are running with `tee` capturing logs
2. Browser DevTools open with Network tab active
3. Database watch terminal updating every 2 seconds

### Step 2: Perform Upload
1. **Click upload button** on http://localhost:3929
2. **Select file:** Use MSFT_FY26Q1_10Q or test document
3. **Start upload**
4. **DO NOT CLOSE OR REFRESH BROWSER**

### Step 3: Watch for Key Events

#### In Backend Log (Terminal 1) - Watch for:
```bash
# Upload initiation
POST /api/v1/upload
POST /api/v1/documents

# File processing
"Processing document: <filename>"
"Creating chunks for document: <id>"
"Document processed successfully"

# Status updates  
"Document status changed: processing -> completed"
"Indexing document chunks to OpenSearch"

# ERRORS to catch:
"ERROR"
"Exception"
"Traceback"
"Failed to process"
"status: failed"
```

#### In Frontend Log (Terminal 2) - Watch for:
```bash
# Upload progress
"Upload started"
"Upload progress: X%"
"Upload completed"

# API calls
"GET /api/v1/documents"
"Fetching documents"

# ERRORS to catch:
"ERROR"
"Failed to fetch"
"Network error"
```

#### In PostgreSQL Log (Terminal 3) - Watch for:
```sql
# Document insertion
INSERT INTO documents

# Status updates
UPDATE documents SET status

# Search space association
INSERT INTO search_space_documents

# ERRORS to catch:
"ERROR:"
"duplicate key"
"foreign key constraint"
```

#### In Database Watch (Terminal 5) - Watch for:
```
Initial: No documents (or existing docs)

During upload:
id | file_name           | status     | created_at
1  | MSFT_FY26Q1_10Q.pdf | processing | 2026-05-04 ...

After processing:
id | file_name           | status    | created_at
1  | MSFT_FY26Q1_10Q.pdf | completed | 2026-05-04 ...

PROBLEM if:
- status stays 'processing' forever
- status changes to 'failed'
- document doesn't appear at all
```

#### In Browser Network Tab - Capture:
```
1. POST /api/v1/upload         (upload file)
   → Response: 200 OK with upload_id

2. POST /api/v1/documents      (create document entry)
   → Response: 200 OK with document_id

3. GET /api/v1/upload/status/{upload_id}  (poll status)
   → Response: {"status": "processing"} or {"status": "completed"}

4. GET /api/v1/documents       (refresh document list)
   → Response: Should include newly uploaded document

PROBLEM if:
- Any request returns 4xx or 5xx
- GET /api/v1/documents returns empty array []
- No polling requests after upload
- Upload succeeds but no GET /api/v1/documents call
```

#### In Browser Console - Watch for:
```javascript
// Normal flow:
"Upload started"
"Upload progress: 50%"
"Upload completed"
"Fetching documents..."

// ERRORS to catch:
"Uncaught TypeError"
"Cannot read property"
"Network request failed"
"401 Unauthorized"
"403 Forbidden"
```

---

## Post-Upload Verification (Wait 30 seconds after upload)

### Immediate Checks:

**1. Database Status:**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, user_id, search_space_id, created_at 
   FROM documents 
   ORDER BY created_at DESC LIMIT 1;"
```

**Expected:** `status = 'completed'`  
**Problem:** `status = 'processing'` or `'failed'`

---

**2. Document Chunks Created:**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT d.file_name, COUNT(dc.id) as chunk_count 
   FROM documents d 
   LEFT JOIN document_chunks dc ON d.id = dc.document_id 
   WHERE d.created_at > NOW() - INTERVAL '5 minutes'
   GROUP BY d.file_name;"
```

**Expected:** chunk_count > 0 (should be hundreds for MSFT doc)  
**Problem:** chunk_count = 0 (chunks not created)

---

**3. OpenSearch Indexing:**
```bash
# Check if chunks indexed to OpenSearch
curl -X GET "http://localhost:9200/_cat/indices/document*?v" 2>/dev/null

# Count documents in index
curl -X GET "http://localhost:9200/document_chunks/_count" 2>/dev/null | jq .
```

**Expected:** Count increases after upload  
**Problem:** Count unchanged (indexing failed)

---

**4. Frontend API Response:**
```bash
# Get JWT token from browser first
TOKEN="<paste_jwt_from_browser>"

curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq .
```

**Expected:** Array includes newly uploaded document with status='completed'  
**Problem:** Empty array or document missing or status='processing'

---

**5. Browser Devtools Final State:**
- **Network tab:** Last request should be `GET /api/v1/documents` with 200 OK
- **Console tab:** No errors
- **Application → Cookies:** JWT token still present

---

## Critical Timestamps to Record

Create a timeline file:

```bash
cat > upload-timeline-$(date +%Y%m%d-%H%M%S).txt << 'EOF'
UPLOAD TIMELINE
================

[HH:MM:SS] Upload button clicked in browser
[HH:MM:SS] POST /api/v1/upload seen in Network tab
[HH:MM:SS] Response received (200 or error?)
[HH:MM:SS] "Processing document" appears in backend log
[HH:MM:SS] Document INSERT seen in PostgreSQL log
[HH:MM:SS] Document appears in database with status='processing'
[HH:MM:SS] "Creating chunks" appears in backend log
[HH:MM:SS] Status changes to 'completed' in database
[HH:MM:SS] GET /api/v1/documents called by frontend
[HH:MM:SS] Documents page shows skeleton loaders (PROBLEM!)
[HH:MM:SS] Documents page shows actual documents (SUCCESS!)

TOTAL TIME: ___ seconds from upload to display
EOF
```

---

## Data to Capture for Analysis

### 1. Network Tab Export
```
1. Right-click in Network tab
2. "Save all as HAR with content"
3. Save as: upload-network-YYYYMMDD-HHMMSS.har
```

### 2. Console Log Export
```
1. Right-click in Console tab
2. "Save as..."
3. Save as: upload-console-YYYYMMDD-HHMMSS.log
```

### 3. Backend Error Logs
```bash
docker logs backend 2>&1 | grep -i "error\|exception\|traceback" > backend-errors.log
```

### 4. Full API Response
```bash
# After upload completes
TOKEN="<jwt>"
curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq . > documents-after-upload.json
```

### 5. Database Snapshot
```bash
docker exec postgres psql -U user -d dbname << 'SQL' > database-snapshot.txt
-- Documents
SELECT id, file_name, status, user_id, search_space_id, created_at 
FROM documents 
ORDER BY created_at DESC LIMIT 10;

-- Chunks count
SELECT document_id, COUNT(*) as chunks 
FROM document_chunks 
GROUP BY document_id 
ORDER BY document_id DESC;

-- Search space associations
SELECT ss.id as space_id, ss.name, d.id as doc_id, d.file_name 
FROM search_spaces ss
LEFT JOIN search_space_documents ssd ON ss.id = ssd.search_space_id
LEFT JOIN documents d ON ssd.document_id = d.id
LIMIT 20;
SQL
```

---

## Key Questions to Answer

After capturing logs, answer these:

### Upload Process:
- [ ] Did POST /api/v1/upload succeed? (Response code: ___)
- [ ] Was document created in database? (Yes/No, ID: ___)
- [ ] What was initial status? (processing/completed/failed)
- [ ] Were chunks created? (Count: ___)
- [ ] Did status change to 'completed'? (Yes/No, When: ___)
- [ ] How long did processing take? (___ seconds)

### Document Association:
- [ ] Is document linked to user? (user_id: ___)
- [ ] Is document linked to search space? (search_space_id: ___)
- [ ] Is search space correct? (Expected: 1, Actual: ___)

### Frontend Behavior:
- [ ] Did frontend call GET /api/v1/documents after upload? (Yes/No)
- [ ] What did GET /api/v1/documents return? (empty/populated)
- [ ] Did response include uploaded document? (Yes/No)
- [ ] Are there JavaScript errors? (Yes/No, Errors: ___)
- [ ] Does UI show skeleton loaders? (Yes/No)
- [ ] Does UI show actual documents? (Yes/No)

### The Gap:
- [ ] **If document exists in DB but not in API response → Data retrieval issue**
- [ ] **If document in API response but not rendered → Frontend rendering issue**
- [ ] **If document never created in DB → Backend processing issue**
- [ ] **If status stuck at 'processing' → Worker/async task issue**

---

## Expected vs Broken Flow

### Expected (Working):
```
1. [00:00] User clicks upload
2. [00:01] POST /api/v1/upload → 200 OK
3. [00:02] Backend: "Processing document..."
4. [00:03] Database: INSERT document (status='processing')
5. [00:05] Backend: "Creating chunks..." → 2344 chunks created
6. [00:10] Database: UPDATE status='completed'
7. [00:11] Frontend: GET /api/v1/documents → Returns array with new doc
8. [00:12] UI: Shows document list with new document
```

### Broken (Current):
```
1. [00:00] User clicks upload
2. [00:01] POST /api/v1/upload → 200 OK (or error?)
3. [00:02] Backend: "Processing document..."
4. [00:03] Database: INSERT document (status='processing')
5. [00:05] Backend: "Creating chunks..." → 2344 chunks created
6. [00:10] Database: UPDATE status='completed'
7. [00:11] Frontend: GET /api/v1/documents → Returns ??? (empty? wrong format?)
8. [00:12] UI: Shows skeleton loaders (STUCK!)

WHERE IS THE BREAK?
```

---

## Stop Conditions

**Stop monitoring when ONE of these occurs:**

✅ **SUCCESS:** Documents page shows actual document list (not skeletons)

❌ **FAILURE MODE 1:** Documents page shows skeletons for >30 seconds after upload completes

❌ **FAILURE MODE 2:** Console shows JavaScript errors

❌ **FAILURE MODE 3:** Network tab shows failed API requests (4xx/5xx)

❌ **FAILURE MODE 4:** Database shows status='failed'

❌ **FAILURE MODE 5:** Database shows status='processing' for >60 seconds

---

## Emergency Debug Commands

If upload seems stuck:

```bash
# Check backend is processing
docker logs backend --tail 50 | grep -i "processing\|chunk\|document"

# Check worker status (if separate container)
docker ps | grep -i worker
docker logs <worker> --tail 50

# Check database status
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, updated_at FROM documents ORDER BY updated_at DESC LIMIT 5;"

# Check if any background jobs running
docker exec backend ps aux | grep -i celery

# Force status check in backend
curl -X GET "http://localhost:8929/api/health"
```

---

## Final Deliverable

After upload test, create a summary file:

```bash
cat > upload-debug-summary.txt << EOF
UPLOAD DEBUG SUMMARY
====================
Date: $(date)
File uploaded: <filename>
Upload duration: <seconds>

TIMELINE:
- Upload started: <timestamp>
- Backend received: <timestamp>
- DB document created: <timestamp>
- Processing completed: <timestamp>
- Frontend queried: <timestamp>
- UI updated: <timestamp>

RESULTS:
- Document in database: YES/NO
- Document status: <status>
- Chunks created: <count>
- API returns document: YES/NO
- UI renders document: YES/NO

PROBLEM IDENTIFIED:
<Describe where the flow breaks>

LOGS ATTACHED:
- upload-backend-*.log
- upload-frontend-*.log
- upload-postgres-*.log
- upload-network-*.har
- upload-console-*.log
- database-snapshot.txt
- documents-after-upload.json

NEXT STEPS:
<What to investigate based on findings>
EOF
```

---

## Share with Parent Machine

Compress and share all logs:

```bash
tar -czf upload-debug-$(date +%Y%m%d-%H%M%S).tar.gz \
  upload-*.log \
  upload-*.har \
  upload-timeline-*.txt \
  database-snapshot.txt \
  documents-after-upload.json \
  upload-debug-summary.txt

# File will be ready at:
# /mnt/ssd1/projects/DocumentAI/upload-debug-*.tar.gz
```

---

**IMPORTANT:** Don't stop any terminals until you've verified success or captured the failure mode!
