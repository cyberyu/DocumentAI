# SurfSense Integration Guide: Adapter Architecture

## Overview

**The adapter architecture integrates seamlessly with your existing SurfSense deployment.** You're already using:
- **SurfSense Web UI** (`ghcr.io/modsetter/surfsense-web`) - No changes needed
- **SurfSense Backend** (`ghcr.io/modsetter/surfsense-backend`) - Already has DeepAgents framework

The adapters are **mounted as volume overlays** into the SurfSense backend container, extending it with configurable RAG capabilities without modifying the core SurfSense codebase.

---

## Architecture: How Adapters Integrate with SurfSense

### Current SurfSense Stack

```
┌─────────────────────────────────────────────────────────────┐
│                   SurfSense Web UI                          │
│         (ghcr.io/modsetter/surfsense-web)                   │
│   - Document upload interface                               │
│   - Chat UI with agents                                     │
│   - Document management                                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP API
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              SurfSense Backend (Flask/FastAPI)              │
│         (ghcr.io/modsetter/surfsense-backend)               │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │         EXISTING DeepAgents Framework               │  │
│   │  - chat_deepagent.py (agent orchestration)          │  │
│   │  - KnowledgeBaseSearchMiddleware (RAG integration)  │  │
│   │  - Memory injection, tool use, reasoning            │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │    NEW: Adapter Layer (Volume-Mounted Files)        │  │
│   │  ┌───────────────────────────────────────────────┐  │  │
│   │  │  adapter_base_classes.py                      │  │  │
│   │  │  adapter_dataflow_models.py                   │  │  │
│   │  │  adapter_examples.py                          │  │  │
│   │  │  rag_config_manager.py                        │  │  │
│   │  │  rag_orchestrator.py                          │  │  │
│   │  └───────────────────────────────────────────────┘  │  │
│   │                                                       │  │
│   │  Used by existing code:                              │  │
│   │  - document_chunker.py → ChunkingAdapter            │  │
│   │  - chunks_hybrid_search.py → RetrievalAdapter       │  │
│   └─────────────────────────────────────────────────────┘  │
└────────────┬────────────────────────────────────────────────┘
             │
     ┌───────┴───────┬───────────────┬──────────────┐
     ▼               ▼               ▼              ▼
┌──────────┐  ┌──────────────┐  ┌─────────┐  ┌──────────┐
│PostgreSQL│  │  OpenSearch  │  │  Redis  │  │  Celery  │
│(app data)│  │ (vectors+BM25)│  │ (cache) │  │ (workers)│
└──────────┘  └──────────────┘  └─────────┘  └──────────┘
```

### Integration Points

| SurfSense Component | Adapter Integration | How It Works |
|---------------------|---------------------|--------------|
| **Document Upload** | ETLAdapter | When user uploads PDF/DOCX, SurfSense calls `ETLAdapter.extract_from_bytes()` |
| **Document Chunking** | ChunkingAdapter | `document_chunker.py` replaced with adapter-based implementation |
| **Embedding Generation** | EmbeddingAdapter | SurfSense chooses OpenAI/FastEmbed/Voyage via config |
| **Vector Storage** | StorageAdapter (OpenSearch) | `chunks_hybrid_search.py` uses `OpenSearchAdapter` |
| **Query Retrieval** | RetrievalAdapter | DeepAgents middleware calls `retriever.search()` |
| **Reranking** | RerankingAdapter | Optional refinement before LLM context assembly |
| **Agent Framework** | Uses adapters transparently | `KnowledgeBaseSearchMiddleware` gets results via adapters |

---

## Deployment: Single Machine Configuration

### 1. Docker Compose Stack

**File**: [`docker-compose-adaptable-rag.yml`](./docker-compose-adaptable-rag.yml)

