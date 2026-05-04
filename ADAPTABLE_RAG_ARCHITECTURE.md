# Adaptable Agentic RAG System - Architecture Design

**Date**: May 3, 2026  
**Version**: 1.0

> **📖 For a clear overview of the system's purpose, see [SYSTEM_PURPOSE.md](SYSTEM_PURPOSE.md)**
>
> **TL;DR**: This is primarily a **production Agentic RAG system** for answering questions about domain-specific documents (PDF/DOCX/HTML/etc.). The agent optimizer is a one-time setup tool that finds the best configuration, after which the system serves millions of queries on NEW documents in that domain.

> **🔌 SurfSense Integration**: This adapter architecture **extends your existing SurfSense deployment**—reusing the SurfSense web UI and backend (with DeepAgents framework). See [SURFSENSE_INTEGRATION_GUIDE.md](SURFSENSE_INTEGRATION_GUIDE.md) for deployment details.

---

## Executive Summary

This document describes the architecture for an **Adaptable Agentic RAG System** - a self-optimizing RAG pipeline that **automatically discovers the best configuration** for your specific documents and use case.

### 🎯 Core Purpose

Users provide:
1. **Example documents** (PDFs, financial reports, scientific papers, etc.)
2. **Golden standard Q&A dataset** (questions with expected answers)

The **Agent Orchestrator** then:
1. **Explores** all possible component combinations (ETL × Chunking × Embedding × Retrieval × Reranking)
2. **Evaluates** each configuration against the golden standard
3. **Optimizes** iteratively until no further improvement is found
4. **Returns** the best-performing configuration ready for production

### Why "Adaptable Agentic RAG"?

- **Adaptable** - Every component is modular and swappable (ETL, chunking, embedding, storage, retrieval, reranking)
- **Agentic** - Intelligent agent explores the configuration space and converges to optimal setup
- **Self-Optimizing** - No manual hyperparameter tuning; the system finds the best configuration automatically

### Key Capabilities

- **Automatic Configuration Discovery** - Agent tests ETL providers (MinerU/Docling/Unstructured), chunk sizes (128-1024), embedding models (local/cloud), retrieval strategies (hybrid/vector/BM25)
- **Golden Standard Evaluation** - Measures F1 score, exact match, latency, cost against user's Q&A dataset
- **Convergence Detection** - Stops optimization when performance plateaus
- **Pluggable Architecture** - 3 ETL providers, 6 embedding providers (including OpenAI 3K dims), 4 storage options, multiple retrieval strategies
- **Production Deployment** - Best configuration automatically deployed

---

## 🔌 Adapter Architecture: The Foundation of Adaptability

> **📖 For comprehensive details, see [ADAPTER_ARCHITECTURE.md](ADAPTER_ARCHITECTURE.md)**

**The adapter pattern is what makes this system truly adaptable.** Every component—from ETL extraction to embedding generation to storage—is accessed through standardized interfaces with well-defined data contracts. This enables:

### Benefits

✅ **Software-Stack Agnostic**: Components can be Python SDKs (MinerU, FastEmbed), REST APIs (OpenAI, Voyage, Cohere), Docker services (OpenSearch, PostgreSQL), or even CLI tools—orchestrator doesn't care  
✅ **Swappable Components**: Change ETL from MinerU to Docling, embedding from OpenAI to local FastEmbed, storage from PostgreSQL to OpenSearch—all via configuration, zero code changes  
✅ **Standard Data Flow**: All components communicate through typed data models (`RawDocument` → `Chunk` → `EmbeddedChunk` → `SearchResult`)  
✅ **Fault Isolation**: Adapter failure doesn't crash system; graceful degradation with fallback chains  
✅ **Cost Transparency**: Every adapter tracks its cost (API calls, compute), enabling cost-optimized configurations  
✅ **Testing & Debugging**: Mock adapters for unit tests; capture intermediate outputs at every stage  

### Core Adapters

| Adapter Type | Purpose | Examples | Data Contract |
|-------------|---------|----------|---------------|
| **ETLAdapter** | File → RawDocument | MinerU (Python SDK), Unstructured (REST API), Docling (async Python) | `extract_from_file(Path) → RawDocument` |
| **ChunkingAdapter** | RawDocument → Chunks | HybridSandwich, Recursive, Semantic | `chunk_document(RawDocument) → List[Chunk]` |
| **EmbeddingAdapter** | Chunks → EmbeddedChunks | OpenAI (REST API), FastEmbed (local), Voyage (REST API) | `embed_chunks(List[Chunk]) → List[EmbeddedChunk]` |
| **StorageAdapter** | Persist & Search | OpenSearch (Docker), PostgreSQL (Docker), Qdrant (Cloud) | `index_chunks(List[EmbeddedChunk])`, `search()` |
| **RetrievalAdapter** | Query → SearchResults | HybridRRF, VectorOnly, BM25Only | `search(Query, top_k) → List[SearchResult]` |
| **RerankingAdapter** | Refine Results | FlashRank (local), Cohere (API), Voyage (API) | `rerank(Query, List[SearchResult]) → List[RerankedResult]` |

### Data Flow Example

```
PDF Upload (bytes)
   │
   ▼ ETLAdapter.extract_from_bytes()
RawDocument (markdown content, tables, formulas)
   │
   ▼ ChunkingAdapter.chunk_document()
List[Chunk] (256-token chunks with prefix/suffix context)
   │
   ▼ EmbeddingAdapter.embed_chunks()
List[EmbeddedChunk] (3072-dim vectors, cost=$0.013)
   │
   ▼ StorageAdapter.index_chunks()
Persisted to OpenSearch (k-NN + BM25 index)
   │
   ▼ (User query) RetrievalAdapter.search()
List[SearchResult] (top 20, hybrid RRF scores)
   │
   ▼ RerankingAdapter.rerank()
List[RerankedResult] (top 8, cross-encoder refined)
   │
   ▼ RetrievalContext.format_for_llm()
LLM Context String + Citations
```

### Software Stack Handling

The power of the adapter pattern is that **each adapter encapsulates its software stack complexity**:

- **MinerU Adapter** (Python SDK): Direct import, GPU memory management, local inference
- **OpenAI Adapter** (REST API): HTTPS POST, Bearer auth, exponential backoff on rate limits, batch optimization
- **OpenSearch Adapter** (Docker service): HTTP client (opensearch-py), connection pooling, bulk insert
- **Cohere Adapter** (REST API): Binary compression handling, API versioning

**The orchestrator never deals with HTTP, subprocess management, connection pooling, or authentication**—adapters handle it all.

### Example: Swapping Embedding Provider

**Before** (config):
```yaml
embedding:
  provider: openai
  model: text-embedding-3-large
  api_key: ${OPENAI_API_KEY}
```

**After** (change config only):
```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-large-en-v1.5
```

**Result**: Zero code changes, no API costs (local inference), 3x faster

**Key Files**:
- [`adapter_dataflow_models.py`](./adapter_dataflow_models.py) - Standard data models (RawDocument, Chunk, EmbeddedChunk, etc.)
- [`adapter_base_classes.py`](./adapter_base_classes.py) - Abstract base classes for all adapters
- [`adapter_examples.py`](./adapter_examples.py) - Concrete implementations (MinerU, OpenAI, OpenSearch, FlashRank)
- [`ADAPTER_ARCHITECTURE.md`](./ADAPTER_ARCHITECTURE.md) - Comprehensive adapter pattern documentation

---

## Architecture Overview

### Phase 1: Automatic Configuration Discovery (Core Workflow)

```
┌─────────────────────────────────────────────────────────────┐
│                   USER UPLOADS                              │
│  1. Documents:  msft_fy26q1_10q.pdf                         │
│  2. Golden Q&A: [{q: "What was Q1 revenue?",                │
│                   a: "$65.6 billion"}] × 100                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│          AGENT ORCHESTRATOR (Optimization Engine)           │
│                                                             │
│  LOOP until convergence (no improvement for N iterations):  │
│                                                             │
│  1. Generate Configuration Candidates                       │
│     ├─ ETL: [mineru, docling, unstructured]                │
│     ├─ Chunk Size: [128, 256, 512, 1024]                   │
│     ├─ Embedding: [fastembed, openai-3k, voyage-finance]   │
│     ├─ Retrieval: [hybrid_rrf, vector_only, bm25_only]     │
│     └─ Reranking: [enabled, disabled]                      │
│                                                             │
│  2. Evaluate Each Configuration                            │
│     ├─ Index documents with config                         │
│     ├─ Run all 100 golden Q&A queries                      │
│     ├─ Compute: F1 score, exact match, latency, cost       │
│     └─ Store results                                        │
│                                                             │
│  3. Selection & Mutation                                    │
│     ├─ Select top K performers                             │
│     ├─ Generate new candidates (crossover/mutation)        │
│     └─ Check convergence criterion                         │
│                                                             │
│  4. Output Best Configuration                              │
│     └─ Deploy to production profile                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              OPTIMIZED CONFIGURATION                        │
│  Example Output:                                            │
│    etl: mineru (F1: 0.89)  ← Best for tables               │
│    chunk_size: 256         ← Optimal balance                │
│    embedding: voyage-finance-2 ← Domain-specific            │
│    retrieval: hybrid_rrf (k=60)                            │
│    reranking: enabled                                       │
│  Performance: 89.6% F1, 350ms P95, $0.008/query            │
└─────────────────────────────────────────────────────────────┘
```

