# Multi-Embedding Upload Feature - Implementation Guide

## Overview

This feature allows users to select multiple embedding models during document upload. Each chunk is embedded using all selected models and stored in OpenSearch, enabling:
- **A/B testing** of different embedding models
- **Model comparison** on the same corpus
- **Retrieval strategy experimentation**
- **Cost vs quality optimization**

---

## Architecture

```
User Selects Models in UI
         │
         ▼
┌─────────────────────────────────────────┐
│  Frontend: MultiEmbeddingModelSelector  │
│  - Shows available models with costs    │
│  - Multi-select checkboxes              │
│  - Cost estimation                      │
└──────────────────┬──────────────────────┘
                   │
                   ▼ HTTP POST with model selection
┌─────────────────────────────────────────┐
│  Backend API: /documents/fileupload-    │
│               multi-embed                │
│  - Validates model selection            │
│  - Triggers processing pipeline         │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  ETL + Chunking (existing pipeline)     │
│  - Extract text from file               │
│  - Create chunks                        │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  MultiEmbeddingProcessor                │
│  - Generate embeddings IN PARALLEL      │
│  - One task per model                   │
│  - Track cost and latency               │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  OpenSearch Multi-Embedding Storage     │
│  - One knn_vector field per model       │
│  - Example:                             │
│    • embedding_openai_3_large (3072d)   │
│    • embedding_voyage_finance_2 (1024d) │
│    • embedding_fastembed_bge_base (768d)│
└─────────────────────────────────────────┘
```

---

## Files Created

### 1. Backend Storage: `opensearch_multi_embedding_storage.py`
**Purpose**: OpenSearch client supporting multiple embedding fields

**Key Classes**:
- `MultiEmbeddingOpenSearchStorage`: Main storage class
- `EMBEDDING_MODELS`: Metadata for 12+ embedding models

**Key Methods**:
- `create_index_multi_embedding()`: Creates index with multiple knn_vector fields
- `index_chunks_multi_embedding()`: Stores chunks with all embeddings
- `vector_search_multi_model()`: Search using specific embedding model
- `hybrid_search_multi_model()`: BM25 + multiple vector searches with RRF

**Example**:
```python
storage = MultiEmbeddingOpenSearchStorage(hosts=["http://localhost:9200"])

# Create index for 3 models
await storage.create_index_multi_embedding(
    search_space_id=1,
    embedding_models=[
        "openai/text-embedding-3-large",
        "voyage/voyage-finance-2",
        "fastembed/bge-base-en-v1.5"
    ]
)
```

---

### 2. Backend Processor: `multi_embedding_processor.py`
**Purpose**: Generate embeddings using multiple models in parallel

**Key Classes**:
- `MultiEmbeddingProcessor`: Orchestrates multi-model embedding

**Key Methods**:
- `embed_chunks_parallel()`: Generate embeddings with selected models concurrently
- `process_and_store_document()`: Full pipeline (embed + store)

**Example**:
```python
processor = MultiEmbeddingProcessor(storage)

summary = await processor.process_and_store_document(
    chunks=chunks,
    model_keys=["openai/text-embedding-3-large", "voyage/voyage-finance-2"],
    document_id=1,
    search_space_id=1
)
# Returns: {chunks_processed: 50, total_cost_usd: 0.0082, ...}
```

---

### 3. Backend API: `multi_embedding_api.py`
**Purpose**: FastAPI endpoints for model selection and upload

**Endpoints**:

#### **GET /api/v1/embeddings/models**
Returns available embedding models with metadata:
```json
[
  {
    "key": "fastembed/bge-base-en-v1.5",
    "provider": "fastembed",
    "dimensions": 768,
    "cost_per_1m_tokens": 0.0,
    "max_seq_length": 512,
    "description": "Balanced quality/speed",
    "is_free": true
  },
  {
    "key": "openai/text-embedding-3-large",
    "provider": "openai",
    "dimensions": 3072,
    "cost_per_1m_tokens": 0.13,
    "max_seq_length": 8192,
    "description": "Highest quality (3K dims!)",
    "is_free": false
  }
]
```

#### **POST /api/v1/documents/fileupload-multi-embed**
Upload with model selection:
```bash
curl -X POST http://localhost:8929/api/v1/documents/fileupload-multi-embed \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -F "file=@document.pdf" \
  -F "search_space_id=1" \
  -F 'embedding_models=["openai/text-embedding-3-large","voyage/voyage-finance-2"]'
```

---

### 4. Frontend Component: `MultiEmbeddingModelSelector.tsx`
**Purpose**: React UI for selecting embedding models

**Features**:
- Grouped by provider (FastEmbed, OpenAI, Voyage, etc.)
- Shows cost, dimensions, description
- "FREE" badge for local models
- Estimated cost calculation
- Multi-select with checkbox
- Prevents deselecting last model