```bash
# Start entire stack on single machine
docker-compose -f docker-compose-adaptable-rag.yml up -d

# Services running:
# - opensearch:9200        (Vector DB with k-NN + BM25)
# - opensearch-dashboards:5601  (Monitoring UI)
# - db:5432                (PostgreSQL for app data)
# - redis:6379             (Cache & Celery broker)
# - backend:8929           (SurfSense API with adapters)
# - celery_worker          (Background tasks)
# - celery_beat            (Scheduled tasks)
# - frontend:3929          (SurfSense Web UI)
# - zero-cache:5929        (Real-time sync)
# - searxng                (Search engine, optional)
```

**All services run on ONE machine**—no distributed deployment required.

### 2. Volume Mounts: Adapter Files into SurfSense Backend

```yaml
# docker-compose-adaptable-rag.yml (lines 109-125)
backend:
  image: ghcr.io/modsetter/surfsense-backend:latest
  volumes:
    # ── Adapter Files (Extend SurfSense with adapters) ──
    - ./rag_config_schema.yaml:/app/app/config/rag_config_schema.yaml:ro
    - ./rag_config_manager.py:/app/app/rag_config_manager.py:ro
    - ./rag_orchestrator.py:/app/app/rag_orchestrator.py:ro
    - ./adapter_base_classes.py:/app/app/adapters/adapter_base_classes.py:ro
    - ./adapter_dataflow_models.py:/app/app/adapters/adapter_dataflow_models.py:ro
    - ./adapter_examples.py:/app/app/adapters/adapter_examples.py:ro
    
    # ── Patched Components (Use adapters) ──
    - ./document_chunker_patch.py:/app/app/indexing_pipeline/document_chunker.py:ro
    - ./chunks_hybrid_search_patched.py:/app/app/retriever/chunks_hybrid_search.py:ro
```

**How it works**:
1. SurfSense backend container starts with standard image
2. Adapter files are mounted into container from host machine
3. Patched components (`document_chunker_patch.py`, `chunks_hybrid_search_patched.py`) use adapters
4. No need to rebuild SurfSense image—just mount files!

### 3. Configuration: Environment Variables

```bash
# .env file (single machine configuration)

# ── RAG Configuration Profile ──
RAG_ACTIVE_PROFILE=production          # or: production_local, production_hybrid

# ── ETL Provider (File Processing) ──
ETL_PROVIDER=mineru                    # Options: mineru, docling, unstructured
ETL_DETECT_TABLES=true
ETL_DETECT_FORMULAS=true

# ── Embedding Provider ──
# Option 1: OpenAI (remote API, best quality)
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072

# Option 2: FastEmbed (local, free, CPU/GPU)
# EMBEDDING_PROVIDER=fastembed
# EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
# EMBEDDING_DIMENSIONS=1024

# Option 3: Voyage (remote API, domain-specific)
# EMBEDDING_PROVIDER=voyage
# VOYAGE_API_KEY=pa-...
# EMBEDDING_MODEL=voyage-finance-2
# EMBEDDING_DIMENSIONS=1024

# ── Storage (Vector DB) ──
OPENSEARCH_HOSTS=http://opensearch:9200    # Local Docker service
OPENSEARCH_INDEX_PREFIX=surfsense

# ── Retrieval Strategy ──
RETRIEVAL_MODE=hybrid                  # Options: hybrid, vector_only, bm25_only
RETRIEVAL_TOP_K=20
RETRIEVAL_RRF_K=60

# ── Reranking ──
RERANKER_ENABLED=true
RERANKER_PROVIDER=flashrank            # Options: flashrank, cohere, voyage
# COHERE_API_KEY=...                   # If using Cohere reranker

# ── Database (App Data) ──
DATABASE_URL=postgresql+asyncpg://surfsense:surfsense@db:5432/surfsense

# ── Ports ──
BACKEND_PORT=8929
FRONTEND_PORT=3929
```

**All configuration in ONE .env file on ONE machine.**

---

## How Existing SurfSense Code Uses Adapters

### Example 1: Document Upload (ETL)

