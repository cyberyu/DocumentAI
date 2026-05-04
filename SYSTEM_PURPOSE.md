# Adaptable Agentic RAG System - Purpose & Goals

**Date**: May 3, 2026

---

## 🎯 PRIMARY GOAL: Production Agentic RAG System

This system is **first and foremost a production-ready Agentic RAG platform** for answering questions about domain-specific documents (financial reports, legal contracts, scientific papers, technical documentation, etc.).

### What Users Do With The System

**Primary Use (99% of usage)**:
1. Upload NEW documents in their domain (PDF, DOCX, HTML, XLSX, EML, etc.)
2. Ask questions about these documents
3. Get intelligent, cited answers from the agentic RAG system
4. Repeat for thousands/millions of queries

**One-Time Setup (happens once per domain)**:
1. Provide golden standard Q&A dataset (50-100 examples)
2. Run agent optimizer to discover best configuration
3. Deploy optimized configuration
4. System is now ready for primary use

---

## 📊 Two-Phase Architecture

### Phase 1: Optimization (One-Time, 2-8 hours)

**Purpose**: Find the best RAG configuration for a specific domain

**Input**:
- Example documents (10-15 PDFs, DOCX, HTML representing the domain)
- Golden Q&A dataset (50-100 question-answer pairs)

**Process**:
- Agent Optimizer explores component combinations
- Evaluates each config on golden Q&A
- Discovers optimal: ETL provider, chunk size, embedding model, retrieval strategy

**Output**:
- `production_optimized.yaml` (best configuration)
- Performance metrics: 88.1% F1, 380ms latency, $0.005/query
- Typical improvement: +5-15% F1 over baseline

**Frequency**: Once per domain, or when domain significantly changes

---

### Phase 2: Production Agentic RAG ⭐ **(THIS IS THE MAIN GOAL)**

**Purpose**: Serve real user queries on NEW documents in the optimized domain

**Input**:
- NEW user documents (unlimited, in same domain)
- User questions about these documents

**Process**:
1. **Multi-Format Processing**: Convert PDF/DOCX/HTML → clean markdown
2. **Optimized Chunking**: Use best chunk size/strategy from Phase 1
3. **Best Embedding**: Encode with optimal model (maybe Voyage Finance, OpenAI 3K, or local BGE)
4. **Smart Retrieval**: Hybrid RRF with optimal parameters
5. **Reranking**: If beneficial (discovered in Phase 1)
6. **Agentic Intelligence**:
   - Multi-step reasoning over retrieved context
   - Tool use: `search_knowledge_base`, `web_search`, `calculator`
   - Self-correction and validation
   - Generate answer with citations

**Output**:
- High-quality answers grounded in documents
- Citations (document + page references)
- Confidence scores
- Fast (300-500ms P95)
- Cost-efficient ($0.002-0.01/query)

**Frequency**: Millions of queries, continuously

---

## 🚀 End-to-End Example: Financial Document Q&A

### Step 1: One-Time Optimization (4 hours)

```python
# User provides golden standard for financial domain
optimizer = AgentOptimizer()

best_config = optimizer.optimize(
    documents=[
        "example_10q.pdf",
        "example_annual_report.pdf",
        "example_earnings.pdf"
    ],
    golden_qa=load_json("financial_qa_benchmark_100.json")
)

# Agent discovers after testing 127 configurations:
# ✓ MinerU (best for financial PDFs with tables)
# ✓ 256 token chunks (optimal balance)
# ✓ Voyage Finance embeddings (domain-specific, 32K context)
# ✓ Hybrid RRF (k=40)
# ✓ Reranking enabled (+2.3% F1)
#
# Result: 88.1% F1 (vs 78.3% baseline = +9.8% improvement)

best_config.deploy("production")
```

---

### Step 2: Production Use (Ongoing, Millions of Queries)