### Phase 2: Production Inference (Using Discovered Config)

```
┌────────────────────────────────────────────────────────────┐
│                     USER QUERY                             │
│         "What was Microsoft's Q1 FY26 revenue?"            │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────┐
│              RAG ORCHESTRATOR                              │
│  • Loads OPTIMIZED configuration (from Phase 1)            │
│  • Executes RAG pipeline with best components              │
│  • Returns answer with confidence                          │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────┐
│           MODULAR PIPELINE COMPONENTS                      │
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌─────────────┐ ┌──────────────┐
│ ETL Pipeline │ │  Chunking   │ │  Embedding   │
│              │ │   Strategy  │ │    Model     │
├──────────────┤ ├─────────────┤ ├──────────────┤
│• MinerU ⭐   │ │• Sandwich   │ │• MiniLM-L6   │
│• Docling     │ │• Recursive  │ │• BGE-base    │
│• Unstruct.   │ │• Semantic   │ │• OpenAI 3K🔥 │
│+ Transform   │ │• Code-aware │ │• Voyage      │
│  Pipeline    │ │             │ │• Cohere      │
└──────┬───────┘ └──────┬──────┘ └──────┬───────┘
       │                │               │
       └────────────────┼───────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              STORAGE & INDEXING                             │
│  • OpenSearch 2.11 (primary) - k-NN + BM25 + multi-embed    │
│  • PostgreSQL 17 (app metadata only)                        │
│  • Pluggable: Qdrant, Weaviate, Milvus                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│            RETRIEVAL ENGINE                                 │
│  Strategies:                                                │
│    • hybrid_rrf    : Vector + BM25 fusion (RRF k=60) ⭐      │
│    • vector_only   : Pure semantic search                   │
│    • bm25_only     : Pure keyword search (OpenSearch)       │
│    • multi_stage   : Coarse-to-fine retrieval               │
│  OpenSearch native: multiple embeddings per chunk!          │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          POST-PROCESSING                                    │
│  • Reranking (FlashRank, Cohere, Voyage)                    │
│  • Adjacent chunk expansion (sandwich context)              │
│  • Deduplication                                            │
│  • Result fusion                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          CONTEXT BUILDING                                   │
│  Formats:                                                   │
│    • xml_filesystem  : Virtual file system (current)        │
│    • markdown        : Markdown sections                    │
│    • json_chunks     : Structured JSON                      │
│    • plain_text      : Simple concatenation                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│             AGENT GENERATION                                │
│  • DeepAgents framework with middleware stack               │
│  • Multi-model LLM routing (via global_llm_config.yaml)     │
│  • Tool selection (read_file, ls, search_knowledge_base)    │
│  • Dynamic prompt templating                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          FEEDBACK & OPTIMIZATION                            │
│  • Metrics tracking (latency, accuracy, cost)               │
│  • Experiment management (grid search, Bayesian opt)        │
│  • A/B testing (traffic splitting)                          │
│  • Auto-tuning (future: RL-based optimization)              │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 0. Agent Orchestrator (Optimization Engine) - **THE CORE**

**File**: `agent_optimizer.py` (NEW)

**Primary Responsibility**: Automatically discover the best RAG configuration for user's documents and golden Q&A dataset.

**Key Methods**:
```python
class AgentOptimizer:
    def optimize(
        self,
        documents: List[Path],
        golden_qa: List[Dict[str, str]],  # [{"question": ..., "answer": ...}]
        optimization_config: OptimizationConfig
    ) -> OptimizedRAGConfig:
        """
        Main optimization loop:
        1. Generate initial configuration population
        2. Evaluate each config on golden Q&A dataset
        3. Select top performers
        4. Generate new candidates (mutation/crossover)
        5. Repeat until convergence
        6. Return best configuration
        """
    
    def _generate_candidates(self) -> List[RAGConfig]:
        """Generate configuration combinations to test"""
    
    def _evaluate_config(self, config: RAGConfig, golden_qa: List) -> Metrics:
        """
        Evaluate a configuration:
        - Index documents with config
        - Run all golden Q&A queries
        - Compute F1, exact match, latency, cost
        """
    
    def _check_convergence(self, history: List[Metrics]) -> bool:
        """
        Check if optimization has converged:
        - No improvement in last N iterations
        - Performance plateau reached
        """
```

**Optimization Strategies**:
1. **Grid Search** - Exhaustive search over discrete parameters
2. **Random Search** - Sample configurations randomly
3. **Bayesian Optimization** - Model performance and explore high-potential areas
4. **Genetic Algorithm** - Evolve configurations through selection/crossover/mutation
5. **Multi-Armed Bandit** - Balance exploration vs exploitation

**Convergence Criteria**:
- No improvement for `patience` iterations (e.g., 10)
- Performance delta < `min_delta` (e.g., 0.1% F1)
- Maximum iterations reached
- Budget exhausted (time or cost)

### 1. Configuration System

**Files**:
- `rag_config_schema.yaml` - Master configuration with all profiles
- `rag_config_manager.py` - Configuration loader and manager
- `agent_optimizer.py` - **Auto-optimization agent (NEW)**
- `global_llm_config.yaml` - LLM model configurations (existing)

**Features**:
- **Component modularity** - Every component swappable (ETL, chunking, embedding, retrieval, reranking)
- **Search space definition** - Define valid component combinations and parameter ranges
- **Profile inheritance** - Build new configs from base templates
- **Component registry** - Map component names to implementation classes

**Example Config**:
```yaml
profiles:
  production:
    chunking:
      strategy: "hybrid_sandwich"
      config:
        chunk_size: 256
    retrieval:
      strategy: "hybrid_rrf"
      config:
        rrf_k: 60
        max_chunks_per_document: 20
  
  experimental_512:
    inherits: "production"
    overrides:
      chunking:
        config:
          chunk_size: 512
```

### 2. RAG Orchestrator

**File**: `rag_orchestrator.py`

**Dual Purpose**:
1. **During Optimization** - Agent Optimizer calls orchestrator to evaluate each configuration candidate
2. **During Production** - End-users call orchestrator with optimized configuration to get answers

**Responsibilities**:
- Load configuration dynamically (support runtime config swapping)
- Instantiate components on-demand (ETL, chunking, embedding, retrieval, reranking)
- Execute full RAG pipeline for a query
- Track performance metrics (latency, cost, chunks retrieved)
- Support fast component cleanup (critical for agent optimization loop)

**Key Methods**:
```python
class RAGOrchestrator:
    def execute(self, request: RAGRequest, config: RAGConfig) -> RAGResult:
        \"\"\"
        Execute RAG pipeline with given configuration.
        Used by:
        - Agent Optimizer during evaluation (thousands of calls)
        - Production users for queries (optimized config loaded once)
        \"\"\"
        
    def _get_etl_provider(self, config: RAGConfig) -> ETLInterface:
        \"\"\"Instantiate ETL component (mineru/docling/unstructured)\"\"\"
    
    def _get_embedding_provider(self, config: RAGConfig) -> EmbeddingInterface:
        \"\"\"Instantiate embedding model (fastembed/openai/voyage/cohere)\"\"\"
    
    def _get_retriever(self, config: RAGConfig) -> RetrieverInterface:
        \"\"\"Instantiate retrieval strategy (hybrid_rrf/vector_only/bm25_only)\"\"\"
    
    def _get_reranker(self, config: RAGConfig) -> RerankerInterface:
        \"\"\"Instantiate reranker (flashrank/cohere/voyage)\"\"\"
    
    def cleanup(self):
        \"\"\"Release resources (important for agent optimization loop)\"\"\"