**Before** (hardcoded Docling):
```python
# app/indexing_pipeline/document_extractor.py
from docling import DocumentConverter

async def extract_document(file_bytes: bytes, filename: str):
    converter = DocumentConverter()
    result = converter.convert_bytes(file_bytes)
    return result.markdown
```

**After** (adapter-based, configurable):
```python
# app/indexing_pipeline/document_extractor.py
from app.adapters.adapter_base_classes import AdapterFactory
from app.config import settings

async def extract_document(file_bytes: bytes, filename: str):
    # Get ETL adapter based on config (mineru, docling, or unstructured)
    etl_adapter = AdapterFactory.create_etl(
        provider=settings.ETL_PROVIDER,
        config=settings.ETL_CONFIG
    )
    
    # Extract using configured adapter
    raw_document = etl_adapter.extract_from_bytes(file_bytes, filename)
    return raw_document.content  # Returns markdown
```

**Result**: 
- ✅ Switch ETL provider via `ETL_PROVIDER=mineru` environment variable
- ✅ No code changes needed
- ✅ Same API for all providers (MinerU, Docling, Unstructured)

### Example 2: Document Chunking

**Before** (fixed chunk size, basic splitting):
```python
# app/indexing_pipeline/document_chunker.py
def chunk_document(content: str) -> List[str]:
    chunk_size = 512
    chunks = []
    for i in range(0, len(content), chunk_size):
        chunks.append(content[i:i+chunk_size])
    return chunks
```

**After** (adapter-based, configurable strategy):
```python
# document_chunker_patch.py (mounted as volume overlay)
from app.adapters.adapter_base_classes import AdapterFactory
from app.adapters.adapter_dataflow_models import RawDocument, Chunk
from app.config import settings

def chunk_document(content: str, doc_id: str) -> List[Chunk]:
    # Create RawDocument
    raw_doc = RawDocument(
        doc_id=doc_id,
        content=content,
        source_path="uploaded"
    )
    
    # Get chunking adapter from config
    chunker = AdapterFactory.create_chunking(
        strategy=settings.CHUNKING_STRATEGY,  # "hybrid_sandwich", "recursive", etc.
        config={
            "chunk_size": settings.CHUNKER_CHUNK_SIZE,
            "overlap": settings.CHUNKER_OVERLAP
        }
    )
    
    # Chunk using configured strategy
    chunks = chunker.chunk_document(raw_doc)
    return chunks
```

**Result**:
- ✅ Switch chunking strategy via `CHUNKING_STRATEGY=hybrid_sandwich`
- ✅ Adjust chunk size via `CHUNKER_CHUNK_SIZE=256`
- ✅ Chunks include context (prefix/suffix) automatically

### Example 3: Knowledge Base Search (DeepAgents Integration)

**Before** (hardcoded PostgreSQL + pgvector):
```python
# app/agents/new_chat/middlewares/knowledge_base_search.py
async def search_knowledge_base(query: str, user_id: int):
    # Generate embedding
    embedding = await openai.embeddings.create(input=query)
    
    # Raw SQL query to pgvector
    results = await db.execute(
        "SELECT * FROM chunks WHERE user_id = $1 "
        "ORDER BY embedding <-> $2 LIMIT 10",
        user_id, embedding
    )
    return results
```

