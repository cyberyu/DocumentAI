# RAG Components Matrix: Complete Software Stack Catalog

**Last Updated**: May 3, 2026

This document provides a **holistic view** of every RAG pipeline component with all candidate software stacks, performance characteristics, and trade-offs.

---

## 📋 Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Component 1: Document Ingestion (ETL)](#component-1-document-ingestion-etl)
3. [Component 2: Document Chunking](#component-2-document-chunking)
4. [Component 3: Embedding Generation](#component-3-embedding-generation)
5. [Component 4: Vector Storage](#component-4-vector-storage)
6. [Component 5: Hybrid Retrieval](#component-5-hybrid-retrieval)
7. [Component 6: Reranking](#component-6-reranking)
8. [Component 7: Context Assembly](#component-7-context-assembly)
9. [Component 8: LLM Generation](#component-8-llm-generation)
10. [Component 9: Agent Memory](#component-9-agent-memory)
11. [Configuration Matrix](#configuration-matrix)

---

## Pipeline Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         RAG Pipeline Flow                                 │
└──────────────────────────────────────────────────────────────────────────┘

┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   ETL       │───▶│  Chunking   │───▶│  Embedding  │───▶│  Storage    │
│ (Component 1)│    │(Component 2)│    │(Component 3)│    │(Component 4)│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                                                           │
       │                    INDEXING PIPELINE                     │
       └─────────────────────────────────────────────────────────┘

       ┌─────────────────────────────────────────────────────────┐
       │                 RETRIEVAL PIPELINE                       │
       ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    
       │  Retrieval   │───▶│  Reranking  │───▶│   Context   │    
       │(Component 5) │    │(Component 6)│    │ Assembly    │───▶LLM
       └─────────────┘    └─────────────┘    │(Component 7)│    
                                              └─────────────┘    

       ┌─────────────────────────────────────────────────────────┐
       │                 MEMORY & GENERATION                      │
       ┌─────────────┐                         ┌─────────────┐    
       │Agent Memory │                         │ LLM Gen     │    
       │(Component 9)│◀───────────────────────▶│(Component 8)│    
       └─────────────┘                         └─────────────┘    
```

---

## Component 1: Document Ingestion (ETL)

**Purpose**: Extract structured content from various file formats

### Candidate Software Stacks

| Software | Type | Formats | Strengths | Weaknesses | Cost | Latency | Quality |
|----------|------|---------|-----------|------------|------|---------|---------|
| **MinerU** | Python SDK | PDF | ✅ Best table/formula extraction<br>✅ GPU acceleration<br>✅ Free | ❌ PDF only<br>❌ Requires GPU | Free | 50-200ms/page | 9.5/10 |
| **Docling** | Python SDK | PDF, DOCX, PPTX, XLSX, HTML | ✅ Multi-format<br>✅ Fast (async)<br>✅ Good layout analysis | ❌ Table extraction weaker than MinerU | Free | 30-100ms/page | 8.5/10 |
| **Unstructured.io API** | REST API | 20+ formats (PDF, DOCX, HTML, EML, MSG) | ✅ Broadest format support<br>✅ Hosted service | ❌ Paid API<br>❌ Network latency | $0.01/page | 200-500ms | 8/10 |
| **PyMuPDF** | Python SDK | PDF | ✅ Very fast<br>✅ Lightweight | ❌ Basic extraction (no tables)<br>❌ PDF only | Free | 10-30ms/page | 6/10 |
| **Apache Tika** | CLI/REST | 1000+ formats | ✅ Maximum format support<br>✅ Battle-tested | ❌ Java dependency<br>❌ Slower<br>❌ Basic extraction | Free | 100-300ms/doc | 7/10 |
| **pdfplumber** | Python SDK | PDF | ✅ Good table extraction<br>✅ Free | ❌ CPU-bound<br>❌ Slower than MinerU | Free | 100-300ms/page | 7.5/10 |
| **LlamaParse** | REST API | PDF, DOCX, images | ✅ LLM-powered<br>✅ Great for complex layouts | ❌ Expensive ($0.05/page)<br>❌ Slow (2-5s/page) | $0.05/page | 2000-5000ms | 9/10 |

### Recommended Configurations

| Use Case | Primary | Fallback | Rationale |
|----------|---------|----------|-----------|
| **Financial Documents** | MinerU | Docling | Tables/formulas critical |
| **Multi-Format Corpus** | Docling | Unstructured API | Broad format support |
| **Cost-Optimized** | Docling | PyMuPDF | All free, good coverage |
| **Maximum Quality** | LlamaParse | MinerU | Highest extraction quality |
| **Speed-Optimized** | PyMuPDF | Docling | Fastest processing |

### Adapter Implementation

```python
# adapter_examples.py already has:
- MinerUAdapter          # GPU-accelerated PDF
- DoclingAdapter         # Multi-format, fast
- UnstructuredAdapter    # REST API, broad format

# TODO: Add remaining adapters
- PyMuPDFAdapter         # Fast, lightweight PDF
- ApacheTikaAdapter      # Maximum format support
- LlamaParseAdapter      # LLM-powered extraction
```

---

## Component 2: Document Chunking

**Purpose**: Split documents into semantically coherent units

### Candidate Software Stacks

| Strategy | Type | Strengths | Weaknesses | Chunk Size | Overlap | Quality |
|----------|------|-----------|------------|------------|---------|---------|
| **Sandwich Chunking** | Custom | ✅ Context-aware (prefix/suffix)<br>✅ Better coherence<br>✅ Preserves document structure | ❌ Custom implementation | Variable | 20-30% | 9/10 |
| **Semantic Chunking** | Algorithm | ✅ Meaningful boundaries<br>✅ Adaptive size | ❌ Slower<br>❌ Requires embeddings | Variable | 0-10% | 8.5/10 |
| **Recursive Character Split** | LangChain | ✅ Simple, fast<br>✅ Respects boundaries (paragraph, sentence) | ❌ Fixed size<br>❌ Context loss at edges | Fixed | 10-20% | 7/10 |
| **Fixed-Size Split** | Simple | ✅ Fastest<br>✅ Predictable | ❌ Breaks mid-sentence<br>❌ No semantic awareness | Fixed | 10-20% | 5/10 |
| **Sentence-Based** | NLTK/spaCy | ✅ Natural boundaries<br>✅ No broken sentences | ❌ Variable size (too small or large) | Variable | 0% | 6.5/10 |
| **Markdown-Aware** | Custom | ✅ Preserves structure (headers)<br>✅ Good for docs | ❌ Markdown only | Variable | 10% | 7.5/10 |
| **LLM-Based** | GPT-4 | ✅ Intelligent boundaries<br>✅ Summarization | ❌ Very expensive ($0.10/doc)<br>❌ Slow (5-10s/doc) | Variable | 0% | 9.5/10 |

### Recommended Configurations

| Use Case | Strategy | Chunk Size | Overlap | Rationale |
|----------|----------|------------|---------|-----------|
| **General RAG** | Sandwich Chunking | 512 tokens | 25% | Best balance |
| **Long Context Models** | Semantic Chunking | 2000 tokens | 10% | Fewer chunks |
| **Speed-Optimized** | Recursive Character | 256 tokens | 15% | Fastest |
| **Maximum Quality** | LLM-Based | Variable | 0% | Intelligent boundaries |
| **Financial Docs** | Sandwich + Table-Aware | 512 tokens | 30% | Preserve table context |

### Chunking Parameters

| Parameter | Description | Typical Range | Impact |
|-----------|-------------|---------------|--------|
| **Chunk Size** | Target tokens per chunk | 128-2048 | ↑ Size = ↑ Context, ↓ Precision |
| **Overlap** | Overlap between chunks (%) | 0-30% | ↑ Overlap = ↑ Recall, ↑ Cost |
| **Prefix Tokens** | Context before chunk | 0-200 | ↑ Prefix = ↑ Coherence |
| **Suffix Tokens** | Context after chunk | 0-200 | ↑ Suffix = ↑ Coherence |
| **Min Chunk Size** | Minimum viable chunk | 50-200 | Avoid tiny fragments |

### Adapter Implementation

```python
# adapter_examples.py already has:
- HybridSandwichChunker  # Context-aware with prefix/suffix

# TODO: Add remaining adapters
- SemanticChunker        # Embedding-based boundaries
- RecursiveChunker       # LangChain-style
- FixedSizeChunker       # Simple splitting
- MarkdownChunker        # Structure-aware
```

---

## Component 3: Embedding Generation

**Purpose**: Convert text to dense vector representations

### Candidate Software Stacks

| Model | Type | Dimensions | Strengths | Weaknesses | Cost | Latency | Quality |
|-------|------|------------|-----------|------------|------|---------|---------|
| **OpenAI text-embedding-3-large** | REST API | 3072 | ✅ Best quality<br>✅ Reliable<br>✅ Good support | ❌ Expensive ($0.13/1M tokens) | $0.13/1M tokens | 100-200ms/batch | 9.5/10 |
| **OpenAI text-embedding-3-small** | REST API | 1536 | ✅ Good quality<br>✅ Cheaper than large | ❌ Lower quality | $0.02/1M tokens | 80-150ms/batch | 9/10 |
| **Voyage AI voyage-finance-2** | REST API | 1024 | ✅ Finance domain-tuned<br>✅ High quality | ❌ Relatively expensive<br>❌ Domain-specific | $0.12/1M tokens | 120-250ms/batch | 9.3/10 |
| **Voyage AI voyage-law-2** | REST API | 1024 | ✅ Legal domain-tuned | ❌ Domain-specific | $0.12/1M tokens | 120-250ms/batch | 9.3/10 |
| **Cohere embed-english-v3.0** | REST API | 1024/4096 | ✅ Binary compression (50% storage)<br>✅ Good quality | ❌ Moderate cost | $0.10/1M tokens | 100-180ms/batch | 9/10 |
| **Google text-embedding-004** | REST API | 768 | ✅ Cheapest API ($0.025/1M tokens)<br>✅ Good quality | ❌ Lower dimensions | $0.025/1M tokens | 90-150ms/batch | 8.5/10 |
| **Jina AI jina-embeddings-v3** | REST API | 1024 | ✅ 8K context window<br>✅ Multi-lingual | ❌ Moderate cost | $0.02/1M tokens | 100-200ms/batch | 8.8/10 |
| **FastEmbed (BAAI/bge-small-en-v1.5)** | Python SDK | 384 | ✅ FREE ✅<br>✅ Fast local inference<br>✅ GPU acceleration | ❌ Lower quality<br>❌ Lower dimensions | Free | 20-50ms/batch (GPU) | 8/10 |
| **FastEmbed (BAAI/bge-large-en-v1.5)** | Python SDK | 1024 | ✅ FREE ✅<br>✅ High quality | ❌ Slower than small<br>❌ More VRAM | Free | 50-100ms/batch (GPU) | 8.8/10 |
| **Sentence Transformers (all-MiniLM-L6-v2)** | Python SDK | 384 | ✅ FREE ✅<br>✅ Very fast<br>✅ Lightweight | ❌ Lower quality | Free | 15-30ms/batch (GPU) | 7.5/10 |
| **Sentence Transformers (all-mpnet-base-v2)** | Python SDK | 768 | ✅ FREE ✅<br>✅ Good quality | ❌ Slower | Free | 40-80ms/batch (GPU) | 8.3/10 |

### Recommended Configurations

| Use Case | Model | Rationale |
|----------|-------|-----------|
| **Maximum Quality** | OpenAI text-embedding-3-large | Best retrieval performance |
| **Cost-Optimized** | FastEmbed bge-large-en-v1.5 | Free, good quality |
| **Finance Domain** | Voyage voyage-finance-2 | Domain-tuned for financial docs |
| **Legal Domain** | Voyage voyage-law-2 | Domain-tuned for legal docs |
| **Hybrid (Cost+Quality)** | Google text-embedding-004 + FastEmbed fallback | Cheap API + free fallback |
| **Multi-lingual** | Jina jina-embeddings-v3 | 8K context, many languages |
| **Storage-Optimized** | Cohere embed-v3.0 with binary | 50% storage reduction |

### Key Considerations

| Factor | Impact | Optimal Range |
|--------|--------|---------------|
| **Dimensions** | ↑ Dims = ↑ Quality, ↑ Storage, ↑ Latency | 768-1536 for most use cases |
| **Batch Size** | ↑ Batch = ↓ Cost/token, ↓ Latency/token | 32-128 texts per batch |
| **Context Window** | Maximum input tokens | 512-8192 (model-dependent) |
| **Normalization** | L2-normalize vectors | Always for cosine similarity |

### Adapter Implementation

```python
# adapter_examples.py already has:
- OpenAIEmbeddingAdapter   # text-embedding-3-*
- FastEmbedAdapter         # BAAI/bge-* models

# TODO: Add remaining adapters
- VoyageEmbeddingAdapter   # voyage-finance-2, voyage-law-2
- CohereEmbeddingAdapter   # embed-english-v3.0 with binary compression
- GoogleEmbeddingAdapter   # text-embedding-004
- JinaEmbeddingAdapter     # jina-embeddings-v3
```

---

## Component 4: Vector Storage

**Purpose**: Store embeddings and enable similarity search

### Candidate Software Stacks

| Store | Type | Strengths | Weaknesses | Cost | Query Latency | Scale |
|-------|------|-----------|------------|------|---------------|-------|
| **OpenSearch (k-NN)** | Docker/Cloud | ✅ Hybrid search (vector+BM25)<br>✅ Open source<br>✅ Battle-tested | ❌ Slower than specialized<br>❌ Resource-intensive | Free (self-host) / $100+/mo (cloud) | 20-100ms | 10M-100M vectors |
| **Qdrant** | Docker/Cloud | ✅ Fast k-NN<br>✅ Filtering<br>✅ Easy setup | ❌ Smaller ecosystem | Free (self-host) / $30+/mo (cloud) | 10-50ms | 100M+ vectors |
| **Weaviate** | Docker/Cloud | ✅ GraphQL API<br>✅ Modular<br>✅ Good ecosystem | ❌ Complex setup | Free (self-host) / $25+/mo (cloud) | 15-60ms | 100M+ vectors |
| **Milvus** | Docker/Cluster | ✅ Highest scale<br>✅ GPU acceleration<br>✅ Best performance | ❌ Complex setup<br>❌ Heavier resource use | Free (self-host) | 5-30ms | 1B+ vectors |
| **ChromaDB** | Python SDK | ✅ Simplest setup<br>✅ Embedded or server | ❌ Limited scale<br>❌ Basic features | Free | 10-40ms | 1M-10M vectors |
| **Pinecone** | Cloud Only | ✅ Fully managed<br>✅ Easy to use<br>✅ Fast | ❌ Cloud-only<br>❌ Expensive ($70+/mo) | $70+/mo | 15-50ms | 100M+ vectors |
| **PostgreSQL + pgvector** | Docker/VM | ✅ Familiar SQL<br>✅ ACID transactions<br>✅ Great for small-scale | ❌ Not optimized for k-NN<br>❌ Slower at scale | Free | 50-200ms | 1M-10M vectors |
| **Redis (RediSearch)** | Docker/Cloud | ✅ Very fast<br>✅ Hybrid search<br>✅ In-memory | ❌ Expensive memory<br>❌ Limited persistence | Free (self-host) | 5-20ms | 10M-50M vectors |

### Recommended Configurations

| Use Case | Storage | Index Type | Rationale |
|----------|---------|------------|-----------|
| **Hybrid Search** | OpenSearch | HNSW + BM25 | Best for combined semantic+keyword |
| **Pure Vector Search** | Qdrant | HNSW | Fast, specialized |
| **Small-Scale + SQL** | PostgreSQL+pgvector | IVFFlat | Familiar, transactional |
| **Maximum Performance** | Milvus | GPU-IVF-PQ | Highest throughput |
| **Simplest Setup** | ChromaDB | HNSW | Embedded, no setup |
| **Managed Service** | Pinecone | Proprietary | Zero ops |
| **Real-time + Cache** | Redis | HNSW | Ultra-low latency |

### Index Algorithms

| Algorithm | Accuracy | Speed | Memory | Use Case |
|-----------|----------|-------|--------|----------|
| **HNSW** | 95-99% | Fast (5-30ms) | High | Production default |
| **IVF-Flat** | 90-95% | Medium (10-50ms) | Medium | Balanced |
| **IVF-PQ** | 85-95% | Fast (5-20ms) | Low | Storage-constrained |
| **Flat** | 100% | Slow (50-500ms) | High | <100K vectors |
| **GPU-IVF-PQ** | 90-98% | Very Fast (1-10ms) | Low (GPU) | Highest throughput |

### Adapter Implementation

```python
# adapter_examples.py already has:
- OpenSearchAdapter        # k-NN + BM25 hybrid

# TODO: Add remaining adapters
- QdrantAdapter           # Fast k-NN with filtering
- WeaviateAdapter         # GraphQL-based
- PostgreSQLAdapter       # pgvector
- ChromaDBAdapter         # Embedded vector DB
- MilvusAdapter           # High-scale, GPU-accelerated
```

---

## Component 5: Hybrid Retrieval

**Purpose**: Combine semantic (vector) + keyword (BM25) search

### Retrieval Strategies

| Strategy | Strengths | Weaknesses | Use Case |
|----------|-----------|------------|----------|
| **RRF (Reciprocal Rank Fusion)** | ✅ Simple<br>✅ No training<br>✅ Works well | ❌ Fixed weighting | General purpose |
| **Weighted Fusion (α semantic + β BM25)** | ✅ Tunable weights<br>✅ Fast | ❌ Requires tuning | Domain-specific optimization |
| **Contextual Embedding** | ✅ Query-aware<br>✅ Semantic + structure | ❌ Slower<br>❌ Complex | Long documents |
| **Query Expansion** | ✅ Better recall<br>✅ Synonym handling | ❌ Slower<br>❌ Noise risk | Ambiguous queries |
| **HyDE (Hypothetical Document)** | ✅ Semantic richness<br>✅ Better for vague queries | ❌ Requires LLM call<br>❌ Latency +500ms | Complex questions |
| **Sparse+Dense (SPLADE)** | ✅ Best of both worlds<br>✅ Learned | ❌ Requires training<br>❌ Complex | Research-grade quality |

### Recommended Configurations

| Use Case | Strategy | Semantic Weight | BM25 Weight | Top-K |
|----------|----------|-----------------|-------------|-------|
| **General RAG** | RRF | 0.7 | 0.3 | 20 → rerank to 8 |
| **Exact Match Important** | Weighted Fusion | 0.4 | 0.6 | 30 → rerank to 10 |
| **Semantic-Heavy** | Weighted Fusion | 0.8 | 0.2 | 15 → rerank to 5 |
| **Maximum Recall** | Query Expansion + RRF | 0.6 | 0.4 | 50 → rerank to 10 |
| **Research-Grade** | SPLADE | N/A (learned) | N/A | 20 → rerank to 8 |

### Retrieval Parameters

| Parameter | Description | Typical Range | Impact |
|-----------|-------------|---------------|--------|
| **Top-K** | Initial retrieval count | 10-100 | ↑ K = ↑ Recall, ↑ Latency |
| **Semantic Weight** | Vector search contribution | 0.3-0.9 | Domain-dependent |
| **BM25 Weight** | Keyword search contribution | 0.1-0.7 | Complement to semantic |
| **Min Score** | Minimum relevance threshold | 0.3-0.7 | Filter irrelevant results |
| **Query Expansion Factor** | Expanded terms per query | 2-5 | ↑ = ↑ Recall, ↑ Noise |

---

## Component 6: Reranking

**Purpose**: Refine initial retrieval results with more expensive model

### Candidate Software Stacks

| Model | Type | Strengths | Weaknesses | Cost | Latency | Quality |
|-------|------|-----------|------------|------|---------|---------|
| **Cohere Rerank v3** | REST API | ✅ Highest quality<br>✅ Multi-lingual<br>✅ Long context (4K) | ❌ Expensive ($2/1K searches) | $2.00/1K searches | 100-300ms | 9.8/10 |
| **Voyage AI Rerank** | REST API | ✅ High quality<br>✅ Domain options | ❌ Expensive ($0.05/1K searches) | $0.05/1K searches | 80-200ms | 9.5/10 |
| **Jina AI Rerank** | REST API | ✅ Good quality<br>✅ Affordable | ❌ Moderate latency | $0.02/1K searches | 100-250ms | 9/10 |
| **FlashRank (ms-marco-MiniLM)** | Python SDK | ✅ FREE ✅<br>✅ Fast local inference | ❌ Lower quality | Free | 20-80ms | 8/10 |
| **FlashRank (rank-T5-flan)** | Python SDK | ✅ FREE ✅<br>✅ Better quality | ❌ Slower than MiniLM | Free | 50-150ms | 8.5/10 |
| **CrossEncoder (ms-marco-MiniLM-L-6)** | Python SDK | ✅ FREE ✅<br>✅ Fast | ❌ Basic quality | Free | 30-100ms | 7.5/10 |
| **CrossEncoder (ms-marco-electra-base)** | Python SDK | ✅ FREE ✅<br>✅ Good quality | ❌ Slower | Free | 80-200ms | 8.2/10 |
| **LLM-Based Reranking (GPT-4)** | REST API | ✅ Highest quality<br>✅ Explainable | ❌ Very expensive ($10/1M tokens)<br>❌ Very slow (2-5s) | $10/1M tokens | 2000-5000ms | 10/10 |

### Recommended Configurations

| Use Case | Model | Top-K Input | Top-K Output | Rationale |
|----------|-------|-------------|--------------|-----------|
| **Maximum Quality** | Cohere Rerank v3 | 50 | 8 | Best reranking |
| **Cost-Optimized** | FlashRank rank-T5-flan | 30 | 8 | Free, decent quality |
| **Speed-Optimized** | FlashRank ms-marco-MiniLM | 20 | 5 | Fastest free option |
| **Hybrid (Cost+Quality)** | Voyage Rerank | 40 | 10 | Good balance |
| **Multi-lingual** | Cohere Rerank v3 | 50 | 8 | Best multi-lang support |
| **Explainability** | GPT-4 LLM Reranking | 10 | 5 | Reasoning trace |

### Reranking Impact

| Metric | Before Rerank | After Rerank | Improvement |
|--------|---------------|--------------|-------------|
| **P@1 (Precision at rank 1)** | 45% | 72% | +60% |
| **MRR (Mean Reciprocal Rank)** | 0.58 | 0.81 | +40% |
| **NDCG@10** | 0.63 | 0.84 | +33% |
| **Context Quality** | 6.5/10 | 8.7/10 | +34% |

### Adapter Implementation

```python
# TODO: Add reranking adapters
- CohereReranker           # rerank-english-v3.0
- VoyageReranker           # rerank-1
- JinaReranker             # jina-reranker-v2
- FlashRankReranker        # Local, free
- CrossEncoderReranker     # Sentence transformers
```

---

## Component 7: Context Assembly

**Purpose**: Format retrieved chunks into coherent LLM context

### Assembly Strategies

| Strategy | Description | Use Case | Context Length |
|----------|-------------|----------|----------------|
| **Simple Concatenation** | Join chunks with separators | Simple RAG | Variable |
| **Citation Format** | Add [1], [2] markers per chunk | Traceable answers | Variable |
| **Hierarchical Context** | Group by document, section | Multi-doc queries | Long (2K-8K tokens) |
| **Compressed Context** | LLM-based summarization | Large retrieval sets | Fixed (1K-2K tokens) |
| **Sliding Window** | Keep most relevant K tokens | Token-constrained | Fixed (e.g., 2000 tokens) |
| **Structured Context** | JSON/XML format for LLM | Structured output needed | Variable |

### Context Window Utilization

| Model | Context Window | Optimal RAG Context | Model Generation | System Prompt |
|-------|----------------|---------------------|------------------|---------------|
| **GPT-4 Turbo** | 128K tokens | 8K-16K tokens | 2K-4K | 500-1K |
| **Claude 3.5 Sonnet** | 200K tokens | 10K-30K tokens | 2K-4K | 500-1K |
| **Gemini 1.5 Pro** | 1M tokens | 20K-100K tokens | 2K-4K | 500-1K |
| **Llama 3.3 70B** | 128K tokens | 8K-16K tokens | 2K-4K | 500-1K |

### Recommended Configuration

```python
{
    "format": "citation",           # Add [1], [2] markers
    "max_tokens": 2200,            # Total context budget
    "chunks_per_source": 3,        # Max chunks per document
    "include_metadata": true,      # Add source, page number
    "deduplication": "exact_match", # Remove duplicate chunks
    "sort_by": "relevance"         # Order by reranker score
}
```

---

## Component 8: LLM Generation

**Purpose**: Generate final answer from context

### Candidate Software Stacks

| Model | Type | Context | Strengths | Weaknesses | Cost | Latency | Quality |
|-------|------|---------|-----------|------------|------|---------|---------|
| **GPT-4 Turbo** | OpenAI API | 128K | ✅ High quality<br>✅ Reliable<br>✅ Good reasoning | ❌ Expensive ($10/1M in + $30/1M out) | $10/$30/1M | 2-5s | 9.8/10 |
| **GPT-4o** | OpenAI API | 128K | ✅ Faster than Turbo<br>✅ Multimodal | ❌ Expensive | $2.50/$10/1M | 1-3s | 9.7/10 |
| **GPT-4o-mini** | OpenAI API | 128K | ✅ Affordable<br>✅ Good quality | ❌ Slightly lower quality | $0.15/$0.60/1M | 1-2s | 9/10 |
| **Claude 3.5 Sonnet** | Anthropic API | 200K | ✅ Best reasoning<br>✅ Long context<br>✅ Safe | ❌ Expensive<br>❌ Slower | $3/$15/1M | 3-6s | 9.9/10 |
| **Claude 3.5 Haiku** | Anthropic API | 200K | ✅ Fast<br>✅ Affordable | ❌ Lower quality | $0.80/$4/1M | 1-2s | 8.5/10 |
| **Gemini 1.5 Pro** | Google API | 1M | ✅ Massive context<br>✅ Good quality<br>✅ Affordable | ❌ Occasional hallucinations | $1.25/$5/1M | 2-4s | 9.3/10 |
| **Gemini 1.5 Flash** | Google API | 1M | ✅ Very fast<br>✅ Very cheap<br>✅ Long context | ❌ Lower quality | $0.075/$0.30/1M | 0.5-1.5s | 8.2/10 |
| **Llama 3.3 70B** | Local/Groq | 128K | ✅ FREE (self-host)<br>✅ Good quality<br>✅ Groq = very fast | ❌ Requires GPU<br>❌ Lower than GPT-4 | Free (self-host) | 0.5-2s (Groq) / 5-10s (local) | 8.8/10 |
| **Mixtral 8x7B** | Local/API | 32K | ✅ FREE (self-host)<br>✅ Good quality | ❌ Smaller context | Free | 3-8s (local) | 8.3/10 |
| **DeepSeek v3** | API | 64K | ✅ Affordable ($0.27/$1.10/1M)<br>✅ Good reasoning | ❌ Newer, less tested | $0.27/$1.10/1M | 2-4s | 8.9/10 |

### Recommended Configurations

| Use Case | Model | Max Output | Temperature | Rationale |
|----------|-------|------------|-------------|-----------|
| **Maximum Quality** | Claude 3.5 Sonnet | 4096 | 0.3 | Best reasoning |
| **Cost-Optimized** | GPT-4o-mini | 2048 | 0.3 | Good quality, affordable |
| **Speed-Optimized** | Gemini 1.5 Flash | 2048 | 0.3 | Fastest, cheap |
| **Long Context** | Gemini 1.5 Pro | 4096 | 0.3 | 1M context window |
| **Self-Hosted** | Llama 3.3 70B | 2048 | 0.3 | Free, good quality |
| **Balanced** | GPT-4o | 2048 | 0.3 | Fast, reliable, good quality |

---

## Component 9: Agent Memory

**Purpose**: Store long-term memory for agents

### Memory Types

| Type | Purpose | Storage | TTL |
|------|---------|---------|-----|
| **Episodic** | Conversation history | OpenSearch episodic indices | 7-30 days |
| **Semantic** | Facts, knowledge | OpenSearch semantic indices | 30 days - ∞ |
| **Procedural** | User preferences | OpenSearch procedural indices | ∞ (CRITICAL) |
| **Entity** | People, places, things | OpenSearch entity indices | 30 days - ∞ |

### Implementation

```python
# adapter_memory.py provides:
- OpenSearchMemoryAdapter  # All 4 memory types
- Hybrid semantic + keyword search
- Automatic expiration based on importance
- Per-user data isolation
```

**See [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md) for details.**

---

## Configuration Matrix

### Pre-Defined Profiles

| Profile | ETL | Chunk | Embed | Storage | Retrieval | Rerank | LLM | Use Case |
|---------|-----|-------|-------|---------|-----------|--------|-----|----------|
| **production_cloud** | Docling | Sandwich 512/25% | OpenAI 3-large | OpenSearch | RRF 0.7/0.3 | Cohere v3 | GPT-4o | Maximum quality |
| **production_hybrid** | MinerU | Sandwich 512/30% | Voyage-finance | OpenSearch | RRF 0.6/0.4 | Voyage | GPT-4o-mini | Finance domain |
| **production_local** | Docling | Sandwich 512/25% | FastEmbed large | OpenSearch | RRF 0.7/0.3 | FlashRank T5 | Llama 3.3 70B | Zero-cost |
| **development** | PyMuPDF | Recursive 256/15% | FastEmbed small | ChromaDB | Semantic only | None | GPT-4o-mini | Fast iteration |
| **research_quality** | LlamaParse | LLM-based | OpenAI 3-large | Milvus | SPLADE | Cohere v3 | Claude 3.5 Sonnet | Best possible |
| **cost_optimized** | Docling | Fixed 256/10% | Google embed-004 | Qdrant | RRF 0.7/0.3 | FlashRank | Gemini Flash | Minimum cost |
| **speed_optimized** | PyMuPDF | Fixed 256/15% | FastEmbed small | Redis | Semantic only | None | Groq Llama 3.3 | Lowest latency |

### Configuration Generator

Each profile translates to `rag_config_schema.yaml`:

```yaml
# Example: production_cloud
etl:
  adapter: docling
  config:
    format: markdown
    
chunking:
  adapter: sandwich
  config:
    chunk_size: 512
    overlap_pct: 25
    prefix_tokens: 100
    suffix_tokens: 100
    
embedding:
  adapter: openai
  config:
    model: text-embedding-3-large
    batch_size: 64
    
storage:
  adapter: opensearch
  config:
    index_type: hnsw
    
retrieval:
  strategy: rrf
  config:
    semantic_weight: 0.7
    bm25_weight: 0.3
    top_k: 30
    
reranking:
  adapter: cohere
  config:
    model: rerank-english-v3.0
    top_k: 8
    
llm:
  adapter: openai
  config:
    model: gpt-4o
    max_tokens: 2048
    temperature: 0.3
```

---

## Benchmark Pipeline Integration

All components are benchmarked in [`benchmark_pipeline.py`](./benchmark_pipeline.py):

1. **Parallel Configuration Testing**: Run multiple configs simultaneously
2. **Golden Q&A Evaluation**: F1, precision, recall, latency, cost per config
3. **Component Ablation**: Test impact of each component individually
4. **Performance Profiling**: Identify bottlenecks
5. **Cost Analysis**: Total cost per 1000 queries

**See [`benchmark_pipeline.py`](./benchmark_pipeline.py) for implementation.**

---

## Summary: Configuration Strategy

### Decision Tree

```
Start
  │
  ├─ Budget? 
  │  ├─ Zero cost    → production_local (Docling + FastEmbed + Llama)
  │  ├─ Minimal cost → cost_optimized (Google + Gemini Flash)
  │  └─ No limit     → production_cloud (OpenAI + GPT-4o + Cohere)
  │
  ├─ Domain?
  │  ├─ Finance      → production_hybrid (MinerU + Voyage-finance)
  │  ├─ Legal        → Voyage-law + Claude Sonnet
  │  └─ General      → production_cloud
  │
  ├─ Scale?
  │  ├─ <1M docs     → ChromaDB or Qdrant
  │  ├─ 1M-100M docs → OpenSearch
  │  └─ >100M docs   → Milvus
  │
  └─ Priority?
     ├─ Quality      → research_quality (LlamaParse + Claude)
     ├─ Speed        → speed_optimized (Redis + Groq)
     └─ Balance      → production_cloud
```

### Next Steps

1. **Review [`benchmark_pipeline.py`](./benchmark_pipeline.py)** - Parallel testing framework
2. **Choose initial profile** from Configuration Matrix
3. **Run benchmark** on your dataset
4. **Iterate** based on F1/cost/latency metrics
5. **Deploy** winning configuration

---

**Last Updated**: May 3, 2026  
**Components**: 9 (ETL, Chunking, Embedding, Storage, Retrieval, Reranking, Context, LLM, Memory)  
**Software Stacks**: 60+ candidate implementations  
**Pre-Defined Profiles**: 7 configurations for different use cases
