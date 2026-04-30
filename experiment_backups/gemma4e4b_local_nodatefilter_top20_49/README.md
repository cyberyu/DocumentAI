# MSFT FY26Q1 QA Benchmark — Results

Generated: 2026-04-28T01:59:22Z

Benchmark file: `msft_fy26q1_qa_benchmark_100_sanitized.json`  
Model: `google/gemma-4-E4B-it` (vLLM @ localhost:8000)  
Embedding: `sentence-transformers/all-MiniLM-L6-v2`  
DB: PostgreSQL (172.19.0.4:5432 / surfsense) — 1 document, 1469 chunks

---

## Overall Results by Group

| Config | G1 (30q) | G2 (40q) | G3 (30q) | Overall |
|---|---|---|---|---|
| No-date / k=60 / top20 / chunks20 / markers ON | 16/30 (53%) | 14/40 (35%) | 0/30 (0%) | 30/100 (30%) |
| Forced-date / k=60 / top10 / chunks20 / markers ON | 1/30 (3%) | 0/40 (0%) | 0/30 (0%) | 1/100 (1%) |
| Infer-date / k=60 / top10 / chunks20 / markers ON | 15/30 (50%) | 8/40 (20%) | 0/30 (0%) | 23/100 (23%) |
| No-date / k=120 / top10 / chunks20 / markers ON | 16/30 (53%) | 8/40 (20%) | 0/30 (0%) | 24/100 (24%) |
| No-date / k=120 / top20 / chunks-all / markers ON | 1/30 (3%) | 22/40 (55%) | 0/30 (0%) | 23/100 (23%) |
| No-date / k=20 / top10 / chunks20 / markers ON | 16/30 (53%) | 8/40 (20%) | 0/30 (0%) | 24/100 (24%) |
| No-date / k=60 / top10 / chunks20 / markers ON | 16/30 (53%) | 8/40 (20%) | 0/30 (0%) | 24/100 (24%) |
| No-date / k=60 / top10 / chunks20 / markers OFF | 16/30 (53%) | 9/40 (22%) | 0/30 (0%) | 25/100 (25%) |
| No-date / k=60 / top10 / chunks20 / raw-Q | 15/30 (50%) | 7/40 (18%) | 0/30 (0%) | 22/100 (22%) |
| No-date / k=60 / top10 / chunks20 / raw-Q / no-markers | 15/30 (50%) | 6/40 (15%) | 0/30 (0%) | 21/100 (21%) |
| No-date / k=60 / top10 / chunks50 / markers ON | 16/30 (53%) | 14/40 (35%) | 0/30 (0%) | 30/100 (30%) |
| No-date / k=60 / top10 / chunks5 / markers ON | 16/30 (53%) | 7/40 (18%) | 0/30 (0%) | 23/100 (23%) |
| No-date / k=60 / top10 / chunks-all / markers ON | 1/30 (3%) | 21/40 (52%) | 0/30 (0%) | 22/100 (22%) |
| No-date / k=60 / top20 / chunks-all / markers ON | 1/30 (3%) | 22/40 (55%) | 0/30 (0%) | 23/100 (23%) |
| No-date / k=60 / top3 / chunks-all / markers ON | 1/30 (3%) | 22/40 (55%) | 0/30 (0%) | 23/100 (23%) |
| No-date / k=60 / top5 / chunks20 / markers ON | 15/30 (50%) | 5/40 (12%) | 0/30 (0%) | 20/100 (20%) |

---

## Per-Group Detailed Results

### G1 (30 questions)

| Config | Correct | Rate | NumMatch | MeanF1 |
|---|---|---|---|---|
| No-date / k=60 / top20 / chunks20 / markers ON | 16/30 | 53% | 93% | 0.8367 |
| Forced-date / k=60 / top10 / chunks20 / markers ON | 1/30 | 3% | 3% | 0.0000 |
| Infer-date / k=60 / top10 / chunks20 / markers ON | 15/30 | 50% | 87% | 0.7633 |
| No-date / k=120 / top10 / chunks20 / markers ON | 16/30 | 53% | 90% | 0.7900 |
| No-date / k=120 / top20 / chunks-all / markers ON | 1/30 | 3% | 3% | 0.0000 |
| No-date / k=20 / top10 / chunks20 / markers ON | 16/30 | 53% | 90% | 0.7900 |
| No-date / k=60 / top10 / chunks20 / markers ON | 16/30 | 53% | 90% | 0.7900 |
| No-date / k=60 / top10 / chunks20 / markers OFF | 16/30 | 53% | 90% | 0.7900 |
| No-date / k=60 / top10 / chunks20 / raw-Q | 15/30 | 50% | 90% | 0.8100 |
| No-date / k=60 / top10 / chunks20 / raw-Q / no-markers | 15/30 | 50% | 93% | 0.8100 |
| No-date / k=60 / top10 / chunks50 / markers ON | 16/30 | 53% | 90% | 0.8000 |
| No-date / k=60 / top10 / chunks5 / markers ON | 16/30 | 53% | 90% | 0.7900 |
| No-date / k=60 / top10 / chunks-all / markers ON | 1/30 | 3% | 3% | 0.0000 |
| No-date / k=60 / top20 / chunks-all / markers ON | 1/30 | 3% | 3% | 0.0000 |
| No-date / k=60 / top3 / chunks-all / markers ON | 1/30 | 3% | 3% | 0.0000 |
| No-date / k=60 / top5 / chunks20 / markers ON | 15/30 | 50% | 83% | 0.6967 |

