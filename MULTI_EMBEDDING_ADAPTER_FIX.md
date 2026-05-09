# Multi-Embedding Adapter Architecture Fix

## Problem Summary

The current multi-embedding implementation violates adapter architecture principles by:
1. Adding conditional logic to `IndexingPipelineService` (orchestrator)
2. Directly importing concrete implementations in orchestrator layer
3. Accessing config settings in orchestrator layer
4. Bypassing existing `StorageAdapter` interface

## Correct Architecture

### Phase 1: Extend Existing Adapters (No Orchestrator Changes)

#### 1.1 Create MultiModelEmbeddingAdapter

**File: `source/SurfSense/surfsense_backend/app/adapters/multi_model_embedding_adapter.py`**

```python
"""Multi-model embedding adapter following adapter architecture."""
import asyncio
from typing import List, Dict
from adapter_base_classes import EmbeddingAdapter
from adapter_dataflow_models import Chunk, EmbeddedChunk

class MultiModelEmbeddingAdapter(EmbeddingAdapter):
    """
    Wraps multiple embedding adapters to generate multiple embeddings per chunk.
    
    Follows adapter architecture:
    - Implements standard EmbeddingAdapter interface
    - Returns standard EmbeddedChunk objects
    - No orchestrator changes needed
    """
    
    def __init__(self, adapters: Dict[str, EmbeddingAdapter]):
        """
        Args:
            adapters: Dict of {model_key: EmbeddingAdapter}
                e.g., {"openai/text-embedding-3-large": OpenAIAdapter(...)}
        """
        self.adapters = adapters
        self.model_keys = list(adapters.keys())
    
    async def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """
        Generate multiple embeddings per chunk in parallel.
        
        Returns standard EmbeddedChunk with multiple embeddings:
        - embeddings: {"model1": [vec1], "model2": [vec2], ...}
        - embedding_models: ["model1", "model2", ...]
        - embedding_cost_usd: sum of all model costs
        """
        # Parallel embed with all adapters
        tasks = [
            adapter.embed_chunks(chunks) 
            for adapter in self.adapters.values()
        ]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Merge results into single EmbeddedChunk per chunk
        merged_chunks = []
        for i, chunk in enumerate(chunks):
            embeddings = {}
            dimensions = {}
            total_cost = 0.0
            total_latency = 0.0
            providers = []
            
            # Collect embeddings from each model
            for model_key, results in zip(self.model_keys, all_results):
                if isinstance(results, Exception):
                    continue
                    
                embedded = results[i]
                embeddings.update(embedded.embeddings)
                dimensions.update(embedded.embedding_dimensions)
                total_cost += embedded.embedding_cost_usd
                total_latency = max(total_latency, embedded.embedding_latency_ms)
                if embedded.embedding_provider not in providers:
                    providers.append(embedded.embedding_provider)
            
            merged_chunks.append(EmbeddedChunk(
                chunk=chunk,
                embeddings=embeddings,  # Multiple models!
                embedding_provider="+".join(providers),
                embedding_models=list(embeddings.keys()),
                embedding_dimensions=dimensions,
                embedding_cost_usd=total_cost,
                embedding_latency_ms=total_latency,
                searchable_text=chunk.get_full_context(),
            ))
        
        return merged_chunks
    
    def embed_query(self, query_text: str) -> Dict[str, List[float]]:
        """Embed query with all models (for multi-model search)."""
        results = {}
        for model_key, adapter in self.adapters.items():
            results[model_key] = adapter.embed_query(query_text)
        return results
    
    def get_dimensions(self) -> Dict[str, int]:
        """Return dimensions for each model."""
        return {
            model_key: adapter.get_dimensions()
            for model_key, adapter in self.adapters.items()
        }
```

#### 1.2 Extend OpenSearchAdapter for Multiple Vector Fields

**File: `source/SurfSense/surfsense_backend/app/adapters/opensearch_multi_vector_adapter.py`**

