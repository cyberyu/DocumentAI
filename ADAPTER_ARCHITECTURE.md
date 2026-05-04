# Adapter Architecture: The Key to True Adaptability

## 🎯 Core Principle

**Every component in the RAG pipeline can be swapped without breaking the system because ALL communication happens through standardized adapters with well-defined data contracts.**

This document explains the adapter pattern that makes the system truly adaptable across different software stacks (Python SDKs, REST APIs, gRPC, CLI tools, Docker services).

---

## 📐 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                             │
│                    (Upload docs + Ask question)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RAG ORCHESTRATOR                              │
│                  (Coordinates adapters)                          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────┐  ┌──────────────┐  ┌─────────────┐
    │ETL Adapter  │  │Embed Adapter │  │Store Adapter│
    │             │  │              │  │             │
    │ Interface:  │  │ Interface:   │  │ Interface:  │
    │ extract()   │  │ embed()      │  │ index()     │
    │             │  │              │  │ search()    │
    └──────┬──────┘  └──────┬───────┘  └──────┬──────┘
           │                │                 │
           │                │                 │
    ┌──────▼──────────┬─────▼─────────┬──────▼──────────┐
    │                 │               │                 │
    ▼                 ▼               ▼                 ▼
┌────────┐      ┌──────────┐    ┌──────────┐      ┌──────────┐
│MinerU  │      │OpenAI API│    │FastEmbed │      │OpenSearch│
│(Python)│      │(REST)    │    │(Python)  │      │(Docker)  │
└────────┘      └──────────┘    └──────────┘      └──────────┘
    OR              OR              OR                  OR
┌────────┐      ┌──────────┐    ┌──────────┐      ┌──────────┐
│Docling │      │Voyage API│    │Cohere API│      │Qdrant    │
│(Python)│      │(REST)    │    │(REST)    │      │(Cloud)   │
└────────┘      └──────────┘    └──────────┘      └──────────┘
    OR              OR              OR                  OR
┌────────┐      ┌──────────┐    ┌──────────┐      ┌──────────┐
│Unstruct│      │Google API│    │Jina API  │      │Weaviate  │
│(API)   │      │(REST)    │    │(REST)    │      │(Docker)  │
└────────┘      └──────────┘    └──────────┘      └──────────┘
```

**Key Insight**: The orchestrator only knows about **adapter interfaces**, not concrete implementations. You can swap MinerU for Docling, OpenAI for Voyage, OpenSearch for Qdrant—all at runtime through configuration.

---

## 🔄 Data Flow Through Adapters

### Phase 1: Document Ingestion (Indexing Pipeline)

```
File Upload
   │
   ▼
┌──────────────────────────────────────┐
│ ETLAdapter.extract_from_bytes()      │  ← Software Stack: Python SDK / REST API / CLI
├──────────────────────────────────────┤
│ Input:  bytes, filename              │
│ Output: RawDocument                  │
│         - content (markdown/text)    │
│         - metadata (author, date)    │
│         - tables, images, formulas   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ TransformationAdapter.transform()    │  ← Software Stack: Pure Python (regex, NLP)
├──────────────────────────────────────┤
│ Input:  RawDocument                  │
│ Output: RawDocument (cleaned)        │
│         - normalized headers         │
│         - merged split sentences     │
│         - cleaned whitespace         │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ ChunkingAdapter.chunk_document()     │  ← Software Stack: Pure Python / langchain
├──────────────────────────────────────┤
│ Input:  RawDocument                  │
│ Output: List[Chunk]                  │
│         - text, token_count          │
│         - prefix_context, suffix     │
│         - metadata                   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ EmbeddingAdapter.embed_chunks()      │  ← Software Stack: REST API / Python SDK / Local
├──────────────────────────────────────┤
│ Input:  List[Chunk]                  │
│ Output: List[EmbeddedChunk]          │
│         - embeddings (3072-dim vec)  │
│         - cost_usd, latency_ms       │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ StorageAdapter.index_chunks()        │  ← Software Stack: Docker service / Cloud API
├──────────────────────────────────────┤
│ Input:  List[EmbeddedChunk]          │
│ Side Effect: Persisted to storage    │
│         - vector index (k-NN)        │
│         - full-text index (BM25)     │
│         - metadata fields            │
└──────────────────────────────────────┘
```

### Phase 2: Query Answering (Retrieval Pipeline)

```
User Query
   │
   ▼
┌──────────────────────────────────────┐
│ EmbeddingAdapter.embed_query()       │  ← Same adapter as indexing
├──────────────────────────────────────┤
│ Input:  query_text                   │
│ Output: query_vector (3072-dim)      │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ RetrievalAdapter.search()            │  ← Software Stack: Storage client library
├──────────────────────────────────────┤
│ Input:  Query (text + vector)        │
│         top_k, filters               │
│ Output: List[SearchResult]           │
│         - chunk, score               │
│         - vector_score, bm25_score   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ RerankingAdapter.rerank()            │  ← Software Stack: REST API / Python SDK
├──────────────────────────────────────┤
│ Input:  Query + List[SearchResult]   │
│ Output: List[RerankedResult]         │
│         - rerank_score, rerank_rank  │
│         - reranker metadata          │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│ RetrievalContext.format_for_llm()    │  ← Pure data transformation
├──────────────────────────────────────┤
│ Input:  List[RerankedResult]         │
│ Output: formatted_context (string)   │
│         + citations metadata         │
└──────────────────┬───────────────────┘
                   │
                   ▼
            Agent + LLM
         (Generate answer)
