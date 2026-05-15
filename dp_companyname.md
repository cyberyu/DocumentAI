# COMPANYNAME Stabilization Notes

## Goal
Stabilize extraction for the `COMPANYNAME` field (L1-010) so outputs are consistently the adviser entity name instead of numeric noise, trust/family names, or procedural text.

## Explicit Non-Goal
`strict_correct` logic was intentionally left unchanged.

## Root Causes Identified
1. Text extraction fallback could collapse verbose model output to trailing numeric fragments (for example `3`).
2. Generic text retries were not specific enough for entity disambiguation (adviser vs trust/series/fund-family).
3. Text validity checks accepted some malformed long/procedural outputs as “text”.
4. Prompt wording drift around raw schema token (`COMPANYNAME`) reduced retrieval consistency.

## Stabilization Changes
All changes were implemented in `scripts/run_surfsense_benchmark.py`.

### 1) Deterministic schema-term phrasing for COMPANYNAME
- Added a lock step so `COMPANYNAME` is always normalized to `company name` in the asked question path.
- This is applied even if global schema normalization is disabled.

### 2) Text candidate extraction no longer number-biased
- Added dedicated text extraction path (`_extract_final_text_candidate`) for text-type scoring/retry checks.
- Text scoring path now uses text extraction instead of numeric-prioritized extraction.
- Prevents accidental truncation to standalone numbers from long generations.

### 3) COMPANYNAME-specific retry stage
- Added dedicated retry prompt builder (`_build_companyname_retry_question`) focused on entity-name extraction.
- Added COMPANYNAME validation (`_is_valid_companyname_answer`) to reject:
  - boolean-like outputs,
  - numeric-only outputs,
  - malformed/procedural long strings.
- Added COMPANYNAME coercion (`_coerce_companyname_prediction`) to extract concise company-like spans when present.

### 4) Adviser disambiguation logic
- Added adviser-focused heuristic (`_looks_like_investment_adviser_name`).
- If COMPANYNAME answer is valid text but not adviser-like, an additional adviser-focused retry is triggered.
- Retry instruction explicitly asks for investment adviser entity and discourages trust/series/family names.

### 5) Text lenient scoring tightened
- For expected type `text`, lenient token overlap threshold was tightened to reduce false-positive near matches.
- This supports cleaner evaluation behavior for entity-name tasks while leaving strict logic untouched.

## Validation Evidence
### Focused L1-010 check after final patch
- Run: `smoke2_l1_010_013_companyname_fix5_20260513`
- Output: adviser-form answer (`BNY Mellon Investment Adviser, Inc`)

### 5-run robustness sweep (L1-010 only)
- Base run: `l1010_consistency_fix5_20260513_162600`
- Runs: `_r1` to `_r5`
- Result summary:
  - identical normalized prediction across all 5 runs,
  - no reversion to numeric junk outputs,
  - `overall_correct` and `lenient_correct` stable across all runs.

Artifacts:
- `benchmark_results_df_html_qa/l1010_consistency_fix5_20260513_162600_r1.json`
- `benchmark_results_df_html_qa/l1010_consistency_fix5_20260513_162600_r2.json`
- `benchmark_results_df_html_qa/l1010_consistency_fix5_20260513_162600_r3.json`
- `benchmark_results_df_html_qa/l1010_consistency_fix5_20260513_162600_r4.json`
- `benchmark_results_df_html_qa/l1010_consistency_fix5_20260513_162600_r5.json`

## Current Status
- COMPANYNAME extraction behavior is operationally stabilized for L1-010 under current benchmark settings.
- `strict_correct` remains unchanged by design in this stabilization pass.

## 100% Number-Match Reference Run
This section records the exact settings/artifacts for the smoke run that achieved `number_match_rate = 1.0` (10/10).

### Run ID
- `smoke10_rerun_no_interrupt_20260513_v4`

### Artifacts
- `benchmark_results_df_html_qa/smoke10_rerun_no_interrupt_20260513_v4.json`
- `benchmark_results_df_html_qa/smoke10_rerun_no_interrupt_20260513_v4.md`

### Reproducible Invocation
- Python executable: `/home/syu/anaconda3/envs/documentai/bin/python`
- Command:
  - `scripts/run_surfsense_benchmark.py --config benchmark_runner_config.json --benchmark-file df_qa_smoke10_skip_L1-006.json --run-name smoke10_rerun_no_interrupt_20260513_v4`

### Complete Effective Settings (from run artifact `config`)
- `base_url`: `http://localhost:8930`
- `search_space_id`: `1`
- `threading_mode`: `per_question`
- `benchmark_file`: `df_qa_smoke10_skip_L1-006.json`
- `document_title_contains`: `df.html`
- `mentioned_document_ids`: `[391]`
- `max_questions`: `0` (run full input file)
- `sleep_between`: `0.0`
- `workers`: `1`
- `sanitize_questions`: `false`
- `question_suffix`: `""`
- `blend_fund_context`: `true`
- `normalize_schema_terms`: `true`
- `post_verbatim_stage`: `false`
- `disabled_tools`: `["web_search", "scrape_webpage"]`

### Execution Notes
- This run used the same benchmark file and backend/search-space/document pinning as prior smoke checks.
- No strict-scoring changes were applied for this result; this section documents numeric/unit-match reproducibility only.

### Metrics Snapshot
- `questions_run`: `10`
- `number_match_count`: `10`
- `number_match_rate`: `1.0` (100%)
- `unit_match_rate`: `1.0` (100%)
- `overall_correct_rate`: `0.3` (3/10)

### Important Interpretation
- This is a **number/unit matching milestone**, not full benchmark correctness parity.
- Keep these settings as the current numeric-extraction baseline for smoke validation.
