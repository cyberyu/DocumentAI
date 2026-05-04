# Benchmark Pipeline Overview

Three distinct evaluation pipelines were used to benchmark LLMs on the MSFT FY26Q1 10-Q QA dataset (100 sanitized questions, `msft_fy26q1_qa_benchmark_100_sanitized.json`).

---

## Mode A — SurfSense Agentic Pipeline (HTTP API)

**How it works:**
Questions are submitted to the running SurfSense Docker backend via `POST /api/v1/new_chat`. The full agentic pipeline executes:

1. SurfSense receives the question in a thread
2. The agent uses filesystem middleware tools (`ls`, `read_file`, `glob`, `grep`) to explore the search space
3. Hybrid semantic+lexical search queries the **pgvector** database (Docling-parsed Markdown chunks, RRF re-ranking)
4. The agent synthesises an answer via the configured LLM (OpenAI, Anthropic, or local endpoint)
5. The benchmark runner streams the response and extracts the final answer

**Key variables:**
- LLM backend (configured via `global_llm_config.yaml` or `new_llm_configs` DB table, selected per search space via `agent_llm_id`)
- Chunk size at ingestion time (256-token vs 1024-token chunks in pgvector)
- Doc-pinning (`mentioned_document_ids`) vs. open search
- `disabled_tools` (always: `web_search,scrape_webpage`)
- `enforce_ranked_evidence_first` flag
- `stream_new_chat_patched.py`: recursion_limit=300, max_tool_steps=30, synthesis fallback for runaway loops

**Scripts:**
- `scripts/run_surfsense_benchmark.py` — core runner
- `scripts/run_surfsense_benchmark_gpt5nano.py` — GPT-5 Nano wrapper (sets `agent_llm_id=-3` via `PUT /api/v1/search-spaces/{id}/llm-preferences`)
- `scripts/run_surfsense_benchmark_deepseekflash.py` — DeepSeek Flash wrapper
- `scripts/run_surfsense_benchmark_qwen3_lmstudio.py` — Qwen3 LMStudio wrapper (updates LLM config via `PUT /api/v1/new-llm-configs/{id}`)
- `scripts/run_surfsense_benchmark_gemma_lmstudio.py` — Gemma LMStudio wrapper
- `scripts/run_surfsense_benchmark_gpt4o.py` — GPT-4o wrapper

**Results (sanitized benchmark, 100 questions):**

| Model | Chunk size | Correct | Num-match | Notes | Backup |
|---|---|---|---|---|---|
| DeepSeek V4 Flash | 256-token | **96–99%** | 99% | Exceptional; small chunks give dense RRF coverage | `deepseekflash_surfsense_256chunk_96`, `_99_parallel` |
| DeepSeek V4 Flash | 1024-token | 82% | 87% | Standard production config | `deepseekflash_surfsense_1024chunk_82` |
| DeepSeek V4 Flash | hybrid | 82% | 86% | Mixed chunk sizes | `deepseekflash_surfsense_hybridchunk_82` |
| GPT-5 Nano | 1024-token | 81% | 86% | Best GPT-5 Nano run (doc-pinned) | `gpt5nano_surfsense_1024chunk_81` |
| GPT-5 Nano | 1024-token | 77% | 78% | Latest run (v2, 4 failures) | `gpt5nano_surfsense_1024chunk_77` |
| Claude Sonnet 4.6 | 1024-token | 42% | 64% | Rate-limited via throttle proxy; slow pacing hurt results | `claude_sonnet46_surfsense_docpin_noweb_64` |

---

## Mode B — Bypass SurfSense HTTP API, Direct DB + Custom Retrieval

**How it works:**
Questions are answered without calling the SurfSense `/api/v1/new_chat` endpoint. The retrieval pipeline is **reimplemented in Python**, either connecting directly to the SurfSense PostgreSQL/pgvector database or doing in-memory chunking from the local `.docx` file.

Two sub-variants:

**B1 — Direct pgvector query** (`scripts/grid_search_local_pipeline.py`, `scripts/grid_search_benchmark.py`):
1. Connect directly to the SurfSense PostgreSQL container (`172.19.0.4:5432`) via psycopg2
2. Run configurable hybrid search: RRF with tunable `rrf_k`, `top_k`, `max_chunks_per_doc`
3. Optional query rewriting, date filtering, matched-markers inclusion
4. Send retrieved chunks to LLM (DeepSeek API or vLLM) for a single answer call
5. Grid-search sweeps over retrieval parameters to find the optimal config

**B2 — In-memory local pipeline** (`scripts/local_improved_pipeline.py`):
1. Read MSFT 10-Q `.docx` locally via raw XML stripping (no Docling, no Docker)
2. Char-chunk the plain text (default: 2200 chars / 300 overlap, configurable)
3. Lexical top-k ranking per question (token overlap + numeric hint scoring)
4. Single call to cloud LLM or LMStudio-hosted model
5. Grid-search sweeps over `chunk_chars` / `chunk_overlap` / `top_k`

**Key variables:**
- `rrf_k`, `top_k`, `max_chunks_per_doc` (B1) / `chunk_chars`, `chunk_overlap`, `top_k` (B2)
- `query_rewrite` (B1): whether to pre-rewrite the question for retrieval
- `date_filter`: none / infer / forced (B1)
- `matched_markers`: include position markers in chunk context (B1)
- `thinking_mode`: enable LLM chain-of-thought (both)