```

**Critical for Agent Optimization**:
- Must support **fast component swapping** (agent tests 100+ configs)
- Must track **detailed metrics** (F1, latency, cost) for each config
- Must **cleanup resources** properly (avoid memory leaks during optimization)

### 3. Component Interfaces

**Pluggable Components**:

1. **EmbeddingInterface** - Abstract base for embedding providers
   - `embed(text)` - Generate single embedding
   - `embed_batch(texts)` - Batch embedding generation

2. **RetrieverInterface** - Abstract base for retrieval strategies
   - `retrieve(query, embedding, top_k, ...)` - Retrieve relevant chunks

3. **RerankerInterface** - Abstract base for rerankers
   - `rerank(query, chunks, top_k)` - Rerank chunks by relevance

**Adapters** wrap existing implementations to match interfaces:
- `FastEmbedAdapter` → wraps `fastembed.TextEmbedding`
- `OpenAIEmbedAdapter` → wraps OpenAI API client
- `CohereEmbedAdapter` → wraps Cohere API client
- `VoyageEmbedAdapter` → wraps Voyage API client
- `OpenSearchAdapter` → wraps `opensearchpy` client (replaces PostgreSQL storage)
- `MinerUAdapter` → wraps `magic-pdf` MinerU service
- `DoclingAdapter` → wraps existing Docling service
- `HybridRRFAdapter` → wraps `ChucksHybridSearchRetriever`
- `FlashRankAdapter` → wraps `rerankers.Reranker`

### 4. Agent Integration

**File**: `rag_expansion_patch/chat_deepagent.py` (existing)

**Integration Points**:
1. **Pre-search middleware** - Uses RAG orchestrator for initial retrieval
2. **Tool: search_knowledge_base** - Calls orchestrator with dynamic config
3. **Context building** - Orchestrator builds XML filesystem
4. **Metrics feedback** - Agent performance feeds back to optimizer

**Agent Routing Example**:
```python
# Agent detects financial query → routes to "production" profile
request = RAGRequest(
    query="What was Q1 FY26 revenue?",
    search_space_id=1
)
result = await orchestrator.execute(request)
# Uses: sandwich chunking, 256 tokens, hybrid RRF, reranking enabled
```

---

## Configuration Profiles

**Note**: These profiles are **examples of what the agent optimizer might discover**, not manually pre-configured static profiles. The agent explores the search space and automatically finds the best configuration for your specific documents and golden Q&A dataset.

### Example: Discovered Profile for Financial Documents
**Use Case**: Agent optimized for MSFT 10-Q Q&A (discovered automatically)

```yaml
# This configuration was discovered by the agent optimizer
# after testing 120 candidate configurations
profile_name: \"financial_optimized\"
discovered_by: agent_optimizer_v1
optimization_date: \"2026-05-03\"
golden_qa_dataset: \"msft_fy26q1_qa_benchmark_100.json\"
f1_score: 0.881  # 88.1% (improved from 78.3% baseline)

etl:
  provider: mineru  # Agent discovered: MinerU best for table extraction
  config:
    detect_tables: true
    detect_formulas: true
    transformations:
      - clean_whitespace
      - normalize_headers
      - merge_split_sentences

chunking:
  strategy: hybrid_sandwich
  config:
    chunk_size: 256  # Agent tested: 128, 256, 512, 1024 → 256 optimal

embedding:
  provider: voyage  # Agent discovered: domain-specific beats general models
  model: voyage-finance-2
  config:
    dimensions: 1024
    max_seq_length: 32000  # Large context useful for financial docs

storage:
  provider: opensearch
  config:
    knn_algo_params:
      ef_search: 256  # Agent tuned: 128, 256, 512 → 256 optimal

retrieval:
  strategy: hybrid_rrf
  config:
    rrf_k: 40  # Agent tuned: 20, 40, 60, 100 → 40 optimal
    max_chunks_per_document: 20

reranking:
  enabled: true  # Agent discovered: +2.3% F1 improvement
  provider: flashrank
  model: ms-marco-MiniLM-L-12-v2
  config:
    top_k: 30
```

**Performance**: 88.1% F1 score, 380ms P95 latency, $0.005/query

**What the Agent Learned**:
- ✅ MinerU superior to Docling for financial PDFs (table extraction critical)
- ✅ Domain-specific Voyage Finance embedding outperforms general models (+4.2% F1)
- ✅ Chunk size 256 optimal (128 too small, 512+ loses context)
- ✅ RRF constant k=40 better than default k=60 for this corpus
- ✅ Reranking worth the +80ms latency for +2.3% F1 improvement

### Example: Alternative Discovery for Cost-Sensitive Use Case
**Agent optimized for budget constraint: <$0.001/query**

```yaml
profile_name: \"financial_budget_optimized\"
f1_score: 0.817  # 81.7% (vs 88.1% premium config)
cost_per_query: 0.0008  # 6x cheaper!

etl:
  provider: docling  # Faster, good enough for simple tables

embedding:
  provider: fastembed  # Local, FREE
  model: bge-base-en-v1.5
  config:
    dimensions: 768

retrieval:
  strategy: vector_only  # Skip BM25 for speed
  
reranking:
  enabled: false  # Skip to save cost (-2.3% F1, but -$0.001/query)
```

**Trade-off**: -6.4% F1 for 6x cost reduction. Agent discovered this Pareto-optimal point!

### Starting Point: Baseline Profile
**Use Case**: Initial configuration before optimization runs

```yaml
profile_name: \"baseline\"
# Simple, fast, reasonable defaults
# Agent will test variations and improve from here

```yaml
etl:
  provider: mineru  # Advanced table/formula extraction
  config:
    detect_tables: true
    detect_formulas: true
    transformations:
      - clean_whitespace
      - normalize_headers
      - fix_list_formatting
      - merge_split_sentences
chunking:
  strategy: hybrid_sandwich
  chunk_size: 256
embedding:
  provider: fastembed
  model: all-MiniLM-L6-v2
  config:
    dimensions: 384
    max_seq_length: 256
storage:
  provider: opensearch
  config:
    hosts: ["opensearch:9200"]
    knn_algo_params:
      engine: nmslib
      ef_construction: 512
      ef_search: 512
retrieval:
  strategy: hybrid_rrf
  rrf_k: 60
  max_chunks_per_document: 20
reranking:
  enabled: true
  model: ms-marco-MiniLM-L-12-v2
```

**Performance**: 80% accuracy on MSFT benchmark, 300ms p95 latency

### Experimental_512 Profile
**Use Case**: Test larger chunk sizes for better context

```yaml
inherits: production
overrides:
  chunking.config.chunk_size: 512
  embedding.config.max_seq_length: 512
  retrieval.config.max_chunks_per_document: 10
```

### High_Accuracy Profile
**Use Case**: Maximum context for complex queries (trades latency for accuracy)

```yaml
inherits: production
overrides:
  retrieval:
    config:
      top_k_multiplier: 10
      max_chunks_per_document: 50
      total_chunks_limit: 100
      adjacent_expansion:
        expand_before: 2
        expand_after: 2
  reranking:
    config:
      top_k: 100
```

### Fast_Cheap Profile
**Use Case**: Quick answers with minimal compute (for simple queries)

```yaml
inherits: production
overrides:
  retrieval:
    strategy: vector_only
    config:
      total_chunks_limit: 10
  reranking:
    enabled: false
```

---

## Agent Routing Rules

The system automatically selects the best configuration based on:

### 1. Query Classification
```yaml
agent_routing_rules:
  query_classification:
    rules:
      - condition: "query contains financial terms"
        profile: "production"
      
      - condition: "query is code-related"
        profile: "code_specialist"
        overrides:
          chunking.strategy: "code_aware"
      
      - condition: "query needs latest info"
        overrides:
          generation.config.enabled_tools:
            - "web_search"
            - "search_knowledge_base"
```

### 2. Document Count
```yaml
document_count_rules:
  - condition: "document_count < 10"
    overrides:
      retrieval.config.total_chunks_limit: 50
  
  - condition: "document_count > 1000"
    profile: "fast_cheap"
```

### 3. User Preferences
```yaml
user_preferences:
  quality_over_speed:
    profile: "high_accuracy"
  
  speed_over_quality:
    profile: "fast_cheap"
```

---

## Automatic Optimization Framework (CORE FEATURE)

### User Workflow: From Documents to Optimized RAG

```python
# Step 1: User uploads documents and golden Q&A dataset
from agent_optimizer import AgentOptimizer

optimizer = AgentOptimizer()

# User provides:
documents = ["msft_fy26q1_10q.pdf", "msft_annual_report.pdf"]
golden_qa = [
    {"question": "What was Q1 FY26 revenue?", "answer": "$65.6 billion"},
    {"question": "What was operating income?", "answer": "$30.6 billion"},
    # ... 100 total Q&A pairs
]

# Step 2: Agent automatically finds best configuration
best_config = optimizer.optimize(
    documents=documents,
    golden_qa=golden_qa,
    optimization_config={
        "strategy": "bayesian",  # or grid_search, genetic, random
        "max_iterations": 100,
        "patience": 10,  # Stop if no improvement for 10 iterations
        "parallel_evaluations": 4,  # Run 4 configs in parallel
        "metrics": ["f1_score", "latency_p95", "cost_per_query"],
        "primary_metric": "f1_score",  # Optimize for this
    }
)

# Step 3: System returns optimized configuration
print(f"Best F1 Score: {best_config.metrics['f1_score']:.3f}")
print(f"Configuration: {best_config.to_yaml()}")

# Step 4: Deploy to production
best_config.deploy(profile_name="production_optimized")
```

### Configuration Search Space

**The agent explores ALL combinations of:**

