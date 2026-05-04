# Document Upload Not Showing Debug Guide
**Date:** May 4, 2026  
**Issue:** Documents uploaded successfully but show as skeleton loaders on frontend

## Current System State

### What's Working ✅
- **Backend** (port 8929): Documents uploaded successfully
- **Database**: 2344 chunks stored in PostgreSQL
- **OpenSearch**: Document chunks indexed
- **API**: Backend returns document data correctly
- **Upload process**: No errors during upload

### The Problem ❌
- **Official Frontend** (port 3929): Shows skeleton loaders instead of document list
- **Expected**: List of uploaded documents with names, dates, status
- **Actual**: Infinite skeleton loading animation
- **Documents exist**: Verified in database (2344 chunks from MSFT FY26Q1 10-Q)


---

## Probe Questions for Copilot Investigation

### 1. Frontend API Requests Analysis

**Q1.1:** What API calls does the frontend make when loading the documents page?
```javascript
// In browser at http://localhost:3929
// Open DevTools (F12) → Network tab → XHR filter
// Navigate to documents page
// Look for API calls like:
// - GET /api/v1/documents
// - GET /api/v1/search-spaces/{id}/documents
// - GET /api/v1/files
```

**Q1.2:** What do those API responses contain?
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

**Q1.3:** Are there any failed API requests?
```javascript
// In Network tab, filter by:
// - Status: 4xx or 5xx errors
// - Look for red entries
// Check console for fetch/axios errors
```

---

### 2. Browser Console Investigation

**Q2.1:** What JavaScript errors appear in the console?
```bash
# Open http://localhost:3929/documents (or wherever docs are)
# Press F12 → Console tab
# Look for errors related to:
# - "Cannot read property of undefined"
# - "documents is not iterable"
# - React rendering errors
# - API client errors
```

**Q2.2:** Are there any React component errors?
```javascript
// Look for error boundaries triggered
// Look for "Error: undefined" in console
// Check for infinite re-render warnings
```

**Q2.3:** What does the React DevTools show?
```javascript
// Install React DevTools extension
// Check component tree
// Look at Documents/DocumentList component props
// Is documents array empty or populated?
```

---

### 3. Backend Data Verification

**Q3.1:** Do documents actually exist in the database?
```bash
# Get JWT token from browser
# DevTools → Application → Cookies → jwt
TOKEN="your_jwt_token_here"

# Query documents API
curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

# Expected: JSON array with document objects
# If empty: Documents not linked to user/search-space
```

**Q3.2:** What is the document status in the database?
```bash
# Direct PostgreSQL query (if you have access)
docker exec -it postgres psql -U username -d dbname -c \
  "SELECT id, file_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT 10;"

# Look for:
# - status = 'completed' (should show)
# - status = 'processing' (won't show until done)
# - status = 'failed' (won't show)
```

**Q3.3:** Are documents associated with the correct search space?
```bash
# Get search spaces first
curl -X GET "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN"

# Then get documents for specific search space
curl -X GET "http://localhost:8929/api/v1/search-spaces/1/documents" \
  -H "Authorization: Bearer $TOKEN"

# Check if documents appear under correct search space
```

---

### 4. Document List Component Analysis

**Q4.1:** What component renders the document list?
```bash
# Check Network tab for the main JS bundle
# Look at source maps or component names
# Common patterns:
# - DocumentList
# - DocumentGrid
# - FileList
# - UploadedFiles
```

**Q4.2:** Is the component receiving data but not rendering it?
```javascript
// In React DevTools:
// Find the document list component
// Check props: documents, files, or similar
// If array is populated but UI shows skeletons:
//   → Rendering logic bug
// If array is empty:
//   → Data fetching issue
```

**Q4.3:** Is there a loading state stuck as true?
```javascript
// Common bug: isLoading state never set to false
// In React DevTools, check for:
// - isLoading: true (stuck)
// - isFetching: true (stuck)
// - isPending: true (stuck)
```

---

### 5. Network Response Content Analysis

**Q5.1:** What does the documents API actually return?
```bash
# Full response with proper JWT
curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  | jq .

# Check structure:
# - Is it an array?
# - Are there documents in it?
# - What fields do document objects have?
# - Is there pagination metadata?
```

**Q5.2:** Compare API response with what frontend expects:
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

