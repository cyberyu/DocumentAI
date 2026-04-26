# GPT-5 Nano Benchmark Configuration

This document captures the GPT-5 nano approach and the latest reproducible 10-question result.

## Related Baseline

- Baseline rollback run documented in `Eighty_percent_results.md` (`8/10`, `80%`).

## Model Setup

The OpenAI model entry was updated in `global_llm_config.yaml` with:

- `name`: `"GPT-5 nano"`
- `model_name`: `"gpt-5-nano"`
- `description`: `"OpenAI GPT-5 nano via ChatGPT API"`

Backend services were recreated to apply config updates:

```bash
docker compose up -d --force-recreate backend celery_worker celery_beat
```

## Run Command (Foreground)

Run from the project root in the `ai` conda environment:

```bash
conda activate ai
python scripts/run_surfsense_benchmark_gpt4o.py --max-questions 10 --run-name openai_gpt5nano_check10_repro
```

- Run mode: foreground (terminal output only)
- Generated artifacts:
  - `benchmark_results_MSFT_FY26Q1_qa/openai_gpt5nano_check10_repro.json`
  - `benchmark_results_MSFT_FY26Q1_qa/openai_gpt5nano_check10_repro.md`

## Effective Benchmark Runtime Config

From `benchmark_results_MSFT_FY26Q1_qa/openai_gpt5nano_check10_repro.json`:

- `base_url`: `http://localhost:8929`
- `search_space_id`: `1`
- `threading_mode`: `per_question`
- `benchmark_file`: `msft_fy26q1_qa_benchmark_100_sanitized.json`
- `document_title_contains`: `"MSFT_FY26Q1_10Q"`
- `mentioned_document_ids`: `[4]`
- `max_questions`: `10`
- `sleep_between`: `0.0`
- `sanitize_questions`: `false`

## Result Summary (This Run)

- Questions run: `10 / 100`
- Overall correct: `4` (`40.00%`)
- Number match: `4` (`40.00%`)
- Unit match: `4` (`40.00%`)
- Mean token F1: `0.1524`
- Request failures: `2`
- Context overflow failures: `0`

## Failure Pattern Notes

- Empty outputs occurred for some items and are counted under request failures.
- Some incorrect answers reused nearby but wrong values (for example `11,465 million` and `13,061 million`).
- Some responses included extra reasoning text before the final numeric value.

## Comparison With Baseline

- `Eighty_percent_results.md`: `8/10` (`80%`), rollback baseline behavior.
- `GptNano5_results.md` run above: `4/10` (`40%`) on the same first 10 benchmark questions.