```yaml
search_space:
  # ETL Pipeline (3 options)
  etl.provider: [mineru, docling, unstructured]
  etl.config.detect_tables: [true, false]
  etl.config.transformations: [
    [clean_whitespace, normalize_headers],
    [clean_whitespace, normalize_headers, merge_split_sentences],
    # ... multiple transformation pipelines
  ]
  
  # Chunking (16 combinations)
  chunking.strategy: [hybrid_sandwich, recursive, semantic]
  chunking.config.chunk_size: [128, 256, 512, 1024]
  chunking.config.chunk_overlap: [0, 32, 64]
  
  # Embedding (15+ models across 6 providers)
  embedding.provider: [fastembed, openai, cohere, voyage, google, jina]
  embedding.model: [
    # FastEmbed (local, free)
    "all-MiniLM-L6-v2",           # 384 dims
    "bge-base-en-v1.5",           # 768 dims
    "bge-large-en-v1.5",          # 1024 dims
    
    # OpenAI (cloud, high quality)
    "text-embedding-3-small",     # 1536 dims
    "text-embedding-3-large",     # 3072 dims 🔥
    
    # Voyage (domain-specific)
    "voyage-finance-2",           # 1024 dims, 32K context
    "voyage-law-2",
    "voyage-code-2",
    
    # Cohere (compression)
    "embed-english-v3.0",         # 1024 dims + binary
    
    # Google (cost-effective)
    "text-embedding-004",         # 768 dims
    
    # Jina (long context)
    "jina-embeddings-v2-base",    # 768 dims, 8K context
  ]
  
  # Storage (4 options)
  storage.provider: [opensearch, postgresql_pgvector, qdrant, weaviate]
  storage.config.knn_algo_params.ef_search: [128, 256, 512]
  
  # Retrieval (12 combinations)
  retrieval.strategy: [hybrid_rrf, vector_only, bm25_only]
  retrieval.config.rrf_k: [20, 40, 60, 100]
  retrieval.config.max_chunks_per_document: [10, 20, 30, 50]
  
  # Reranking (8 combinations)
  reranking.enabled: [true, false]
  reranking.provider: [flashrank, cohere, voyage]
  reranking.config.top_k: [10, 20, 30, 50]
  
  # Adjacent Expansion
  retrieval.config.adjacent_expansion.enabled: [true, false]
  retrieval.config.adjacent_expansion.expand_before: [1, 2, 3]
  retrieval.config.adjacent_expansion.expand_after: [1, 2, 3]
```

**Total Search Space Size**: ~50,000+ possible configurations!

### Evaluation Metrics

**Primary Metrics** (computed against golden Q&A):
- **F1 Score** - Token-level overlap between generated and expected answer
- **Exact Match** - Binary match (0 or 1)
- **Semantic Similarity** - Embedding cosine similarity
- **ROUGE-L** - Longest common subsequence
- **BLEU** - N-gram precision

**Secondary Metrics** (operational):
- **Latency P50/P95/P99** - Response time percentiles
- **Cost per Query** - Embedding + retrieval + reranking + LLM costs
- **Throughput** - Queries per second

**Combined Objective** (multi-objective optimization):
```python
objective = (
    0.7 * f1_score +           # 70% weight on quality
    0.2 * (1 - latency_norm) + # 20% weight on speed
    0.1 * (1 - cost_norm)      # 10% weight on cost
)
```

### Optimization Strategies

#### 1. **Bayesian Optimization** (Recommended for continuous params)
```yaml
optimization:
  strategy: bayesian
  max_iterations: 100
  initial_random_samples: 20  # Explore randomly first
  acquisition_function: expected_improvement
  kernel: matern52
```

**Pros**: Efficient for expensive evaluations, learns from past configs  
**Cons**: Struggles with categorical variables (ETL provider, embedding model)

#### 2. **Genetic Algorithm** (Recommended for mixed discrete/continuous)
```yaml
optimization:
  strategy: genetic
  population_size: 20
  generations: 50
  mutation_rate: 0.1
  crossover_rate: 0.7
  selection_method: tournament
  elitism: 0.2  # Keep top 20% each generation
```

**Pros**: Handles discrete choices well, explores diverse configs  
**Cons**: Requires more evaluations than Bayesian

#### 3. **Grid Search** (Exhaustive but expensive)
```yaml
optimization:
  strategy: grid_search
  parameters:
    chunking.config.chunk_size: [128, 256, 512]
    embedding.model: ["bge-base-en-v1.5", "voyage-finance-2", "text-embedding-3-large"]
    retrieval.config.rrf_k: [20, 60, 100]
  # Total: 3 × 3 × 3 = 27 configurations
```

**Pros**: Guaranteed to find best in search space  
**Cons**: Exponential growth, infeasible for large spaces

#### 4. **Random Search** (Baseline)
```yaml
optimization:
  strategy: random
  num_samples: 50  # Try 50 random configurations
```

**Pros**: Simple, parallelizable, often beats grid search  
**Cons**: No learning, might miss optimal regions

### Convergence Detection

```python
def check_convergence(optimization_history: List[Metrics]) -> bool:
    """
    Stop optimization when:
    1. No improvement for `patience` iterations
    2. Performance delta < min_delta
    3. Max iterations reached
    """
    if len(optimization_history) < patience:
        return False
    
    # Check last N iterations
    recent_scores = [h.f1_score for h in optimization_history[-patience:]]
    best_recent = max(recent_scores)
    best_overall = max(h.f1_score for h in optimization_history)
    
    improvement = best_recent - (best_overall - recent_scores[0])
    
    return improvement < min_delta  # e.g., 0.001 (0.1% F1)
```

### Example Optimization Run

```
=== Agent Optimizer Started ===
Documents: 1 PDF (MSFT FY26Q1 10-Q)
Golden Q&A: 100 questions
Strategy: Bayesian Optimization
Max Iterations: 100
Patience: 10 iterations

Iteration 1: Random exploration
  Config: mineru, chunk=256, embedding=bge-base, hybrid_rrf
  F1: 0.783, Latency: 320ms, Cost: $0.002/query
  ✓ New best!

Iteration 5: Trying larger embeddings
  Config: mineru, chunk=256, embedding=openai-3k, hybrid_rrf
  F1: 0.852, Latency: 420ms, Cost: $0.008/query
  ✓ New best! (+6.9% F1)

Iteration 12: Domain-specific embedding
  Config: mineru, chunk=256, embedding=voyage-finance, hybrid_rrf
  F1: 0.874, Latency: 390ms, Cost: $0.005/query
  ✓ New best! (+2.2% F1)

Iteration 18: Tuning RRF constant
  Config: mineru, chunk=256, embedding=voyage-finance, hybrid_rrf(k=40)
  F1: 0.881, Latency: 380ms, Cost: $0.005/query
  ✓ New best! (+0.7% F1)

Iteration 25-35: No improvement (plateau detected)

=== Optimization Converged ===
Best Configuration Found:
  ETL: mineru (table extraction enabled)
  Chunk Size: 256 tokens
  Embedding: voyage-finance-2 (1024 dims, domain-specific)
  Retrieval: hybrid_rrf (k=40)
  Reranking: flashrank (top_k=30)
  
Performance:
  F1 Score: 0.881 (88.1%)
  Latency P95: 420ms
  Cost/Query: $0.005
  
Improvement over baseline: +9.8% F1

Configuration saved to: production_optimized.yaml
```

---

## Docker Infrastructure

> **🔌 Full deployment details**: See [SURFSENSE_INTEGRATION_GUIDE.md](SURFSENSE_INTEGRATION_GUIDE.md) for complete SurfSense integration instructions.

### Services Overview

The adapter architecture integrates with your **existing SurfSense deployment** via Docker Compose. All services run on a **single machine**:

```yaml
# docker-compose-adaptable-rag.yml
services:
  # ── Vector Storage ──
  opensearch:
    image: opensearchproject/opensearch:2.11.1
    ports:
      - "9200:9200"  # REST API
      - "9600:9600"  # Performance Analyzer
    environment:
      - discovery.type=single-node
      - "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g"
      - "DISABLE_SECURITY_PLUGIN=true"  # Dev mode
    volumes:
      - opensearch_data:/usr/share/opensearch/data
  
  # ── Monitoring (Optional) ──
  opensearch-dashboards:
    image: opensearchproject/opensearch-dashboards:2.11.1
    ports:
      - "5601:5601"
    environment:
      OPENSEARCH_HOSTS: '["http://opensearch:9200"]'
    profiles:
      - monitoring  # Start with: docker-compose --profile monitoring up
  
  # ── Application Data ──
  db:
    image: postgres:17-alpine  # No pgvector extension needed
    environment:
      POSTGRES_USER: surfsense
      POSTGRES_PASSWORD: surfsense
      POSTGRES_DB: surfsense
  
  # ── Cache & Message Queue ──
  redis:
    image: redis:8-alpine
  
  # ── SurfSense Backend (Extended with Adapters) ──
  backend:
    image: ghcr.io/modsetter/surfsense-backend:latest
    ports:
      - "8929:8000"
    volumes:
      # Adapter Architecture (Volume Mounts)
      - ./adapter_base_classes.py:/app/app/adapters/adapter_base_classes.py:ro
      - ./adapter_dataflow_models.py:/app/app/adapters/adapter_dataflow_models.py:ro
      - ./adapter_examples.py:/app/app/adapters/adapter_examples.py:ro
      
      # RAG Configuration
      - ./rag_config_schema.yaml:/app/app/config/rag_config_schema.yaml:ro
      - ./rag_config_manager.py:/app/app/rag_config_manager.py:ro
      - ./rag_orchestrator.py:/app/app/rag_orchestrator.py:ro
      
      # Component Patches (Use adapters)
      - ./document_chunker_patch.py:/app/app/indexing_pipeline/document_chunker.py:ro
      - ./chunks_hybrid_search_patched.py:/app/app/retriever/chunks_hybrid_search.py:ro
    environment:
      # RAG Configuration
      RAG_CONFIG_PATH: /app/app/config/rag_config_schema.yaml
      RAG_ACTIVE_PROFILE: ${RAG_ACTIVE_PROFILE:-production}
      
      # Adapter Configuration
      ETL_PROVIDER: ${ETL_PROVIDER:-mineru}
      EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER:-openai}
      OPENSEARCH_HOSTS: http://opensearch:9200
      
      # API Keys
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      COHERE_API_KEY: ${COHERE_API_KEY}
      VOYAGE_API_KEY: ${VOYAGE_API_KEY}
  
  # ── Background Workers ──
  celery_worker:
    image: ghcr.io/modsetter/surfsense-backend:latest
    volumes:
      # Same adapter mounts as backend
      - ./adapter_base_classes.py:/app/app/adapters/adapter_base_classes.py:ro
      - ./adapter_dataflow_models.py:/app/app/adapters/adapter_dataflow_models.py:ro
      - ./adapter_examples.py:/app/app/adapters/adapter_examples.py:ro
      - ./rag_config_schema.yaml:/app/app/config/rag_config_schema.yaml:ro
    environment:
      SERVICE_ROLE: worker
  
  # ── SurfSense Web UI ──
  frontend:
    image: ghcr.io/modsetter/surfsense-web:latest
    ports:
      - "3929:3000"
    environment:
      NEXT_PUBLIC_FASTAPI_BACKEND_URL: http://localhost:8929
      RAG_ENABLE_AB_TESTING: "false"
      
      # Storage
      OPENSEARCH_HOSTS: http://opensearch:9200
      
      # Embedding provider API keys
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      COHERE_API_KEY: ${COHERE_API_KEY:-}
      VOYAGE_API_KEY: ${VOYAGE_API_KEY:-}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY:-}
      JINA_API_KEY: ${JINA_API_KEY:-}
    depends_on:
      - opensearch
      - db
      - redis
  
  # Celery worker for async tasks
  celery_worker:
    image: ghcr.io/modsetter/surfsense-backend:latest
    volumes:
      - ./rag_config_schema.yaml:/app/app/config/rag_config_schema.yaml:ro
  
  # Frontend
  frontend:
    image: ghcr.io/modsetter/surfsense-web:latest
```

---

## Usage Examples

### PRIMARY USE CASE: Automatic Configuration Discovery

```python
from agent_optimizer import AgentOptimizer
import json

# ============================================================================
# Step 1: User uploads documents and golden Q&A dataset
# ============================================================================

# Documents to optimize for
documents = [
    "msft_fy26q1_10q.pdf",
    "msft_annual_report_2025.pdf"
]

# Golden standard Q&A dataset (100 examples)
with open("msft_fy26q1_qa_benchmark_100.json") as f:
    golden_qa = json.load(f)
    
# Example format:
# [
#     {"question": "What was Q1 FY26 revenue?", "answer": "$65.6 billion"},
#     {"question": "What was operating income?", "answer": "$30.6 billion"},
#     ...
# ]

# ============================================================================
# Step 2: Run agent optimizer to discover best configuration
# ============================================================================

optimizer = AgentOptimizer()

best_config = optimizer.optimize(
    documents=documents,
    golden_qa=golden_qa,
    optimization_config={
        "strategy": "bayesian",  # bayesian | genetic | grid_search | random
        "max_iterations": 100,
        "patience": 10,  # Stop if no improvement for 10 iterations
        "parallel_evaluations": 4,  # Run 4 configs simultaneously
        
        # Metrics to track
        "metrics": ["f1_score", "exact_match", "latency_p95", "cost_per_query"],
        "primary_metric": "f1_score",  # Optimize for this
        
        # Multi-objective optimization (optional)
        "objective_weights": {
            "f1_score": 0.7,      # 70% weight on quality
            "latency_p95": 0.2,   # 20% on speed (lower is better)
            "cost_per_query": 0.1 # 10% on cost (lower is better)
        },
        
        # Constraints (optional)
        "constraints": {
            "max_latency_p95": 500,  # ms
            "max_cost_per_query": 0.01  # dollars
        }
    }
)

# ============================================================================
# Step 3: Agent returns optimized configuration
# ============================================================================

print("=== Optimization Complete ===")
print(f"Best F1 Score: {best_config.metrics['f1_score']:.3f}")
print(f"Latency P95: {best_config.metrics['latency_p95']:.0f}ms")
print(f"Cost/Query: ${best_config.metrics['cost_per_query']:.4f}")
print()
print("Configuration:")
print(f"  ETL: {best_config.etl.provider}")
print(f"  Chunk Size: {best_config.chunking.config.chunk_size}")
print(f"  Embedding: {best_config.embedding.provider}/{best_config.embedding.model}")
print(f"  Retrieval: {best_config.retrieval.strategy}")
print(f"  Reranking: {'enabled' if best_config.reranking.enabled else 'disabled'}")
print()
print(f"Improvement over baseline: +{best_config.improvement_percent:.1f}% F1")

# ============================================================================
# Step 4: Deploy optimized configuration to production
# ============================================================================

best_config.save("production_optimized.yaml")
best_config.deploy(profile_name="production")

print("Configuration deployed! 🚀")
```

**Expected Output**:
```
=== Optimization Complete ===
Best F1 Score: 0.881
Latency P95: 420ms
Cost/Query: $0.0052

Configuration:
  ETL: mineru
  Chunk Size: 256
  Embedding: voyage/voyage-finance-2
  Retrieval: hybrid_rrf
  Reranking: enabled

Improvement over baseline: +9.8% F1

Optimization took 127 iterations (42 minutes, 3 GPUs)
Explored: 127/50,000 configs (0.25% of search space)
Converged: No improvement for 10 iterations

Configuration deployed! 🚀
```

---

### SECONDARY USE CASE: Production Inference (Using Discovered Config)

Once the agent has discovered the optimal configuration, use it for production queries:

```python
from rag_orchestrator import create_rag_orchestrator, RAGRequest

# ============================================================================
# Load optimized configuration discovered by agent
# ============================================================================

orchestrator = create_rag_orchestrator(
    config_path="production_optimized.yaml"  # From agent optimizer
)

# ============================================================================
# Execute queries with optimized config
# ============================================================================

# User query
request = RAGRequest(
    query="What was Microsoft's revenue in Q1 FY26?",
    search_space_id=1  # Document collection ID
)

# RAG pipeline executes with agent-discovered optimal configuration
result = await orchestrator.execute(request)

print(f"Answer: {result.answer}")
print(f"Confidence: {result.confidence:.2f}")
print(f"Chunks retrieved: {result.chunks_retrieved}")
print(f"Latency: {result.total_latency_ms}ms")
print(f"Cost: ${result.cost:.4f}")

# ============================================================================
# Optional: Re-optimize if performance degrades
# ============================================================================

# Monitor production performance
if result.f1_score < 0.85:  # Threshold
    print("Performance degraded, triggering re-optimization...")
    # Update golden Q&A with new examples
    # Re-run optimizer
    new_best_config = optimizer.optimize(documents, updated_golden_qa)
    new_best_config.deploy(profile_name="production")
```

---

### Advanced: Custom Search Space

```python
# Constrain search space to reduce optimization time
optimizer.optimize(
    documents=documents,
    golden_qa=golden_qa,
    search_space={
        # Only test these ETL providers
        "etl.provider": ["mineru", "docling"],
        
        # Only test these chunk sizes
        "chunking.config.chunk_size": [256, 512],
        
        # Test 3 embedding models
        "embedding.provider": ["fastembed", "voyage", "openai"],
        "embedding.model": {
            "fastembed": ["bge-base-en-v1.5"],
            "voyage": ["voyage-finance-2"],
            "openai": ["text-embedding-3-large"]
        },
        
        # Fix retrieval strategy (don't search)
        "retrieval.strategy": ["hybrid_rrf"],
        "retrieval.config.rrf_k": [40, 60],
        
        # Always use reranking
        "reranking.enabled": [True]
    },
    optimization_config={
        "strategy": "grid_search",  # Exhaustive for constrained space
        # 2 ETL × 2 chunks × 3 embeddings × 2 RRF_k = 24 configs
    }
)
```

