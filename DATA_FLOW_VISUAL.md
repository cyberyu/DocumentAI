# RAG Pipeline Data Flow - Complete Visual Reference

This document provides **ASCII diagrams** showing data flow through all 9 components with concrete examples.

---

## 📊 End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INDEXING PIPELINE                                    │
└─────────────────────────────────────────────────────────────────────────────┘

INPUT: financial_report.pdf (15 pages)
   │
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 1: ETL (Document Ingestion)                                     │
│ Adapter: MinerU / Docling / Unstructured / PyMuPDF / Tika / LlamaParse   │
│ Output: RawDocument                                                        │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ RawDocument(
   │   content="Q1 FY26 Revenue was $65.6B, up 16% YoY...",
   │   format="markdown",
   │   metadata={"pages": 15, "tables": 8}
   │ )
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 2: Chunking (Text Splitting)                                    │
│ Adapter: Sandwich / Semantic / Recursive / Fixed / LLM-based             │
│ Output: List[Chunk]                                                        │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ [
   │   Chunk(id="c1", content="Q1 FY26 Revenue was $65.6B, up 16%...", tokens=512),
   │   Chunk(id="c2", content="Azure and cloud services grew 31%...", tokens=480),
   │   Chunk(id="c3", content="Office 365 commercial revenue...", tokens=495),
   │   ... (30 total chunks)
   │ ]
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 3: Embedding (Vector Generation)                                │
│ Adapter: OpenAI / Voyage / Cohere / Google / Jina / FastEmbed           │
│ Output: List[EmbeddedChunk]                                               │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ [
   │   EmbeddedChunk(
   │     chunk_id="c1",
   │     content="Q1 FY26 Revenue...",
   │     embedding=[0.134, -0.221, 0.089, ...],  # 1024-3072 dims
   │     cost_usd=0.000052
   │   ),
   │   ... (30 chunks)
   │ ]
   │ Total embedding cost: $0.00156
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 4: Storage (Vector Database)                                    │
│ Adapter: OpenSearch / Qdrant / Weaviate / Milvus / Pinecone / pgvector  │
│ Output: IndexingResult                                                     │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ IndexingResult(
   │   indexed_count=30,
   │   index_name="documents_prod_cloud",
   │   latency_ms=850,
   │   cost_usd=0.00156
   │ )
   │
   └─► Stored in OpenSearch with k-NN + BM25 indices


┌─────────────────────────────────────────────────────────────────────────────┐
│                         RETRIEVAL PIPELINE                                   │
└─────────────────────────────────────────────────────────────────────────────┘