```

---

## 📦 Standard Data Models

All data models are defined in [`adapter_dataflow_models.py`](./adapter_dataflow_models.py).

### Core Types (in flow order)

| Type | Purpose | Key Fields | Producer | Consumer |
|------|---------|------------|----------|----------|
| **RawDocument** | Extracted document | content, metadata, tables, images | ETLAdapter | ChunkingAdapter |
| **Chunk** | Document fragment | text, token_count, prefix/suffix context | ChunkingAdapter | EmbeddingAdapter |
| **EmbeddedChunk** | Chunk + vector | chunk, embeddings, cost, latency | EmbeddingAdapter | StorageAdapter |
| **Query** | User question | text, embedding, filters | User/Agent | RetrievalAdapter |
| **SearchResult** | Retrieved chunk | chunk, score, vector/bm25 scores | RetrievalAdapter | RerankingAdapter |
| **RerankedResult** | Final ranked result | search_result, rerank_score | RerankingAdapter | Agent/LLM |
| **RetrievalContext** | Full context | results, latency, cost, citations | Orchestrator | Agent/LLM |

### Why Standardized Models?

1. **Software-stack agnostic**: MinerU (Python SDK) and Unstructured (REST API) both produce `RawDocument`
2. **Swappable components**: Any `EmbeddingAdapter` can replace another—just needs to produce `EmbeddedChunk`
3. **Rich metadata**: Track cost, latency, lineage for debugging and optimization
4. **Type safety**: Pydantic validation ensures data integrity
5. **Forward compatible**: Optional fields allow gradual API evolution

**Example**: Switching from OpenAI to Voyage embeddings requires ZERO orchestrator code changes:

```python
# Before
embedding_adapter = OpenAIEmbeddingAdapter(config)  # Produces EmbeddedChunk

# After (just change config)
embedding_adapter = VoyageEmbeddingAdapter(config)  # Also produces EmbeddedChunk

# Orchestrator doesn't care—both implement EmbeddingAdapter interface
embedded_chunks = embedding_adapter.embed_chunks(chunks)  # Works with both!
```

---

## 🔌 Base Adapter Classes

All adapter interfaces are defined in [`adapter_base_classes.py`](./adapter_base_classes.py).

### 1. ETLAdapter

**Purpose**: Extract content from files (any format) → RawDocument

**Interface**:
```python
class ETLAdapter(ABC):
    @abstractmethod
    def extract_from_file(self, file_path: Path) -> RawDocument:
        """Extract from file on disk"""
        pass
    
    @abstractmethod
    def extract_from_bytes(self, file_bytes: bytes, filename: str) -> RawDocument:
        """Extract from uploaded bytes"""
        pass
    
    @abstractmethod
    def supported_formats(self) -> List[str]:
        """Return [".pdf", ".docx", ...]"""
        pass
```

**Software Stack Examples**:

| Adapter | Technology | Stack Type | Special Handling |
|---------|-----------|------------|------------------|
| `MinerUAdapter` | MinerU library | Python SDK | Import `magic_pdf`, call `extract()` |
| `DoclingAdapter` | Docling library | Python SDK | Import `docling`, async API |
| `UnstructuredAdapter` | Unstructured.io | REST API | `requests` library, API key auth |
| `TikaAdapter` | Apache Tika | Java/REST | Subprocess `java -jar` or HTTP client |

**Key Adaptability**: Orchestrator calls `extract_from_file()`. It doesn't know whether that calls a Python function, hits a REST endpoint, or spawns a subprocess—abstraction hides all complexity.

### 2. ChunkingAdapter

**Purpose**: Split RawDocument → List[Chunk]

**Interface**:
```python
class ChunkingAdapter(ABC):
    @abstractmethod
    def chunk_document(self, document: RawDocument) -> List[Chunk]:
        """Split into chunks with configurable strategy"""
        pass
```

**Software Stack Examples**:

| Adapter | Technology | Stack Type |
|---------|-----------|------------|
| `HybridSandwichChunker` | Custom Python | Pure Python (regex, spaCy) |
| `RecursiveChunker` | Langchain | Python SDK |
| `SemanticChunker` | spaCy + sentence-transformers | Python SDK |
| `CodeAwareChunker` | tree-sitter | Python bindings to C library |

**Key Adaptability**: All chunkers produce the same `Chunk` data model. Switching strategies is a config change.

### 3. EmbeddingAdapter

**Purpose**: Chunks → EmbeddedChunks (with vector embeddings)

**Interface**:
```python
class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """Generate embeddings (handles batching)"""
        pass
    
    @abstractmethod
    def embed_query(self, query_text: str) -> List[float]:
        """Embed single query"""
        pass
    
    @abstractmethod
    def get_dimensions(self) -> int:
        """Return vector dimensions"""
        pass