---

## Migration Path

### Phase 1: Configuration Layer (Done ✓)
- `rag_config_schema.yaml` - Complete configuration schema
- `rag_config_manager.py` - Configuration management
- `rag_orchestrator.py` - Pipeline orchestration

### Phase 2: Agent Optimizer Implementation (HIGHEST PRIORITY)

**Core Implementation: `agent_optimizer.py`**

1. **Optimization Engine**:
   ```python
   class AgentOptimizer:
       def optimize(documents, golden_qa, strategy="bayesian") -> BestConfig
       def _generate_candidates() -> List[RAGConfig]
       def _evaluate_config(config, golden_qa) -> Metrics
       def _check_convergence(history) -> bool
   ```

2. **Search Space Manager**:
   ```python
   class SearchSpace:
       def sample_random() -> RAGConfig
       def get_neighbors(config) -> List[RAGConfig]  # For local search
       def mutate(config) -> RAGConfig  # For genetic algorithm
       def crossover(config1, config2) -> RAGConfig
   ```

3. **Evaluation Harness**:
   ```python
   class ConfigEvaluator:
       def evaluate(config, documents, golden_qa) -> Metrics:
           # 1. Index documents with config
           # 2. Run all Q&A queries
           # 3. Compute metrics (F1, latency, cost)
           # 4. Return aggregate results
   ```

4. **Optimization Strategies**:
   - `BayesianOptimizer` - Gaussian process surrogate model
   - `GeneticOptimizer` - Population-based evolution
   - `GridSearchOptimizer` - Exhaustive search
   - `RandomSearchOptimizer` - Baseline

### Phase 3: Component Adapters (Supporting Infrastructure)

1. Create adapters for modular components:
   - `OpenSearchAdapter` - Primary vector storage with k-NN + BM25
   - `MinerUAdapter` - Advanced PDF parsing with table/formula extraction
   - `DoclingAdapter` - Fast multi-format converter
   - `FastEmbedAdapter` - Local embedding models
   - `OpenAIEmbedAdapter` - OpenAI embeddings (including 3K dims)
   - `CohereEmbedAdapter` - Cohere embeddings with compression
   - `VoyageEmbedAdapter` - Domain-specific embeddings (finance, law, code)
   - `HybridRRFAdapter` - Wrap existing hybrid search
   - `FlashRankAdapter` - Existing reranker integration

2. **Critical Requirement**: Each adapter must support **fast swapping**
   - Components instantiated on-demand
   - Cleanup after evaluation
   - Parallel evaluation support

### Phase 4: Production Deployment (After Optimization)

1. **Deploy Optimized Config**:
   ```python
   # Agent found best config, now deploy it
   best_config.save("production_optimized.yaml")
   orchestrator.load_profile("production_optimized")
   ```

2. **Continuous Monitoring**:
   - Track production metrics vs golden standard
   - Alert if performance degrades
   - Trigger re-optimization if needed

3. **A/B Testing** (Optional):
   - Run current production vs new optimized config
   - Gradually shift traffic if improvement confirmed

4. **Re-Optimization Triggers**:
   - New documents added to corpus
   - User updates golden Q&A dataset
   - Performance drops below threshold
   - New embedding models available

---

## Performance Characteristics

### Current Production Profile
| Metric | Value |
|--------|-------|
| **ETL** | **MinerU (table/formula extraction)** |
| Chunk size | 256 tokens |
| Embedding model | FastEmbed all-MiniLM-L6-v2 (384-dim) |
| **Storage** | **OpenSearch 2.11 (k-NN + BM25)** |
| Retrieval strategy | Hybrid RRF (k=60) |
| Reranking | FlashRank ms-marco-MiniLM-L-12-v2 |
| **Accuracy** | **80% (MSFT benchmark)** |
| **Avg latency** | **~250ms** |
| **P95 latency** | **~350ms** |

### Advanced Configuration Options
| Component | Options Available |
|-----------|-------------------|
| **ETL** | MinerU (complex PDFs), Docling (fast), Unstructured (broad formats) |
| **Embeddings** | FastEmbed (12 models, free), OpenAI (1536-3072 dims), Cohere (binary compression), Voyage (finance/law/code), Google (cheap), Jina (long context) |
| **Storage** | OpenSearch (primary, multi-embed), PostgreSQL (app data), Qdrant, Weaviate, Milvus |
| **Transformations** | clean_whitespace, normalize_headers, fix_list_formatting, merge_split_sentences, extract_metadata, detect_sections |

### Optimization Opportunities
- **Larger chunks (512)** → +5% accuracy, +20% latency
- **Disable reranking** → -3% accuracy, -30% latency
- **Adjacent expansion** → +8% accuracy, +15% latency
- **Multi-stage retrieval** → +10% accuracy, +40% latency

---

## Monitoring & Observability

### Metrics Dashboard
```yaml
monitoring:
  metrics:
    # Retrieval
    - retrieval_latency
    - chunks_retrieved
    - reranking_score_distribution
    - document_coverage
    
    # Generation
    - llm_latency
    - prompt_tokens
    - completion_tokens
    - tool_calls_count
    
    # Quality (with ground truth)
    - exact_match
    - f1_score
    - citation_accuracy
```

### Logging
- **DEBUG**: Component loading, config resolution
- **INFO**: Request routing, metrics per query
- **WARNING**: Config validation issues, fallbacks
- **ERROR**: Component instantiation failures

### Tracing
- OpenTelemetry spans for each pipeline stage
- LangSmith integration for LLM call tracing

---

## Security & Compliance

### Configuration Security
- Secrets (API keys) stored in `.env`, not in YAML
- Configuration files read-only in Docker containers
- Profile selection logged for audit trail

### Data Privacy
- Query logs can be disabled per profile
- PII filtering before metrics storage
- Configurable data retention policies

---

---

## Adapter Pattern: Ensuring Connectivity Across Software Stacks

**The adapter pattern is the critical design that enables EVERY component to be swapped and reintegrated—regardless of their underlying software stack.**

### The Problem: Software Stack Heterogeneity

Our system integrates:
- **Python libraries** (MinerU, FastEmbed, FlashRank): Direct imports, method calls
- **REST APIs** (OpenAI, Voyage, Cohere, Google): HTTP requests, authentication, rate limiting
- **Docker services** (OpenSearch, PostgreSQL, Redis): Network clients, connection pooling
- **Cloud services** (Qdrant Cloud, Weaviate Cloud): OAuth2, region selection
- **CLI tools** (Apache Tika): Subprocess management

**Without adapters**, the orchestrator would need to handle:
- ❌ HTTP client logic for each API
- ❌ Retry logic and exponential backoff
- ❌ Connection pooling for databases
- ❌ GPU memory management for local models
- ❌ Authentication (API keys, OAuth2, Bearer tokens)
- ❌ Batching and rate limiting

This would **tightly couple** the orchestrator to specific technologies.

### The Solution: Adapter Interfaces + Standard Data Models

#### 1. Standard Data Models (Data Contracts)

Every adapter produces/consumes standardized types:

```python
# ETL Adapter Output
RawDocument(
    content="# Microsoft Corporation\n\n## Revenue...",
    metadata={"pages": 50, "title": "10-Q Filing"},
    tables=[{"data": [...], "page": 3}],
    formulas=["P/E = \\frac{Price}{EPS}"],
    etl_provider="mineru"
)

# Chunking Adapter Output
Chunk(
    text="Revenue increased 16% year-over-year...",
    token_count=256,
    prefix_context="# Financial Highlights\n## Revenue",
    suffix_context="The growth was driven by cloud services...",
    metadata={"source": "10-Q", "page": 3},
    chunking_strategy="hybrid_sandwich"
)

# Embedding Adapter Output
EmbeddedChunk(
    chunk=<Chunk>,
    embeddings={"text-embedding-3-large": [0.023, -0.145, ...]},  # 3072-dim vector
    embedding_provider="openai",
    embedding_cost_usd=0.00013,
    embedding_latency_ms=245
)

# Storage Adapter Input/Output
SearchResult(
    chunk=<Chunk>,
    vector_score=0.87,
    bm25_score=12.4,
    rrf_score=0.041,
    retrieval_method="hybrid_rrf"
)
```

**Key Insight**: MinerU (Python SDK) and Unstructured (REST API) both produce `RawDocument`. OpenAI (REST API) and FastEmbed (local Python) both produce `EmbeddedChunk`. **The orchestrator only sees the data models, never the implementation details.**

#### 2. Adapter Base Classes (Interfaces)

Each adapter type has a well-defined interface:

```python
class EmbeddingAdapter(ABC):
    """All embedding providers implement this interface"""
    
    @abstractmethod
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """Convert chunks to embeddings"""
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

**Concrete implementations hide software stack complexity**:

```python
# REST API Implementation (OpenAI)
class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    def embed_chunks(self, chunks):
        texts = [chunk.get_full_context() for chunk in chunks]
        
        # HTTP POST with retry logic
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts}
        )
        
        # Parse response, handle errors, compute costs
        return self._to_embedded_chunks(response.json())