INPUT: User Query "What was Microsoft's Q1 revenue?"
   │
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 5: Retrieval (Hybrid Search)                                    │
│ Strategy: RRF / Weighted Fusion / Query Expansion / HyDE / SPLADE        │
│ Output: List[SearchResult]                                                │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ Query("What was Microsoft's Q1 revenue?")
   │   ├─► Semantic Search (Vector): top 30 results
   │   └─► BM25 (Keyword): top 30 results
   │        ↓
   │   RRF Fusion (0.7 semantic + 0.3 BM25)
   │
   │ [
   │   SearchResult(chunk_id="c1", score=0.923, content="Q1 FY26 Revenue was $65.6B..."),
   │   SearchResult(chunk_id="c4", score=0.887, content="Revenue breakdown by segment..."),
   │   SearchResult(chunk_id="c7", score=0.854, content="Compared to Q1 FY25..."),
   │   ... (30 results)
   │ ]
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 6: Reranking (Result Refinement)                                │
│ Adapter: Cohere / Voyage / Jina / FlashRank / CrossEncoder / LLM-based   │
│ Output: List[RerankedResult]                                               │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ Rerank top 30 → top 8 most relevant
   │
   │ [
   │   RerankedResult(chunk_id="c1", rerank_score=0.981, original_score=0.923),
   │   RerankedResult(chunk_id="c4", rerank_score=0.956, original_score=0.887),
   │   RerankedResult(chunk_id="c7", rerank_score=0.934, original_score=0.854),
   │   RerankedResult(chunk_id="c2", rerank_score=0.912, original_score=0.832),
   │   RerankedResult(chunk_id="c9", rerank_score=0.898, original_score=0.801),
   │   RerankedResult(chunk_id="c11", rerank_score=0.876, original_score=0.789),
   │   RerankedResult(chunk_id="c15", rerank_score=0.854, original_score=0.767),
   │   RerankedResult(chunk_id="c18", rerank_score=0.832, original_score=0.745)
   │ ]
   │ Reranking cost: $0.002
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 7: Context Assembly (Format for LLM)                            │
│ Format: Citation / Hierarchical / Compressed / Sliding Window            │
│ Output: RetrievalContext                                                   │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ RetrievalContext(
   │   chunks=[...8 chunks...],
   │   formatted_context="""
   │     [1] Q1 FY26 Revenue was $65.6B, up 16% YoY driven by Azure growth.
   │     
   │     [2] Revenue breakdown by segment:
   │         - Intelligent Cloud: $28.5B (+20%)
   │         - Productivity: $20.3B (+12%)
   │         - Personal Computing: $16.8B (+17%)
   │     
   │     [3] Compared to Q1 FY25 ($56.5B), growth was driven by...
   │     
   │     [4] Azure and cloud services revenue grew 31% YoY...
   │     
   │     [5-8] ... (additional context)
   │   """,
   │   total_tokens=2187,
   │   total_cost_usd=0.00356
   │ )
   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 8: LLM Generation (Answer Generation)                           │
│ Adapter: OpenAI GPT-4o / Claude Sonnet / Gemini / Llama / DeepSeek       │
│ Output: GeneratedAnswer                                                    │
└───────────────────────────────────────────────────────────────────────────┘
   │
   │ Prompt:
   │   System: "You are a helpful assistant. Use the context below to answer."
   │   Context: [2187 tokens from RetrievalContext]
   │   Query: "What was Microsoft's Q1 revenue?"
   │
   │ ↓ GPT-4o generates answer
   │
   │ GeneratedAnswer(
   │   answer="Microsoft reported Q1 FY26 revenue of $65.6 billion, representing 
   │            16% year-over-year growth [1]. This growth was driven primarily by 
   │            Intelligent Cloud ($28.5B, +20%) and strong Azure performance 
   │            (31% growth) [2][4]. Compared to Q1 FY25 ($56.5B), revenue 
   │            increased by $9.1 billion [3].",
   │   citations=["[1]", "[2]", "[3]", "[4]"],
   │   tokens_used={"input": 2187, "output": 89},
   │   cost_usd=0.0321,
   │   latency_ms=2340
   │ )
   │
   ▼
OUTPUT: "Microsoft reported Q1 FY26 revenue of $65.6 billion..."


┌─────────────────────────────────────────────────────────────────────────────┐
│                         MEMORY PIPELINE (PARALLEL)                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────┐
│ COMPONENT 9: Agent Memory (Long-term Storage)                             │
│ Adapter: OpenSearchMemoryAdapter                                          │
│ Types: Episodic / Semantic / Procedural / Entity                          │
└───────────────────────────────────────────────────────────────────────────┘
   │
   ├─► EPISODIC MEMORY
   │   Store conversation turn:
   │   EpisodicMemory(
   │     user_message="What was Microsoft's Q1 revenue?",
   │     agent_response="Microsoft reported Q1 FY26 revenue of $65.6B...",
   │     documents_used=["financial_report.pdf"],
   │     retention=30 days
   │   )
   │
   ├─► SEMANTIC MEMORY
   │   Extract and store fact:
   │   SemanticMemory(
   │     fact="Microsoft Q1 FY26 revenue: $65.6B (+16% YoY)",
   │     confidence=0.98,
   │     source="financial_report.pdf",
   │     retention=90 days
   │   )
   │
   ├─► PROCEDURAL MEMORY
   │   Learn user preference:
   │   ProceduralMemory(
   │     preference_key="response_style",
   │     preference_value="concise with citations",
   │     retention=forever (CRITICAL)
   │   )
   │
   └─► ENTITY MEMORY
       Track mentioned entities:
       EntityMemory(
         entity_name="Microsoft",
         entity_type="organization",
         attributes={"Q1_FY26_revenue": "$65.6B", "growth": "16%"},
         mention_count=1,
         retention=365 days
       )
       
       All stored in OpenSearch with hybrid search (vector + keyword)