```

**Software Stack Examples** (6 providers, 40+ models):

| Adapter | Technology | Stack Type | Authentication | Special Handling |
|---------|-----------|------------|----------------|------------------|
| `OpenAIEmbeddingAdapter` | OpenAI API | REST API | API key header | Batch 100 chunks, exponential backoff |
| `VoyageEmbeddingAdapter` | Voyage API | REST API | Bearer token | 32K context, finance-specific models |
| `CohereEmbeddingAdapter` | Cohere API | REST API | API key | Binary compression, batch 96 |
| `FastEmbedAdapter` | FastEmbed library | Python SDK (local) | None (free) | GPU acceleration, ONNX runtime |
| `GoogleEmbeddingAdapter` | Google Vertex AI | gRPC/REST | OAuth2 | Task-type parameter |
| `JinaEmbeddingAdapter` | Jina API | REST API | Bearer token | 8K context |

**Key Adaptability**: 
- **REST APIs**: Use `requests`/`httpx` with retry logic, rate limiting, auth headers
- **Python SDKs**: Direct function calls, handle GPU memory
- **Cost tracking**: Each adapter computes cost_usd based on provider pricing
- **Batching**: All adapters handle batching internally—orchestrator just calls `embed_chunks()`

**Example—OpenAI Adapter** (handles REST API complexity):
```python
class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, config):
        super().__init__(config)
        self.api_key = config["api_key"]
        self.endpoint = "https://api.openai.com/v1/embeddings"
        self.model = config.get("model", "text-embedding-3-large")
        self.dims = 3072 if "3-large" in self.model else 1536
        
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        embedded = []
        # Batch in groups of 100 (OpenAI limit: 2048 per request)
        for batch in self._batch(chunks, 100):
            texts = [chunk.get_full_context() for chunk in batch]
            
            # REST API call with retry
            response = self._call_api_with_retry({
                "model": self.model,
                "input": texts,
                "dimensions": self.dims
            })
            
            # Parse response and create EmbeddedChunk objects
            for chunk, embedding_data in zip(batch, response["data"]):
                embedded.append(EmbeddedChunk(
                    chunk=chunk,
                    embeddings={self.model: embedding_data["embedding"]},
                    embedding_provider="openai",
                    embedding_models=[self.model],
                    embedding_dimensions={self.model: self.dims},
                    embedding_cost_usd=self._compute_cost(len(texts)),
                ))
        
        return embedded
    
    def _call_api_with_retry(self, payload):
        """Handle HTTP, rate limits, exponential backoff"""
        for attempt in range(5):
            try:
                response = requests.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt < 4 and "rate_limit" in str(e):
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                raise EmbeddingAdapterError(f"OpenAI API failed: {e}")
```

**Contrast with FastEmbed** (Python SDK, local, free):
```python
class FastEmbedAdapter(EmbeddingAdapter):
    def __init__(self, config):
        super().__init__(config)
        from fastembed import TextEmbedding  # Import only when used
        self.model = TextEmbedding(config.get("model", "BAAI/bge-small-en-v1.5"))
        
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        texts = [chunk.get_full_context() for chunk in chunks]
        
        # Local inference (no API calls, no cost)
        embeddings = list(self.model.embed(texts))
        
        return [
            EmbeddedChunk(
                chunk=chunk,
                embeddings={self.model.model_name: embedding.tolist()},
                embedding_provider="fastembed",
                embedding_cost_usd=0.0,  # FREE!
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
```

**Both adapters implement the same interface**—orchestrator doesn't know the difference!

### 4. StorageAdapter

**Purpose**: Persist EmbeddedChunks, enable search

**Interface**:
```python
class StorageAdapter(ABC):
    @abstractmethod
    def create_index(self, embedding_dimensions: int, **kwargs):
        """Setup index with vector + metadata fields"""
        pass
    
    @abstractmethod
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int = 100):
        """Bulk insert chunks"""
        pass
    
    @abstractmethod
    def delete_by_doc_id(self, doc_id: str):
        """Remove all chunks from a document"""
        pass
```

**Software Stack Examples**:

| Adapter | Technology | Stack Type | Connection | Special Handling |
|---------|-----------|------------|------------|------------------|
| `OpenSearchAdapter` | OpenSearch | Docker service | HTTP client (`opensearch-py`) | k-NN + BM25, multiple vector fields |
| `PostgreSQLAdapter` | PostgreSQL + pgvector | Docker service | TCP (`psycopg2`) | SQL queries, ivfflat index |
| `QdrantAdapter` | Qdrant | Docker/Cloud | gRPC/HTTP | Collections, payload indexing |
| `WeaviateAdapter` | Weaviate | Docker/Cloud | GraphQL | Schema classes, cross-references |

**Key Adaptability**:
- **Docker services**: Use client libraries (opensearch-py, psycopg2)
- **Cloud services**: Handle authentication, connection pooling
- **Index configuration**: Each adapter translates generic config to provider-specific settings

**Example—OpenSearch Adapter**:
```python
class OpenSearchAdapter(StorageAdapter):
    def __init__(self, config):
        super().__init__(config)
        from opensearchpy import OpenSearch
        
        self.client = OpenSearch(
            hosts=config.get("hosts", ["http://localhost:9200"]),
            timeout=30,
            max_retries=3,
        )
        self.index_name = config.get("index_name", "rag_chunks")
    
    def create_index(self, embedding_dimensions: int, **kwargs):
        """Create index with k-NN + BM25"""
        index_body = {
            "settings": {
                "index": {
                    "knn": True,  # Enable k-NN
                    "number_of_shards": 2,
                }
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "text": {"type": "text"},  # For BM25
                    "embedding": {  # For k-NN
                        "type": "knn_vector",
                        "dimension": embedding_dimensions,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                            "parameters": {"ef_construction": 256, "m": 16}
                        }
                    },
                    "metadata": {"type": "object"},
                }
            }
        }
        
        # Create index (handles existing index)
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        self.client.indices.create(index=self.index_name, body=index_body)
    
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int = 100):
        """Bulk index with batching"""
        from opensearchpy import helpers
        
        actions = []
        for embedded in chunks:
            chunk = embedded.chunk
            embedding_vector = embedded.get_embedding()
            
            actions.append({
                "_index": self.index_name,
                "_id": chunk.chunk_id,
                "_source": {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "embedding": embedding_vector,
                    "metadata": chunk.metadata,
                }
            })
            
            # Bulk insert when batch is full
            if len(actions) >= batch_size:
                helpers.bulk(self.client, actions)
                actions = []
        
        # Insert remaining
        if actions:
            helpers.bulk(self.client, actions)