# Python SDK Implementation (FastEmbed, local)
class FastEmbedAdapter(EmbeddingAdapter):
    def embed_chunks(self, chunks):
        from fastembed import TextEmbedding
        
        model = TextEmbedding(self.model_name)
        texts = [chunk.get_full_context() for chunk in chunks]
        
        # Local inference, no API calls
        embeddings = list(model.embed(texts))
        return self._to_embedded_chunks(embeddings)
```

**Orchestrator code is identical for both**:

```python
# Works with any adapter!
embedding_adapter = AdapterFactory.create_embedding(provider, config)
embedded_chunks = embedding_adapter.embed_chunks(chunks)
```

#### 3. Adapter Factory (Dynamic Loading)

Components are instantiated at runtime based on configuration:

```python
class AdapterFactory:
    """Registry of all adapters"""
    
    etl_adapters = {
        "mineru": MinerUAdapter,
        "docling": DoclingAdapter,
        "unstructured": UnstructuredAdapter
    }
    
    embedding_adapters = {
        "openai": OpenAIEmbeddingAdapter,
        "fastembed": FastEmbedAdapter,
        "voyage": VoyageEmbeddingAdapter,
        "cohere": CohereEmbeddingAdapter
    }
    
    @classmethod
    def create_embedding(cls, provider: str, config: dict):
        adapter_class = cls.embedding_adapters[provider]
        return adapter_class(config)
```

**Configuration-driven instantiation**:

```yaml
# config.yaml
embedding:
  provider: openai  # Change to "fastembed" for local inference
  model: text-embedding-3-large
  api_key: ${OPENAI_API_KEY}
```

**Result**: Swap providers by changing one line in config, zero code changes.

### How Adapters Enable Connectivity

#### Example: Complete Pipeline with 5 Different Software Stacks

```
User uploads financial_report.pdf
   │
   ▼ MinerUAdapter (Python SDK)
RawDocument + tables + formulas
   │
   ▼ HybridSandwichChunker (Pure Python)
120 Chunks with context
   │
   ▼ OpenAIEmbeddingAdapter (REST API)
120 EmbeddedChunks (3072-dim vectors, $0.016 cost)
   │
   ▼ OpenSearchAdapter (Docker service)
Indexed to OpenSearch (k-NN + BM25)
   │
   ▼ User asks: "What was Q1 revenue?"
   │
   ▼ HybridRRFRetriever (uses OpenSearchAdapter)
20 SearchResults (vector + BM25 fused)
   │
   ▼ FlashRankReranker (Python SDK, local)
8 RerankedResults (cross-encoder refined)
   │
   ▼ Agent generates answer with citations
```

**Five different software stacks, seamlessly connected through adapters:**
1. MinerU: Python method call (`extract()`)
2. OpenAI: HTTPS POST to `api.openai.com`
3. OpenSearch: HTTP client (`opensearch-py`) to `localhost:9200`
4. FlashRank: Local model inference
5. Agent: Uses standard `RetrievalContext` data model

**The orchestrator never knows about HTTP, subprocess management, or GPU memory**—adapters abstract it all.

### Benefits for Optimization

The adapter pattern is essential for the automatic optimizer:

1. **Test Multiple Providers**: Optimizer can test MinerU vs Docling vs Unstructured—same interface, different implementations
2. **Cost Tracking**: Each adapter reports its cost (`embedding_cost_usd`, `retrieval_latency_ms`)
3. **Isolated Failures**: If OpenAI API fails, optimizer automatically tries FastEmbed fallback
4. **Performance Measurement**: Standardized metrics across all components (latency, cost, quality)

**Example Configuration Space Exploration**:

```
Iteration 1: MinerU + OpenAI-3K + OpenSearch → F1: 0.89, Cost: $0.008/query
Iteration 2: MinerU + FastEmbed + OpenSearch → F1: 0.84, Cost: $0.000/query (FREE!)
Iteration 3: Docling + Voyage-Finance + OpenSearch → F1: 0.91, Cost: $0.004/query ✅ BEST
```

Optimizer automatically discovers that **Docling + Voyage is optimal** for this domain—without manual testing!

---

## Component Details

> **💡 Multi-Format Support is a PRODUCTION Feature**
>
> The system handles **PDF, DOCX, HTML, XLSX, PPTX, EML** in production. After optimization discovers the best ETL provider for your domain, that provider processes ALL NEW documents users upload - whether it's a new 10-Q PDF, a contract DOCX, or investor presentation PPTX. This is the core value: **process unlimited NEW documents in various formats** after one-time optimization.

### ETL Providers (Multi-Format Processing)

**Supported Formats in Production**:

| Format | Provider | Use Cases | Key Features |
|--------|----------|-----------|--------------|
| **PDF** | MinerU | Financial reports, scientific papers, complex docs | Table extraction, formula recognition (LaTeX), multi-column |
| **PDF** | Docling | General documents, fast processing | Good table detection, CPU-optimized |
| **DOCX** | Docling | Word documents, contracts, proposals | Structure preservation, native support |
| **HTML** | Unstructured | Web pages, documentation, wikis | Clean text extraction, HTML parsing |
| **XLSX** | Docling | Spreadsheets, financial data | Table structure preservation |
| **PPTX** | Docling | Presentations, investor decks | Slide text extraction |
| **EML** | Unstructured | Email archives, correspondence | Thread parsing, attachment handling |
| **XML** | Unstructured | Structured data | Schema-aware parsing |

**How It Works**:
1. Agent optimizer tests different ETL providers on your golden standard
2. Discovers which works best for YOUR document types (e.g., "MinerU for financial PDFs")
3. Production system uses that provider to process ALL NEW documents users upload
4. Same optimized config handles multiple formats (PDF + DOCX + HTML in same pipeline)

---

**Provider Details**:

**MinerU** (Primary - Complex PDFs)
- Advanced table structure recognition
- Formula extraction (LaTeX output)
- Multi-column layout understanding
- Best for: Financial reports, scientific papers
- Requires: `magic-pdf` package

**Docling** (Fast General-Purpose)
- Multi-format support (PDF, DOCX, XLSX, PPTX)
- CPU-optimized, fast processing
- Best for: Quick general document conversion

**Unstructured** (Broad Format Support)
- Email, HTML, XML parsing
- 20+ file format support
- Best for: Diverse document collections

### Embedding Providers

**Local (FastEmbed)** - FREE, Offline
- all-MiniLM-L6-v2: 384 dims, fast baseline
- bge-base-en-v1.5: 768 dims, high quality
- bge-large-en-v1.5: 1024 dims, best local
- multilingual-e5-large: 1024 dims, 100+ languages

**OpenAI** - Highest Quality
- text-embedding-3-small: 1536 dims, $0.02/1M
- **text-embedding-3-large: 3072 dims, $0.13/1M** 🔥
- 8K context window, dimension shortening support

**Voyage AI** - Domain-Specific
- voyage-finance-2: 1024 dims, 32K context, financial docs
- voyage-law-2: 1024 dims, 16K context, legal docs
- voyage-code-2: 1536 dims, 16K context, code/technical

**Cohere** - Compression
- embed-english-v3.0: 1024 dims, binary compression (32x smaller!)
- embed-multilingual-v3.0: 1024 dims, 100+ languages

**Google** - Cost-Effective
- text-embedding-004: 768 dims, $0.01/1M (cheapest!)

**Jina AI** - Long Context
- jina-embeddings-v2-base: 768 dims, 8K context
- jina-embeddings-v3: 1024 dims, multilingual

### Storage Providers

**OpenSearch** (Primary) ✅
- Native k-NN vector search (nmslib/faiss/lucene engines)
- Native BM25 full-text search
- **Multiple embedding fields per document**
- Dimension support: up to 16,000 dims
- Native analytics and monitoring
- Horizontal scaling built-in

**PostgreSQL** (Application Metadata)
- User accounts, sessions, documents
- No longer used for vector storage

**Qdrant** (Alternative)
- Pure vector database, 65K max dims
- Payload indexing, filtering

**Weaviate** (Alternative)
- GraphQL API, hybrid search
- 65K max dims

### Data Transformations

**Post-ETL, Pre-Chunking Pipeline:**
1. `clean_whitespace` - Remove excessive spaces/newlines
2. `normalize_headers` - Standardize header levels
3. `fix_list_formatting` - Correct bullet/numbered lists
4. `merge_split_sentences` - Join sentences broken across lines
5. `extract_metadata` - Extract title, author, date
6. `detect_sections` - Identify document structure

## Future Enhancements

### 1. Multi-Modal RAG
```yaml
etl:
  vision_llm:
    enabled: true
    model: "gpt-4o-mini"
  audio_transcription:
    provider: "whisper"
    model: "large-v3"
