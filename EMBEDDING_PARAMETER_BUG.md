# Multi-Embedding Parameter Bug

## Objective
Add support for uploading documents with multiple embedding models (e.g., 3 models simultaneously) to generate embeddings from each model and store them in OpenSearch.

## Current Status: BLOCKED

### The Problem
The `embedding_models` form parameter is **not being received** by the backend endpoint, causing the multi-embedding feature to fail.

**Symptom**: When uploading a document with `embedding_models=["model1", "model2", "model3"]`, the backend receives `None` or doesn't process the parameter, resulting in default single-embedding behavior.

## What Was Implemented

### 1. Backend Route (`documents_routes.py`)
- Added `embedding_models: Optional[str] = Form(default=None)` parameter to `/documents/fileupload` endpoint
- Added parsing logic to convert JSON string array to `embedding_config` dict:
  ```python
  # Lines 154-180 in documents_routes.py
  if embedding_models:
      parsed_models = json.loads(embedding_models)
      if len(parsed_models) > 1:
          embedding_config = {"mode": "multi", "model_keys": parsed_models}
  ```
- Debug logging added at line 160: `logger.info(f"[DEBUG] embedding_models received: {repr(embedding_models)}")`

### 2. Indexing Pipeline (`indexing_pipeline_service.py`)
- Added `embedding_config` parameter to `index_document_pipeline` function
- Threads through to multi-embedding processor
- Debug logging at line 400: `logger.info(f"[indexing] Received embedding_config: {embedding_config}")`

### 3. Multi-Embedding Processor (`multi_embedding_processor.py`)
- Created processor to generate embeddings from multiple models
- Stores each embedding with model-specific index suffix

## What We Tried

### Attempt 1: Volume Mounting
- Mounted fixed files via docker-compose volumes
- **Result**: Import errors (`ModuleNotFoundError: No module named 'app.storage'`)

### Attempt 2: FastAPI Form Syntax Fix
- Fixed invalid syntax: `Form(None)` → `Form(default=None)`
- Added `from typing import Optional`
- **Result**: Backend crashes or doesn't start properly, connection reset on upload

### Attempt 3: Docker Image Rebuild
- Rebuilt backend image with fixes: `docker build -t documentai-backend:latest`
- **Result**: Same issues persist

### Attempt 4: Storage Module Mount
- Added `opensearch_chunk_storage.py` volume mount to fix import errors
- **Result**: Backend still unhealthy, database migration errors

## Current Issues

### 1. Backend Won't Start Properly
```
sqlalchemy.exc.ProgrammingError: relation "agent_action_log" already exists
```
Backend fails health check and crashes when receiving upload requests.

### 2. No Debug Logs Appearing
Despite adding debug logging at line 160 in `documents_routes.py`:
```bash
grep "\[DEBUG\] embedding_models" backend_logs  # No output
```
This suggests either:
- Endpoint not being hit
- Logging not configured properly
- Request not reaching the route handler

### 3. Connection Reset on Upload
```
curl: (56) Recv failure: Connection reset by peer
```
Backend crashes when receiving file upload with `embedding_models` parameter.

## Test Case

### Upload Command
```bash
TOKEN=$(curl -s -X POST http://localhost:8929/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=shee.yu@gmail.com&password=PASSWORD" | jq -r .access_token)

MODELS='["fastembed/bge-base-en-v1.5","sentence-transformers/all-MiniLM-L6-v2","BAAI/bge-small-en-v1.5"]'

curl -X POST http://localhost:8929/api/v1/documents/fileupload \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@MSFT_FY26Q1_10Q.docx" \
  -F "search_space_id=2" \
  -F "embedding_models=$MODELS"
```

**Expected**: Backend receives 3 model names, generates 3 embeddings per chunk  
**Actual**: Backend crashes with connection reset

## Files Modified

1. **source/SurfSense/surfsense_backend/app/routes/documents_routes.py**
   - Lines 4, 128, 159-180: Added Optional import, embedding_models parameter, parsing logic

2. **source/SurfSense/surfsense_backend/app/indexing_pipeline/indexing_pipeline_service.py**
   - Added embedding_config parameter threading, debug logging

3. **docker-compose-adaptable-rag.yml**
   - Added volume mounts for above files + storage module
   - Lines 120-125, 256-258

4. **multi_embedding_processor.py** (created)
   - Multi-embedding generation logic

5. **opensearch_multi_embedding_storage.py** (created)
   - Storage layer for multi-embeddings

## Root Cause Hypothesis

### Theory 1: FastAPI Form Handling Issue
The backend may not properly handle optional Form parameters in this version of FastAPI. The volume-mounted file might have syntax errors or incompatibilities.

### Theory 2: Backend Build State Mismatch
The Docker image rebuild may not have properly incorporated the code changes, causing runtime mismatches between mounted volumes and baked-in code.

### Theory 3: Database Migration Conflict
Backend startup fails due to migration errors, preventing it from ever reaching a state where it can handle requests.

## Next Steps (For Future Debugging)

1. **Fix Backend Startup**
   - Resolve database migration conflict (agent_action_log table)
   - Ensure backend reaches healthy state before testing

2. **Simplify Test**
   - Test with single model first: `embedding_models='["fastembed/bge-base-en-v1.5"]'`
   - Verify parameter is received before testing multi-model

3. **Direct Backend Test**
   - Exec into backend container and test route handler directly
   - Bypass Docker networking issues

4. **Check FastAPI Docs**
   - Visit `http://localhost:8929/docs` and use Swagger UI to test endpoint
   - See what form fields FastAPI expects

5. **Rebuild Clean**
   - Remove all volume mounts
   - Bake all code changes into Docker image
   - Test with fresh build

## Time Spent
Approximately 2-3 hours debugging without resolving core issue.

## Conclusion
The multi-embedding feature cannot be tested until the backend startup and form parameter reception issues are resolved. The problem appears to be at the infrastructure/deployment level rather than the business logic level.