```

### 5. RetrievalAdapter

**Purpose**: Execute search (vector + keyword + hybrid)

**Interface**:
```python
class RetrievalAdapter(ABC):
    def __init__(self, config, storage: StorageAdapter, embedding: EmbeddingAdapter):
        self.config = config
        self.storage = storage  # Uses storage's search capabilities
        self.embedding = embedding  # To embed query
    
    @abstractmethod
    def search(self, query: Query, top_k: int = 10) -> List[SearchResult]:
        """Execute search strategy"""
        pass
```

**Software Stack Examples**:

| Adapter | Strategy | Stack |
|---------|----------|-------|
| `HybridRRFRetriever` | Vector + BM25 → RRF | Uses StorageAdapter's native capabilities |
| `VectorOnlyRetriever` | Pure semantic search | k-NN only |
| `BM25OnlyRetriever` | Pure keyword search | Full-text only |
| `MultiStageRetriever` | Fast → precise | Two-pass search |

**Key Adaptability**: Retrieval adapters **compose** with storage adapters. They don't know whether storage is OpenSearch, PostgreSQL, or Qdrant—they just call the storage adapter's methods.

### 6. RerankingAdapter

**Purpose**: Refine search results with cross-encoder

**Interface**:
```python
class RerankingAdapter(ABC):
    @abstractmethod
    def rerank(
        self, 
        query: Query, 
        results: List[SearchResult], 
        top_k: Optional[int] = None
    ) -> List[RerankedResult]:
        """Rerank with query-document cross-attention"""
        pass
```

**Software Stack Examples**:

| Adapter | Technology | Stack Type |
|---------|-----------|------------|
| `FlashRankReranker` | FlashRank library | Python SDK (local) |
| `CohereReranker` | Cohere rerank API | REST API |
| `VoyageReranker` | Voyage rerank API | REST API |
| `CrossEncoderReranker` | Sentence-transformers | Python SDK |

---

## 🔧 Adapter Factory Pattern

**Problem**: How to create the right adapter based on configuration?

**Solution**: `AdapterFactory` with dynamic registration

```python
# Registration (happens at app startup)
AdapterFactory.register_etl("mineru", MinerUAdapter)
AdapterFactory.register_etl("docling", DoclingAdapter)
AdapterFactory.register_embedding("openai", OpenAIEmbeddingAdapter)
AdapterFactory.register_embedding("voyage", VoyageEmbeddingAdapter)
# ... etc for all adapters

# Creation (happens at request time)
config = {
    "etl_provider": "mineru",
    "embedding_provider": "openai",
    "embedding_model": "text-embedding-3-large",
    # ...
}

etl = AdapterFactory.create_etl(config["etl_provider"], config)
embedding = AdapterFactory.create_embedding(config["embedding_provider"], config)