```

### 2. Learning to Rank
```yaml
retrieval:
  strategy: "learned_to_rank"
  config:
    model_path: "models/ltr_ranker.pkl"
    features:
      - bm25_score
      - vector_similarity
      - document_recency
      - user_feedback
```

### 3. Contextual Retrieval
```yaml
chunking:
  strategy: "contextual"
  config:
    context_mode: "llm_generated"
    context_model: "gpt-4o-mini"
```

---

## Key Design Decisions Based on Feedback

### 0. Self-Optimization: The Core Purpose ✅
**Goal**: 
- System automatically discovers best RAG configuration for user's documents and golden Q&A dataset
- No manual hyperparameter tuning required
- Agent explores component combinations and converges to optimal setup

**Why This Matters**:
- RAG systems have **dozens of hyperparameters**: chunk size, embedding model, retrieval strategy, RRF constant, reranking threshold, etc.
- Optimal settings vary by domain: financial docs ≠ legal docs ≠ scientific papers
- Manual tuning requires weeks of experimentation
- **This system optimizes automatically in hours**

**User Workflow**:
1. Upload documents (PDFs, etc.)
2. Provide 50-100 golden Q&A pairs
3. Run agent optimizer
4. Receive best configuration + performance metrics
5. Deploy to production

**Search Space**: ~50,000+ possible configurations
- 3 ETL providers × 4 chunk sizes × 15 embedding models × 3 retrieval strategies × 4 RRF constants × 2 reranking options = massive combinatorial space

**Convergence**: Agent stops when no improvement for N iterations (typically 10-20% of search space explored)

### 1. Storage: OpenSearch (Primary) ✅
**Rationale**: 
- Native support for **multiple embedding fields** per document (critical for multi-model experiments)
- Built-in BM25 full-text search (no separate Elasticsearch needed)
- Better horizontal scaling than PostgreSQL+pgvector
- Native k-NN algorithms (nmslib, faiss, lucene)
- Supports up to 16K dimensions (vs pgvector 2K limit)
- Production-grade monitoring with OpenSearch Dashboards

**Migration**:
- PostgreSQL → Application metadata only (users, sessions, documents)
- OpenSearch → All vectors and full-text search
- Docker Compose updated with OpenSearch 2.11.1 service

### 2. ETL: MinerU (Primary) + Docling + Unstructured ✅
**Rationale**:
- **MinerU** provides superior table structure recognition for financial reports
- Formula extraction with LaTeX output (scientific papers)
- Multi-column layout understanding
- **Data transformation pipeline** ensures clean markdown:
  - `clean_whitespace`, `normalize_headers`, `fix_list_formatting`
  - `merge_split_sentences`, `extract_metadata`, `detect_sections`
- Docling retained for fast general-purpose conversion
- Unstructured for broad format support (email, HTML, etc.)

**Configuration**: Fully configurable per profile:
```yaml
etl:
  provider: mineru  # or docling, unstructured
  config:
    detect_tables: true
    detect_formulas: true
    table_format: markdown  # html, latex, csv
    transformations: [clean_whitespace, normalize_headers, ...]
```

### 3. Embeddings: Comprehensive Multi-Provider Support ✅
**Rationale**:
- Support **all mainstream embeddings** for maximum flexibility
- Enable quality vs cost trade-offs
- Domain-specific models (finance, legal, code)
- High-dimensional options for precision-critical use cases

**Providers Added**:
1. **FastEmbed** (Local) - 12 models, 384-1024 dims, FREE
2. **OpenAI** - Including **3072-dim text-embedding-3-large** 🔥
3. **Cohere** - Binary compression (32x storage reduction)
4. **Voyage AI** - Domain models (finance-2, law-2, code-2)
5. **Google** - Cost-effective ($0.01/1M tokens)
6. **Jina AI** - Long context (8K tokens)

**Multi-Embedding Strategy**: OpenSearch supports multiple embedding fields per chunk:
```yaml
embedding_fields:
  - name: "embedding_fast_local"   # 768 dims, baseline
    weight: 0.3
  - name: "embedding_openai_3k"    # 3072 dims, high quality
    weight: 0.7  # Weighted combination!
```

### 4. Profiles for Common Scenarios ✅
- `production` - MinerU + FastEmbed + OpenSearch + Hybrid RRF (80% F1)
- `experimental_openai_3k` - 3072-dim embeddings (89%+ F1 estimated)
- `experimental_voyage_finance` - Domain-optimized for financial docs (32K context)
- `experimental_cohere_compressed` - Binary embeddings, ultra-fast retrieval
- `scientific_papers` - MinerU formula detection + 512-token chunks
- `high_accuracy` - Maximum context (100 chunks, adjacent expansion)
- `fast_cheap` - Vector-only, minimal processing

---

## Summary

This architecture provides a **self-optimizing agentic RAG system** where:

✅ **Automatic Configuration Discovery** - Agent explores 50,000+ possible component combinations  
✅ **Golden Standard Evaluation** - Measures performance against user's Q&A dataset  
✅ **Convergence-Based Optimization** - Stops when no further improvement found  
✅ **Modular Component Architecture** - Every component swappable (ETL, chunking, embedding, retrieval, reranking)  
✅ **Multi-Provider Support** - 3 ETL providers, 6 embedding providers (OpenAI 3K dims, Voyage finance, Cohere binary), OpenSearch storage  
✅ **Advanced Capabilities** - 3K-dim embeddings, binary compression, 32K context, domain models  
✅ **Data Quality** - Transformation pipeline ensures clean markdown input  
✅ **Production Ready** - Optimized config deployed automatically

### The Key Innovation

Traditional RAG systems require manual tuning of dozens of hyperparameters. This system **learns the optimal configuration automatically** from your documents and golden Q&A dataset.

**User provides**:
- Documents (PDFs, etc.)
- 100 example Q&A pairs

**System returns**:
- Best ETL provider for your document type
- Optimal chunk size for your content
- Best embedding model for your domain (possibly OpenAI 3K, Voyage finance, or local)
- Ideal retrieval strategy (hybrid/vector/BM25)
- Optimized reranking settings
- **Performance metrics**: F1 score, latency, cost per query

**Example**: For MSFT 10-Q financial Q&A:
- Agent discovers: MinerU ETL (table extraction) + voyage-finance-2 embeddings + hybrid_rrf(k=40) achieves **88.1% F1 score**
- Baseline config: 78.3% F1
- **Improvement: +9.8% F1** without any manual tuning!

**Next Steps**:

### Priority 1: Agent Optimizer (CORE FEATURE) 🎯
1. **Implement `agent_optimizer.py`**:
   - Optimization loop with convergence detection
   - Search space manager (sample/mutate/crossover)
   - Config evaluator (index + run golden Q&A + compute metrics)
   - Multiple strategies (Bayesian, Genetic, Grid, Random)
   
2. **Golden Standard Evaluation**:
   - Load user's Q&A dataset
   - Run queries through RAG pipeline
   - Compute F1, exact match, semantic similarity
   - Track latency and cost per configuration
   
3. **Convergence Logic**:
   - Detect performance plateau (no improvement for N iterations)
   - Early stopping to avoid wasted compute
   - Multi-objective optimization (F1 + latency + cost)

### Priority 2: Modular Component Architecture
1. **Component Adapters** (supporting infrastructure):
   - OpenSearchAdapter (storage)
   - MinerUAdapter, DoclingAdapter (ETL)
   - OpenAIEmbedAdapter, VoyageEmbedAdapter, FastEmbedAdapter (embeddings)
   - HybridRRFAdapter, FlashRankAdapter (retrieval/reranking)
   
2. **Fast Component Swapping**:
   - Instantiate components on-demand during evaluation
   - Cleanup resources after each config test
   - Support parallel evaluations (4-8 configs simultaneously)

### Priority 3: Testing & Validation
1. **End-to-End Test**:
   - Upload MSFT 10-Q document
   - Provide 100 golden Q&A pairs
   - Run agent optimizer (Bayesian strategy, 50 iterations)
   - Validate: Best config found, F1 improvement measured
   
2. **Benchmark Optimization Strategies**:
   - Compare Bayesian vs Genetic vs Random vs Grid
   - Measure: iterations to convergence, final F1 score
   
3. **Cost Analysis**:
   - Track API costs during optimization
   - Optimize: free local embeddings vs paid cloud
   - Balance quality vs cost

### Priority 4: Production Deployment
1. Deploy optimized configuration automatically
2. Set up continuous monitoring (performance drift detection)
3. Enable re-optimization triggers (new docs, updated Q&A, performance drop)

### Documentation
- See [EMBEDDING_MODELS_GUIDE.md](EMBEDDING_MODELS_GUIDE.md) for embedding selection
- See [ADAPTABLE_RAG_QUICKSTART.md](ADAPTABLE_RAG_QUICKSTART.md) for usage guide
- See [ADAPTABLE_RAG_SUMMARY.md](ADAPTABLE_RAG_SUMMARY.md) for executive overview

**Questions or Enhancements?** Let me know what components you want to prioritize!