```

---

## 🔄 Component-by-Component Data Transformation

### Component 1: ETL → RawDocument

```
INPUT: financial_report.pdf (binary file)

MinerUAdapter.extract() {
  - Load PDF
  - OCR text
  - Extract tables (8 tables detected)
  - Extract formulas (12 formulas)
  - Generate markdown
  - Execution time: 3.2s
  - Cost: $0 (local GPU)
}

OUTPUT: RawDocument(
  document_id="doc_abc123",
  content="""
    # Microsoft Corporation Q1 FY26 Financial Report
    
    ## Revenue Summary
    Q1 FY26 Revenue was $65.6B, up 16% YoY...
    
    | Segment | Revenue | YoY Growth |
    |---------|---------|------------|
    | Intelligent Cloud | $28.5B | +20% |
    | Productivity | $20.3B | +12% |
    | Personal Computing | $16.8B | +17% |
    
    ## Cloud Services
    Azure and cloud services grew 31% YoY...
  """,
  format="markdown",
  metadata={
    "source_file": "financial_report.pdf",
    "pages": 15,
    "tables_extracted": 8,
    "formulas_extracted": 12,
    "extraction_latency_ms": 3200
  },
  extraction_metadata={
    "adapter": "mineru",
    "model": "structeqtable",
    "gpu_used": true
  }
)
```

### Component 2: RawDocument → Chunks

```
INPUT: RawDocument(content="...")