**Q5.3:** Is there pagination or filtering breaking the query?
```bash
# Try different query parameters
curl "http://localhost:8929/api/v1/documents?page=1&limit=10" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8929/api/v1/documents?status=completed" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8929/api/v1/documents?search_space_id=1" -H "Authorization: Bearer $TOKEN"

# Check which returns results
```

---

### 6. Backend Logs During Page Load

**Q6.1:** What does the backend log when you load the documents page?
```bash
# Terminal 1: Watch backend logs
docker logs backend -f --tail 100

# Terminal 2: Refresh documents page in browser
# Go to http://localhost:3929/documents (or wherever)

# Look in Terminal 1 for:
# - GET /api/v1/documents - 200 (successful)
# - GET /api/v1/documents - 404 (not found)
# - GET /api/v1/documents - 500 (server error)
# - No request at all (frontend not calling API)
```

**Q6.2:** Are there any errors in backend logs?
```bash
# Check for SQL errors
docker logs backend | grep -i "error\|exception\|traceback" | tail -20

# Check for query errors
docker logs backend | grep -i "select.*documents" | tail -10
```

---

### 7. Database Document Status Check

**Q7.1:** What statuses do the uploaded documents have?
```sql
-- Connect to PostgreSQL
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

**Q7.2:** Are documents marked as "completed" or still "processing"?
```sql
-- Count by status
SELECT status, COUNT(*) 
FROM documents 
GROUP BY status;

-- Expected: status = 'completed' or 'indexed'
-- If 'processing': Backend still working on them
-- If 'failed': Upload failed
```

**Q7.3:** Are the 2344 chunks actually linked to documents?
```sql
-- Check chunks exist
SELECT COUNT(*) FROM document_chunks;

-- Check chunks are linked to documents
SELECT 
  d.file_name,
  COUNT(dc.id) as chunk_count
FROM documents d
LEFT JOIN document_chunks dc ON d.id = dc.document_id
GROUP BY d.file_name;

-- If chunks exist but no documents: Orphaned chunks
```

---

### 8. Frontend State Management

**Q8.1:** Is there a state management issue (Redux/Zustand/Context)?
```javascript
// In browser console:
// Check global state
window.__REDUX_DEVTOOLS_EXTENSION__?.()
window.__ZUSTAND__

// Look for documents in state
// If populated but UI shows skeletons: Rendering bug
// If empty: Fetch issue
```

**Q8.2:** Is the fetch query being called correctly?
```javascript
// Check if using React Query / SWR / TanStack Query
// In console:
localStorage.getItem('REACT_QUERY_OFFLINE_CACHE')

// Or manually check the query:
fetch('http://localhost:8929/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)[1]
  }
}).then(r => r.json()).then(console.log)
```

---

### 9. Document Upload vs Display Disconnect

**Q9.1:** Did upload complete successfully?
```bash
# Check upload endpoint
curl -X GET "http://localhost:8929/api/v1/upload/status/{upload_id}" \
  -H "Authorization: Bearer $TOKEN"

# Check if status is "completed"
```

**Q9.2:** Is there a webhook/callback that frontend is waiting for?
```bash
# Check backend logs for WebSocket connections
docker logs backend | grep -i "websocket\|ws://"

# Check frontend for EventSource or WebSocket code
# DevTools → Network → WS (WebSocket filter)
```

**Q9.3:** Does the frontend need a manual refresh or polling?
```javascript
// Is there an auto-refresh mechanism?
// Check for:
// - setInterval polling
// - WebSocket updates
// - Server-Sent Events
// If none: Frontend might show old cached data
```

---

### 10. Frontend Routing and Component Mounting

**Q10.1:** Is the documents page route even rendering?
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

**Q10.2:** Are there race conditions in data fetching?
```javascript
// Common bug: Component unmounts before data loads
// Check in console:
// - "Can't perform a React state update on unmounted component"

