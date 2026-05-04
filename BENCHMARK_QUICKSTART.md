# RAG Benchmark Pipeline - Quick Start Guide

This guide shows how to **benchmark and compare** different RAG configurations systematically.

---

## 📋 Overview

The benchmark pipeline allows you to:

✅ **Test multiple configurations in parallel** (e.g., production_cloud vs production_local)  
✅ **Measure quality** (F1, precision, recall, exact match)  
✅ **Profile performance** (latency breakdown per component)  
✅ **Track costs** (per query, per 1K queries, per component)  
✅ **Compare configurations** (automatic ranking by F1 score)

---

## 🚀 Quick Start

### 1. Review Available Configurations

See [`RAG_COMPONENTS_MATRIX.md`](./RAG_COMPONENTS_MATRIX.md) for complete list of:
- **9 Components**: ETL, Chunking, Embedding, Storage, Retrieval, Reranking, Context, LLM, Memory
- **60+ Software Stacks**: All candidate implementations with trade-offs
- **7 Pre-Defined Profiles**: Ready-to-use configurations

**Pre-Defined Profiles:**

| Profile | Use Case | Cost/1K | Quality | Speed |
|---------|----------|---------|---------|-------|
| **production_cloud** | Maximum quality | $2.50 | 9.5/10 | Medium |
| **production_local** | Zero cost (self-hosted) | $0.00 | 8.5/10 | Medium |
| **production_hybrid** | Finance domain | $1.50 | 9.0/10 | Medium |
| **cost_optimized** | Budget-constrained | $0.20 | 8.0/10 | Medium |
| **speed_optimized** | Real-time, <1s latency | $0.80 | 7.5/10 | Fast |
| **research_quality** | Best possible quality | $15.00 | 10/10 | Slow |

### 2. Prepare Your Dataset

Create a JSON file with Q&A pairs:

```json
[
  {
    "id": "q1",
    "question": "What was Microsoft's Q1 FY26 revenue?",
    "answer": "$65.6 billion",
    "expected_chunks": ["chunk_123", "chunk_456"],
    "metadata": {"category": "finance"}
  },
  {
    "id": "q2",
    "question": "Who is the CEO of Microsoft?",
    "answer": "Satya Nadella",
    "expected_chunks": ["chunk_789"],
    "metadata": {"category": "factual"}
  }
]
```

**Example datasets:**
- [`msft_fy26q1_qa_benchmark_100_sanitized.json`](./msft_fy26q1_qa_benchmark_100_sanitized.json) - Microsoft 10-Q questions

### 3. Index Your Documents

Before benchmarking, index documents using your chosen configuration:

```bash
# Using production_cloud config
python index_documents.py \
  --config configs/production_cloud.yaml \
  --documents ./documents/*.pdf \
  --index-name documents_prod_cloud
```

### 4. Run Benchmark

**Single Configuration:**

```bash
python benchmark_pipeline.py \
  --configs production_cloud \
  --dataset msft_fy26q1_qa_benchmark_100_sanitized.json \
  --output-dir benchmark_results_MSFT_FY26Q1_qa
```

**Multiple Configurations (Parallel):**

```bash
python benchmark_pipeline.py \
  --configs production_cloud,production_local,production_hybrid \
  --dataset msft_fy26q1_qa_benchmark_100_sanitized.json \
  --max-parallel 3 \
  --output-dir benchmark_results_MSFT_FY26Q1_qa
```

**All Pre-Defined Profiles:**

```bash
python benchmark_pipeline.py \
  --configs production_cloud,production_local,production_hybrid,cost_optimized,speed_optimized,research_quality \
  --dataset msft_fy26q1_qa_benchmark_100_sanitized.json \
  --max-parallel 4 \
  --output-dir benchmark_results_MSFT_FY26Q1_qa
```

### 5. Review Results

Results are saved to `benchmark_results_MSFT_FY26Q1_qa/`:

```
benchmark_results_MSFT_FY26Q1_qa/
├── production_cloud_20260503_143022.json      # Detailed results
├── production_local_20260503_143045.json
├── production_hybrid_20260503_143108.json
└── comparison_20260503_143108.md              # Summary table
```

**Example comparison table:**

