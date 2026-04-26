# Eighty Percent Benchmark Configuration

This document captures the exact setup that produced the 80% (8/10) result.

## Run Command (Foreground)

```bash
python3 scripts/run_surfsense_benchmark.py \
  --benchmark-file msft_fy26q1_qa_benchmark_100_sanitized.json \
  --max-questions 10 \
  --run-name rollback_8of10_check_live
```

- Run mode: foreground (no output redirection)
- Generated artifacts:
  - `benchmark_results_MSFT_FY26Q1_qa/rollback_8of10_check_live.json`
  - `benchmark_results_MSFT_FY26Q1_qa/rollback_8of10_check_live.md`

## Effective Benchmark Runtime Config

From `benchmark_results_MSFT_FY26Q1_qa/rollback_8of10_check_live.json`:

- `base_url`: `http://localhost:8929`
- `search_space_id`: `1`
- `threading_mode`: `per_question`
- `benchmark_file`: `msft_fy26q1_qa_benchmark_100_sanitized.json`
- `document_title_contains`: `null`
- `mentioned_document_ids`: `[]`
- `max_questions`: `10`
- `sleep_between`: `0.0`
- `sanitize_questions`: `true`

## Result Summary (This Run)

- Questions run: `10 / 100`
- Overall correct: `8` (`80.00%`)
- Number match: `8` (`80.00%`)
- Unit match: `9` (`90.00%`)
- Mean token F1: `0.5106`
- Request failures: `0`
- Context overflow failures: `0`

## Notes

- This is the rollback (non-hard-pin) behavior baseline.
- The run used Group1 questions (`G1-001` to `G1-010`) in this 10-question check.