# Use adapters (polymorphism)
document = etl.extract_from_file(Path("report.pdf"))  # MinerU extracts
chunks = chunker.chunk_document(document)
embedded = embedding.embed_chunks(chunks)  # OpenAI embeds
```

**Benefits**:
1. **Zero orchestrator changes**: Swap components via config
2. **Runtime configuration**: Different configs for different documents
3. **Plugin architecture**: Add new adapters without modifying core code

---

## 🌐 Multi-Software-Stack Support

### Design Principle: Adapters Hide Complexity

The orchestrator should never care about:
- ❌ "Is this a REST API or Python SDK?"
- ❌ "Do I need an API key or OAuth2?"
- ❌ "Is this service running locally or in the cloud?"
- ❌ "How do I handle rate limits?"

Adapters encapsulate ALL software-stack complexity:

| Software Stack | Adapter Responsibilities | Examples |
|----------------|-------------------------|----------|
| **Python SDK** | Import library, call methods, handle exceptions | MinerU, FastEmbed, FlashRank |
| **REST API** | HTTP client, auth headers, retry logic, rate limits | OpenAI, Voyage, Cohere, Google |
| **gRPC** | Protocol buffers, channel management, streaming | Google Vertex AI (optional) |
| **CLI Tools** | Subprocess management, stdin/stdout parsing | Tika (java -jar) |
| **Docker Services** | Network clients, connection pooling, health checks | OpenSearch, PostgreSQL, Redis |
| **Cloud Services** | Authentication (OAuth2, API keys), region selection | Qdrant Cloud, Weaviate Cloud |

### Example: Three Embedding Providers, Three Stacks

#### Stack 1: REST API (OpenAI)
```python
class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def embed_chunks(self, chunks):
        # HTTP POST with retry logic
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts}
        )
        return self._parse_response(response.json())
```

#### Stack 2: Python SDK (FastEmbed, local)
```python
class FastEmbedAdapter(EmbeddingAdapter):
    def embed_chunks(self, chunks):
        # Direct method call, GPU inference
        from fastembed import TextEmbedding
        model = TextEmbedding(self.model)
        embeddings = list(model.embed(texts))
        return self._to_embedded_chunks(embeddings)
```

#### Stack 3: gRPC (Google Vertex AI)
```python
class GoogleEmbeddingAdapter(EmbeddingAdapter):
    def embed_chunks(self, chunks):
        # gRPC channel with OAuth2
        from google.cloud import aiplatform
        
        client = aiplatform.gapic.PredictionServiceClient()
        request = PredictRequest(endpoint=self.endpoint, instances=texts)
        response = client.predict(request)
        return self._parse_grpc_response(response)
```

**All three implement the same interface**—orchestrator code is identical:

```python
# Orchestrator doesn't care about the stack
embedding_adapter = AdapterFactory.create_embedding(provider, config)
embedded_chunks = embedding_adapter.embed_chunks(chunks)  # Works for all!
```

---

## 🔄 Dataflow Example: End-to-End

Let's trace a **single document** through the entire pipeline with **concrete adapters**:

### Scenario
- **Document**: `financial_report.pdf` (10-Q filing, 50 pages)
- **Config**: MinerU + OpenAI 3K + OpenSearch + FlashRank

### Step-by-Step Dataflow

#### 1. ETL: PDF → RawDocument
```python
# Adapter: MinerUAdapter (Python SDK)
etl = AdapterFactory.create_etl("mineru", config)
raw_doc = etl.extract_from_file(Path("financial_report.pdf"))

# Data: RawDocument
print(raw_doc.content[:200])  # "# Microsoft Corporation\n\n## Quarterly Report..."
print(len(raw_doc.tables))     # 15 (extracted with structure)
print(len(raw_doc.formulas))   # 8 (LaTeX representations)
```

**Software Stack**: MinerU library (Python), local GPU for table detection

#### 2. Transformation: Clean content
```python
# Adapter: WhitespaceTransformer (Pure Python)
transformer = WhitespaceTransformer()
raw_doc = transformer.transform(raw_doc)

# Data: RawDocument (cleaned)
# - Multiple newlines → single newline
# - Trailing spaces removed
# - Headers normalized
```

#### 3. Chunking: RawDocument → List[Chunk]
```python
# Adapter: HybridSandwichChunker (Pure Python)
chunker = AdapterFactory.create_chunking("hybrid_sandwich", config)
chunks = chunker.chunk_document(raw_doc)

# Data: List[Chunk] (120 chunks)
chunk = chunks[0]
print(chunk.text[:100])          # "Revenue increased 16% year-over-year..."
print(chunk.prefix_context)      # "# Financial Highlights\n## Revenue"
print(chunk.token_count)         # 256
```

#### 4. Embedding: Chunks → EmbeddedChunks
```python
# Adapter: OpenAIEmbeddingAdapter (REST API)
embedding = AdapterFactory.create_embedding("openai", config)
embedded = embedding.embed_chunks(chunks)

# Data: List[EmbeddedChunk] (120 embedded chunks)
emb_chunk = embedded[0]
print(len(emb_chunk.embeddings["text-embedding-3-large"]))  # 3072
print(emb_chunk.embedding_cost_usd)  # 0.00013 (per OpenAI pricing)
print(emb_chunk.embedding_latency_ms)  # 245ms (API call + processing)
```

**Software Stack**: 
- HTTPS POST to `api.openai.com/v1/embeddings`
- Bearer token authentication
- Batched 100 chunks per request (120 chunks = 2 API calls)
- Exponential backoff on rate limit
- Total cost: $0.016 for 120 chunks

#### 5. Storage: EmbeddedChunks → Persisted
```python
# Adapter: OpenSearchAdapter (Docker service)
storage = AdapterFactory.create_storage("opensearch", config)
storage.create_index(embedding_dimensions=3072)
storage.index_chunks(embedded, batch_size=100)

