# Document Upload Debug Session - README

## Purpose
Capture comprehensive logs during document upload to debug why documents show as skeleton loaders instead of displaying properly.

## Quick Start

### On Machine with Docker (where you'll upload):

**Step 1: Setup monitoring** (2 minutes)
```bash
cd /mnt/ssd1/projects/DocumentAI
./setup-upload-monitoring.sh
```

This creates a session directory and shows you 4 commands to run in separate terminals.

**Step 2: Open browser and prepare** (1 minute)
1. Open http://localhost:3929
2. Press F12 (DevTools)
3. Network tab → Check "Preserve log" 
4. Console tab → Keep it visible

**Step 3: Start all monitoring terminals** (1 minute)
Open the 4 terminal commands shown by setup script:
- Terminal 1: Backend logs
- Terminal 2: Frontend logs  
- Terminal 3: PostgreSQL logs
- Terminal 4: Database watch (auto-refreshing)

**Step 4: Upload document**
- Click upload button
- Select file (e.g., MSFT_FY26Q1_10Q.pdf)
- Watch all terminals and browser DevTools
- **Don't close anything until complete!**

**Step 5: Collect data** (after upload completes or fails)
```bash
cd upload-debug-[TIMESTAMP]
./collect-data.sh
```

This will gather all logs, database snapshots, and API responses.

**Step 6: Package for analysis**
```bash
tar -czf upload-debug.tar.gz .
```

---

## Files Explained

### Setup & Execution
- **`setup-upload-monitoring.sh`** - One-time setup, creates session directory
- **`UPLOAD_MONITOR_QUICK_REF.md`** - Keep this open during upload (cheat sheet)
- **`UPLOAD_LOG_CAPTURE_GUIDE.md`** - Detailed guide (read before starting)

### Generated During Session
- **`backend.log`** - All backend output during upload
- **`frontend.log`** - Frontend container logs
- **`postgres.log`** - Database logs
- **`api-documents.json`** - GET /documents API response
- **`database-documents.txt`** - Documents table snapshot
- **`database-chunks.txt`** - Chunk counts per document
- **`SUMMARY.txt`** - Automated analysis summary

---

## What We're Looking For

### The Mystery
Documents upload successfully to database (2344 chunks created), but frontend shows skeleton loaders instead of document list.

### Possible Root Causes
1. **API returns empty array** - Document not linked to user/search-space
2. **API returns wrong structure** - Frontend expects array, gets nested object
3. **Frontend doesn't call API** - Routing or component mounting issue
4. **Loading state stuck** - isLoading never set to false
5. **Document status wrong** - Still 'processing' instead of 'completed'

### Key Evidence to Capture
- ✅ Does backend process and mark document as 'completed'?
- ✅ Does frontend call GET /api/v1/documents after upload?
- ✅ What does that API call return?
- ✅ Are there JavaScript errors in console?
- ✅ Is document linked to correct search_space_id and user_id?

---

## Expected Timeline

```
00:00 - Click upload button
00:01 - POST /api/v1/upload → 200 OK
00:03 - Document appears in DB (status='processing')
00:05 - Backend creates chunks (watch backend.log)
00:10 - Status changes to 'completed' (watch Terminal 4)
00:11 - Frontend calls GET /api/v1/documents (watch Network tab)
00:12 - UI updates (SUCCESS) or shows skeletons (FAILURE)
```

Total time: ~12 seconds for small doc, ~60 seconds for large doc

---

## During Upload - What to Watch

### Terminal 1 (Backend Log)
```
✓ "Processing document: filename.pdf"
✓ "Creating chunks for document"
✓ "Document processed successfully"
✓ "status changed to: completed"

✗ "ERROR" or "Exception"
✗ "Failed to process"
✗ "status: failed"
```

### Terminal 4 (Database Watch)
```
Before: Empty or previous documents

During:
id | filename.pdf | processing | timestamp

After:
id | filename.pdf | completed  | timestamp

✗ Status stuck at 'processing'
✗ Document doesn't appear
```