```python
"""OpenSearch adapter that supports multiple embedding fields."""
from typing import List, Dict
from adapter_base_classes import StorageAdapter
from adapter_dataflow_models import EmbeddedChunk

class OpenSearchMultiVectorAdapter(StorageAdapter):
    """
    OpenSearch storage with support for multiple knn_vector fields.
    
    Creates one field per embedding model:
    - embedding_openai_text_embedding_3_large: {"type": "knn_vector", "dimension": 3072}
    - embedding_fastembed_bge_small_en_v1_5: {"type": "knn_vector", "dimension": 384}
    """
    
    def create_index(self, embedding_dimensions: Dict[str, int], **kwargs):
        """
        Create index with multiple vector fields.
        
        Args:
            embedding_dimensions: {model_key: dimensions}
                e.g., {"openai/text-embedding-3-large": 3072, ...}
        """
        properties = {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "text": {"type": "text"},  # BM25 full-text search
            "metadata": {"type": "object"},
        }
        
        # Create one knn_vector field per model
        for model_key, dims in embedding_dimensions.items():
            field_name = self._normalize_field_name(model_key)
            properties[field_name] = {
                "type": "knn_vector",
                "dimension": dims,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "parameters": {"ef_construction": 256, "m": 16}
                }
            }
        
        index_body = {
            "settings": {
                "index": {"knn": True, "number_of_shards": 2}
            },
            "mappings": {"properties": properties}
        }
        
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        self.client.indices.create(index=self.index_name, body=index_body)
    
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int = 100):
        """
        Index chunks with multiple embeddings.
        
        Each chunk gets multiple knn_vector fields populated.
        """
        actions = []
        for embedded in chunks:
            chunk = embedded.chunk
            
            # Build document with all embedding fields
            doc = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "metadata": chunk.metadata,
            }
            
            # Add each embedding to its field
            for model_key, embedding_vector in embedded.embeddings.items():
                field_name = self._normalize_field_name(model_key)
                doc[field_name] = embedding_vector
            
            actions.append({
                "_index": self.index_name,
                "_id": chunk.chunk_id,
                "_source": doc
            })
            
            if len(actions) >= batch_size:
                helpers.bulk(self.client, actions)
                actions = []
        
        if actions:
            helpers.bulk(self.client, actions)
    
    def _normalize_field_name(self, model_key: str) -> str:
        """Convert 'openai/text-embedding-3-large' to 'embedding_openai_text_embedding_3_large'"""
        return "embedding_" + model_key.replace("/", "_").replace("-", "_")
```

#### 1.3 Register with AdapterFactory

**File: `source/SurfSense/surfsense_backend/app/adapters/adapter_factory.py`**

```python
from adapter_factory import AdapterFactory
from multi_model_embedding_adapter import MultiModelEmbeddingAdapter
from opensearch_multi_vector_adapter import OpenSearchMultiVectorAdapter

# Register multi-model support
AdapterFactory.register_embedding("multi", MultiModelEmbeddingAdapter)
AdapterFactory.register_storage("opensearch_multi", OpenSearchMultiVectorAdapter)
```

#### 1.4 Remove Orchestrator Changes

**File: `source/SurfSense/surfsense_backend/app/indexing_pipeline/indexing_pipeline_service.py`**

```python
# REVERT lines 389-435 back to original single embedding code
# The adapter handles multi-embedding internally now!

# Original code (NO CHANGES):
texts_to_embed = [content, *chunk_texts]
embeddings = await asyncio.to_thread(embed_texts, texts_to_embed)
summary_embedding, *chunk_embeddings = embeddings

chunks = [
    Chunk(content=text, embedding=emb)
    for text, emb in zip(chunk_texts, chunk_embeddings, strict=False)
]
```

### Phase 2: Config-Driven Selection

**File: `rag_config_schema.yaml`**

```yaml
embedding:
  # Option 1: Single model (existing behavior)
  provider: openai
  model: text-embedding-3-large
  api_key: ${OPENAI_API_KEY}

# OR

embedding:
  # Option 2: Multiple models (new behavior)
  provider: multi
  adapters:
    - provider: openai
      model: text-embedding-3-large
      api_key: ${OPENAI_API_KEY}
    - provider: fastembed
      model: BAAI/bge-small-en-v1.5
      cache_dir: ./models
    - provider: voyage
      model: voyage-finance-2
      api_key: ${VOYAGE_API_KEY}

storage:
  # Automatically uses multi-vector support if needed
  provider: opensearch_multi
  hosts:
    - http://localhost:9200
  index_name: rag_chunks
```

**Adapter Creation (NO ORCHESTRATOR CODE CHANGES):**

```python
# In file_upload_adapter.py or wherever adapters are created
def create_adapters_from_config(config):
    """Factory function to create adapters from config."""
    
    embedding_config = config["embedding"]
    
    if embedding_config["provider"] == "multi":
        # Create individual adapters
        adapters = {}
        for adapter_config in embedding_config["adapters"]:
            provider = adapter_config["provider"]
            adapter = AdapterFactory.create_embedding(provider, adapter_config)
            model_key = f"{provider}/{adapter_config['model']}"
            adapters[model_key] = adapter
        
        # Wrap in multi-model adapter
        embedding_adapter = MultiModelEmbeddingAdapter(adapters)
    else:
        # Single model (existing)
        embedding_adapter = AdapterFactory.create_embedding(
            embedding_config["provider"],
            embedding_config
        )
    
    # Storage adapter
    storage_adapter = AdapterFactory.create_storage(
        config["storage"]["provider"],
        config["storage"]
    )
    
    return embedding_adapter, storage_adapter
```

### Phase 3: API Layer Integration

**File: `source/SurfSense/surfsense_backend/app/routes/documents_routes.py`**

```python
# Instead of passing embedding_models as separate parameter,
# construct a custom config object

@router.post("/documents/fileupload")
async def upload_file(
    file: UploadFile,
    search_space_id: int = Form(...),
    embedding_models: str = Form(None),  # JSON: ["openai/text-embedding-3-large", ...]
    ...
):
    # Parse selected models
    selected_models = json.loads(embedding_models) if embedding_models else None
    
    # Build config dynamically
    if selected_models and len(selected_models) > 1:
        # Multi-model config
        embedding_config = {
            "provider": "multi",
            "adapters": [
                get_adapter_config_for_model(model)
                for model in selected_models
            ]
        }
    else:
        # Single model config (existing)
        embedding_config = get_default_embedding_config()
    
    # Pass config to dispatcher (NOT raw model list)
    await dispatcher.dispatch_file_processing(
        embedding_config=embedding_config,  # Config object, not list
        ...
    )
```

## Benefits of This Approach

1. ✅ **No Orchestrator Changes**: `IndexingPipelineService.index()` unchanged
2. ✅ **Adapter Pattern**: All complexity in adapter layer
3. ✅ **Config-Driven**: Select models via config, not code
4. ✅ **Standard Data Models**: Uses `EmbeddedChunk.embeddings` dict
5. ✅ **Backward Compatible**: Single-model still works
6. ✅ **Testable**: Mock adapters for unit tests
7. ✅ **Extensible**: Add new models by registering adapters

## Migration Path

### Step 1: Create new adapter classes (above)
### Step 2: Revert orchestrator changes

```bash
cd /mnt/ssd1/projects/DocumentAI/source/SurfSense/surfsense_backend
git diff app/indexing_pipeline/indexing_pipeline_service.py
# Revert lines 389-435 to original
```

### Step 3: Update API layer to use config objects
### Step 4: Test with both single and multi-model configs
### Step 5: Deprecate direct model list parameter

## Conclusion

The adapter architecture requires that:
- **Orchestrator knows only interfaces, not implementations**
- **All decisions made by adapters, not orchestrator**
- **Configuration drives component selection**
- **Standard data models enable interoperability**

Your current implementation violates these principles by adding conditional logic to the orchestrator. The fix is to move all multi-embedding logic into adapter classes that implement the standard interfaces.