# Data: Stored in OpenSearch
# - 120 documents indexed
# - k-NN index built (HNSW with faiss)
# - BM25 inverted index built
# - Metadata indexed for filtering
```

**Software Stack**:
- HTTP client to `http://localhost:9200`
- Bulk API: 2 requests (100 + 20 chunks)
- OpenSearch handles index creation, sharding, replication

#### 6. Query: User asks question
```python
query = Query(text="What was the revenue growth in Q1?")
```

#### 7. Retrieval: Query → SearchResults
```python
# Adapter: HybridRRFRetriever (uses OpenSearchAdapter)
retriever = AdapterFactory.create_retrieval("hybrid_rrf", config, storage, embedding)
results = retriever.search(query, top_k=20)

# Data: List[SearchResult] (20 results)
result = results[0]
print(result.chunk.text)         # "Revenue increased 16% year-over-year..."
print(result.vector_score)       # 0.87 (cosine similarity)
print(result.bm25_score)         # 12.4 (BM25 score)
print(result.rrf_score)          # 0.041 (RRF combined)
```

**Software Stack**:
- Query embedding: OpenAI API call (same as indexing)
- OpenSearch hybrid query:
  - k-NN search: `POST /rag_chunks/_search` with `knn` clause
  - BM25 search: `POST /rag_chunks/_search` with `match` query
  - RRF fusion: Application-level (Python)

#### 8. Reranking: Refine top results
```python
# Adapter: FlashRankReranker (Python SDK, local)
reranker = AdapterFactory.create_reranking("flashrank", config)
reranked = reranker.rerank(query, results, top_k=8)

# Data: List[RerankedResult] (8 final results)
reranked_result = reranked[0]
print(reranked_result.rerank_score)  # 0.94 (cross-encoder score)
print(reranked_result.rerank_rank)   # 1 (top result)
```

**Software Stack**:
- Local inference with FlashRank (ms-marco-MiniLM-L-12-v2)
- CPU inference, ~50ms per query-doc pair
- No API cost

#### 9. Context Assembly
```python
# Data: RetrievalContext
context = RetrievalContext(
    query=query,
    results=reranked,
    total_latency_ms=450,
    retrieval_latency_ms=380,
    rerank_latency_ms=70,
)

# Format for LLM
llm_context = context.format_for_llm(max_chunks=5)
print(llm_context)
# [1] (score: 0.940)
# Revenue increased 16% year-over-year...
# Source: financial_report.pdf, Page 3
# ---
# [2] (score: 0.912)
# ...

citations = context.get_citations()
# [{"chunk_id": "...", "source": "financial_report.pdf", "page": 3, "score": 0.940}, ...]
```

### Summary of Software Stacks Used

| Component | Adapter | Stack Type | Communication |
|-----------|---------|------------|---------------|
| ETL | MinerUAdapter | Python SDK | Direct function call |
| Chunking | HybridSandwichChunker | Pure Python | In-process |
| Embedding (index) | OpenAIEmbeddingAdapter | REST API | HTTPS POST, Bearer auth |
| Storage | OpenSearchAdapter | Docker service | HTTP client (opensearch-py) |
| Embedding (query) | OpenAIEmbeddingAdapter | REST API | HTTPS POST |
| Retrieval | HybridRRFRetriever | Composite | Uses storage adapter |
| Reranking | FlashRankReranker | Python SDK | Local model inference |

**Key Insight**: 7 different software stacks, seamlessly integrated through standardized adapters. Swapping any component requires only a config change.

---

## ✅ Benefits of Adapter Architecture

### 1. **True Adaptability**
- Swap any component without touching orchestrator code
- Mix and match: MinerU + Voyage + Qdrant + Cohere reranker
- Runtime configuration per request

### 2. **Software-Stack Agnostic**
- Python SDKs, REST APIs, gRPC, CLI tools, Docker services—all hidden behind interfaces
- Orchestrator never handles HTTP, subprocess management, or connection pooling

### 3. **Fault Isolation**
- Adapter failure doesn't crash the system
- Graceful degradation: fallback to simpler model if API fails
- Rich error messages with adapter-specific context

### 4. **Cost Transparency**
- Every adapter tracks its cost (API calls, compute)
- Aggregate costs across pipeline: `context.total_cost_usd`
- Optimization engine can minimize cost

### 5. **Performance Optimization**
- Adapters handle batching transparently
- Connection pooling for network services
- GPU memory management for local models

### 6. **Testing & Debugging**
- Mock adapters for unit tests (no external dependencies)
- Capture intermediate outputs at every stage (RawDocument → Chunk → EmbeddedChunk → SearchResult)
- Lineage tracking: trace every chunk back to source document

### 7. **Plugin Architecture**
- Add new adapter: Implement interface + register with factory
- No orchestrator changes needed
- Community can contribute adapters for new services

---

## 🚀 Swapping Components: Examples

### Example 1: Switch Embedding Provider

**Scenario**: OpenAI is expensive for high-volume. Switch to local FastEmbed.

