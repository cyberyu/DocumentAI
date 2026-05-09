# Self-Adaptive Master Agent (DeepSeek + SurfSense)

## Purpose

This module adds a **self-optimizing master agent** that evaluates multiple RAG pipeline configurations and recommends the best one for your benchmark dataset.

- LLM for QA loop: `deepseek-v4-flash`
- Ground truth benchmark: `msft_fy26q1_qa_benchmark_100_sanitized.json`
- Target document: uploaded DOCX (e.g., `MSFT_FY26Q1_10Q.docx`)

## Architecture

### Master Agent

The master agent (script: `scripts/self_adaptive_master_agent.py`) performs:

1. Build candidate universe from Cartesian product:
   - chunking strategies
   - embedding models
2. Assign each candidate to a subagent job.
3. Collect subagent reports.
4. Rank candidates by objective score.
5. Emit recommendation + full leaderboard.

### Subagent

Each subagent runs one fixed pipeline config:

- one chunking strategy
- one embedding model

Execution flow:

1. Upload a uniquely named document variant with form params:
   - `chunking_strategy`
   - `embedding_models` (single model list)
2. Poll `/api/v1/documents/status` until `ready`.
3. Run benchmark (`scripts/run_surfsense_benchmark.py`) against that variant.
4. Parse benchmark metrics and return report.
5. Optionally delete temporary document.

### Document Identity Model

- `document_id` (stable): deterministic identity derived from the source file content hash.
   - Same for all pipeline variants built from the same source document.
- `pipeline_upload_id` (per variant): SurfSense upload row ID returned by `/fileupload`.
   - Different per pipeline run and used in `mentioned_document_ids` for backend execution.

Subagents should join/query by both:
- `pipeline_id` to select the pipeline variant
- `document_id` to anchor all variants back to the same logical source document

## Objective Function

Composite score used for ranking:

`0.60 * overall_correct_rate + 0.30 * number_match_rate + 0.10 * mean_token_f1 - 0.01 * request_failures`

Priority order is correctness-first:

1. `overall_correct_rate`
2. `number_match_rate`
3. `mean_token_f1`

## Outputs

For each run prefix, the master writes:

- `<output_dir>/<run_prefix>__master_summary.json`
- `<output_dir>/<run_prefix>__master_summary.md`

Subagent benchmark outputs are also kept in the same output directory.

## Run Example

```bash
python3 scripts/self_adaptive_master_agent.py \
  --config benchmark_runner_config.json \
  --search-space-id 2 \
  --source-doc MSFT_FY26Q1_10Q.docx \
  --benchmark-file msft_fy26q1_qa_benchmark_100_sanitized.json \
  --llm-model deepseek-v4-flash \
  --chunking-strategies chunk_text,chunk_recursive,sandwitch_chunk \
  --embedding-models openai/text-embedding-3-small,openai/text-embedding-3-large \
  --subagent-workers 2 \
  --benchmark-workers 20 \
  --run-prefix deepseek_v4_flash_master
```

## Notes

- This orchestration assumes SurfSense backend + Celery are already running.
- Search space should already be configured to use DeepSeek v4 Flash.
- The script intentionally creates unique document titles per pipeline variant.
- All variants from the same source file now share one stable `document_id` identity in reports.
