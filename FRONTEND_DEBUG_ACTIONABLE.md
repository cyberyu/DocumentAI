# Frontend Document Display - Actionable Debug Steps

## Summary of Backend Investigation

✅ **Backend is working perfectly:**
- Document id=27 uploaded with status `{"state": "ready"}`
- API GET /api/v1/documents returns the document correctly
- 2344 chunks created and indexed
- No backend errors

❌ **Problem: Frontend shows skeleton loaders despite correct API responses**

---

## Critical Missing Data (Need to Capture)

The log file shows backend is perfect, but we need **browser-side** evidence:

### 1. Is the Frontend Calling the API?

**Action: Check Browser DevTools Network Tab**

```
1. Open http://localhost:3929 (or your frontend URL)
2. F12 → Network tab
3. Filter: XHR or Fetch
4. Look for: GET /api/v1/documents
```

**Expected outcomes:**

| Observation | Diagnosis | Next Step |
|-------------|-----------|-----------|
| ✅ API call appears with 200 | Frontend receiving data | Check response format |
| ❌ No API call at all | **Frontend not querying** | Check component mounting |
| ❌ API call with 401/403 | Authentication issue | Check JWT token |
| ❌ API call with 404 | Wrong endpoint | Check frontend API URL config |

---

### 2. What Does the API Response Contain (Frontend View)?

**Action: Click on the GET request in Network tab**

```
Network tab → Click "documents" request → Response tab
```

**Check:**
- Is the response the same format as backend log shows?
- Does `items` array contain the document?
- Is `total: 1`?

**If response is empty `[]`:**
```javascript
// In browser console, manually test:
fetch('/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)?.[1]
  }
}).then(r => r.json()).then(console.log)
```

---

### 3. Browser Console Errors?

**Action: Check Console for JavaScript Errors**

```
F12 → Console tab
```

**Look for:**
- ❌ `Cannot read property 'map' of undefined`
- ❌ `items is not iterable`
- ❌ React component errors
- ❌ `Uncaught TypeError`

**If you see errors, share the exact error message.**

---

### 4. React Component State (Advanced)

**Action: Use React DevTools**

```
1. Install React DevTools extension (if not installed)
2. F12 → React/Components tab
3. Find: DocumentList or similar component
4. Check props/state:
   - documents (or items): Should be array with 1 item
   - isLoading: Should be false
   - error: Should be null
```

**If `isLoading` is stuck as `true`:**
- Frontend state management bug (loading state never set to false)

**If `documents` array is populated but UI shows skeletons:**
- Rendering logic bug (data exists but component not displaying it)

---

## Quick Test: Manual API Call from Browser

**Run this in browser console while on http://localhost:3929:**

```javascript
// Test 1: Can fetch documents?
fetch('/api/v1/documents', {
  headers: {
    'Authorization': 'Bearer ' + document.cookie.match(/jwt=([^;]+)/)?.[1],
    'Content-Type': 'application/json'
  }
})
.then(r => r.json())
.then(data => {
  console.log('✅ API Response:', data);
  console.log('📊 Total docs:', data.total);
  console.log('📄 Items count:', data.items?.length);
  console.log('🔍 First doc:', data.items?.[0]);
})
.catch(err => console.error('❌ API Error:', err));
```

**Expected output:**
```
✅ API Response: {items: [{id: 27, title: "MSFT_FY26Q1_10Q.docx", ...}], total: 1}
📊 Total docs: 1
📄 Items count: 1
🔍 First doc: {id: 27, title: "MSFT_FY26Q1_10Q.docx", ...}
```

---

## Most Likely Root Causes (Ranked)

### 1. Frontend Not Calling API (40%)

**Symptoms:**
- No GET /api/v1/documents in Network tab
- Manual console fetch works

**Causes:**
- Component not mounted on page load
- useEffect missing or misconfigured
- Route guard blocking
- Authentication redirect loop

**Fix:** Check component mounting and useEffect dependencies

---

### 2. Data Structure Mismatch (30%)

**Symptoms:**
- API called and returns data
- Console error about `map` or undefined

**Causes:**
```javascript
// Backend returns:
{items: [...], total: 1}

// But frontend expects:
{documents: [...]}  // Wrong key

// Or frontend expects flat array:
[...]  // But gets nested object
```

**Fix:** Update frontend data parsing or backend response format

---

### 3. Loading State Stuck (20%)

**Symptoms:**
- API called, data received
- React DevTools shows `isLoading: true` forever

**Causes:**
- Promise not resolving correctly
- State update not called
- Component unmounted before data arrives