**Before** (`rag_config_schema.yaml`):
```yaml
embedding:
  provider: openai
  model: text-embedding-3-large
  dimensions: 3072
  api_key: ${OPENAI_API_KEY}
```

**After**:
```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-large-en-v1.5
  dimensions: 1024
```

**Result**: 
- ✅ Zero code changes
- ✅ No API costs (local inference)
- ✅ 3x faster (no network latency)
- ⚠️ Slightly lower accuracy (1024 dims vs 3072 dims)

**Orchestrator code unchanged**:
```python
embedding_adapter = AdapterFactory.create_embedding(config["provider"], config)
embedded = embedding_adapter.embed_chunks(chunks)  # Works for both!
```

### Example 2: Switch Storage Backend

**Scenario**: PostgreSQL can't handle scale. Switch to OpenSearch.

**Before**:
```yaml
storage:
  provider: postgresql
  host: localhost
  port: 5432
  table: embeddings
```

**After**:
```yaml
storage:
  provider: opensearch
  hosts:
    - http://localhost:9200
  index: rag_chunks
```

**Result**:
- ✅ Better performance (native k-NN + BM25)
- ✅ Horizontal scaling (sharding)
- ✅ Multiple embedding fields (hybrid strategies)

**Orchestrator code unchanged**:
```python
storage_adapter = AdapterFactory.create_storage(config["provider"], config)
storage_adapter.index_chunks(embedded_chunks)  # Works for both!
```

### Example 3: Multi-ETL Pipeline

**Scenario**: Use best extractor for each file type.

**Configuration**:
```yaml
etl:
  providers:
    - name: mineru
      formats: [".pdf"]  # Best for PDFs with tables
    - name: docling
      formats: [".docx", ".pptx"]  # Fast for Office files
    - name: unstructured
      formats: [".html", ".eml", ".xml"]  # Broad format support
```

**Orchestrator logic** (auto-select adapter):
```python
def get_etl_adapter(file_path: Path) -> ETLAdapter:
    for provider_config in config["etl"]["providers"]:
        adapter = AdapterFactory.create_etl(provider_config["name"], provider_config)
        if adapter.can_handle(file_path):
            return adapter
    raise ValueError(f"No adapter for {file_path.suffix}")

# Usage
adapter = get_etl_adapter(Path("report.pdf"))  # Returns MinerUAdapter
document = adapter.extract_from_file(file_path)
```

**Result**: Automatic best-tool selection based on file type.

---

## 🎓 Advanced Patterns

### Pattern 1: Adapter Chaining (Transformations)

**Use Case**: Apply multiple transformations after ETL

```python
class TransformationPipeline:
    def __init__(self, transformers: List[TransformationAdapter]):
        self.transformers = transformers
    
    def transform(self, document: RawDocument) -> RawDocument:
        for transformer in self.transformers:
            document = transformer.transform(document)
        return document

# Configuration
pipeline = TransformationPipeline([
    WhitespaceTransformer(),
    HeaderNormalizer(),
    SentenceMerger(),
    MetadataExtractor(),
])

clean_doc = pipeline.transform(raw_doc)
```

### Pattern 2: Adapter Composition (Multi-Stage Retrieval)

**Use Case**: Fast initial retrieval → precise reranking

```python
class MultiStageRetriever(RetrievalAdapter):
    def __init__(self, config, storage, embedding):
        super().__init__(config, storage, embedding)
        self.stage1_top_k = 100  # Fast, less precise
        self.stage2_top_k = 20   # Slow, very precise
    
    def search(self, query: Query, top_k: int) -> List[SearchResult]:
        # Stage 1: Vector-only (fast)
        stage1_retriever = VectorOnlyRetriever(self.config, self.storage, self.embedding)
        candidates = stage1_retriever.search(query, self.stage1_top_k)
        
        # Stage 2: Cross-encoder reranking (slow, precise)
        reranker = FlashRankReranker(self.config)
        reranked = reranker.rerank(query, candidates, self.stage2_top_k)
        
        return [r.search_result for r in reranked[:top_k]]
```

### Pattern 3: Fallback Chain (Reliability)

**Use Case**: Primary adapter fails → fallback to secondary

```python
class FallbackEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, primary: EmbeddingAdapter, fallback: EmbeddingAdapter):
        self.primary = primary
        self.fallback = fallback
    
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        try:
            return self.primary.embed_chunks(chunks)
        except EmbeddingAdapterError as e:
            logger.warning(f"Primary embedding failed: {e}. Using fallback.")
            return self.fallback.embed_chunks(chunks)

# Usage: OpenAI (primary) → FastEmbed (fallback if API down)
embedding_adapter = FallbackEmbeddingAdapter(
    primary=OpenAIEmbeddingAdapter(config),
    fallback=FastEmbedAdapter(config)
)
```

### Pattern 4: Cost-Aware Routing

**Use Case**: Use cheap model for bulk indexing, expensive model for critical queries