**After** (adapter-based, supports OpenSearch hybrid search):
```python
# chunks_hybrid_search_patched.py (mounted as volume overlay)
from app.adapters.adapter_base_classes import AdapterFactory
from app.adapters.adapter_dataflow_models import Query, RetrievalContext
from app.config import settings

async def search_knowledge_base(query: str, user_id: int) -> RetrievalContext:
    # Create Query object
    query_obj = Query(
        text=query,
        user_id=str(user_id),
        filters={"user_id": user_id}
    )
    
    # Get embedding adapter
    embedding = AdapterFactory.create_embedding(
        provider=settings.EMBEDDING_PROVIDER,
        config={"api_key": settings.OPENAI_API_KEY, "model": settings.EMBEDDING_MODEL}
    )
    
    # Get storage adapter
    storage = AdapterFactory.create_storage(
        provider="opensearch",
        config={"hosts": [settings.OPENSEARCH_HOSTS]}
    )
    
    # Get retrieval adapter (hybrid RRF by default)
    retriever = AdapterFactory.create_retrieval(
        strategy=settings.RETRIEVAL_MODE,  # "hybrid_rrf", "vector_only", "bm25_only"
        config={},
        storage=storage,
        embedding=embedding
    )
    
    # Search
    results = retriever.search(query_obj, top_k=settings.RETRIEVAL_TOP_K)
    
    # Optional reranking
    if settings.RERANKER_ENABLED:
        reranker = AdapterFactory.create_reranking(
            provider=settings.RERANKER_PROVIDER,
            config={}
        )
        reranked = reranker.rerank(query_obj, results, top_k=8)
        results = [r.search_result for r in reranked]
    
    # Build context
    context = RetrievalContext(
        query=query_obj,
        results=results,
        total_latency_ms=...,
        config_snapshot={"profile": settings.RAG_ACTIVE_PROFILE}
    )
    
    return context
```

**Result**:
- ✅ Hybrid search (vector + BM25) instead of pure vector
- ✅ Configurable embedding provider (OpenAI, FastEmbed, Voyage)
- ✅ Optional reranking for better results
- ✅ Cost and latency tracking built-in

### Example 4: DeepAgents Framework Integration

**SurfSense DeepAgents** already has:
- `create_surfsense_deep_agent()` - Agent factory
- `KnowledgeBaseSearchMiddleware` - RAG integration point
- Tool use, memory injection, reasoning

**Adapter integration** (transparent to DeepAgents):

```python
# app/agents/new_chat/chat_deepagent.py (existing SurfSense code)
from app.agents.new_chat.middlewares.knowledge_base_search import search_knowledge_base

async def process_user_query(query: str, user_id: int):
    # Create agent
    agent = create_surfsense_deep_agent(user_id=user_id)
    
    # Search knowledge base (NOW uses adapters transparently)
    context = await search_knowledge_base(query, user_id)
    
    # Format context for agent
    context_str = context.format_for_llm(max_chunks=5)
    
    # Agent processes with context
    response = await agent.process(
        query=query,
        context=context_str,
        citations=context.get_citations()
    )
    
    return response
```

**Key insight**: DeepAgents middleware calls `search_knowledge_base()`, which now uses adapters internally. **No changes to DeepAgents framework needed**—adapters are transparent.

---

## Configuration Profiles: Switch Behavior on Single Machine

### Profile 1: All Local (No API Costs)

```yaml
# rag_config_schema.yaml
profiles:
  production_local:
    etl:
      provider: mineru          # Local GPU processing
    embedding:
      provider: fastembed       # Local CPU/GPU inference
      model: BAAI/bge-large-en-v1.5
      dimensions: 1024
    storage:
      provider: opensearch      # Local Docker container
    retrieval:
      strategy: hybrid_rrf      # Vector + BM25
    reranking:
      enabled: true
      provider: flashrank       # Local inference
```

**Usage**:
```bash
export RAG_ACTIVE_PROFILE=production_local
docker-compose up
```

**Machine requirements**: 16GB RAM, 8 cores, optional GPU  
**Cost per query**: $0.00 (100% local!)

### Profile 2: Hybrid (Best Quality + Reasonable Cost)

```yaml
profiles:
  production_hybrid:
    etl:
      provider: mineru          # Local GPU
    embedding:
      provider: openai          # Remote API
      model: text-embedding-3-large
      dimensions: 3072
    storage:
      provider: opensearch      # Local Docker
    retrieval:
      strategy: hybrid_rrf
    reranking:
      enabled: true
      provider: flashrank       # Local inference
```

**Usage**:
```bash
export RAG_ACTIVE_PROFILE=production_hybrid
export OPENAI_API_KEY=sk-...
docker-compose up
```

**Cost per query**: ~$0.008 (only embedding API calls)  
**Machine requirements**: 16GB RAM, 8 cores, optional GPU