**Fix:** Check loading state management in fetch logic

---

### 4. React Rendering Bug (10%)

**Symptoms:**
- Data in component state
- No console errors
- UI still shows skeletons

**Causes:**
- Conditional rendering logic wrong
- CSS hiding elements
- Component not re-rendering after state update

**Fix:** Check render logic and force re-render

---

## Capture Browser Data

**To complete the investigation, run these commands in browser console:**

```javascript
// === BROWSER DEBUG REPORT ===
console.log('=== DOCUMENT DEBUG REPORT ===');

// 1. Check if JWT exists
const jwt = document.cookie.match(/jwt=([^;]+)/)?.[1];
console.log('1. JWT exists:', !!jwt);
console.log('   JWT preview:', jwt?.substring(0, 20) + '...');

// 2. Test API call
fetch('/api/v1/documents', {
  headers: {'Authorization': 'Bearer ' + jwt}
})
.then(r => r.json())
.then(data => {
  console.log('2. API Response Status: OK');
  console.log('   Total from API:', data.total);
  console.log('   Items from API:', data.items?.length);
  console.log('   Full response:', data);
})
.catch(e => console.error('2. API Error:', e));

// 3. Check for React DevTools
console.log('3. React DevTools:', typeof window.__REACT_DEVTOOLS_GLOBAL_HOOK__ !== 'undefined' ? 'Installed' : 'Not found');

// 4. Current page URL
console.log('4. Current URL:', window.location.href);

// 5. Check for errors in console
console.log('5. Check console above for any red errors');
```

**Copy and paste ALL console output and share it.**

---

## What We Need from You

1. **Network Tab Screenshot:**
   - Show the XHR/Fetch requests when on documents page
   - Highlight GET /api/v1/documents (if it exists)

2. **Console Output:**
   - Run the "BROWSER DEBUG REPORT" script above
   - Copy all output

3. **Frontend URL:**
   - What URL shows skeleton loaders? (e.g., http://localhost:3929/documents)

4. **Browser Console Errors:**
   - Any red errors when page loads?

5. **React DevTools (if installed):**
   - Component name that should show documents
   - Component state (documents, isLoading, items)

---

## Quick Wins to Try

### Try 1: Hard Refresh
```
Ctrl + Shift + R (or Cmd + Shift + R on Mac)
```
Sometimes cached JavaScript prevents API calls.

### Try 2: Clear Browser Cache
```
F12 → Application → Clear Storage → Clear site data
```
Then refresh page.

### Try 3: Check Auth Token
```javascript
// In console:
document.cookie.match(/jwt=([^;]+)/)
```
If null, you're not logged in.

### Try 4: Direct API Test
```bash
# From terminal (replace TOKEN):
TOKEN="your_jwt_from_browser"
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN"
```

If this returns documents but browser doesn't show them → **Frontend issue confirmed**

---

## Decision Tree

```
Skeleton loaders showing?
│
├─ Network tab: No GET /api/v1/documents?
│  └─ Frontend not calling API
│     ├─ Check component mounting
│     ├─ Check useEffect dependencies
│     └─ Check route configuration
│
├─ Network tab: GET /api/v1/documents with 200?
│  ├─ Response body empty []?
│  │  └─ Backend filtering issue (unlikely, API test showed data)
│  │
│  └─ Response has documents?
│     ├─ Console errors?
│     │  └─ Data structure mismatch or rendering bug
│     │
│     └─ No console errors?
│        ├─ React DevTools: isLoading=true?
│        │  └─ Loading state stuck
│        │
│        └─ React DevTools: documents populated?
│           └─ Rendering logic bug (data exists but not displayed)
```

---

## Share This Information

Please provide:

1. ✅ Network tab status (screenshot or description)
2. ✅ Console output from debug script
3. ✅ Any red console errors
4. ✅ Current page URL showing skeleton loaders
5. ✅ React DevTools state (if available)

With this info, we can pinpoint the exact issue and provide a fix.

---

## Current Known State

**Backend (from log analysis):**
- ✅ Document uploaded: id=27, "MSFT_FY26Q1_10Q.docx"
- ✅ Chunks: 2344
- ✅ Status: {"state": "ready"}
- ✅ API endpoint working: GET /api/v1/documents returns document
- ✅ No backend errors

**Frontend (needs investigation):**
- ❓ Unknown: Is API being called?
- ❓ Unknown: What does browser console show?
- ❓ Unknown: React component state?
- ❌ Known: Skeleton loaders visible instead of documents

**Next:** Capture frontend browser data to complete diagnosis.
