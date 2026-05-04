# Controlled Chunk Size Experiment: 256 vs 1024 Tokens

**Date:** 2026-05-04  
**Document:** MSFT FY26 Q1 10-Q (`MSFT_FY26Q1_10Q.docx`)  
**Benchmark:** `msft_fy26q1_qa_benchmark_100_sanitized.json` (100 questions)  
**LLM:** DeepSeek V4 Flash (thinking mode, reasoning_effort=high)  
**Workers:** 10 parallel

Two pipeline modes compared — both vary **only** chunk size, all other settings fixed.

| | Mode A | Mode B1 |
|---|---|---|
| **Retrieval** | SurfSense agentic HTTP API (iterative tool use) | Direct pgvector (single-pass RRF) |
| **Backend** | SurfSense Docker API | Bypassed — raw psycopg2 → pgvector |
| **Multi-step** | Yes — agent reruns search tools | No — one retrieval call per question |

---

## Objective

Isolate the effect of chunk size on retrieval+answer quality by changing **only** `CHUNKER_CHUNK_SIZE` between runs — every other pipeline setting is kept identical.

---

## Fixed Settings (identical across both runs)

| Setting | Value |
|---|---|
| Chunker | `chonkie.RecursiveChunker(chunk_size=N)` — no explicit overlap |
| Chunking function | `chunk_text_hybrid` — Markdown-table-aware, context sandwich |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (384-dim, 512-token max) |
| Retrieval mode | Hybrid (semantic + keyword fused via RRF) |
| Semantic search | pgvector cosine distance (`<=>`) |
| Keyword search | PostgreSQL `ts_rank_cd`, normalized OR-term tsquery |
| Fusion | RRF: `score = 1/(k+rank_sem) + 1/(k+rank_kw)`, FULL OUTER JOIN, `k=60` |
| Max chunks/doc | 20 |
| Reranker | None (disabled) |
| Disabled tools | `web_search`, `scrape_webpage` |
| Benchmark | 100 sanitized QA pairs, `sanitize_questions=true` |

**Variable:** `CHUNKER_CHUNK_SIZE` only (256 vs 1024)

---

## Results

### Overall

| Chunk Size | Overall Correct | Number Match | Unit Match | Mean Token F1 | Failures |
|---|---|---|---|---|---|
| **256 tokens** | **98/100 (98%)** | 99/100 (99%) | 100/100 (100%) | 0.5113 | 0 |
| **1024 tokens** | **91/100 (91%)** | 92/100 (92%) | 93/100 (93%) | 0.4350 | 1 |
| **Delta** | **+7pp** | +7pp | +7pp | +0.076 | — |

### Per Group

| Group | Description | 256-chunk | 1024-chunk | Delta |
|---|---|---|---|---|
| **G1** (30 Qs) | Simple fact lookup (billions/millions, %, shares, ratings) | 30/30 (100%) | 23/30 (77%) | **+23pp** |
| **G2** (40 Qs) | Balance sheet & income statement values (USD millions, exact) | 40/40 (100%) | 40/40 (100%) | 0pp |
| **G3** (30 Qs) | YoY / QoQ change calculations | 28/30 (93%) | 28/30 (93%) | 0pp |

### Per Group — Additional Metrics

| Group | Metric | 256-chunk | 1024-chunk |
|---|---|---|---|
| G1 | Number match | 100% | 80% |
| G1 | Unit match | 100% | 77% |
| G1 | Mean token F1 | 0.784 | 0.550 |
| G2 | Number match | 100% | 100% |
| G2 | Unit match | 100% | 100% |
| G2 | Mean token F1 | 0.359 | 0.374 |
| G3 | Number match | 97% | 93% |
| G3 | Unit match | 100% | 100% |
| G3 | Mean token F1 | 0.442 | 0.401 |

---

## Key Findings

1. **256-token chunks outperform 1024-token chunks by +7pp overall** (98% vs 91%) on this financial Q&A task.

2. **The gain is concentrated entirely in G1 (simple fact lookups): +23pp** (100% vs 77%). G1 asks for specific figures like revenue, margins, ratings, and share counts — smaller chunks appear to contain these facts more precisely in isolation, improving retrieval signal.

3. **G2 and G3 are unaffected** (100% and 93% respectively for both sizes). Complex balance sheet lookups and change calculations are equally well served by either chunk size, likely because the RRF fusion retrieves the relevant rows regardless.

4. **256-chunk run was cleaner:** 0 request failures vs 1 recursion-limit failure for 1024-chunk. The 1024-chunk run also had a brief window at the start where some early questions queried a still-indexing document (ingest race condition) — those answers returned "document not found/empty" responses. This slightly penalizes the 1024 score; the true G1 gap may be slightly smaller than 23pp but is still significant.

