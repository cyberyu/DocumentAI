# SurfSense Claude Benchmark Tweaks (API-Limit Safe)

This backup captures the final merged benchmark results and the benchmark runner used for the successful SurfSense + Claude (Sonnet 4.6) run.

## Backed Up Artifacts

- `surfsense_claude_sonnet46_proxy_check100_merged_v1.json`
- `surfsense_claude_sonnet46_proxy_check100_merged_v1.md`
- `run_surfsense_benchmark.py`
- `anthropic_throttle_proxy.py`

## Tweaks Applied (One by One)

1. Fixed Claude model identifier format.
- Problem: invalid model id (`claude-sonnet-4.6`) caused validation failure.
- Fix: use `claude-sonnet-4-6`.

2. Added Sonnet config in SurfSense and pinned search space to it.
- Created `new_llm_configs` entry (id `12`) with provider `ANTHROPIC` and model `claude-sonnet-4-6`.
- Search space `My Search Space` set to `agent_llm_id=12`.

3. Added benchmark-side delay before each SurfSense API call.
- File: `scripts/run_surfsense_benchmark.py`.
- New flag: `--delay-per-request`.
- Applies to primary `/api/v1/new_chat` call and all retry paths.

4. Added resume capability by question index.
- File: `scripts/run_surfsense_benchmark.py`.
- New flag: `--start-question` (1-based).
- Enabled split execution (`Q1-10` and `Q11-100`) and clean merge by question id.

5. Added config default for per-request delay.
- File: `benchmark_runner_config.json`.
- Set `"DELAY_PER_REQUEST": 70` (outer benchmark pacing).

6. Introduced internal Anthropic-call throttling proxy.
- File: `scripts/anthropic_throttle_proxy.py`.
- Function: enforce minimum interval between upstream Anthropic calls.
- Default behavior: 60s spacing between internal calls.

7. Routed SurfSense Claude config through proxy.
- Updated `new_llm_configs.id=12` `api_base` to `http://172.19.0.1:9100`.
- This made internal planning/retrieval/final calls obey 60s minimum spacing.

8. Increased benchmark HTTP timeout for long proxy-throttled turns.
- Issue: some questions exceeded default 180s and failed with timeout.
- Fix: run with `--request-timeout 900` for stability.

9. Pinned benchmark to target document and disabled web tools.
- Used `--document-title-contains MSFT_FY26Q1_10Q`.
- Kept disabled tools `web_search,scrape_webpage` for deterministic doc-only runs.

10. Executed split runs and merged by canonical benchmark id order.
- Q1-10 file: `surfsense_claude_sonnet46_proxycheck10_v2.json`.
- Q11-100 file: `surfsense_claude_sonnet46_proxy_q11_100_v1.json`.
- Final merged file: `surfsense_claude_sonnet46_proxy_check100_merged_v1.json`.

## Final Merged Summary

- Overall correct: 42/100 (42.00%)
- Number match: 64/100 (64.00%)
- Unit match: 91/100 (91.00%)
- Request failures: 0

## Repro Notes

1. Ensure throttle proxy is running:
- `conda run --no-capture-output -n ai python -u scripts/anthropic_throttle_proxy.py`

2. Ensure SurfSense Claude config points to proxy API base:
- `http://172.19.0.1:9100`

3. Run benchmark with extended timeout:
- `conda run --no-capture-output -n ai python -u scripts/run_surfsense_benchmark.py --config benchmark_runner_config.json --request-timeout 900 ...`