```python
class CostAwareEmbeddingRouter:
    def __init__(self, cheap: EmbeddingAdapter, expensive: EmbeddingAdapter):
        self.cheap = cheap      # FastEmbed (free, local)
        self.expensive = expensive  # OpenAI 3K ($$, best quality)
    
    def embed_for_indexing(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """Bulk indexing: use cheap model"""
        return self.cheap.embed_chunks(chunks)
    
    def embed_for_query(self, query_text: str) -> List[float]:
        """User query: use expensive model for best results"""
        return self.expensive.embed_query(query_text)
```

---

## 🧠 Agent Long-term Memory

The adapter pattern extends beyond RAG pipelines to enable **agent long-term memory** using OpenSearch.

### Memory Types

| Memory Type | Purpose | Examples |
|------------|---------|----------|
| **Episodic** | Conversation history | Past Q&A turns, tool usage, reasoning traces |
| **Semantic** | Facts & knowledge | "Microsoft Q1 revenue: $65.6B", learned concepts |
| **Procedural** | User preferences | Response style (concise/detailed), document format |
| **Entity** | People, places, things | Companies, executives, locations across documents |

### Key Features

1. **Hybrid Search**: Semantic (vector) + keyword search for accurate retrieval
2. **Temporal Decay**: Recent memories weighted higher, with automatic expiration
3. **Importance Levels**: CRITICAL (never expire), HIGH (30d), MEDIUM (7d), LOW (1d)
4. **Per-User Isolation**: Separate OpenSearch indices per user for privacy
5. **Access Tracking**: Frequently accessed memories get boosted in ranking

### Architecture

```
Agent Query → Memory Adapter.search_memories()
                     ↓
          OpenSearch Memory Indices
          ┌──────────────────────────┐
          │ episodic_user_123        │ Conversations
          │ semantic_user_123        │ Facts
          │ procedural_user_123      │ Preferences
          │ entity_user_123          │ Entities
          └──────────────────────────┘
                     ↓
          Memory Results (ranked by relevance + recency)
                     ↓
          Format as LLM Context
                     ↓
          Enhanced Agent Response
```

### Integration Example

```python
from adapter_memory import OpenSearchMemoryAdapter, EpisodicMemory, MemoryImportance

# Initialize memory adapter
memory_adapter = OpenSearchMemoryAdapter(
    storage=opensearch_adapter,
    embedding=fastembed_adapter,
    config={"opensearch_hosts": ["http://opensearch:9200"]}
)

# Store conversation
memory = EpisodicMemory(
    user_id="user_123",
    conversation_id="conv_456",
    user_message="What was Microsoft's Q1 revenue?",
    agent_response="Microsoft reported Q1 FY26 revenue of $65.6B, up 16% YoY.",
    importance=MemoryImportance.MEDIUM,
    tags=["finance", "microsoft"]
)
memory_adapter.store_memory(memory)

# Later: Search memories for context
results = memory_adapter.search_memories(
    query="Microsoft revenue discussion",
    user_id="user_123",
    top_k=5
)

# Add to agent prompt
context = format_memories_for_agent(results)
```

### Use Cases

- **Follow-up Questions**: "What did we discuss about X?" references previous conversation
- **Learning Preferences**: User says "be concise" → future responses auto-adjusted
- **Cross-Document Entities**: Track "Microsoft" across 10-Q, news, analyst reports
- **Fact Verification**: Check if learned fact contradicts new information

**See [`adapter_memory.py`](./adapter_memory.py) and [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md) for full implementation.**

---

## 📁 File Reference

| File | Purpose | Lines |
|------|---------|-------|
| [`adapter_dataflow_models.py`](./adapter_dataflow_models.py) | Standard data models (RawDocument, Chunk, EmbeddedChunk, etc.) | ~400 |
| [`adapter_base_classes.py`](./adapter_base_classes.py) | Abstract base classes for all adapters | ~500 |
| [`adapter_examples.py`](./adapter_examples.py) | Concrete adapter implementations (MinerU, Docling, OpenAI, etc.) | ~700 |
| [`adapter_memory.py`](./adapter_memory.py) | Agent long-term memory using OpenSearch | ~700 |
| [`rag_orchestrator.py`](./rag_orchestrator.py) | Orchestrator that uses adapters to execute pipeline | ~500 |
| [`rag_config_schema.yaml`](./rag_config_schema.yaml) | Configuration defining which adapters to use | ~500 |
| [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md) | Memory integration guide with examples | ~800 |

---

## 🎯 Summary: Why Adapters Enable Adaptability

1. **Software-Stack Agnostic**: Python SDKs, REST APIs, Docker services—all hidden behind interfaces
2. **Swappable Components**: Change config, not code
3. **Data Contracts**: Standard models (RawDocument, Chunk, EmbeddedChunk) enable interoperability
4. **Fault Isolation**: Adapter failures don't crash system
5. **Cost & Performance Tracking**: Every adapter reports metrics
6. **Plugin Architecture**: Add new adapters without modifying core
7. **Testable**: Mock adapters for unit tests
8. **Agent Memory**: Long-term episodic, semantic, procedural, and entity memory via OpenSearch

**The adapter pattern is the foundation that makes every other feature possible**—without it, the system would be tightly coupled to specific technologies and impossible to optimize or evolve.