SandwichChunker.chunk() {
  - Split into sections by headers
  - Create 512-token chunks with 25% overlap
  - Add prefix (100 tokens before) and suffix (100 tokens after)
  - Respect table boundaries (don't split tables)
  - Respect sentence boundaries
  - Min chunk size: 100 tokens
  - Generated 30 chunks
}

OUTPUT: [
  Chunk(
    chunk_id="c1",
    content="Q1 FY26 Revenue was $65.6B, up 16% YoY driven by...",
    prefix="# Microsoft Corporation Q1 FY26 Financial Report\n## Revenue Summary\n",
    suffix="...compared to Q1 FY25 ($56.5B). Growth was driven by...",
    chunk_index=0,
    token_count=512,
    metadata={
      "section": "Revenue Summary",
      "has_table": true,
      "has_numbers": true
    }
  ),
  Chunk(
    chunk_id="c2",
    content="Azure and cloud services grew 31% YoY...",
    prefix="...Q1 FY26 Revenue was $65.6B, up 16% YoY driven by\n## Cloud Services\n",
    suffix="...Office 365 commercial revenue increased 15%...",
    chunk_index=1,
    token_count=480,
    metadata={
      "section": "Cloud Services",
      "has_table": false
    }
  ),
  ... (28 more chunks)
]
```

### Component 3: Chunks → EmbeddedChunks

```
INPUT: [Chunk(id="c1", content="..."), ...]

OpenAIEmbeddingAdapter.embed_batch() {
  - Model: text-embedding-3-large (3072 dimensions)
  - Batch size: 64
  - Total chunks: 30
  - Total tokens: 14,320
  - API calls: 1 (batched)
  - Latency: 180ms
  - Cost: $0.00186 (14,320 tokens * $0.13/1M tokens)
}

OUTPUT: [
  EmbeddedChunk(
    chunk_id="c1",
    content="Q1 FY26 Revenue was $65.6B, up 16% YoY...",
    embedding=[
      0.13456, -0.22134, 0.08923, 0.45612, -0.11234, ...  # 3072 floats
    ],
    embedding_model="text-embedding-3-large",
    embedding_dimensions=3072,
    token_count=512,
    cost_usd=0.000062,
    latency_ms=6,
    metadata={...}
  ),
  ... (29 more)
]
```

### Component 4: EmbeddedChunks → Storage

```
INPUT: [EmbeddedChunk(...), ...]

OpenSearchAdapter.index_batch() {
  - Index: documents_prod_cloud
  - Index type: HNSW (hierarchical navigable small world)
  - HNSW params: m=16, ef_construction=200
  - Bulk index 30 chunks
  - Create k-NN index (vector search)
  - Create BM25 index (keyword search)
  - Latency: 850ms
}

OUTPUT: IndexingResult(
  indexed_count=30,
  failed_count=0,
  index_name="documents_prod_cloud",
  latency_ms=850,
  index_size_mb=92.3
)

OpenSearch Storage:
{
  "c1": {
    "content": "Q1 FY26 Revenue...",
    "embedding": [0.13456, -0.22134, ...],  # k-NN index
    "metadata": {...}
  },
  ... (29 more)
}
```

### Component 5: Query → SearchResults

```
INPUT: Query(query_text="What was Microsoft's Q1 revenue?")

HybridRetrievalAdapter.retrieve() {
  1. Embed query: [0.14123, -0.19234, ...]
  
  2. Semantic search (k-NN):
     - Top 30 by cosine similarity
     - Results: [
         {id: "c1", score: 0.923},
         {id: "c4", score: 0.887},
         {id: "c7", score: 0.854},
         ...
       ]
  
  3. BM25 search (keyword):
     - Top 30 by BM25 score
     - Results: [
         {id: "c1", score: 12.4},
         {id: "c2", score: 11.8},
         {id: "c5", score: 10.3},
         ...
       ]
  
  4. RRF Fusion (0.7 semantic + 0.3 BM25):
     - Reciprocal rank fusion
     - Combined scores
  
  5. Return top 30
}

OUTPUT: [
  SearchResult(
    chunk_id="c1",
    content="Q1 FY26 Revenue was $65.6B, up 16% YoY...",
    semantic_score=0.923,
    bm25_score=12.4,
    combined_score=0.945,
    rank=1
  ),
  ... (29 more)
]
```

### Component 6: SearchResults → RerankedResults

```
INPUT: [SearchResult(...) × 30]

CohereReranker.rerank() {
  - Model: rerank-english-v3.0
  - Input: 30 chunks
  - Output: Top 8 chunks
  - Cross-encoder scoring (query-document pairs)
  - Latency: 180ms
  - Cost: $0.002 (1 search * $2/1K)
}

OUTPUT: [
  RerankedResult(
    chunk_id="c1",
    content="Q1 FY26 Revenue was $65.6B, up 16% YoY...",
    original_score=0.945,
    rerank_score=0.981,  # Higher after reranking!
    rank=1
  ),
  RerankedResult(
    chunk_id="c4",
    content="Revenue breakdown by segment...",
    original_score=0.921,
    rerank_score=0.956,
    rank=2
  ),
  ... (6 more, total 8)
]
```

### Component 7: RerankedResults → RetrievalContext

```
INPUT: [RerankedResult(...) × 8]

ContextAssembler.assemble() {
  - Format: citation
  - Max tokens: 2200
  - Chunks per source: 3
  - Deduplication: exact_match
  - Sort by: relevance (rerank_score)
}

OUTPUT: RetrievalContext(
  query="What was Microsoft's Q1 revenue?",
  chunks=[... 8 chunks ...],
  formatted_context="""
Context for answering the query:

[1] Q1 FY26 Revenue was $65.6B, up 16% YoY driven by Azure growth.

[2] Revenue breakdown by segment:
    - Intelligent Cloud: $28.5B (+20%)
    - Productivity: $20.3B (+12%)
    - Personal Computing: $16.8B (+17%)

[3] Compared to Q1 FY25 ($56.5B), growth was driven by cloud services.

[4] Azure and cloud services revenue grew 31% YoY, reaching $28.5B.

[5] Office 365 commercial revenue increased 15% to $12.3B.

[6] LinkedIn revenue grew 10% to $4.2B.

[7] Xbox content and services revenue increased 61% driven by Activision.

[8] Windows OEM revenue decreased 3% due to PC market decline.
  """,
  total_tokens=2187,
  num_chunks=8,
  sources=["financial_report.pdf"],
  citations=["[1]", "[2]", "[3]", "[4]", "[5]", "[6]", "[7]", "[8]"],
  total_cost_usd=0.00356,
  retrieval_latency_ms=1030
)
```

### Component 8: RetrievalContext → Answer

```
INPUT: RetrievalContext(formatted_context="...", query="...")

OpenAILLMAdapter.generate() {
  - Model: gpt-4o
  - Max tokens: 2048
  - Temperature: 0.3
  
  - Prompt:
    System: "You are a financial analyst. Use the context to answer."
    Context: [2187 tokens]
    Query: "What was Microsoft's Q1 revenue?"
  
  - Total input tokens: 2187 + 50 (system) + 8 (query) = 2245
  - Output tokens: 89
  - Latency: 2340ms
  - Cost: $0.0321
    - Input: 2245 tokens * $2.50/1M = $0.0056
    - Output: 89 tokens * $10/1M = $0.0009
}

OUTPUT: "Microsoft reported Q1 FY26 revenue of $65.6 billion, representing 
16% year-over-year growth [1]. This growth was driven primarily by 
Intelligent Cloud ($28.5B, +20%) and strong Azure performance (31% growth) 
[2][4]. Compared to Q1 FY25 ($56.5B), revenue increased by $9.1 billion [3]. 
Key contributors included Azure and cloud services (+31%), Office 365 
(+15%), and Gaming (+61%) from the Activision acquisition [4][5][7]."
```

### Component 9: Memory Storage

```
PARALLEL TO RETRIEVAL:

1. EPISODIC MEMORY:
   EpisodicMemory(
     user_message="What was Microsoft's Q1 revenue?",
     agent_response="Microsoft reported Q1 FY26 revenue of $65.6B...",
     turn_index=42,
     documents_used=["financial_report.pdf"],
     embedding=[...],  # Vector for semantic search
     importance=MEDIUM,
     retention=30 days
   )
   → Stored in agent_memory_episodic_user123

2. SEMANTIC MEMORY:
   SemanticMemory(
     fact="Microsoft Q1 FY26 revenue: $65.6B (+16% YoY)",
     confidence=0.98,
     source="financial_report.pdf",
     embedding=[...],
     importance=HIGH,
     retention=90 days
   )
   → Stored in agent_memory_semantic_user123

3. ENTITY MEMORY:
   EntityMemory(
     entity_name="Microsoft",
     entity_type="organization",
     attributes={
       "Q1_FY26_revenue": "$65.6B",
       "YoY_growth": "16%",
       "CEO": "Satya Nadella"
     },
     mention_count=1,
     embedding=[...],
     retention=365 days
   )
   → Stored in agent_memory_entity_user123
```

---

## 📊 Complete Metrics Summary

```
INDEXING PIPELINE (financial_report.pdf):
┌──────────────┬───────────┬─────────┬──────────────┐
│ Component    │ Latency   │ Cost    │ Output       │
├──────────────┼───────────┼─────────┼──────────────┤
│ ETL          │ 3200ms    │ $0.00   │ 1 document   │
│ Chunking     │ 120ms     │ $0.00   │ 30 chunks    │
│ Embedding    │ 180ms     │ $0.0019 │ 30 vectors   │
│ Storage      │ 850ms     │ $0.00   │ Indexed      │
├──────────────┼───────────┼─────────┼──────────────┤
│ TOTAL        │ 4350ms    │ $0.0019 │ Ready        │
└──────────────┴───────────┴─────────┴──────────────┘

RETRIEVAL PIPELINE (single query):
┌──────────────┬───────────┬─────────┬──────────────┐
│ Component    │ Latency   │ Cost    │ Output       │
├──────────────┼───────────┼─────────┼──────────────┤
│ Retrieval    │ 80ms      │ $0.00   │ 30 results   │
│ Reranking    │ 180ms     │ $0.0020 │ 8 results    │
│ Context      │ 5ms       │ $0.00   │ 2187 tokens  │
│ LLM          │ 2340ms    │ $0.0321 │ Answer       │
│ Memory       │ 45ms      │ $0.00   │ 3 memories   │
├──────────────┼───────────┼─────────┼──────────────┤
│ TOTAL        │ 2650ms    │ $0.0341 │ Complete     │
└──────────────┴───────────┴─────────┴──────────────┘

BREAKDOWN:
- Retrieval: 3% latency
- Reranking: 7% latency
- LLM: 88% latency (dominant)
- Memory: 2% latency

COST BREAKDOWN:
- Embedding (index): $0.0019 one-time
- Reranking: $0.0020 per query
- LLM: $0.0321 per query (dominant: 94%)
- Total per query: $0.0341
- Cost per 1000 queries: $34.10
```

---

## 🔀 Alternative Configurations Comparison

### Production Cloud vs Production Local

```
CONFIGURATION: production_cloud
┌──────────────┬──────────────────────────┬─────────┬──────────┐
│ Component    │ Software Stack           │ Cost    │ Quality  │
├──────────────┼──────────────────────────┼─────────┼──────────┤
│ ETL          │ Docling                  │ Free    │ 8.5/10   │
│ Chunking     │ Sandwich                 │ Free    │ 9/10     │
│ Embedding    │ OpenAI (3072-dim)        │ $0.0019 │ 9.5/10   │
│ Storage      │ OpenSearch               │ Free    │ 9/10     │
│ Retrieval    │ RRF (0.7/0.3)           │ Free    │ 9/10     │
│ Reranking    │ Cohere v3                │ $0.0020 │ 9.8/10   │
│ Context      │ Citation                 │ Free    │ 9/10     │
│ LLM          │ GPT-4o                   │ $0.0321 │ 9.7/10   │
│ Memory       │ OpenSearch               │ Free    │ 9/10     │
├──────────────┼──────────────────────────┼─────────┼──────────┤
│ TOTAL        │                          │ $0.0341 │ 9.5/10   │
└──────────────┴──────────────────────────┴─────────┴──────────┘
                                      Cost/1K: $34.10

CONFIGURATION: production_local
┌──────────────┬──────────────────────────┬─────────┬──────────┐
│ Component    │ Software Stack           │ Cost    │ Quality  │
├──────────────┼──────────────────────────┼─────────┼──────────┤
│ ETL          │ Docling                  │ Free    │ 8.5/10   │
│ Chunking     │ Sandwich                 │ Free    │ 9/10     │
│ Embedding    │ FastEmbed (1024-dim)     │ Free    │ 8.8/10   │
│ Storage      │ OpenSearch               │ Free    │ 9/10     │
│ Retrieval    │ RRF (0.7/0.3)           │ Free    │ 9/10     │
│ Reranking    │ FlashRank (T5-flan)      │ Free    │ 8.5/10   │
│ Context      │ Citation                 │ Free    │ 9/10     │
│ LLM          │ Llama 3.3 70B (local)    │ Free    │ 8.8/10   │
│ Memory       │ OpenSearch               │ Free    │ 9/10     │
├──────────────┼──────────────────────────┼─────────┼──────────┤
│ TOTAL        │                          │ $0.00   │ 8.7/10   │
└──────────────┴──────────────────────────┴─────────┴──────────┘
                                      Cost/1K: $0.00

COMPARISON:
- production_cloud: 9.5/10 quality, $34/1K cost
- production_local: 8.7/10 quality, $0/1K cost
- Quality difference: -0.8 (8.4% lower)
- Cost savings: 100%
- Latency difference: +500ms average (local LLM slower)
```

---

This completes the visual reference for all 9 components! 🎉