### Profile 3: Cloud-Heavy (Minimal Machine Requirements)

```yaml
profiles:
  production_cloud:
    etl:
      provider: unstructured    # Remote API
    embedding:
      provider: openai          # Remote API
    storage:
      provider: opensearch      # Local Docker (or Qdrant Cloud)
    retrieval:
      strategy: hybrid_rrf
    reranking:
      enabled: true
      provider: cohere          # Remote API
```

**Usage**:
```bash
export RAG_ACTIVE_PROFILE=production_cloud
export OPENAI_API_KEY=sk-...
export COHERE_API_KEY=...
export UNSTRUCTURED_API_KEY=...
docker-compose up
```

**Cost per query**: ~$0.015 (ETL + embedding + reranking APIs)  
**Machine requirements**: 4GB RAM, 4 cores (minimal)

---

## Step-by-Step: Deploy on Single Machine

### Prerequisites

- Docker & Docker Compose installed
- 16GB RAM recommended (8GB minimum for cloud profile)
- Optional: NVIDIA GPU for local ETL/embedding

### Step 1: Clone and Configure

```bash
cd /mnt/ssd1/projects/DocumentAI

# Copy environment template
cp .env.adaptable-rag .env

# Edit configuration
nano .env
```

**Key settings to configure**:
```bash
# Choose profile
RAG_ACTIVE_PROFILE=production_hybrid

# API keys (if using remote providers)
OPENAI_API_KEY=sk-...
COHERE_API_KEY=...
VOYAGE_API_KEY=...

# Ports (adjust if needed)
BACKEND_PORT=8929
FRONTEND_PORT=3929
```

### Step 2: Start Services

```bash
# Start all services (single command)
docker-compose -f docker-compose-adaptable-rag.yml up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f backend
```

**Services starting**:
- OpenSearch: ~60 seconds (building indices)
- PostgreSQL: ~10 seconds
- Redis: ~5 seconds
- Backend: ~30 seconds (loading adapters)
- Frontend: ~20 seconds

### Step 3: Verify Installation

```bash
# Test OpenSearch
curl http://localhost:9200/_cluster/health
# Expected: {"status":"green","number_of_nodes":1,...}

# Test Backend
curl http://localhost:8929/health
# Expected: {"status":"healthy","adapters_loaded":true,...}

# Test Frontend
curl http://localhost:3929
# Expected: HTML (SurfSense UI)
```

### Step 4: Access UI

**Open browser**: `http://localhost:3929`

**You'll see the standard SurfSense UI**:
- Document upload
- Chat interface
- Settings

**Behind the scenes**, the adapter architecture is now handling:
- ✅ Multi-format document extraction (PDF, DOCX, HTML via adapters)
- ✅ Configurable chunking strategy (hybrid_sandwich by default)
- ✅ Flexible embedding provider (OpenAI, FastEmbed, or Voyage)
- ✅ Hybrid search (vector + BM25 via OpenSearch)
- ✅ Optional reranking (FlashRank or Cohere)

### Step 5: Upload a Document

1. **Click "Upload Document"** in SurfSense UI
2. **Select PDF/DOCX** (e.g., financial report)
3. **Watch processing**:
   - ETL adapter extracts content (MinerU detects tables)
   - Chunker creates 256-token chunks with context
   - Embedding adapter generates vectors (OpenAI 3K dims)
   - Storage adapter indexes to OpenSearch (k-NN + BM25)
4. **Ask a question**: "What was the revenue in Q1?"
5. **See results**:
   - Retrieval adapter searches (hybrid RRF)
   - Reranking adapter refines results (FlashRank)
   - DeepAgent generates answer with citations

**All adapter-driven, all configurable, all on one machine.**

---

## Switching Configurations Without Restart

### Dynamic Adapter Loading