### G2 (40 questions)

| Config | Correct | Rate | NumMatch | MeanF1 |
|---|---|---|---|---|
| No-date / k=60 / top20 / chunks20 / markers ON | 14/40 | 35% | 52% | 0.2350 |
| Forced-date / k=60 / top10 / chunks20 / markers ON | 0/40 | 0% | 0% | 0.0000 |
| Infer-date / k=60 / top10 / chunks20 / markers ON | 8/40 | 20% | 35% | 0.2050 |
| No-date / k=120 / top10 / chunks20 / markers ON | 8/40 | 20% | 35% | 0.2050 |
| No-date / k=120 / top20 / chunks-all / markers ON | 22/40 | 55% | 72% | 0.2675 |
| No-date / k=20 / top10 / chunks20 / markers ON | 8/40 | 20% | 35% | 0.2050 |
| No-date / k=60 / top10 / chunks20 / markers ON | 8/40 | 20% | 35% | 0.2050 |
| No-date / k=60 / top10 / chunks20 / markers OFF | 9/40 | 22% | 35% | 0.1833 |
| No-date / k=60 / top10 / chunks20 / raw-Q | 7/40 | 18% | 32% | 0.1617 |
| No-date / k=60 / top10 / chunks20 / raw-Q / no-markers | 6/40 | 15% | 32% | 0.1650 |
| No-date / k=60 / top10 / chunks50 / markers ON | 14/40 | 35% | 50% | 0.2450 |
| No-date / k=60 / top10 / chunks5 / markers ON | 7/40 | 18% | 38% | 0.2133 |
| No-date / k=60 / top10 / chunks-all / markers ON | 21/40 | 52% | 72% | 0.2775 |
| No-date / k=60 / top20 / chunks-all / markers ON | 22/40 | 55% | 72% | 0.2675 |
| No-date / k=60 / top3 / chunks-all / markers ON | 22/40 | 55% | 72% | 0.2550 |
| No-date / k=60 / top5 / chunks20 / markers ON | 5/40 | 12% | 25% | 0.1550 |

### G3 (30 questions)

| Config | Correct | Rate | NumMatch | MeanF1 |
|---|---|---|---|---|
| No-date / k=60 / top20 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| Forced-date / k=60 / top10 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| Infer-date / k=60 / top10 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=120 / top10 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=120 / top20 / chunks-all / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=20 / top10 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks20 / markers OFF | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks20 / raw-Q | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks20 / raw-Q / no-markers | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks50 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks5 / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top10 / chunks-all / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top20 / chunks-all / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top3 / chunks-all / markers ON | 0/30 | 0% | 0% | 0.0000 |
| No-date / k=60 / top5 / chunks20 / markers ON | 0/30 | 0% | 0% | 0.0000 |

---

## Key Findings

### Difficulty stratification (full 100-question run, baseline config)

| Group | Difficulty | Type | Correct | Rate |
|---|---|---|---|---|
| G1 | 1 | Direct factual lookup (clear phrasing) | 16/30 | 53% |
| G2 | 2 | Ambiguous / terse field-name lookup | 8/40 | 20% |
| G3 | 3 | Arithmetic reasoning (subtract two values) | 0/30 | 0% |
| **Total** | | | **24/100** | **24%** |

### Pipeline parameter findings (G1 16-config grid, 10-question pilot)

- **Date filter = primary regression driver**: `force` date → 0 docs retrieved → 1/10 (10%)
- **`max_chunks_per_doc=None` is catastrophic**: dumps all 1469 chunks → context overflow → 1/10
- **RRF k (20/60/120)**: no accuracy difference
- **top_k (5/10/20)**: no accuracy difference
- **Matched markers ON/OFF**: no accuracy difference at this scale
- **Query rewrite ON/OFF**: no accuracy difference at this scale
- Best F1: `chunks50` config (0.74 vs 0.71 baseline) — slightly more context width helps

### Root causes for G2/G3 failures

- **G2**: Questions use terse field names ('what is Product?', 'what is Service and other?') that match
  multiple table cells across time periods — model picks the wrong row/column without further context.
- **G3**: All difficulty-3 questions require arithmetic (e.g. difference between fair value and unrealized losses).
  The `gemma-4-E4B-it` model returns N/A rather than performing the calculation from retrieved chunks.