**Results (per-group JSON files in `experiment_backups/`):**

| Model | Variant | Best correct | Num-match | Notes | Backup |
|---|---|---|---|---|---|
| DeepSeek V4 Flash | B1 (pgvector, k=60, top10, chunks50) | 57% (G1 only) | 62% | thinking_mode=True; G2 and G3 much weaker | `deepseekflash_local_think_chunks50_62` |
| DeepSeek V4 Pro | B1 (pgvector, k=60, top10, chunks50) | 57% (G1 only) | 63% | thinking_mode=True | `deepseekpro_local_think_chunks50_63` |
| Gemma 4 31B (LMStudio) | B1 (pgvector, top20) | 57% (G1 only) | 97% (num) | High number-match but low strict-correct | `gemma431b_local_think_top20_57` |
| Gemma 4E 4B (LMStudio) | B1 (pgvector, top20) | 53% (G1 only) | 93% (num) | Small model, unit confusion | `gemma4e4b_local_think_top20_54`, `_nodatefilter_49` |

> **Note:** Mode B did not outperform Mode A or C. The main bottleneck was retrieval quality — even with optimised pgvector params, the single-pass RRF retrieval returned less relevant context than Mode A's iterative agentic tool use. Meanwhile Mode C's simple lexical scorer proved surprisingly competitive without any vector infrastructure.

---

## Mode C — Fully Direct: Local Lexical Retrieval + Single Cloud/Local LLM Call

**How it works:**
Completely bypasses SurfSense and its database. Everything runs in-process from a local copy of the `.docx` file:

1. Read the MSFT 10-Q `.docx` via raw XML stripping
2. Char-chunk the plain text (default: 2200 chars / 300 overlap)
3. Rank chunks per question using **lexical token overlap + numeric hint scoring** (no embeddings, no vector DB)
4. Send top-k chunks as context to the LLM in a single chat/completions call
5. Parse and evaluate the model's answer against the benchmark ground truth

**Key variables:**
- `top_k`: number of retrieved chunks passed to the LLM (default: 8)
- `chunk_chars` / `chunk_overlap`: text splitting parameters
- LLM model and endpoint (DeepSeek API, OpenAI API, Anthropic API, LMStudio)
- System prompt and answer extraction format

**Scripts:**
- `scripts/run_deepseek_direct_benchmark.py` — DeepSeek API
- `scripts/run_openai_direct_benchmark.py` — OpenAI API
- `scripts/run_claude_direct_benchmark.py` — Anthropic API
- `scripts/run_lmstudio_direct_benchmark.py` — LMStudio (local models)
- `scripts/run_vllm_direct_benchmark.py` — vLLM server

**Results (100 questions):**

| Model | Correct | Num-match | Notes | Backup |
|---|---|---|---|---|
| DeepSeek V4 Flash | **85%** | 96% | Best Mode C result; `ctxanchor` run 2026-05-02 | `deepseek_v4_flash_direct_20260502_222014` |
| DeepSeek V4 Pro | 78% | 94% | Re-run 2026-05-02 | `deepseek_v4_pro_direct_20260502_rerun` |
| DeepSeek V4 Pro | 62% | 92% | Earlier run with same params | `deepseek_pro_direct_92` |
| DeepSeek V4 Flash | 58% | 83% | Earlier run (pre-ctxanchor) | `deepseek_direct_83` |
| Gemma 4 31B (LMStudio) | 68% | 83% | Local model via LMStudio | `gemma4_31b_lmstudio_direct_83` |
| Gemma 4E 4B (LMStudio) | 55% | 83% | Smaller local model | `gemma4e4b_lmstudio_direct_83` |
| GPT-5 Nano | 39% | 89% | High num-match but low strict-correct; unit/rounding issues | `gpt5nano_openai_direct_89` |
| Claude Sonnet 4.6 | 30% | 49% | Poor single-call prompting; needs agentic pipeline | `claude_sonnet46_direct_30` |

---

## Cross-Mode Summary

| Mode | Best correct | Best num-match | Best model | Requires Docker |
|---|---|---|---|---|
| **A** SurfSense Agentic | **99%** (256-chunk) / 82% (1024-chunk) | 99% | DeepSeek V4 Flash | Yes |
| **B** Bypass API, custom retrieval | 57% (per group) | 63% | DeepSeek V4 Flash/Pro | B1: Yes (DB); B2: No |
| **C** Fully direct, no DB | **85%** | 96% | DeepSeek V4 Flash | No |

**Key takeaways:**
- Mode A with 256-token chunks + RRF achieves the highest accuracy, but requires the full SurfSense stack running
- Mode C (direct) is surprisingly competitive at 85% correct with zero infrastructure — the MSFT 10-Q is dense with numbers and the lexical scorer performs well on numeric lookup questions
- Mode B struggled because direct pgvector retrieval without the SurfSense agent's iterative tool use loses the multi-step reasoning benefit; the per-group results show weak G2/G3 performance
- The scoring metric matters: `number_match_rate` (numeric value present anywhere in answer) is looser than `overall_correct_rate` (requires correct numeric value **and** correct unit)