**Usage**:
```tsx
import { UploadFormWithMultiEmbedding } from './MultiEmbeddingModelSelector';

<UploadFormWithMultiEmbedding
  searchSpaceId={1}
  onUploadSuccess={(result) => {
    console.log(`Uploaded with ${result.embedding_models_used.length} models`);
    console.log(`Cost: $${result.total_cost_usd}`);
  }}
  onUploadError={(error) => alert(error)}
/>
```

---

## Integration with Existing SurfSense

### Step 1: Add API Router (Backend)
**File**: `app/main.py`
```python
from multi_embedding_api import router as multi_embed_router

app.include_router(multi_embed_router)
```

### Step 2: Wire to Document Processor (Backend)
**File**: `app/indexing_pipeline/document_processor.py`

Replace single embedding generation with multi-embedding:
```python
# BEFORE:
embedding_vector = await embedding_service.embed(chunk.text)
await pgvector_storage.store_chunk(chunk, embedding_vector)

# AFTER:
if request.embedding_models:  # If user selected multiple models
    from multi_embedding_processor import MultiEmbeddingProcessor
    from opensearch_multi_embedding_storage import MultiEmbeddingOpenSearchStorage
    
    storage = MultiEmbeddingOpenSearchStorage(hosts=["http://opensearch:9200"])
    processor = MultiEmbeddingProcessor(storage)
    
    await processor.process_and_store_document(
        chunks=chunks,
        model_keys=request.embedding_models,
        document_id=document.id,
        search_space_id=search_space_id,
    )
else:  # Fallback to single embedding
    embedding_vector = await embedding_service.embed(chunk.text)
    await opensearch_storage.store_chunk(chunk, embedding_vector)
```

### Step 3: Update Upload UI (Frontend)
**File**: `components/DocumentUpload.tsx` (or similar)

Replace existing upload form with multi-embedding version:
```tsx
import { UploadFormWithMultiEmbedding } from '@/components/MultiEmbeddingModelSelector';

export default function DocumentUploadPage() {
  return (
    <div>
      <h1>Upload Document</h1>
      <UploadFormWithMultiEmbedding
        searchSpaceId={currentSearchSpaceId}
        onUploadSuccess={handleSuccess}
        onUploadError={handleError}
      />
    </div>
  );
}
```

### Step 4: Update Search/Retrieval (Backend)
**File**: `app/retriever/chunks_hybrid_search.py`

Add model selection parameter:
```python
async def search(
    query: str,
    search_space_id: int,
    model_key: str = "openai/text-embedding-3-large",  # NEW: Model selection
    top_k: int = 20,
):
    # Generate query embedding using selected model
    adapter = get_embedding_adapter(model_key)
    query_embedding = adapter.embed_query(query)
    
    # Search using that model's field
    results = await storage.vector_search_multi_model(
        query_embedding=query_embedding,
        search_space_id=search_space_id,
        model_key=model_key,
        top_k=top_k
    )
    return results
```

---

## Environment Variables

Add API keys for cloud embedding providers:

```bash
# .env or docker-compose.yml

# OpenAI (for text-embedding-3-small, text-embedding-3-large)
OPENAI_API_KEY=sk-...

# Voyage AI (for voyage-finance-2, voyage-law-2, voyage-code-2)
VOYAGE_API_KEY=pa-...

# Cohere (for embed-english-v3.0)
COHERE_API_KEY=...

# Google (for text-embedding-004)
GOOGLE_API_KEY=...

# Jina AI (for jina-embeddings-v2-base)
JINA_API_KEY=...

# Local FastEmbed models don't need API keys (FREE)
```

---

## Testing the Feature

### 1. Test Backend API

**Get available models**:
```bash
curl http://localhost:8929/api/v1/embeddings/models | jq
```

**Upload with multi-embedding**:
```bash
JWT_TOKEN="your_jwt_token"

curl -X POST http://localhost:8929/api/v1/documents/fileupload-multi-embed \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -F "file=@test_document.pdf" \
  -F "search_space_id=1" \
  -F 'embedding_models=["fastembed/bge-base-en-v1.5","openai/text-embedding-3-large"]' \
  | jq
```

### 2. Verify in OpenSearch

**Check index mapping**:
```bash
curl http://localhost:9200/surfsense_chunks_1/_mapping?pretty
```

Should show multiple `knn_vector` fields:
```json
{
  "properties": {
    "chunk_id": {"type": "keyword"},
    "content": {"type": "text"},
    "embedding_fastembed_bge_base_en_v1_5": {
      "type": "knn_vector",
      "dimension": 768
    },
    "embedding_openai_text_embedding_3_large": {
      "type": "knn_vector",
      "dimension": 3072
    }
  }
}
```