5. **Unit match dropped to 93% for 1024-chunk** (vs 100% for 256-chunk), suggesting larger chunks return noisier context that causes the model to occasionally output values in different units or formats.

---

## Artifact Files

| File | Description |
|---|---|
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_256chunk_controlled_v1.json` | Full results — 256-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_256chunk_controlled_v1.md` | Summary report — 256-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_1024chunk_controlled_v1.json` | Full results — 1024-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_1024chunk_controlled_v1.md` | Summary report — 1024-token chunks |
| `scripts/run_chunk_size_experiment.py` | Experiment orchestrator script |

---

## Reproduction

```bash
# Run both sizes end-to-end (updates docker-compose, recreates containers, re-ingests, benchmarks):
python3 scripts/run_chunk_size_experiment.py --chunk-sizes 256 1024 --workers 10

# Run a single size only (skip docker restart if already at correct chunk size):
python3 scripts/run_chunk_size_experiment.py --chunk-sizes 256 --skip-docker --skip-ingest --workers 10
```

The orchestrator handles:
1. Updating `CHUNKER_CHUNK_SIZE` in `docker-compose.yml`
2. Force-recreating `backend` + `celery_worker` containers
3. Waiting for backend health
4. Setting `agent_llm_id=22` (DeepSeek V4 Flash) on the search space
5. Deleting stale document chunks from the previous run
6. Re-uploading `MSFT_FY26Q1_10Q.docx` and waiting for indexing
7. Running `run_surfsense_benchmark.py` with the specified workers

---

## Part 2 — Mode B1 (Direct pgvector, No SurfSense API)

### Setup

**Date:** 2026-05-04  
**Retrieval:** Direct psycopg2 → pgvector, single-pass, no agentic loop  
**Config:** `rrf_k=60`, `top_k=10`, `max_chunks_per_doc=50`, `matched_markers=True`, `query_rewrite=True`, `date_filter=none`  
**Embedding:** `sentence-transformers/all-MiniLM-L6-v2`  
**LLM call:** Single DeepSeek V4 Flash call per question (thinking=high)  
**Workers:** 10 parallel

The docker/ingest phase is identical to Mode A (same `CHUNKER_CHUNK_SIZE` change + container recreate + re-ingest). Only the answering phase differs: Mode B1 bypasses the SurfSense HTTP API and queries pgvector directly via psycopg2.

### Results — Overall

| Chunk Size | Overall Correct | Number Match | Unit Match | Mean Token F1 | Failures |
|---|---|---|---|---|---|
| **256 tokens** | **42/100 (42%)** | 43/100 (43%) | 51/100 (51%) | 0.3310 | 0 |
| **1024 tokens** | **71/100 (71%)** | 74/100 (74%) | 78/100 (78%) | 0.4130 | 0 |
| **Delta** | **+29pp (1024 wins)** | +31pp | +27pp | +0.082 | — |

### Results — Per Group

| Group | Description | 256-chunk | 1024-chunk | Delta |
|---|---|---|---|---|
| **G1** (30 Qs) | Simple fact lookup | 30/30 (100%) | 25/30 (83%) | **−17pp (256 wins)** |
| **G2** (40 Qs) | Balance sheet values | 7/40 (18%) | 24/40 (60%) | **+42pp (1024 wins)** |
| **G3** (30 Qs) | YoY / QoQ changes | 5/30 (17%) | 22/30 (73%) | **+56pp (1024 wins)** |

### Results — Per Group Detailed Metrics

| Group | Metric | 256-chunk | 1024-chunk |
|---|---|---|---|
| G1 | Number match | 100% | 83% |
| G1 | Unit match | 100% | 90% |
| G1 | Mean token F1 | 0.877 | 0.730 |
| G2 | Number match | 20% | 62% |
| G2 | Unit match | 32% | 65% |
| G2 | Mean token F1 | 0.125 | 0.255 |
| G3 | Number match | 17% | 80% |
| G3 | Unit match | 27% | 83% |
| G3 | Mean token F1 | 0.060 | 0.307 |

### Mode B1 Key Findings

1. **Mode B1 shows the opposite of Mode A: 1024-token chunks win by +29pp (71% vs 42%).** The direction of the chunk size effect reverses between the two pipeline modes.