### Browser Network Tab
```
✓ POST /api/v1/upload → 200
✓ POST /api/v1/documents → 200
✓ GET /api/v1/documents → 200 (after upload)

✗ Any 4xx or 5xx responses
✗ No GET /documents call after upload
```

### Browser Console
```
✓ No errors

✗ "Uncaught TypeError"
✗ "Cannot read property"
✗ "401 Unauthorized"
```

---

## Post-Upload Verification

After upload finishes, verify:

```bash
# 1. Document in database?
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status FROM documents ORDER BY created_at DESC LIMIT 1;"

# 2. Chunks created?
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) FROM document_chunks WHERE document_id=(SELECT MAX(id) FROM documents);"

# 3. API returns document? (need JWT from browser cookies)
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer YOUR_JWT" | jq .

# 4. Does UI show it?
# Visually check browser - skeletons or actual documents?
```

---

## Success vs Failure

### ✅ Success Looks Like:
- Document in DB with status='completed'
- Chunks count > 0
- API returns array with new document
- UI shows document in list (name, date, etc.)
- No errors in any logs or console

### ❌ Failure Looks Like:
- UI shows skeleton loaders even after upload completes
- One of these is broken:
  1. Document not in DB → Backend processing failed
  2. Document in DB but status='processing' → Worker stuck
  3. Document in DB but not in API response → Data retrieval issue
  4. Document in API but not rendered → Frontend bug

---

## Troubleshooting

### "setup-upload-monitoring.sh not found"
```bash
cd /mnt/ssd1/projects/DocumentAI
ls -la setup-upload-monitoring.sh
# If missing, it should be in this directory
```

### "Permission denied" 
```bash
chmod +x setup-upload-monitoring.sh
```

### Can't connect to PostgreSQL
```bash
# Check container name
docker ps | grep postgres

# If different name, edit commands to use correct name
docker exec <postgres_container_name> psql ...
```

### Don't know database credentials
```bash
# Check docker-compose file
cat docker-compose*.yml | grep -A 5 "POSTGRES"

# Or check environment
docker exec postgres env | grep POSTGRES
```

---

## After Data Collection

Once you've run `collect-data.sh` and packaged the tarball:

1. **Review SUMMARY.txt first** - Quick overview of findings
2. **Check if documents match:**
   - Count in `database-documents.txt`
   - Count in `api-documents.json`
   - If mismatch → data retrieval issue
3. **Look for errors:**
   - `backend-errors.txt`
   - `postgres-errors.txt`
   - Browser console (screenshot)
4. **Check associations:**
   - `database-associations.txt`
   - Are documents linked to correct search_space_id?

---

## Questions These Logs Will Answer

1. **Did the upload succeed?** → Check backend.log for "processed successfully"
2. **Is document in database?** → Check database-documents.txt
3. **What status does it have?** → Look for 'completed' vs 'processing' vs 'failed'
4. **Are chunks created?** → Check database-chunks.txt
5. **Does API return it?** → Check api-documents.json
6. **Are there errors?** → Check backend-errors.txt and console
7. **Is it linked correctly?** → Check database-associations.txt
8. **Does frontend query for it?** → Check Network tab HAR file
9. **Why doesn't UI show it?** → Compare API response vs UI state

---

## Share Results

Send the upload-debug.tar.gz to the other machine where the main debugging AI is running. The tarball contains everything needed for analysis:
- All logs from backend, frontend, database
- API responses  
- Database snapshots
- Error extracts
- Automated summary

---

## Need Help?

Refer to detailed guides:
- **UPLOAD_LOG_CAPTURE_GUIDE.md** - Comprehensive step-by-step
- **UPLOAD_MONITOR_QUICK_REF.md** - Quick reference during upload
- **CUSTOM_FRONTEND_DEBUG_GUIDE.md** - Frontend-specific debugging
- **CUSTOM_FRONTEND_DEBUG_CHECKLIST.md** - Quick diagnosis checklist

---

**Ready? Run `./setup-upload-monitoring.sh` to begin!**
