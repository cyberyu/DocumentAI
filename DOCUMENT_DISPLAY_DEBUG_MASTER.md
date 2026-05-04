# Document Display Debug Master Guide
**Complete guide for debugging: Documents upload successfully but show as skeleton loaders**

---

## 📋 Table of Contents

1. [Quick Start - Upload Monitoring](#quick-start---upload-monitoring)
2. [The Issue](#the-issue)
3. [Critical First Tests (5 minutes)](#critical-first-tests)
4. [Upload Monitoring Session](#upload-monitoring-session)
5. [Comprehensive Probe Questions](#comprehensive-probe-questions)
6. [Post-Upload Analysis](#post-upload-analysis)
7. [Most Likely Root Causes](#most-likely-root-causes)
8. [Success Criteria](#success-criteria)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start - Upload Monitoring

### On Machine with Docker (where you'll upload)

**Step 1: Setup** (30 seconds)
```bash
cd /mnt/ssd1/projects/DocumentAI
./setup-upload-monitoring.sh
```

**Step 2: Open Monitoring Terminals** (1 minute)
The script will show you commands - open them in separate terminals:
- Terminal 1: Backend logs
- Terminal 2: Database watch (auto-refresh)
- Terminal 3: (Optional) PostgreSQL logs
- Terminal 4: (Optional) Frontend logs

**Step 3: Browser Setup** (30 seconds)
```
1. Open http://localhost:3929
2. Press F12 (DevTools)
3. Network tab → ✓ Preserve log
4. Console tab → Keep visible
```

**Step 4: Upload & Monitor**
- Upload your document
- Watch all terminals and browser
- **Don't close anything!**

**Step 5: Collect Data**
```bash
cd upload-debug-[TIMESTAMP]
./collect-data.sh
tar -czf upload-debug.tar.gz .
```

---

## The Issue

### What's Working ✅
- Backend (port 8929): Documents uploaded successfully
- Database: 2344 chunks stored in PostgreSQL
- OpenSearch: Document chunks indexed
- API: Backend returns document data correctly
- Upload process: No errors during upload

### The Problem ❌
- **Frontend (port 3929)**: Shows skeleton loaders instead of document list
- **Expected**: List of uploaded documents with names, dates, status
- **Actual**: Infinite skeleton loading animation
- **Documents exist**: Verified in database

### The Mystery
Documents upload successfully (2344 chunks created), backend processes them, database has them with status='completed', but frontend shows skeleton loaders forever instead of displaying the document list.

---

## Critical First Tests

*Run these first - they'll identify the root cause in ~5 minutes*

### Test 1: Browser Network Tab - Is API Called?
```
1. Open http://localhost:3929/documents (or wherever docs page is)
2. F12 → Network tab → XHR filter
3. Look for: GET /api/v1/documents
```

**✅ Working:** API call appears with 200 response  
**❌ Broken:** No API call made

**If no API call → Frontend routing/mounting issue**

---

### Test 2: Browser Network Response - What Data Returns?
```
1. Click on the GET /documents request in Network tab
2. Go to "Response" tab
3. Check the content
```

**✅ Working:** Array of document objects `[{id: 1, file_name: "...", ...}, ...]`  
**❌ Broken:** Empty array `[]` or error message

**If empty array → Data retrieval/filtering issue**

---

### Test 3: Browser Console - Any JavaScript Errors?
```
F12 → Console tab
Look for errors when documents page loads
```

**Look for:**
- ❌ "Cannot read property 'map' of undefined"
- ❌ "documents is not iterable"
- ❌ React component errors
- ✅ No errors (then it's a data issue, not code error)

**If errors → Frontend code bug**

---

### Test 4: Backend API Direct Test
```bash
# Get JWT token from browser first
# DevTools → Application → Cookies → jwt (copy the value)

TOKEN="paste_your_jwt_here"

curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq .
```

**✅ Expected:** JSON array with your uploaded documents  
**❌ Broken:** Empty array `[]` → Document not linked to user/search-space

**If empty → Document association issue**

---

### Test 5: Database Document Status Check
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, user_id, search_space_id 
   FROM documents 
   ORDER BY created_at DESC 
   LIMIT 5;"
```

**✅ Must show:** `status = 'completed'` (will display)  
**❌ Problem:** `status = 'processing'` (won't show yet) or `'failed'` (won't show)

**If wrong status → Backend processing issue**

---

### Decision Tree After First Tests

```
Documents not showing?
│
├─ Test 1: Is GET /documents API called?
│  ├─ NO → Frontend problem
│  │  ├─ Console errors? → Fix JavaScript bugs
│  │  ├─ Component not mounted? → Fix routing
│  │  └─ isLoading stuck? → Fix state management
│  │
│  └─ YES → API called, data issue
│     ├─ Test 2: Response empty []?
│     │  ├─ Test 4: API returns empty? → Backend filtering issue
│     │  │  └─ Test 5: Check DB status & associations
│     │  └─ API has data but frontend shows empty? → Data structure mismatch
│     │
│     └─ Test 2: Response has data?
│        ├─ Test 3: Console errors? → Rendering bug
│        └─ No errors? → Loading state stuck
```

---

## Upload Monitoring Session

### Pre-Upload Setup

#### Terminal 1 - Backend Logs (REQUIRED)
```bash
cd /mnt/ssd1/projects/DocumentAI
docker logs backend -f | tee upload-backend-$(date +%Y%m%d-%H%M%S).log
```

**Watch for:**
```
✓ "Processing document: filename.pdf"
✓ "Creating chunks for document"
✓ "Document processed successfully"
✓ "status: completed"

✗ "ERROR" or "Exception"
✗ "Failed to process"
✗ "status: failed"
```

---

#### Terminal 2 - Database Watch (REQUIRED)
```bash
watch -n 2 'docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, created_at 
   FROM documents 
   ORDER BY created_at DESC 
   LIMIT 3;" 2>/dev/null'
```

**Watch for:**
```
Before upload: Empty or existing documents

During upload:
id | file_name.pdf | processing | timestamp

After processing:
id | file_name.pdf | completed  | timestamp

✗ Status stuck at 'processing' for >60 seconds
✗ Document never appears
✗ Status changes to 'failed'
```

---

#### Browser DevTools (REQUIRED)

**Network Tab Setup:**
```
1. F12 → Network tab
2. ✓ Preserve log (check this!)
3. ✓ Disable cache
4. Clear existing entries
5. Filter: XHR or Fetch
```

**Console Tab:**
```
Keep visible to catch errors in real-time
```

---

### During Upload - Timeline Expectations

```
⏱️ 00:00  Click upload button
⏱️ 00:01  POST /api/v1/upload → 200 OK
⏱️ 00:02  Document appears in DB (status='processing')
⏱️ 00:03  Backend: "Processing document..."
⏱️ 00:05  Backend: "Creating chunks..." → Creating 2344 chunks
⏱️ 00:10  Status → 'completed' in database
⏱️ 00:11  Frontend: GET /api/v1/documents (auto-refresh)
⏱️ 00:12  UI updates (SUCCESS ✅) or shows skeletons (FAILURE ❌)
```

**Total time:** ~12 sec for small doc, ~60 sec for large doc

---

### What to Capture

#### Browser Network Tab
```
✓ POST /api/v1/upload → 200 OK
✓ POST /api/v1/documents → 200 OK (creates entry)
✓ GET /api/v1/upload/status/{id} → Polling (optional)
✓ GET /api/v1/documents → Returns array with new doc

✗ Any 4xx or 5xx errors
✗ No GET /documents call after upload
✗ GET /documents returns empty []
```

#### Browser Console Errors
```
✓ No errors (clean)

✗ "Uncaught TypeError: Cannot read property 'map' of undefined"
✗ "documents is not iterable"
✗ React rendering errors
✗ "401 Unauthorized" or "403 Forbidden"
```

---

### Post-Upload Verification

**Stop Condition:** 30 seconds after database shows status='completed'

**Run these checks:**

**1. Document Status:**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, created_at 
   FROM documents 
   ORDER BY created_at DESC 
   LIMIT 1;"
```

**2. Chunks Created:**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) as chunks 
   FROM document_chunks 
   WHERE document_id = (SELECT MAX(id) FROM documents);"
```

**3. API Returns Document:**
```bash
TOKEN="<from_browser>"
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**4. UI Shows Document:**
```
Visually check browser:
✅ Document list with names, dates
❌ Skeleton loaders persisting
```

---

### Collect Data After Upload

```bash
cd upload-debug-[TIMESTAMP]
./collect-data.sh

# This collects:
# - All terminal logs
# - Database snapshots
# - API responses
# - Error extracts
# - Automated summary

# Package everything
tar -czf upload-debug.tar.gz .
```

---

## Comprehensive Probe Questions

*Detailed investigation if initial tests don't reveal the issue*

### 1. Frontend API Requests Analysis

**Q1.1: What API calls does the frontend make when loading documents page?**
```javascript
// In browser at http://localhost:3929
// Open DevTools (F12) → Network tab → XHR filter
// Navigate to documents page
// Look for API calls like:
// - GET /api/v1/documents
// - GET /api/v1/search-spaces/{id}/documents
// - GET /api/v1/files
```

**Q1.2: What do those API responses contain?**
```javascript
// In DevTools Network tab:
// Click on each API request
// Check "Response" tab
// Look for:
// - Empty array []
// - Documents with status "processing"
// - Documents with status "completed"
// - Error messages
```

**Q1.3: Are there any failed API requests?**
```javascript
// In Network tab, filter by:
// - Status: 4xx or 5xx errors
// - Look for red entries
// Check console for fetch/axios errors
```

---

### 2. Backend Data Verification

**Q2.1: Do documents actually exist in the database?**
```bash
TOKEN="your_jwt_token"

curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq .

# Expected: JSON array with document objects
# If empty: Documents not linked to user/search-space
```

**Q2.2: What is the document status in the database?**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, created_at 
   FROM documents 
   ORDER BY created_at DESC 
   LIMIT 10;"

# Look for:
# - status = 'completed' (should show)
# - status = 'processing' (won't show until done)
# - status = 'failed' (won't show)
```

**Q2.3: Are documents associated with the correct search space?**
```bash
# Get search spaces first
curl -X GET "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Then get documents for specific search space
curl -X GET "http://localhost:8929/api/v1/search-spaces/1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

### 3. Network Response Content Analysis

**Q3.1: What does the documents API actually return?**
```bash
curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Check structure:
# - Is it an array?
# - Are there documents in it?
# - What fields do document objects have?
# - Is there pagination metadata?
```

**Q3.2: Compare API response with what frontend expects:**
```javascript
// If API returns:
{
  "documents": [...],  // nested
  "total": 10,
  "page": 1
}

// But frontend expects:
[
  {...},  // flat array
  {...}
]

// → Data structure mismatch
```

**Q3.3: Is there pagination or filtering breaking the query?**
```bash
# Try different query parameters
curl "http://localhost:8929/api/v1/documents?page=1&limit=10" \
  -H "Authorization: Bearer $TOKEN"

curl "http://localhost:8929/api/v1/documents?status=completed" \
  -H "Authorization: Bearer $TOKEN"

curl "http://localhost:8929/api/v1/documents?search_space_id=1" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 4. Backend Logs During Page Load

**Q4.1: What does backend log when you load documents page?**
```bash
# Terminal 1: Watch backend logs
docker logs backend -f --tail 100

# Terminal 2: Refresh documents page in browser

# Look in Terminal 1 for:
# - GET /api/v1/documents - 200 (successful)
# - GET /api/v1/documents - 404 (not found)
# - GET /api/v1/documents - 500 (server error)
# - No request at all (frontend not calling API)
```

**Q4.2: Are there any errors in backend logs?**
```bash
docker logs backend | grep -i "error\|exception\|traceback" | tail -20
```

---

### 5. Document List Component Analysis

**Q5.1: What component renders the document list?**
```javascript
// Use React DevTools extension
// Look for components like:
// - DocumentList
// - DocumentGrid
// - FileList
// - UploadedFiles
```

**Q5.2: Is the component receiving data but not rendering it?**
```javascript
// In React DevTools:
// Find the document list component
// Check props: documents, files, or similar

// If array is populated but UI shows skeletons:
//   → Rendering logic bug

// If array is empty:
//   → Data fetching issue
```

**Q5.3: Is there a loading state stuck as true?**
```javascript
// Common bug: isLoading state never set to false
// In React DevTools, check for:
// - isLoading: true (stuck)
// - isFetching: true (stuck)
// - isPending: true (stuck)
```

---

### 6. Database Document Status Check

**Q6.1: What statuses do the uploaded documents have?**
```sql
SELECT 
  id,
  file_name,
  status,
  created_at,
  updated_at,
  user_id,
  search_space_id
FROM documents
ORDER BY created_at DESC
LIMIT 20;
```

**Q6.2: Are the 2344 chunks actually linked to documents?**
```sql
-- Check chunks exist
SELECT COUNT(*) as total_chunks FROM document_chunks;

-- Check chunks are linked to documents
SELECT 
  d.file_name,
  COUNT(dc.id) as chunk_count
FROM documents d
LEFT JOIN document_chunks dc ON d.id = dc.document_id
GROUP BY d.file_name
ORDER BY d.created_at DESC;

-- If chunks exist but no documents: Orphaned chunks
```

---

### 7. Frontend State Management

**Q7.1: Is there a state management issue?**
```javascript
// In browser console, check global state:
window.__REDUX_DEVTOOLS_EXTENSION__?.()
window.__ZUSTAND__

// Look for documents in state
// If populated but UI shows skeletons: Rendering bug
// If empty: Fetch issue
```

**Q7.2: Is the fetch query being called correctly?**
```javascript
// Manually test the fetch in console:
fetch('http://localhost:8929/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)[1]
  }
}).then(r => r.json()).then(console.log)
```

---

### 8. Document Upload vs Display Disconnect

**Q8.1: Does the frontend need a manual refresh or polling?**
```javascript
// Is there an auto-refresh mechanism?
// Check for:
// - setInterval polling
// - WebSocket updates
// - Server-Sent Events

// If none: Frontend might show old cached data
```

**Q8.2: Is there a webhook/callback that frontend is waiting for?**
```bash
# Check backend logs for WebSocket connections
docker logs backend | grep -i "websocket\|ws://"

# Check frontend for EventSource or WebSocket code
# DevTools → Network → WS (WebSocket filter)
```

---

### 9. Frontend Routing and Component Mounting

**Q9.1: Is the documents page route even rendering?**
```javascript
// Check URL when on documents page
// Should be something like:
// - /documents
// - /files
// - /search-spaces/1/documents

// In React DevTools component tree:
// - Is DocumentList component mounted?
// - Is it inside a Suspense boundary?
// - Is useEffect running?
```

**Q9.2: Are there race conditions in data fetching?**
```javascript
// Common bug: Component unmounts before data loads
// Check console for:
// "Can't perform React state update on unmounted component"

// Or: Multiple fetches interfering
// Check Network tab for duplicate requests
```

---

### 10. Browser Debug Tests

**Q10.1: Test API call directly from browser:**
```javascript
// In browser console at http://localhost:3929:
fetch('/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)?.[1]
  }
})
.then(r => r.json())
.then(data => {
  console.log('Documents:', data);
  console.log('Count:', data?.length || data?.documents?.length);
  console.log('Structure:', Object.keys(data));
});
```

**Q10.2: Monitor all fetch calls:**
```javascript
// Intercept fetch to log all API calls
const originalFetch = window.fetch;
window.fetch = function(...args) {
  console.log('FETCH:', args[0]);
  return originalFetch.apply(this, args).then(response => {
    console.log('RESPONSE:', response.status, args[0]);
    return response;
  });
};

// Reload page and watch console
```

---

## Post-Upload Analysis

### Data Files Generated

After running `collect-data.sh`:

```
upload-debug-[TIMESTAMP]/
├── backend.log                  # Backend container logs
├── frontend.log                 # Frontend container logs
├── postgres.log                 # PostgreSQL logs
├── api-documents.json           # GET /documents response
├── api-search-spaces.json       # GET /search-spaces response
├── database-documents.txt       # Documents table snapshot
├── database-chunks.txt          # Chunk counts
├── database-associations.txt    # Search space links
├── backend-errors.txt           # Extracted errors
├── postgres-errors.txt          # DB errors
└── SUMMARY.txt                  # Automated analysis
```

---

### Analysis Workflow

**Step 1: Read SUMMARY.txt**
```bash
cat SUMMARY.txt
```

Quick overview of:
- Documents in API vs database
- Error counts
- Next investigation steps

---

**Step 2: Check Document Counts Match**
```bash
# Database count
grep -c "^\s*[0-9]" database-documents.txt

# API response count
jq 'length' api-documents.json

# If mismatch → Data retrieval issue
# If both 0 → Upload/processing issue
# If DB > 0 but API = 0 → Association/filtering issue
```

---

**Step 3: Verify Document Status**
```bash
cat database-documents.txt | grep -i "status"

# All should be 'completed'
# If 'processing' → Background job stuck
# If 'failed' → Processing error
```

---

**Step 4: Check Error Logs**
```bash
# Backend errors
cat backend-errors.txt

# PostgreSQL errors
cat postgres-errors.txt

# Look for:
# - SQL errors
# - Foreign key violations
# - Processing exceptions
```

---

**Step 5: Examine API Response Structure**
```bash
jq 'keys' api-documents.json

# Expected structures:
# Case A: ["documents", "total", "page"]  # Nested
# Case B: Top-level array [0, 1, 2, ...]  # Flat

# If frontend expects A but gets B → Structure mismatch
```

---

**Step 6: Check Search Space Associations**
```bash
cat database-associations.txt

# Verify documents linked to:
# - Correct search_space_id (usually 1)
# - Correct user_id
# - Not null values
```

---

### Results Matrix

| Evidence | Working State | Broken State | Diagnosis |
|----------|---------------|--------------|-----------|
| Network tab | GET /documents with 200 | No API call | Frontend routing issue |
| API response | Array with documents | Empty array [] | Data retrieval issue |
| Console | No errors | React/JS errors | Frontend code bug |
| DB documents | status='completed' | status='processing' | Processing incomplete |
| DB associations | Linked to user/space | NULL or wrong IDs | Association issue |
| Backend logs | "processed successfully" | Errors/exceptions | Backend processing bug |
| Chunks | Count > 0 linked to doc | Count = 0 or orphaned | Chunking failed |
| React state | isLoading=false | isLoading=true (stuck) | State management bug |

---

## Most Likely Root Causes

### 1. API Returns Empty Array (50% probability)

**Symptom:** API call succeeds (200 OK) but returns `[]`

**Root causes:**
- Documents not associated with current user's ID
- Documents in different search space than UI is querying
- Documents have status other than 'completed' (e.g., 'processing')
- Wrong API endpoint being called
- Backend filtering logic excluding documents

**How to verify:**
```bash
# Direct database check
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*), status, user_id, search_space_id 
   FROM documents 
   GROUP BY status, user_id, search_space_id;"

# Check user association
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq 'length'
```

**Fix approaches:**
- Check document ownership in DB
- Verify search_space_id linkage
- Check status filter in backend API
- Verify authentication/authorization

---

### 2. Frontend Data Structure Mismatch (25% probability)

**Symptom:** API returns data but frontend can't read it

**Root causes:**
```javascript
// Backend returns:
{
  "data": {
    "documents": [...],
    "total": 10
  }
}

// But frontend expects:
{
  "documents": [...]
}

// Or just:
[...]
```

**How to verify:**
```javascript
// In browser console:
fetch('/api/v1/documents', {
  headers: {'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)[1]}
})
.then(r => r.json())
.then(data => {
  console.log('Structure:', Object.keys(data));
  console.log('Type:', Array.isArray(data) ? 'Array' : 'Object');
  console.log('Full data:', data);
});
```

**Fix approaches:**
- Check API response format
- Update frontend data parsing
- Add adapter/transformer layer
- Fix backend response structure

---

### 3. Loading State Stuck (15% probability)

**Symptom:** Data might be there but UI shows loaders forever

**Root causes:**
- `isLoading` state never set to false
- React Query/SWR misconfigured (`enabled: false`)
- Component re-rendering infinitely
- Error boundary catching but not displaying error

**How to verify:**
```javascript
// Use React DevTools:
// 1. Find DocumentList component
// 2. Check state: isLoading, isFetching, isPending
// 3. If stuck as true → state update bug

// In console, monitor state changes:
// Look for infinite re-render warnings
```

**Fix approaches:**
- Check loading state logic in component
- Verify query configuration
- Add error handling
- Check dependency arrays in useEffect

---

### 4. API Not Being Called (7% probability)

**Symptom:** No network requests in DevTools

**Root causes:**
- Component not mounted properly
- Route guard blocking page
- useEffect missing dependencies
- Conditional rendering preventing execution

**How to verify:**
```
DevTools → Network tab → XHR filter
Should see GET /api/v1/documents
If missing → routing/mounting issue
```

**Fix approaches:**
- Check route configuration
- Verify component lifecycle
- Check authentication guards
- Review conditional rendering logic

---

### 5. Document Status Not 'completed' (3% probability)

**Symptom:** Documents stuck in 'processing' status

**Root causes:**
- Background job not finished
- ETL pipeline failed
- Celery worker not running
- Async task queue stuck

**How to verify:**
```bash
docker exec postgres psql -U user -d dbname -c \
  "SELECT status, COUNT(*) 
   FROM documents 
   GROUP BY status;"

# If all show 'processing':
docker logs backend | grep -i "celery\|worker\|processing"
docker ps | grep -i worker
```

**Fix approaches:**
- Check worker logs
- Restart workers
- Check task queue
- Review processing pipeline

---

## Success Criteria

### ✅ You'll Know It's Fixed When:

1. **Browser Network tab** shows GET /api/v1/documents with 200 OK
2. **API response** contains array of document objects (length > 0)
3. **Browser Console** shows no errors
4. **Documents page** displays document list (not skeletons)
5. **React DevTools** shows documents array populated in component
6. **Loading state** is false after data loads

### ✅ Full Success Test:

```bash
# 1. Document in database
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) FROM documents WHERE status='completed';"
# Should be > 0

# 2. API returns it
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq 'length'
# Should match database count

# 3. UI shows it
# Visually: Document list visible with names, dates, sizes
# No skeleton loaders

# 4. Can interact with it
# Click document → Opens successfully
# Search works
# Filters work
```

---

## Troubleshooting

### "setup-upload-monitoring.sh not found"
```bash
cd /mnt/ssd1/projects/DocumentAI
ls -la setup-upload-monitoring.sh

# If missing, check you're in the right directory
pwd
```

### "Permission denied"
```bash
chmod +x setup-upload-monitoring.sh
```

### Can't connect to PostgreSQL
```bash
# Check container name
docker ps | grep postgres

# If different name, use it:
docker exec <actual_postgres_name> psql -U user -d dbname -c "..."

# Check credentials
docker exec postgres env | grep POSTGRES
```

### Don't know database name/user
```bash
# Check docker-compose
cat docker-compose*.yml | grep -A 5 "POSTGRES"

# Common defaults:
# User: postgres, user, admin
# DB: postgres, documentai, surfsense, db
```

### "jq: command not found"
```bash
# Install jq
sudo apt-get install jq

# Or use python instead:
curl ... | python3 -m json.tool
```

### Upload takes too long
```bash
# Check backend is processing
docker logs backend --tail 50 | grep -i "processing\|chunk"

# Check if worker running (if separate container)
docker ps | grep -i worker

# Check resources
docker stats
```

### Frontend shows old data
```bash
# Force refresh in browser
Ctrl + Shift + R

# Clear browser cache
DevTools → Application → Clear storage

# Check API response is fresh
# Network tab → Disable cache ✓
```

---

## Quick Reference Commands

### Check Everything is Running
```bash
docker ps | grep -E "backend|frontend|postgres"
curl http://localhost:8929/api/health
curl -I http://localhost:3929
```

### Get JWT Token
```
Browser → F12 → Application → Cookies → jwt
Copy the Value field
```

### Test API Directly
```bash
TOKEN="your_jwt_token"

# Get documents
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Get search spaces  
curl "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

### Check Database
```bash
# Document count
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) FROM documents;"

# Recent documents
docker exec postgres psql -U user -d dbname -c \
  "SELECT * FROM documents ORDER BY created_at DESC LIMIT 3;"

# Chunk count
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) FROM document_chunks;"
```

### Watch Logs Live
```bash
# Backend
docker logs backend -f

# Frontend
docker logs documentai-frontend-1 -f

# PostgreSQL
docker logs postgres -f
```

### Browser Console Tests
```javascript
// Test API call
fetch('/api/v1/documents', {
  headers: {'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)[1]}
}).then(r => r.json()).then(console.log)

// Monitor fetch calls
const originalFetch = window.fetch;
window.fetch = function(...args) {
  console.log('FETCH:', args[0]);
  return originalFetch.apply(this, args);
};
```

---

## Contact & Next Steps

After collecting all logs and data:

1. **Review SUMMARY.txt** for quick diagnosis
2. **Compare counts:** Documents in DB vs API response
3. **Check errors:** backend-errors.txt and postgres-errors.txt
4. **Verify structure:** API response format vs frontend expectations
5. **Check associations:** Documents linked to correct user/space

**Package everything:**
```bash
tar -czf upload-debug.tar.gz upload-debug-*/
```

**Share with debugging AI:**
- upload-debug.tar.gz
- Screenshots of browser DevTools (Network + Console)
- Description of what you observed

---

## Additional Resources

- **UPLOAD_LOG_CAPTURE_GUIDE.md** - Detailed step-by-step upload monitoring
- **UPLOAD_MONITOR_QUICK_REF.md** - One-page cheat sheet for monitoring
- **UPLOAD_DEBUG_README.md** - Original upload debug guide

---

**Ready to debug? Run `./setup-upload-monitoring.sh` to begin!**