// Or: Multiple fetches interfering
// Check Network tab for duplicate requests
```

---

## Quick Test Commands

### Verify Documents Exist in Backend
```bash
TOKEN=$(curl -X POST "http://localhost:8929/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

curl "http://localhost:8929/api/v1/documents" -H "Authorization: Bearer $TOKEN" | jq .
```

### Check Frontend Network Requests
```javascript
// In browser console at http://localhost:3929:
// Monitor fetch calls
const originalFetch = window.fetch;
window.fetch = function(...args) {
  console.log('FETCH:', args[0]);
  return originalFetch.apply(this, args);
};

// Reload page and watch console
```

### Test Direct API Call from Browser
```javascript
// In browser console (JWT token already in cookies):
fetch('/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)?.[1]
  }
})
.then(r => r.json())
.then(data => {
  console.log('Documents:', data);
  console.log('Count:', data?.length || data?.documents?.length);
});
```

---

## Expected vs Actual Behavior

### Expected (Working)
1. Frontend makes `GET /api/v1/documents` request
2. Backend returns JSON array of documents
3. Frontend receives data, sets loading=false
4. Document list component renders with data
5. User sees document names, dates, file sizes

### Actual (Broken)
1. Frontend loads documents page
2. Shows skeleton loader animation
3. Animation never disappears
4. Either:
   - API call never made → Frontend bug
   - API returns empty array → Backend/DB issue
   - API returns data but not rendered → React rendering bug
   - isLoading stuck as true → State management bug

---

## Critical Questions to Answer

1. **Does the frontend make an API call for documents?** (Check Network tab)
2. **What does that API call return?** (Check Response in Network tab)
3. **Are there JavaScript errors?** (Check Console tab)
4. **Do documents exist in database with status='completed'?** (Check PostgreSQL)
5. **Is the document list component receiving data?** (Check React DevTools)

---

## Most Likely Root Causes (Ranked)

### 1. API Returns Empty Array (60% probability)
```javascript
// Backend returns:
{
  "documents": [],
  "total": 0
}

// Because:
// - Documents not linked to current user
// - Documents not linked to current search space
// - Wrong status filter (only showing 'completed', but docs are 'processing')
```

**Fix:** Check document ownership and search space association

---

### 2. Frontend Data Structure Mismatch (25% probability)
```javascript
// Backend returns:
{
  "data": {
    "documents": [...]
  }
}

// Frontend expects:
{
  "documents": [...]
}

// Or just: [...]
```

**Fix:** Check API response structure vs frontend expectations

---

### 3. Loading State Stuck (10% probability)
```javascript
// isLoading never set to false
// Common with React Query when:
// - enabled: false (query disabled)
// - refetchOnMount: false
// - staleTime: Infinity with no data
```

**Fix:** Check query configuration and loading state updates

---

### 4. Component Rendering Logic Bug (3% probability)
```javascript
// Data is fetched but conditional rendering broken:
{documents?.length > 0 ? (
  <DocumentList documents={documents} />
) : (
  <SkeletonLoader />  // Always shown even when data exists
)}
```

**Fix:** Check rendering conditions

---

### 5. CORS or Network Error (2% probability)
```javascript
// API call fails silently
// Check console for CORS errors
// Check Network tab for failed requests
```

**Fix:** Check CORS configuration

---

## Data Collection Script

Run this to collect all diagnostics:

```bash
#!/bin/bash
# Save as collect-debug-data.sh

echo "=== Collecting Document Display Debug Data ==="

# Get JWT token (manual step - copy from browser)
read -p "Enter JWT token from browser cookies: " TOKEN

echo -e "\n=== 1. Documents API Response ===" > debug-report.txt
curl -s "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  | jq . >> debug-report.txt

echo -e "\n=== 2. Search Spaces ===" >> debug-report.txt
curl -s "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN" \
  | jq . >> debug-report.txt

echo -e "\n=== 3. Backend Recent Logs ===" >> debug-report.txt
docker logs backend --tail 100 >> debug-report.txt

echo -e "\n=== 4. PostgreSQL Document Status ===" >> debug-report.txt
docker exec postgres psql -U user -d db -c \
  "SELECT id, file_name, status, user_id, search_space_id, created_at FROM documents ORDER BY created_at DESC LIMIT 10;" \
  >> debug-report.txt 2>&1

echo -e "\n=== 5. Document Chunks Count ===" >> debug-report.txt  
docker exec postgres psql -U user -d db -c \
  "SELECT COUNT(*) as total_chunks FROM document_chunks;" \
  >> debug-report.txt 2>&1

echo -e "\n=== Debug report saved to debug-report.txt ==="
echo "Also check browser console and network tab!"
```

---

## Browser Debug Checklist

Open http://localhost:3929 and check:

- [ ] **Console tab:** Any JavaScript errors?
- [ ] **Network tab → XHR:** Is GET /api/v1/documents called?
- [ ] **Network tab → Response:** What does the API return?
- [ ] **Application tab → Cookies:** Is JWT token present?
- [ ] **React DevTools:** Is DocumentList component mounted?
- [ ] **React DevTools:** What are the component props?

Screenshot and share:
