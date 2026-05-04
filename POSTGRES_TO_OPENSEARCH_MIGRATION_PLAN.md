# PostgreSQL to OpenSearch Migration Plan

## Executive Summary

**Goal**: Replace PostgreSQL pgvector with OpenSearch for chunk storage and retrieval while maintaining PostgreSQL for relational data (users, documents, search spaces).

**Rationale**:
- ✅ **Better Performance**: OpenSearch native k-NN is optimized for vector search at scale
- ✅ **Superior Hybrid Search**: Built-in BM25 + k-NN fusion with better scoring
- ✅ **Horizontal Scalability**: Scale vector storage independently from relational data
- ✅ **Already Configured**: `docker-compose-adaptable-rag.yml` has OpenSearch ready
- ✅ **Adapter Pattern**: Swap storage without changing application logic

## Current Architecture

### PostgreSQL Usage (Before Migration)

```
┌─────────────────────────────────────────┐
│         PostgreSQL + pgvector           │
├─────────────────────────────────────────┤
│ 1. Users, SearchSpaces, Documents       │ ← Keep in PostgreSQL
│ 2. Chunk.content, Chunk.embedding       │ ← Migrate to OpenSearch
│ 3. Full-text search (tsvector/tsquery)  │ ← Replace with OpenSearch BM25
│ 4. Vector search (pgvector <=>)         │ ← Replace with OpenSearch k-NN
└─────────────────────────────────────────┘
```

**Current Code**:
- `chunks_hybrid_search_patched.py`: Direct SQLAlchemy queries to PostgreSQL
  - `vector_search()`: Uses `Chunk.embedding.op("<=>")(query_embedding)`
  - `full_text_search()`: Uses `to_tsvector()` and `plainto_tsquery()`
  - `hybrid_search()`: RRF fusion at application level

## Target Architecture

### Hybrid Storage (After Migration)

```
┌──────────────────────┐       ┌──────────────────────┐
│     PostgreSQL       │       │      OpenSearch      │
├──────────────────────┤       ├──────────────────────┤
│ Users                │       │ Chunks Index         │
│ SearchSpaces         │       │ - chunk_id           │
│ Documents            │       │ - content (text)     │
│   ├─ id              │◄──────│ - document_id (FK)   │
│   ├─ title           │       │ - embedding (vector) │
│   ├─ metadata        │       │ - metadata           │
│   └─ search_space_id │       │                      │
└──────────────────────┘       │ k-NN + BM25 search   │
                               └──────────────────────┘
```

**Benefits**:
1. **Separation of concerns**: Relational data (PostgreSQL) vs vector data (OpenSearch)
2. **Independent scaling**: Scale vector storage without affecting user DB
3. **Better performance**: Native k-NN index (HNSW) vs pgvector extension
4. **Richer search**: OpenSearch query DSL for complex filters

## Implementation Plan

### Phase 1: Adapter Implementation ✅ (Already Done)

**Status**: Adapter architecture already exists in:
- `adapter_base_classes.py`: `StorageAdapter` base class
- `adapter_examples.py`: `OpenSearchAdapter` implementation
- `adapter_dataflow_models.py`: `EmbeddedChunk`, `SearchResult` models

**Existing OpenSearchAdapter Features**:
```python
class OpenSearchAdapter(StorageAdapter):
    def create_index(self, embedding_dimensions: int)
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int)
    def search(self, query: Query, top_k: int) -> List[SearchResult]
    def hybrid_search(self, query: Query, top_k: int) -> List[SearchResult]
    def delete_by_document_id(self, document_id: str)
```

### Phase 2: Backend Integration (Current Task)

#### Task 2.1: Create OpenSearch Chunk Storage Service

**File**: `/app/app/storage/opensearch_chunk_storage.py` (mount via volume)

```python
"""
OpenSearch-backed chunk storage service.
Replaces PostgreSQL pgvector for chunk embeddings.
"""
from typing import List, Dict, Any, Optional
from opensearchpy import AsyncOpenSearch
from app.adapters.adapter_dataflow_models import EmbeddedChunk
from app.db import Document  # Still use PostgreSQL for document metadata


class OpenSearchChunkStorage:
    """Manages chunk embeddings in OpenSearch"""
    
    def __init__(self, hosts: List[str], index_prefix: str = "surfsense"):
        self.client = AsyncOpenSearch(
            hosts=hosts,
            use_ssl=False,
            verify_certs=False
        )
        self.index_prefix = index_prefix
    
    def _get_index_name(self, search_space_id: int) -> str:
        """One index per search space for isolation"""
        return f"{self.index_prefix}_chunks_{search_space_id}"
    
    async def create_index(
        self,
        search_space_id: int,
        embedding_dimensions: int = 384
    ):
        """Create k-NN + BM25 index for chunks"""
        index_name = self._get_index_name(search_space_id)
        
        # Index mapping with k-NN and text fields
        mapping = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100,
                },
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "content": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": embedding_dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "faiss",
                            "parameters": {"ef_construction": 128, "m": 16},
                        },
                    },
                    "metadata": {"type": "object"},
                    "indexed_at": {"type": "date"},
                }
            },
        }
        
        if not await self.client.indices.exists(index=index_name):
            await self.client.indices.create(index=index_name, body=mapping)
    
    async def index_chunks(
        self,
        chunks: List[Dict[str, Any]],
        search_space_id: int,
        batch_size: int = 100
    ):
        """Bulk index chunks to OpenSearch"""
        index_name = self._get_index_name(search_space_id)
        
        from opensearchpy.helpers import async_bulk
        
        actions = [
            {
                "_index": index_name,
                "_id": chunk["chunk_id"],
                "_source": {
                    "chunk_id": chunk["chunk_id"],
                    "document_id": chunk["document_id"],
                    "content": chunk["content"],
                    "embedding": chunk["embedding"],
                    "metadata": chunk.get("metadata", {}),
                    "indexed_at": chunk.get("indexed_at"),
                },
            }
            for chunk in chunks
        ]
        
        success, failed = await async_bulk(
            self.client, actions, chunk_size=batch_size
        )
        return success, failed
    
    async def vector_search(
        self,
        query_embedding: List[float],
        search_space_id: int,
        top_k: int = 20,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """k-NN vector search"""
        index_name = self._get_index_name(search_space_id)
        
        query = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "content", "metadata"],
        }
        
        # Add filters if provided
        if filters:
            query["query"] = {
                "bool": {
                    "must": [{"knn": query["query"]["knn"]}],
                    "filter": [filters],
                }
            }
        
        response = await self.client.search(index=index_name, body=query)
        return [
            {
                "chunk_id": hit["_id"],
                "document_id": hit["_source"]["document_id"],
                "content": hit["_source"]["content"],
                "metadata": hit["_source"].get("metadata", {}),
                "vector_score": hit["_score"],
            }
            for hit in response["hits"]["hits"]
        ]
    
    async def full_text_search(
        self,
        query_text: str,
        search_space_id: int,
        top_k: int = 20,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """BM25 full-text search"""
        index_name = self._get_index_name(search_space_id)
        
        query = {
            "size": top_k,
            "query": {
                "match": {
                    "content": {
                        "query": query_text,
                        "operator": "or",
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "content", "metadata"],
        }
        
        if filters:
            query["query"] = {
                "bool": {
                    "must": [query["query"]],
                    "filter": [filters],
                }
            }
        
        response = await self.client.search(index=index_name, body=query)
        return [
            {
                "chunk_id": hit["_id"],
                "document_id": hit["_source"]["document_id"],
                "content": hit["_source"]["content"],
                "metadata": hit["_source"].get("metadata", {}),
                "bm25_score": hit["_score"],
            }
            for hit in response["hits"]["hits"]
        ]
    
    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: List[float],
        search_space_id: int,
        top_k: int = 20,
        filters: Optional[Dict] = None,
        rrf_k: int = 60
    ) -> List[Dict]:
        """Hybrid RRF search (vector + BM25)"""
        
        # Fetch more candidates for RRF fusion
        n_results = top_k * 5
        
        # Parallel execution of vector and text search
        import asyncio
        vector_results, text_results = await asyncio.gather(
            self.vector_search(query_embedding, search_space_id, n_results, filters),
            self.full_text_search(query_text, search_space_id, n_results, filters),
        )
        
        # RRF fusion
        chunk_scores = {}
        chunk_data = {}
        
        for rank, result in enumerate(vector_results, 1):
            chunk_id = result["chunk_id"]
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0) + 1 / (rrf_k + rank)
            chunk_data[chunk_id] = result
        
        for rank, result in enumerate(text_results, 1):
            chunk_id = result["chunk_id"]
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0) + 1 / (rrf_k + rank)
            if chunk_id not in chunk_data:
                chunk_data[chunk_id] = result
        
        # Sort by RRF score and return top_k
        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]
        
        return [
            {
                **chunk_data[chunk_id],
                "rrf_score": score,
            }
            for chunk_id, score in sorted_chunks
        ]
    
    async def delete_by_document_id(self, document_id: str, search_space_id: int):
        """Delete all chunks for a document"""
        index_name = self._get_index_name(search_space_id)
        
        query = {"query": {"term": {"document_id": document_id}}}
        await self.client.delete_by_query(index=index_name, body=query)
```

#### Task 2.2: Update `chunks_hybrid_search_patched.py`

Replace direct PostgreSQL queries with OpenSearch calls:

```python
class ChunksHybridSearchRetriever:
    def __init__(self, db_session, opensearch_storage=None):
        """
        Initialize the hybrid search retriever.
        
        Args:
            db_session: SQLAlchemy AsyncSession (for document metadata)
            opensearch_storage: OpenSearchChunkStorage instance (for chunks)
        """
        self.db_session = db_session
        self.opensearch_storage = opensearch_storage or self._init_opensearch()
    
    def _init_opensearch(self):
        from app.config import config
        hosts = config.OPENSEARCH_HOSTS.split(",")
        return OpenSearchChunkStorage(
            hosts=hosts,
            index_prefix=config.OPENSEARCH_INDEX_PREFIX
        )
    
    async def vector_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list:
        """Vector search using OpenSearch k-NN"""
        from app.config import config
        
        # Get embedding for query
        embedding_model = config.embedding_model_instance
        query_embedding = await asyncio.to_thread(embedding_model.embed, query_text)
        
        # Build document filters for time range
        filters = None
        if start_date or end_date:
            # Get matching document IDs from PostgreSQL
            doc_ids = await self._get_filtered_document_ids(
                search_space_id, start_date, end_date
            )
            filters = {"terms": {"document_id": doc_ids}}
        
        # Search OpenSearch
        results = await self.opensearch_storage.vector_search(
            query_embedding=query_embedding,
            search_space_id=search_space_id,
            top_k=top_k,
            filters=filters
        )
        
        # Hydrate with document metadata from PostgreSQL
        return await self._hydrate_chunks_with_documents(results)
    
    async def hybrid_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        document_type: str | list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        query_embedding: list | None = None,
    ) -> list:
        """Hybrid RRF search using OpenSearch"""
        from app.config import config
        
        # Get or compute embedding
        if query_embedding is None:
            embedding_model = config.embedding_model_instance
            query_embedding = await asyncio.to_thread(embedding_model.embed, query_text)
        
        # Build filters from PostgreSQL metadata
        filters = await self._build_filters(
            search_space_id, document_type, start_date, end_date
        )
        
        # Search OpenSearch with RRF
        results = await self.opensearch_storage.hybrid_search(
            query_text=query_text,
            query_embedding=query_embedding,
            search_space_id=search_space_id,
            top_k=top_k,
            filters=filters
        )
        
        # Group by document and hydrate metadata
        return await self._group_by_document(results)
    
    async def _get_filtered_document_ids(
        self, search_space_id: int, start_date, end_date
    ) -> List[int]:
        """Get document IDs from PostgreSQL matching filters"""
        from sqlalchemy import select
        from app.db import Document
        
        query = select(Document.id).where(Document.search_space_id == search_space_id)
        if start_date:
            query = query.where(Document.updated_at >= start_date)
        if end_date:
            query = query.where(Document.updated_at <= end_date)
        
        result = await self.db_session.execute(query)
        return [row[0] for row in result.all()]
    
    async def _hydrate_chunks_with_documents(self, opensearch_results) -> list:
        """Add document metadata from PostgreSQL to OpenSearch results"""
        # Fetch documents in batch
        doc_ids = list(set(r["document_id"] for r in opensearch_results))
        
        from sqlalchemy import select
        from app.db import Document
        
        query = select(Document).where(Document.id.in_(doc_ids))
        result = await self.db_session.execute(query)
        documents = {doc.id: doc for doc in result.scalars().all()}
        
        # Attach document to each chunk
        for chunk_result in opensearch_results:
            chunk_result["document"] = documents.get(chunk_result["document_id"])
        
        return opensearch_results
```

#### Task 2.3: Update Indexing Pipeline

**File**: `document_chunker_patch.py` - Update to index to OpenSearch

```python
async def index_chunks_to_opensearch(
    chunks: List[Chunk],
    document_id: int,
    search_space_id: int,
    embedding_model
):
    """Index chunks to OpenSearch after chunking"""
    from app.storage.opensearch_chunk_storage import OpenSearchChunkStorage
    from app.config import config
    
    opensearch = OpenSearchChunkStorage(
        hosts=config.OPENSEARCH_HOSTS.split(","),
        index_prefix=config.OPENSEARCH_INDEX_PREFIX
    )
    
    # Ensure index exists
    embedding_dim = len(chunks[0].embedding) if chunks else 384
    await opensearch.create_index(search_space_id, embedding_dim)
    
    # Prepare chunks for indexing
    chunk_docs = [
        {
            "chunk_id": chunk.id,
            "document_id": document_id,
            "content": chunk.content,
            "embedding": chunk.embedding,
            "metadata": {
                "token_count": getattr(chunk, "token_count", None),
                "prefix_context": getattr(chunk, "prefix_context", None),
            },
            "indexed_at": datetime.utcnow().isoformat(),
        }
        for chunk in chunks
    ]
    
    # Bulk index
    success, failed = await opensearch.index_chunks(
        chunk_docs, search_space_id, batch_size=100
    )
    
    logger.info(
        f"Indexed {success} chunks to OpenSearch for document {document_id}, "
        f"failed: {failed}"
    )
```

### Phase 3: Docker Configuration Updates

#### Task 3.1: Use `docker-compose-adaptable-rag.yml`

The adaptable RAG compose file already has OpenSearch configured! Just need to:

1. **Start services with adaptable RAG compose**:
```bash
cd /mnt/ssd1/projects/DocumentAI
sudo docker-compose -f docker-compose-adaptable-rag.yml up -d
```

2. **Set environment variables** (add to `.env`):
```bash
# OpenSearch Configuration
OPENSEARCH_HOSTS=http://opensearch:9200
OPENSEARCH_USE_SSL=false
OPENSEARCH_VERIFY_CERTS=false
OPENSEARCH_INDEX_PREFIX=surfsense

# Keep PostgreSQL for relational data only (no pgvector needed)
DATABASE_URL=postgresql+asyncpg://surfsense:surfsense@db:5432/surfsense
```

#### Task 3.2: Update `rag_config_schema.yaml` Storage Config

Change default storage provider from PostgreSQL to OpenSearch:

```yaml
storage:
  provider: opensearch  # Changed from postgresql_pgvector
  config:
    hosts:
      - http://opensearch:9200
    index_prefix: surfsense
    use_ssl: false
    verify_certs: false
```

### Phase 4: Migration & Testing

#### Task 4.1: Data Migration Script

**File**: `migrate_postgres_to_opensearch.py`

```python
"""
Migrate existing chunks from PostgreSQL to OpenSearch.
Run once after deploying new storage layer.
"""
import asyncio
from sqlalchemy import select
from app.db import get_async_session, Chunk, Document
from app.storage.opensearch_chunk_storage import OpenSearchChunkStorage
from app.config import config


async def migrate_chunks():
    """Migrate all chunks from PostgreSQL to OpenSearch"""
    
    opensearch = OpenSearchChunkStorage(
        hosts=config.OPENSEARCH_HOSTS.split(","),
        index_prefix=config.OPENSEARCH_INDEX_PREFIX
    )
    
    async for session in get_async_session():
        # Get all search spaces
        result = await session.execute(
            select(Document.search_space_id).distinct()
        )
        search_space_ids = [row[0] for row in result.all()]
        
        for space_id in search_space_ids:
            print(f"Migrating search space {space_id}...")
            
            # Get chunks for this search space
            query = (
                select(Chunk)
                .join(Document)
                .where(Document.search_space_id == space_id)
            )
            result = await session.execute(query)
            chunks = result.scalars().all()
            
            if not chunks:
                continue
            
            # Create index
            embedding_dim = len(chunks[0].embedding) if chunks else 384
            await opensearch.create_index(space_id, embedding_dim)
            
            # Prepare and index chunks
            chunk_docs = [
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "content": chunk.content,
                    "embedding": chunk.embedding,
                    "metadata": {},
                    "indexed_at": chunk.created_at.isoformat(),
                }
                for chunk in chunks
            ]
            
            success, failed = await opensearch.index_chunks(
                chunk_docs, space_id, batch_size=100
            )
            
            print(f"  Indexed {success} chunks, failed: {failed}")
        
        print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate_chunks())
```

#### Task 4.2: Testing Strategy

1. **Unit Tests**: Test OpenSearchChunkStorage methods
2. **Integration Tests**: Test end-to-end query pipeline
3. **Performance Tests**: Compare latency PostgreSQL vs OpenSearch
4. **A/B Test**: Run both systems in parallel, compare results

### Phase 5: Deployment Checklist

- [ ] Deploy OpenSearch service
- [ ] Mount `opensearch_chunk_storage.py` in backend container
- [ ] Update `chunks_hybrid_search_patched.py` to use OpenSearch
- [ ] Update `document_chunker_patch.py` indexing logic
- [ ] Set `OPENSEARCH_HOSTS` environment variable
- [ ] Run migration script for existing data
- [ ] Test search quality (F1 score with benchmark)
- [ ] Monitor OpenSearch performance
- [ ] Remove pgvector extension from PostgreSQL (optional cleanup)

## Rollback Plan

If issues arise, rollback is simple:

1. **Revert to old `docker-compose.yml`** (uses pgvector)
2. **Restore old `chunks_hybrid_search_patched.py`** (direct PostgreSQL queries)
3. **Data is safe**: PostgreSQL still has chunks as backup

## Performance Expectations

| Metric | PostgreSQL pgvector | OpenSearch k-NN | Improvement |
|--------|---------------------|-----------------|-------------|
| Vector Search Latency | 150-300ms | 50-100ms | **2-3x faster** |
| Index Build Time | 5min (100K chunks) | 2min (100K chunks) | **2.5x faster** |
| Memory Usage | High (in-memory index) | Optimized (HNSW) | **Lower** |
| Horizontal Scaling | Limited (single DB) | Excellent (sharding) | **Unlimited** |
| Hybrid Search Quality | Application-level RRF | Native query fusion | **Better ranking** |

## Cost Analysis

| Component | Before (pgvector) | After (OpenSearch) | Delta |
|-----------|-------------------|-------------------|-------|
| PostgreSQL | 8GB RAM, 4 CPU | 2GB RAM, 2 CPU | -75% resources |
| OpenSearch | N/A | 4GB RAM, 2 CPU | +4GB RAM |
| **Total** | 8GB RAM | 6GB RAM | **-25% memory** |

**Reasoning**: PostgreSQL no longer needs to hold vector index in memory.

## Success Metrics

1. **Performance**: P95 query latency < 100ms (vs 200ms with pgvector)
2. **Quality**: F1 score maintained or improved (benchmark test)
3. **Scalability**: Handle 1M+ chunks without degradation
4. **Reliability**: 99.9% uptime for search service

## Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Adapter ✅ | Complete | None |
| Phase 2: Backend Integration | 2 days | Adapter completion |
| Phase 3: Docker Config | 1 day | Backend integration |
| Phase 4: Migration & Testing | 2 days | Docker deployment |
| Phase 5: Production Deployment | 1 day | Testing validation |
| **Total** | **6 days** | |

## Next Steps

1. ✅ Review and approve this plan
2. Create `opensearch_chunk_storage.py` service
3. Update `chunks_hybrid_search_patched.py` 
4. Test locally with docker-compose-adaptable-rag.yml
5. Run benchmark to validate quality
6. Deploy to production

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-03  
**Author**: Adaptable RAG Team
