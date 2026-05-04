# Upload Monitoring Quick Reference
**Keep this open during upload test**

## 🚀 Pre-Upload Setup (2 minutes)

```bash
# Terminal 1 - Backend (MUST HAVE)
docker logs backend -f | tee upload-backend.log

# Terminal 2 - Database Status (MUST HAVE)
watch -n 2 'docker exec postgres psql -U user -d dbname -c "SELECT id, file_name, status FROM documents ORDER BY created_at DESC LIMIT 3;" 2>/dev/null'

# Browser (MUST HAVE)
# F12 → Network tab → Check "Preserve log"
# F12 → Console tab → Watch for errors
```

---

## 👀 What to Watch

### Browser Network Tab
```
✓ POST /api/v1/upload → 200 OK
✓ POST /api/v1/documents → 200 OK
✓ GET /api/v1/documents → Returns array with new doc
✗ Any 4xx or 5xx errors
```

### Backend Log
```
✓ "Processing document: <filename>"
✓ "Creating chunks"
✓ "Document processed successfully"
✓ "status: completed"
✗ "ERROR" or "Exception" or "Failed"
```

### Database Watch
```
✓ Row appears with status='processing'
✓ Status changes to 'completed' (within 60 sec)
✗ Stays 'processing' forever
✗ Changes to 'failed'
```

### Browser Console
```
✓ No errors
✗ "Uncaught TypeError"
✗ "Cannot read property"
✗ "401" or "403"
```

---

## ⏱️ Timeline Expectations

```
00:00  Click upload
00:01  POST upload → 200 OK
00:02  Document appears in DB (status='processing')
00:05  Backend: "Creating chunks..."
00:10  Status → 'completed'
00:11  Frontend: GET /documents
00:12  UI updates (SUCCESS) or shows skeletons (FAIL)
```

---

## 🎯 Success Criteria

- [ ] Document in database with status='completed'
- [ ] Chunks count > 0
- [ ] GET /api/v1/documents returns new document
- [ ] UI shows document (not skeleton loaders)

---

## 🔴 Stop & Investigate If:

1. **Status stuck at 'processing' for >60 seconds**
2. **Console shows errors**
3. **Network requests fail (red in DevTools)**
4. **Skeleton loaders persist for >30 seconds after upload**

---

## 📸 Capture These

- [ ] Screenshot: Network tab with all requests
- [ ] Screenshot: Console (if errors present)
- [ ] Screenshot: Final UI state (skeletons or docs)
- [ ] Save: Terminal backend log (Ctrl+C, then save file)

---

## 🐛 Quick Debug Commands

```bash
# Check document status
docker exec postgres psql -U user -d dbname -c \
  "SELECT id, file_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT 1;"

# Check chunks
docker exec postgres psql -U user -d dbname -c \
  "SELECT COUNT(*) FROM document_chunks WHERE document_id=(SELECT MAX(id) FROM documents);"

# Test API directly (get JWT from browser cookies first)
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer YOUR_JWT" | jq .
```

---

## 📋 Post-Upload Checklist

After upload completes (success or failure):

```bash
# 1. Save backend log
# Ctrl+C in Terminal 1, log saved to upload-backend.log

# 2. Get final DB state
docker exec postgres psql -U user -d dbname -c \
  "SELECT * FROM documents ORDER BY created_at DESC LIMIT 1;" \
  > final-document-state.txt

# 3. Get API response
TOKEN="<from browser>"
curl "http://localhost:8929/api/v1/documents" \
  -H "Authorization: Bearer $TOKEN" | jq . > api-response.json

# 4. Export Network HAR
# DevTools → Network → Right-click → Save all as HAR

# 5. Create summary
echo "Upload Status: SUCCESS/FAILURE
Document created: YES/NO
Status in DB: <status>
UI shows doc: YES/NO
Problem: <describe issue>" > upload-summary.txt
```

---

## 🎁 Package for Analysis

```bash
tar -czf upload-debug.tar.gz \
  upload-backend.log \
  final-document-state.txt \
  api-response.json \
  upload-summary.txt \
  network-capture.har
```

---

**Ready? Start monitoring, then upload the document!**