```python
# In SurfSense backend code (e.g., API endpoint)
from app.adapters.adapter_base_classes import AdapterFactory

@app.post("/admin/switch-embedding-provider")
async def switch_embedding_provider(provider: str, model: str):
    # Create new adapter on the fly
    new_adapter = AdapterFactory.create_embedding(
        provider=provider,
        config={"model": model, "api_key": os.getenv(f"{provider.upper()}_API_KEY")}
    )
    
    # Update global adapter registry
    app.state.embedding_adapter = new_adapter
    
    return {"status": "switched", "provider": provider, "model": model}
```

**Usage**:
```bash
# Switch from OpenAI to FastEmbed without restart
curl -X POST http://localhost:8929/admin/switch-embedding-provider \
  -H "Content-Type: application/json" \
  -d '{"provider": "fastembed", "model": "BAAI/bge-large-en-v1.5"}'
```

**Result**: Next document upload uses FastEmbed instead of OpenAI—zero downtime.

---

## Monitoring & Debugging

### View Adapter Metrics

```bash
# Check which adapters are active
curl http://localhost:8929/admin/adapter-status
# Response:
# {
#   "etl": {"provider": "mineru", "last_used": "2026-05-03T10:45:23Z"},
#   "embedding": {"provider": "openai", "model": "text-embedding-3-large", "cost_total": 0.034},
#   "storage": {"provider": "opensearch", "index_count": 1, "chunk_count": 1234},
#   "retrieval": {"strategy": "hybrid_rrf", "avg_latency_ms": 145},
#   "reranking": {"provider": "flashrank", "enabled": true}
# }
```

### View OpenSearch Indices

```bash
# Access OpenSearch Dashboards
open http://localhost:5601

# Or use curl
curl http://localhost:9200/_cat/indices?v
# Expected:
# health status index           docs.count
# green  open   surfsense_chunks    1234
```

### View Logs with Adapter Context

```bash
docker-compose logs -f backend | grep -i adapter
# Example output:
# [2026-05-03 10:45:23] INFO: ETL adapter 'mineru' processing document.pdf
# [2026-05-03 10:45:28] INFO: Embedding adapter 'openai' generated 120 embeddings, cost=$0.016
# [2026-05-03 10:45:29] INFO: Storage adapter 'opensearch' indexed 120 chunks to surfsense_chunks
# [2026-05-03 10:45:35] INFO: Retrieval adapter 'hybrid_rrf' found 20 results in 145ms
# [2026-05-03 10:45:36] INFO: Reranking adapter 'flashrank' refined to 8 results in 45ms
```

---

## Summary: Single Machine, Full Configurability

✅ **Reuses SurfSense UI**: Standard `ghcr.io/modsetter/surfsense-web` image, no changes  
✅ **Reuses SurfSense Backend**: Standard `ghcr.io/modsetter/surfsense-backend` image, adapters mounted as volumes  
✅ **Reuses DeepAgents Framework**: Existing agentic framework, now uses adapters for RAG  
✅ **Single Machine Deployment**: Docker Compose runs all services (OpenSearch, PostgreSQL, Redis, backend, frontend)  
✅ **Runtime Configuration**: Switch adapters via environment variables, no code changes  
✅ **Profile-Based**: Choose `production_local` (all local), `production_hybrid` (mixed), or `production_cloud` (API-heavy)  
✅ **Zero UI Changes**: Users see same SurfSense interface, better RAG under the hood  

**The adapter architecture extends SurfSense with configurable RAG capabilities while keeping your existing UI and backend intact.**

---

## Next Steps

1. **Start Stack**: `docker-compose -f docker-compose-adaptable-rag.yml up -d`
2. **Access UI**: `http://localhost:3929`
3. **Upload Test Document**: See adapters in action
4. **Check Metrics**: `curl http://localhost:8929/admin/adapter-status`
5. **Experiment with Profiles**: Change `RAG_ACTIVE_PROFILE` in `.env`, restart
6. **Monitor Performance**: OpenSearch Dashboards at `http://localhost:5601`

**All on one machine, all configurable, all integrated with your existing SurfSense setup.**