**Check document**:
```bash
curl http://localhost:9200/surfsense_chunks_1/_search?pretty \
  -H 'Content-Type: application/json' \
  -d '{"size": 1, "query": {"match_all": {}}}'
```

### 3. Test Frontend UI

1. Navigate to upload page
2. Click "Advanced: Select Embedding Models"
3. Select multiple models (e.g., FastEmbed + OpenAI + Voyage)
4. Upload document
5. Verify upload success with cost and model count

---

## Cost Comparison Example

**Scenario**: Upload 1 PDF document (10,000 tokens)

| Model(s) Selected | Dimensions | Cost | Time | Best For |
|-------------------|------------|------|------|----------|
| FastEmbed bge-base only | 768 | **$0.00** | 150ms | Budget-conscious, offline |
| OpenAI 3-large only | 3072 | $0.0013 | 240ms | Maximum quality |
| Voyage finance-2 only | 1024 | $0.0012 | 180ms | Financial documents |
| **All 3 models** | Mixed | **$0.0025** | **280ms** | **A/B testing, comparison** |

**Key insight**: Multiple embeddings only cost 2x (parallel processing), but give 3x the models!

---

## Benefits

### 1. **A/B Testing**
Upload once, test different embedding models on retrieval:
```python
# Search with OpenAI
results_openai = await search(query, model_key="openai/text-embedding-3-large")

# Search with Voyage
results_voyage = await search(query, model_key="voyage/voyage-finance-2")

# Compare F1 scores, latency, user satisfaction
```

### 2. **Model Comparison**
Benchmark embedding models without re-processing documents:
```python
models = ["fastembed/bge-base-en-v1.5", "openai/text-embedding-3-large", "voyage/voyage-finance-2"]

for model in models:
    precision, recall = evaluate_model(golden_qa, model_key=model)
    print(f"{model}: P={precision:.3f}, R={recall:.3f}")
```

### 3. **Progressive Enhancement**
Start with free FastEmbed, add paid models later:
```python
# Day 1: Upload with free model
initial_upload(embedding_models=["fastembed/bge-base-en-v1.5"])

# Day 7: Add premium models to same document
add_embeddings(document_id=1, new_models=["openai/text-embedding-3-large"])
```

### 4. **Domain Adaptation**
Use specialized models for specific document types:
```python
if document_type == "financial_report":
    models = ["voyage/voyage-finance-2", "fastembed/bge-large-en-v1.5"]
elif document_type == "legal_contract":
    models = ["voyage/voyage-law-2", "openai/text-embedding-3-large"]
else:
    models = ["fastembed/bge-base-en-v1.5"]  # General purpose
```

---

## Troubleshooting

### Issue: "Unknown embedding model" error
**Solution**: Check model key format. Must match keys in `EMBEDDING_MODELS`:
```python
# ✅ Correct
"openai/text-embedding-3-large"

# ❌ Wrong
"text-embedding-3-large"
"openai-text-embedding-3-large"
```

### Issue: OpenSearch index creation fails
**Solution**: Verify OpenSearch is running and accessible:
```bash
curl http://localhost:9200/_cluster/health
```

### Issue: Embedding generation slow with multiple models
**Expected**: Parallel processing should be ~10-30% slower than single model.
If much slower, check:
- Network latency to API
- API rate limits
- CPU/GPU availability for local models

### Issue: Cost higher than expected
**Solution**: Check token count in chunks. Large chunks = higher cost:
```python
total_tokens = sum(chunk.token_count for chunk in chunks)
cost = total_tokens / 1_000_000 * model_cost_per_1m
```

---

## Next Steps

1. **Add More Embedding Adapters**:
   - VoyageEmbeddingAdapter
   - CohereEmbeddingAdapter
   - GoogleEmbeddingAdapter
   - JinaEmbeddingAdapter

2. **Model Comparison Dashboard**:
   - UI showing retrieval performance per model
   - Cost breakdown by model
   - Recommendation engine

3. **Auto-Optimization**:
   - Agent automatically tests all models
   - Selects best model(s) for corpus
   - Cost-benefit analysis

4. **Hybrid Model Retrieval**:
   - Search across multiple models simultaneously
   - Weighted fusion of results
   - Model ensembling

---

## Summary

This implementation provides:
- ✅ Multi-embedding storage in OpenSearch
- ✅ Parallel embedding generation
- ✅ User-friendly UI for model selection
- ✅ Cost transparency and estimation
- ✅ Full integration with SurfSense pipeline
- ✅ Support for 12+ embedding models (local + cloud)

**Result**: Users can now experiment with different embedding models without re-uploading documents, enabling data-driven optimization of retrieval quality.
