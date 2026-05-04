# Document Display Debug Checklist
**Quick reference for debugging documents not showing (skeleton loader issue)**

## ⚡ Critical First Tests (Run These First)

### 1. Browser Network Tab - Document API Call
```bash
# Open http://localhost:3929 in browser
# Press F12 → Network tab → XHR filter
# Navigate to documents page
# Look for: GET /api/v1/documents (or similar)
```

**Expected working output:** API call to documents endpoint with 200 response  
**Current broken output:** Either no API call, or API returns empty array

---

### 2. Browser Network Response - What Data Returns
```bash
# In DevTools Network tab:
# Click on the documents API request
# Go to "Response" tab
# Check what's returned
```

**Expected working:** Array of document objects with names, IDs, status  
**Current broken:** Empty array `[]` or missing documents key

---

### 3. Browser Console - JavaScript Errors
```bash
# F12 → Console tab
# Look for errors when documents page loads
```

**Look for:**
- ❌ "Cannot read property 'map' of undefined"
- ❌ "documents is not iterable"  
- ❌ React component errors
- ✅ No errors (then it's a data issue, not code error)

---

### 4. Backend API Direct Test
```bash
# Get JWT token from browser cookies first
# DevTools → Application → Cookies → jwt (copy the value)

TOKEN="paste_your_jwt_here"

curl -X GET "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq .
```

**Expected:** JSON array with your uploaded documents  
**If empty:** Documents not linked to your user/search-space

---

### 5. Database Document Status Check
```bash
# Check if documents exist and their status
docker exec postgres psql -U username -d dbname -c \
  "SELECT id, file_name, status, user_id, search_space_id FROM documents LIMIT 10;"
```

**Must show:**
- `status = 'completed'` (will display)
- If `status = 'processing'` (won't show yet)
- If `status = 'failed'` (won't show)

---

## 🔍 Secondary Investigation

### 6. React DevTools Component State
```bash
# Install React DevTools browser extension
# Open DevTools → Components tab
# Find DocumentList or similar component
# Check props and state
```

**Look for:**
- `documents` prop: Is it populated or empty array?
- `isLoading` state: Is it stuck as `true`?
- `error` state: Does it show an error message?

---

### 7. Backend Logs During Page Load
```bash
# Terminal 1: Watch backend
docker logs backend -f --tail 50

# Terminal 2: Reload documents page in browser

# Look in Terminal 1 for:
# GET /api/v1/documents - 200 (good!)
# GET /api/v1/documents - 404 (endpoint doesn't exist)
# GET /api/v1/documents - 500 (server error)
# Nothing at all (frontend not calling API)
```

---

### 8. Search Space Association Check
```bash
# Documents might be in wrong search space
curl -X GET "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Try each search space
curl -X GET "http://localhost:8929/api/v1/search-spaces/1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

### 9. Document Chunks vs Documents Link
```bash
# Check if chunks exist but not linked to documents
docker exec postgres psql -U user -d db -c \
  "SELECT 
    (SELECT COUNT(*) FROM document_chunks) as total_chunks,
    (SELECT COUNT(*) FROM documents) as total_documents;"
```

**If chunks > 0 but documents = 0:** Orphaned chunks, upload incomplete

---

### 10. API Response Structure Check
```bash
# Compare what backend sends vs what frontend expects
curl "http://localhost:8929/api/v1/documents" -H "Authorization: Bearer $TOKEN" | jq 'keys'

# Common structures:
# Case 1: {"documents": [...], "total": 10}  # Nested
# Case 2: [{...}, {...}]                      # Flat array
# Case 3: {"data": {"items": [...]}}          # Double nested
```

Frontend might expect structure A but backend returns structure B

---

## 📊 Results Matrix

| Test | Working Behavior | Broken (Current) | Diagnosis |
|------|------------------|------------------|-----------|
| Network tab | Shows GET /documents with 200 | No API call made | Frontend routing/mounting issue |
| API response | Array with documents | Empty array [] | Data retrieval or filtering issue |
| Console errors | No errors | React/JS errors | Frontend code bug |
| Database status | Documents with status='completed' | No documents or status='processing' | Backend processing issue | Loading state | isLoading=false after data loads | isLoading stuck as true | State management bug |
| Backend logs | Shows incoming GET requests | No requests logged | Frontend not calling API |
| Document-chunks link | Chunks linked to document_id | Orphaned chunks | Upload incomplete |

---

## 🎯 Decision Tree

```
Start: Documents not showing, skeleton loaders persist
│
├─ API call appears in Network tab?
│  │
│  ├─ NO → Frontend not making API call
│  │  ├─ Console errors? → Fix JavaScript bugs
│  │  ├─ isLoading stuck? → Fix state management
│  │  └─ Component not mounted? → Fix routing
│  │
│  └─ YES → API call made but something wrong
│     │
│     ├─ Response is empty []
│     │  ├─ Documents in DB? → Check document ownership/search-space
│     │  ├─ Wrong status? → Check if status='processing' vs 'completed'
│     │  └─ Wrong user? → Check user_id association
│     │
│     ├─ Response has data
│     │  ├─ Wrong structure? → Frontend expects array, backend sends {documents:[]}
│     │  ├─ Data not rendering? → Check component render logic
│     │  └─ Loading never clears? → Check state updates
│     │
│     └─ Response is error (4xx/5xx)
│        ├─ 401/403 → Authentication issue
│        ├─ 404 → Wrong endpoint or route
│        └─ 500 → Backend error (check logs)
```

---

## 💾 Data to Collect for Copilot

Create these files and share:

```bash
# Get JWT token first
# Browser DevTools → Application → Cookies → jwt
TOKEN="your_jwt_token"

# 1. Documents API response
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq . > documents-api.json

# 2. Search spaces
curl "http://localhost:8929/api/v1/search-spaces" \
  -H "Authorization: Bearer $TOKEN" | jq . > search-spaces.json

# 3. Backend logs
docker logs backend --tail 200 > backend-logs.txt

# 4. PostgreSQL document status
docker exec postgres psql -U user -d db -c \
  "SELECT id, file_name, status, user_id, search_space_id, created_at FROM documents LIMIT 20;" \
  > documents-db.txt

# 5. Take screenshots
# - Browser console (any errors?)
# - Browser network tab (what API calls?)
# - Documents page showing skeleton loaders
```

Share these files with Copilot on the other machine.

---

## 🚨 Most Likely Causes (Ranked)

### 1. API Returns Empty Array (50% probability)
**Symptom:** API call succeeds but returns `[]`

**Root causes:**
- Documents not associated with current user's ID
- Documents in different search space than UI is querying
- Documents have status other than 'completed' (e.g., 'processing')
- Wrong API endpoint being called

**How to verify:**
```bash
# Direct database check
docker exec postgres psql -U user -d db -c \
  "SELECT COUNT(*), status FROM documents GROUP BY status;"

# Check user association
curl "http://localhost:8929/api/v1/documents" -H "Authorization: Bearer $TOKEN" | jq 'length'
```

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

// Or just: [...]
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
  console.log('Full data:', data);
});
```

---

### 3. Loading State Stuck (15% probability)
**Symptom:** Data might be there but UI shows loaders forever

**Root causes:**
- `isLoading` state never set to false
- React Query/SWR misconfigured
- Component re-rendering infinitely

**How to verify:**
```javascript
// Use React DevTools:
// 1. Find DocumentList component
// 2. Check state: isLoading, isFetching
// 3. If stuck as true → state update bug
```

---

### 4. API Not Being Called (7% probability)
**Symptom:** No network requests in DevTools

**Root causes:**
- Component not mounted properly
- Route guard blocking page
- useEffect missing dependencies

**How to verify:**
- DevTools → Network tab → XHR filter
- Should see GET /api/v1/documents
- If missing → frontend routing issue

---

### 5. Document Status Not 'completed' (3% probability)
**Symptom:** Documents stuck in 'processing' status

**Root causes:**
- Background job not finished
- ETL pipeline failed
- Celery worker not running

**How to verify:**
```bash
docker exec postgres psql -U user -d db -c \
  "SELECT status, COUNT(*) FROM documents GROUP BY status;"

# If all show 'processing':
docker logs backend | grep -i "celery\|worker\|processing"
```

---

## ✅ Success Criteria

You'll know it's fixed when:

1. **Browser Network tab** shows GET /api/v1/documents with 200 OK
2. **API response** contains array of document objects
3. **Browser Console** shows no errors
4. **Documents page** displays document list (not skeletons)
5. **React DevTools** shows documents array populated in component

---

## 🔗 Quick Commands Reference

```bash
# Check backend is running
docker ps | grep backend
curl http://localhost:8929/api/health

# Check documents via API (need JWT token first)
TOKEN="your_jwt"
curl "http://localhost:8929/api/v1/documents" -H "Authorization: Bearer $TOKEN" | jq .

# Check database directly
docker exec postgres psql -U user -d db -c "SELECT * FROM documents LIMIT 5;"

# Watch logs while testing
docker logs backend -f

# Test from browser console
fetch('/api/v1/documents', {
  headers: {'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)[1]}
}).then(r => r.json()).then(console.log)
```

---

## 📝 Report Template for Copilot

```markdown
Document Display Debug Results
===============================

**Frontend URL:** http://localhost:3929
**Backend URL:** http://localhost:8929
**Issue:** Skeleton loaders persist, documents not displayed

Test Results:
-------------

1. Browser Network Tab:
   [ ] GET /api/v1/documents appears? YES / NO
   [ ] Response status code: ___
   [ ] Response body length: ___ (0 = empty, >0 = has data)

2. API Response Structure:
   ```json
   [paste response here]
   ```

3. Browser Console Errors:
   ```
   [paste errors or "No errors"]
   ```

4. Database Document Count:
   Total documents: ___
   Status breakdown:
   - completed: ___
   - processing: ___
   - failed: ___

5. React DevTools State:
   Component: ___
   documents prop: [populated / empty / undefined]
   isLoading state: [true / false]

6. Backend Logs (during page load):
   ```
   [paste relevant logs]
   ```

Conclusion:
-----------
Primary issue: [select one]
[ ] API returns empty array (data retrieval issue)
[ ] API not being called (frontend mounting issue)
[ ] Data structure mismatch (integration issue)
[ ] Loading state stuck (state management bug)
[ ] Documents still processing (backend job issue)

Next step: [what to investigate next]
```

---

**Start with tests 1-5, they'll identify the root cause within 5 minutes.**