```markdown
## Summary Table

| Rank | Config | F1 | Precision | Recall | Latency (p50) | Cost/1K | Errors |
|------|--------|----|-----------| -------|---------------|---------|--------|
| 1 | **research_quality** | 0.912 | 0.931 | 0.894 | 3200ms | $15.20 | 0 (0.0%) |
| 2 | **production_cloud** | 0.887 | 0.902 | 0.873 | 850ms | $2.45 | 0 (0.0%) |
| 3 | **production_hybrid** | 0.865 | 0.883 | 0.848 | 920ms | $1.48 | 1 (1.0%) |
| 4 | **production_local** | 0.823 | 0.841 | 0.806 | 780ms | $0.00 | 2 (2.0%) |
| 5 | **cost_optimized** | 0.801 | 0.819 | 0.784 | 650ms | $0.18 | 3 (3.0%) |
| 6 | **speed_optimized** | 0.765 | 0.788 | 0.743 | 320ms | $0.82 | 5 (5.0%) |
```

---

## 🔬 Component Ablation Studies

Test the impact of individual components by creating custom configs.

### Example: Embedding Model Comparison

Create 3 configs that differ only in embedding model:

**configs/ablation_embed_openai.yaml:**
```yaml
embedding:
  adapter: "openai"
  config:
    model: "text-embedding-3-large"
# ... rest same as production_cloud
```

**configs/ablation_embed_voyage.yaml:**
```yaml
embedding:
  adapter: "voyage"
  config:
    model: "voyage-finance-2"
# ... rest same as production_cloud
```

**configs/ablation_embed_fastembed.yaml:**
```yaml
embedding:
  adapter: "fastembed"
  config:
    model: "BAAI/bge-large-en-v1.5"
# ... rest same as production_cloud
```

**Run ablation:**

```bash
python benchmark_pipeline.py \
  --configs ablation_embed_openai,ablation_embed_voyage,ablation_embed_fastembed \
  --dataset msft_fy26q1_qa_benchmark_100_sanitized.json \
  --output-dir benchmark_results_ablation_embedding
```

**Result** shows impact of embedding model on F1/cost/latency.

### Other Ablation Studies

- **Chunking strategies**: `sandwich` vs `recursive` vs `fixed` vs `semantic`
- **Retrieval strategies**: `rrf` vs `weighted_fusion` vs `semantic_only` vs `bm25_only`
- **Reranker models**: `cohere` vs `voyage` vs `flashrank` vs `none`
- **Context window**: 1000 vs 2000 vs 5000 vs 8000 tokens
- **Top-K values**: 10 vs 20 vs 50 vs 100 initial retrieval

---

## 📊 Understanding Results

### Quality Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **F1 Score** | `2 * (P * R) / (P + R)` | Harmonic mean of precision and recall (0-1) |
| **Precision** | `correct_tokens / predicted_tokens` | Accuracy of generated answer (0-1) |
| **Recall** | `correct_tokens / ground_truth_tokens` | Coverage of ground truth (0-1) |
| **Exact Match** | `prediction == ground_truth` | Percentage of perfect answers (0-100%) |

**Rule of thumb:**
- F1 > 0.85 = Excellent
- F1 0.7-0.85 = Good
- F1 0.5-0.7 = Acceptable
- F1 < 0.5 = Needs improvement

### Performance Metrics

| Metric | Description |
|--------|-------------|
| **Avg Latency** | Mean response time across all queries |
| **P50 Latency** | 50th percentile (median) |
| **P95 Latency** | 95th percentile (only 5% slower) |
| **P99 Latency** | 99th percentile (worst case) |

**Component Latency Breakdown:**
```
ETL:        50ms  (document ingestion)
Chunking:   20ms  (text splitting)
Embedding:  100ms (vector generation)
Storage:    10ms  (indexing)
Retrieval:  80ms  (hybrid search)
Reranking:  150ms (re-scoring)
Context:    5ms   (assembly)
LLM:        2000ms (generation)
-------------------------------
Total:      2415ms
```

### Cost Metrics

| Metric | Description |
|--------|-------------|
| **Total Cost** | Sum across all queries in benchmark |
| **Cost per Query** | Average cost per single query |
| **Cost per 1K Queries** | Projected monthly cost estimate |

**Component Cost Breakdown:**
```
ETL:        $0.0005  (LlamaParse: expensive, Docling: free)
Embedding:  $0.0013  (OpenAI: $0.13/1M tokens)
Reranking:  $0.0020  (Cohere: $2/1K searches)
LLM:        $0.0300  (GPT-4o: $2.50+$10/1M tokens)
---------------------------------------
Total:      $0.0338 per query
```

---

## 🎯 Configuration Decision Tree