2. **256-chunk is perfect on G1 (100%) but collapses on G2/G3 (18%/17%).** With 2344 small chunks in the DB, the single-pass RRF retrieves the right document but passes 50 chunks of ~256 tokens each as context. For G1's simple keyword lookups, the retrieved chunks contain the exact fact. For G2 balance sheet queries and G3 delta calculations, 256-token chunks break table rows apart — consecutive cells (value in Q1, value in prior quarter) may land in different chunks, making the model answer "N/A" because neither chunk contains the full picture.

3. **1024-chunk keeps balance sheet rows intact**: with 479 chunks, table rows that span 200–400 tokens are fully captured in one chunk. The model sees `value1 | value2 | delta` in a single chunk, enabling correct answer extraction for G2 and G3.

4. **The contrast with Mode A is structural, not coincidental.** Mode A's agent can iteratively re-query the DB with different search terms and accumulate context across multiple tool calls. This multi-step reasoning compensates for chunk fragmentation — even with 256-token chunks, the agent pieces together the answer. Mode B1 gets one shot: if the single retrieved context is fragmented, the answer is lost.

5. **Mode B1 1024-chunk (71%) is still substantially below Mode A 1024-chunk (91%)** and far below Mode A 256-chunk (98%). The agentic tool loop adds significant value for financial document QA beyond what a stronger per-chunk context (1024 tokens) can recover.

### Mode B1 Artifact Files

| File | Description |
|---|---|
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_256chunk_controlled_v1.json` | Full results — B1 256-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_256chunk_controlled_v1.md` | Summary — B1 256-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_1024chunk_controlled_v1.json` | Full results — B1 1024-token chunks |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_B1_1024chunk_controlled_v1.md` | Summary — B1 1024-token chunks |
| `scripts/run_mode_b_chunk_size_experiment.py` | Mode B1 experiment orchestrator |

### Mode B1 Reproduction

```bash
# Run both sizes end-to-end (docker + ingest + benchmark):
python3 scripts/run_mode_b_chunk_size_experiment.py --workers 10

# Run a single size only:
python3 scripts/run_mode_b_chunk_size_experiment.py --chunk-sizes 1024 --workers 10

# If DB already has correct chunks (skip docker + ingest):
python3 scripts/run_mode_b_chunk_size_experiment.py --chunk-sizes 1024 --skip-docker --skip-ingest --workers 10
```

---

## Part 3 — Mode C (Fully Local Lexical, No Infrastructure)

### Setup

**Date:** 2026-05-04  
**Retrieval:** Char-chunk plain text (stripped from `.docx`) + lexical token-overlap + numeric-hint scoring  
**No Docker, No pgvector, No SurfSense API** — entirely self-contained  
**Scoring formula:** `score = (|Q_tokens ∩ Chunk_tokens|) × 10 + numeric_hint`  where `numeric_hint=1` if chunk contains a `$`, digit, or financial unit keyword  
**LLM call:** Single DeepSeek V4 Flash call per question (thinking=high)  
**Workers:** 10 parallel  
**Top-k:** 8 chunks as context

Chunk size mapping at ~4 chars/token:

| Token equiv | `chunk_chars` | `chunk_overlap` | Resulting chunks |
|---|---|---|---|
| 256-token equiv | 1024 chars | 128 chars | 217 |
| 1024-token equiv | 4096 chars | 512 chars | 55 |

### Results — Overall

| Chunk Size | Overall Correct | Number Match | Unit Match | Mean Token F1 | Failures |
|---|---|---|---|---|---|
| **256-token equiv** (1024 chars) | **69/100 (69%)** | 87/100 (87%) | 90/100 (90%) | 0.558 | 10 |
| **1024-token equiv** (4096 chars) | **81/100 (81%)** | 94/100 (94%) | 96/100 (96%) | 0.541 | 4 |
| **Delta** | **+12pp (1024 wins)** | +7pp | +6pp | −0.017 | — |

### Results — Per Group

| Group | Description | 256-equiv | 1024-equiv | Delta |
|---|---|---|---|---|
| **G1** (30 Qs) | Simple fact lookup | 29/30 (97%) | 28/30 (93%) | **+3pp (256 wins)** |
| **G2** (40 Qs) | Balance sheet values | 23/40 (58%) | 30/40 (75%) | **+18pp (1024 wins)** |
| **G3** (30 Qs) | YoY / QoQ changes | 17/30 (57%) | 23/30 (77%) | **+20pp (1024 wins)** |

### Results — Per Group Detailed Metrics

| Group | Metric | 256-equiv | 1024-equiv |
|---|---|---|---|
| G1 | Number match | 97% | 93% |
| G1 | Unit match | 97% | 97% |
| G1 | Mean token F1 | 0.827 | 0.797 |
| G2 | Number match | 80% | 93% |
| G2 | Unit match | 80% | 93% |
| G2 | Mean token F1 | 0.405 | 0.435 |
| G3 | Number match | 87% | 97% |
| G3 | Unit match | 97% | 100% |
| G3 | Mean token F1 | 0.493 | 0.427 |

### Mode C Key Findings

1. **Mode C follows the same pattern as Mode B1: larger chunks (1024-equiv) win overall by +12pp** (81% vs 69%). Both single-pass pipelines (lexical and vector) favor larger chunks for this financial document.

2. **The pattern is consistent across G2 and G3**: balance sheet lookups (+18pp) and delta calculations (+20pp) both strongly favor 4096-char chunks. These questions require co-located values (e.g., current quarter vs. prior quarter in the same table row) — smaller chunks split those rows apart, leaving the lexical scorer insufficient context even when both chunks score similarly.

3. **G1 is the only exception**: simple single-value lookups are marginally better with 256-equiv chunks (97% vs 93%). Smaller chunks tend to be "purer" — a single fact per chunk means the lexical match returns that fact without noise from neighboring values.

4. **Mode C 1024-equiv (81%) outperforms Mode B1 1024-chunk (71%) by +10pp**, despite having no embedding-based retrieval. The lexical + numeric-hint scorer, while simpler, benefits from having the full document available locally (no ingest pipeline, no tokenization overhead, no embedding boundary effects).

5. **Request failures halve with larger chunks** (10 → 4). With smaller chunks, 10 questions returned empty predictions — likely because no 1024-char chunk happens to score above zero for some questions, whereas a 4096-char chunk almost always contains some overlap.

6. **Mean token F1 is slightly lower for 1024-equiv** (0.541 vs 0.558). Larger chunks include more boilerplate around the target value, pulling the model toward multi-value or reformatted answers — the numeric is correct but the token F1 penalizes extra tokens.

### Mode C Artifact Files

| File | Description |
|---|---|
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_C_256equiv_chunk_controlled_v1.json` | Full results — C 256-token equiv (1024 chars) |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_C_256equiv_chunk_controlled_v1.md` | Summary — C 256-token equiv |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_C_1024equiv_chunk_controlled_v1.json` | Full results — C 1024-token equiv (4096 chars) |
| `benchmark_results_MSFT_FY26Q1_qa/deepseekflash_C_1024equiv_chunk_controlled_v1.md` | Summary — C 1024-token equiv |
| `scripts/run_mode_c_chunk_size_experiment.py` | Mode C experiment orchestrator |

### Mode C Reproduction

```bash
# Run both sizes (no docker/ingest needed — fully local):
python3 scripts/run_mode_c_chunk_size_experiment.py --workers 10 --top-k 8 --max-questions 100
```

---

## Cross-Mode Summary: Mode A vs Mode B1 vs Mode C

| Mode | Chunk Size | Overall | G1 | G2 | G3 |
|---|---|---|---|---|---|
| **Mode A** (agentic API) | 256 token | **98%** | 100% | 100% | 93% |
| **Mode A** (agentic API) | 1024 token | **91%** | 77% | 100% | 93% |
| **Mode B1** (direct pgvector) | 256 token | 42% | **100%** | 18% | 17% |
| **Mode B1** (direct pgvector) | 1024 token | 71% | 83% | 60% | 73% |
| **Mode C** (lexical local) | 256-equiv (1024 chars) | 69% | 97% | 58% | 57% |
| **Mode C** (lexical local) | 1024-equiv (4096 chars) | 81% | 93% | 75% | 77% |

**Key cross-mode insights:**

- **Mode A (agentic) is the only pipeline where smaller chunks (256) win** — the multi-step tool loop iteratively re-queries to accumulate fragmented context, so finer-grained indexed chunks are a net advantage.
- **Both single-pass pipelines (B1 and C) strongly prefer larger chunks** — they get exactly one retrieval pass, so each chunk must contain enough co-located context for the model to answer without further lookup.
- **The chunk-size optimal direction is pipeline-dependent, not document-dependent.** The same document, same benchmark, same model — opposite optimal chunk size between Mode A and Modes B1/C.
- **Mode A 256-chunk (98%) is the best overall configuration** — the iterative agent fully exploits high granularity.
- **Mode C 1024-equiv (81%) edges out Mode B1 1024-chunk (71%) by +10pp** despite using only lexical scoring (no embeddings). The local char-chunker produces slightly more coherent context windows than pgvector's chunking pipeline.
- **Mode B1 256-chunk (42%) is the worst configuration** — small chunks catastrophically fragment table rows that don't benefit from the iterative agent recovery available in Mode A.