```python
# Different users upload THEIR financial documents
orchestrator = RAGOrchestrator(config="production")

# User 1 uploads their company's 10-Q
user1_result = orchestrator.execute(
    query="What was our R&D spending in Q3?",
    documents=["acme_corp_q3_10q.pdf"]  # NEW document!
)
# Returns: "R&D spending was $12.3M in Q3 2025, up 8% YoY..."
# [Citation: 10-Q page 15, Operating Expenses table]

# User 2 uploads investor presentation
user2_result = orchestrator.execute(
    query="What are the key growth drivers mentioned?",
    documents=["investor_presentation_2026.pptx"]  # NEW document, different format!
)
# Returns: "Three key growth drivers: 1) Cloud revenue (+45% YoY)..."
# [Citations: Slide 8, Slide 12]

# User 3 uploads legal filing
user3_result = orchestrator.execute(
    query="Are there any material litigation risks disclosed?",
    documents=["sec_filing_8k.html"]  # NEW document, HTML format!
)
# Returns: "Yes, two material risks disclosed: 1) Patent infringement..."
# [Citation: Risk Factors section, para 3]
```

**Key Point**: The system was optimized ONCE on example financial documents, but now serves queries on UNLIMITED NEW financial documents in various formats (PDF, PPTX, HTML, DOCX, etc.).

---

## 🔑 Critical Distinction

| Aspect | Phase 1: Optimization | Phase 2: Production RAG |
|--------|------------------------|-------------------------|
| **Purpose** | Find best config | Answer questions |
| **Documents** | 10-15 examples | Unlimited NEW docs |
| **Queries** | 100 golden Q&A | Millions of user queries |
| **Frequency** | Once per domain | Continuous |
| **Duration** | 2-8 hours | Milliseconds per query |
| **User-Facing** | No (setup) | **YES (main product)** |
| **Goal** | Optimization | **Production RAG** |

---

## 📁 Multi-Format Support (Production Feature)

The **primary value** of the system is handling diverse document formats in production:

| Format | Example Use Cases | ETL Provider | Features |
|--------|-------------------|--------------|----------|
| **PDF** | Financial reports, research papers, contracts | MinerU, Docling | Table extraction, formula recognition |
| **DOCX** | Corporate docs, proposals, reports | Docling | Structure preservation |
| **HTML** | Web documentation, articles, wikis | Unstructured | Clean text extraction |
| **XLSX** | Financial data, spreadsheets | Docling | Table structure |
| **PPTX** | Presentations, investor decks | Docling | Slide text extraction |
| **EML** | Email archives, customer correspondence | Unstructured | Thread parsing |

**Agent optimization determines which ETL provider works best for YOUR domain**, then production system uses that provider to process ALL NEW documents in that format.

---

## 🤖 Agentic Intelligence (Production Feature)

The production system provides **agentic capabilities** beyond simple retrieval:

1. **Multi-Step Reasoning**
   - "Compare Q1 vs Q2 revenue and explain the variance"
   - Agent retrieves Q1 data, then Q2 data, then computes difference, then searches for explanations

2. **Tool Use**
   - `search_knowledge_base` - Query the optimized RAG pipeline
   - `web_search` - Augment with external data if needed
   - `calculator` - Perform computations on extracted numbers
   - `read_file` - Access full documents for deep analysis

3. **Self-Correction**
   - Validates answers against retrieved context
   - Re-queries if confidence is low
   - Acknowledges uncertainty: "The document doesn't explicitly state..."

4. **Citations**
   - Every claim linked to source chunk
   - Document references: "10-Q page 12, Revenue Recognition section"
   - Confidence scores: 0.94

---

## 💡 Summary

### What This System Is:
✅ **Production Agentic RAG platform** for domain-specific document Q&A  
✅ **Multi-format processor** (PDF, DOCX, HTML, XLSX, PPTX, EML)  
✅ **Intelligent agent** with reasoning, tool use, self-correction  
✅ **Self-optimizing** (learns best config from golden standard)  
✅ **Scalable** (serves millions of queries on unlimited NEW documents)

### What Happens:
1. **Setup** (Once): Optimize configuration for domain using golden standard
2. **Production** (Continuous): Serve real queries on NEW documents with optimized setup
3. **Value**: Users get high-quality answers on THEIR documents, not just examples

### The Innovation:
- Traditional RAG: Manual tuning, limited to specific documents
- **This system**: Auto-optimizes once, then handles ANY document in domain with intelligent agentic responses

---

**The agent optimizer is a means to an end. The end is production agentic RAG on NEW domain-specific documents.**