```
Start: Which config should I use?
│
├─ Budget?
│  ├─ Zero cost    → production_local
│  ├─ <$0.50/1K   → cost_optimized
│  └─ No limit    → research_quality
│
├─ Domain?
│  ├─ Finance     → production_hybrid (MinerU + Voyage-finance)
│  ├─ Legal       → [Create custom with Voyage-law]
│  └─ General     → production_cloud
│
├─ Scale?
│  ├─ <1M docs    → production_cloud or production_local
│  ├─ 1M-100M     → production_cloud (OpenSearch)
│  └─ >100M       → research_quality (Milvus GPU)
│
└─ Priority?
   ├─ Quality     → research_quality (F1 ~0.91)
   ├─ Speed       → speed_optimized (320ms p50)
   ├─ Cost        → cost_optimized ($0.20/1K)
   └─ Balance     → production_cloud
```

---

## 🔧 Creating Custom Configurations

Copy an existing config and modify:

```bash
cp configs/production_cloud.yaml configs/my_custom_config.yaml
```

Edit `my_custom_config.yaml`:

```yaml
metadata:
  name: "my_custom_config"
  description: "Custom config for legal documents"

etl:
  adapter: "docling"  # Fast multi-format

embedding:
  adapter: "voyage"
  config:
    model: "voyage-law-2"  # Legal domain-tuned

llm:
  adapter: "anthropic"
  config:
    model: "claude-3-5-sonnet-20241022"  # Best reasoning
```

**Benchmark your custom config:**

```bash
python benchmark_pipeline.py \
  --configs my_custom_config,production_cloud \
  --dataset legal_qa_benchmark.json \
  --output-dir benchmark_results_legal
```

---

## 📈 Optimization Workflow

### Step 1: Baseline

Run `production_cloud` as baseline:

```bash
python benchmark_pipeline.py \
  --configs production_cloud \
  --dataset your_dataset.json
```

**Result**: F1 = 0.85, Latency = 850ms, Cost = $2.45/1K

### Step 2: Ablation

Test each component individually:

```bash
# Test different embedding models
python benchmark_pipeline.py \
  --configs embed_openai,embed_voyage,embed_fastembed \
  --dataset your_dataset.json
```

**Result**: Voyage gives +0.03 F1 for your domain.

### Step 3: Cost Optimization

Replace expensive components:

```bash
# Replace GPT-4o with GPT-4o-mini
# Replace Cohere reranking with FlashRank
python benchmark_pipeline.py \
  --configs production_cloud_optimized \
  --dataset your_dataset.json
```

**Result**: F1 = 0.83 (-0.02), Cost = $0.80/1K (-67% cost)

### Step 4: Deploy Winner

Deploy the configuration with best F1/cost/latency trade-off.

---

## 🔍 Troubleshooting

### Benchmark fails with "No results"

**Cause**: Documents not indexed yet.

**Fix**:
```bash
python index_documents.py \
  --config configs/production_cloud.yaml \
  --documents ./documents/*.pdf
```

### F1 scores are very low (<0.3)

**Possible causes:**
1. **Wrong index name**: Config points to empty index
2. **Documents not indexed**: Run indexing first
3. **Bad chunking**: Chunks too small/large
4. **Poor retrieval**: Top-K too low

**Debug**:
```bash
# Check index
curl http://localhost:9200/documents_prod_cloud/_count

# View sample retrieval
python debug_retrieval.py --query "test query" --top-k 10
```

### Benchmark is very slow

**Reduce dataset size** for iteration:
```bash
# Test on first 10 questions
head -n 10 your_dataset.json > your_dataset_small.json

python benchmark_pipeline.py \
  --configs production_cloud \
  --dataset your_dataset_small.json
```

### Out of memory errors

**Reduce parallelism**:
```bash
python benchmark_pipeline.py \
  --configs production_cloud,production_local \
  --max-parallel 1  # Sequential instead of parallel
```

---

## 📚 Next Steps

1. **Review [`RAG_COMPONENTS_MATRIX.md`](./RAG_COMPONENTS_MATRIX.md)** - Complete components catalog
2. **Choose initial profile** from pre-defined configs
3. **Prepare your Q&A dataset** (JSON format)
4. **Index your documents** using chosen config
5. **Run benchmark** with `benchmark_pipeline.py`
6. **Analyze results** in comparison table
7. **Iterate**: Adjust configs based on F1/cost/latency
8. **Deploy** winning configuration to production

---

## 🆘 Support

- **Components**: See [`RAG_COMPONENTS_MATRIX.md`](./RAG_COMPONENTS_MATRIX.md)
- **Architecture**: See [`ADAPTER_ARCHITECTURE.md`](./ADAPTER_ARCHITECTURE.md)
- **SurfSense Integration**: See [`SURFSENSE_INTEGRATION_GUIDE.md`](./SURFSENSE_INTEGRATION_GUIDE.md)
- **Memory**: See [`MEMORY_INTEGRATION.md`](./MEMORY_INTEGRATION.md)

---

**Happy Benchmarking!** 🚀
