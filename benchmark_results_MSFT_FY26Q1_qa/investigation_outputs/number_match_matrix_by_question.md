# Number Match Matrix by Question

Legend: `Y` = number_match true, `N` = number_match false, `-` = missing question in run.

## Included Runs

| Label | number_match_rate | overall_correct_rate | file |
|---|---:|---:|---|
| gemma4e2b_surfsense_docpin_noweb_8/docker_gemma4e2b_vllm_docpin_noweb_check100_locked | 8.00% | 4.00% | experiment_backups/gemma4e2b_surfsense_docpin_noweb_8/docker_gemma4e2b_vllm_docpin_noweb_check100_locked.json |
| gemma4e4b_surfsense_noweb_34/full100_live_rollback_check100 | 34.00% | 18.00% | experiment_backups/gemma4e4b_surfsense_noweb_34/full100_live_rollback_check100.json |
| gemma4e4b_vllm_direct_35/vllm_direct_gemma4_check100_corrected | 35.00% | 18.00% | experiment_backups/gemma4e4b_vllm_direct_35/vllm_direct_gemma4_check100_corrected.json |
| gemma4e4b_vllm_direct_39/vllm_direct_gemma4_check10 | 39.00% | 21.00% | experiment_backups/gemma4e4b_vllm_direct_39/vllm_direct_gemma4_check10.json |
| gpt4o_openai_direct_37/openai_direct_gpt4o_check100_corrected | 37.00% | 25.00% | experiment_backups/gpt4o_openai_direct_37/openai_direct_gpt4o_check100_corrected.json |
| gpt5nano_openai_direct_37/openai_direct_gpt5nano_backfill72_100 | 37.00% | 19.00% | experiment_backups/gpt5nano_openai_direct_37/openai_direct_gpt5nano_backfill72_100.json |
| gpt5nano_surfsense_docpin_noweb_32/docker_gpt5nano_docpin_check100_noweb | 32.00% | 14.00% | experiment_backups/gpt5nano_surfsense_docpin_noweb_32/docker_gpt5nano_docpin_check100_noweb.json |
| benchmark_results_MSFT_FY26Q1_qa/full100_live | 46.00% | 26.00% | benchmark_results_MSFT_FY26Q1_qa/full100_live.json |

## Matrix

| ID | gemma4e2b_surfsense_docpin_noweb_8/docker_gemma4e2b_vllm_docpin_noweb_check100_locked | gemma4e4b_surfsense_noweb_34/full100_live_rollback_check100 | gemma4e4b_vllm_direct_35/vllm_direct_gemma4_check100_corrected | gemma4e4b_vllm_direct_39/vllm_direct_gemma4_check10 | gpt4o_openai_direct_37/openai_direct_gpt4o_check100_corrected | gpt5nano_openai_direct_37/openai_direct_gpt5nano_backfill72_100 | gpt5nano_surfsense_docpin_noweb_32/docker_gpt5nano_docpin_check100_noweb | benchmark_results_MSFT_FY26Q1_qa/full100_live |
|---|---|---|---|---|---|---|---|---|
| G1-001 | Y | Y | Y | Y | Y | Y | Y | Y |
| G1-002 | N | Y | Y | Y | Y | Y | N | Y |
| G1-003 | N | Y | Y | Y | Y | Y | N | Y |
| G1-004 | Y | N | Y | Y | Y | Y | Y | Y |
| G1-005 | N | Y | Y | Y | Y | Y | N | Y |
| G1-006 | N | Y | Y | Y | Y | Y | N | Y |
| G1-007 | Y | N | Y | Y | Y | Y | Y | N |
| G1-008 | N | Y | Y | Y | Y | Y | N | Y |
| G1-009 | N | Y | Y | Y | Y | Y | N | Y |
| G1-010 | N | N | N | N | N | N | N | Y |
| G1-011 | N | Y | Y | Y | Y | Y | N | Y |
| G1-012 | N | Y | Y | Y | Y | Y | Y | Y |
| G1-013 | N | N | Y | Y | Y | Y | N | Y |
| G1-014 | N | Y | Y | Y | Y | Y | N | Y |
| G1-015 | Y | Y | Y | Y | Y | Y | N | Y |
| G1-016 | N | Y | Y | Y | Y | Y | Y | Y |
| G1-017 | Y | Y | Y | Y | Y | Y | N | Y |
| G1-018 | Y | N | Y | Y | Y | Y | N | N |
| G1-019 | N | N | Y | Y | Y | Y | N | Y |
| G1-020 | Y | Y | Y | Y | Y | Y | Y | Y |
| G1-021 | N | N | N | N | N | N | Y | Y |
| G1-022 | N | N | N | N | N | N | N | N |
| G1-023 | N | N | N | N | Y | Y | N | Y |
| G1-024 | N | Y | N | Y | Y | Y | Y | Y |
| G1-025 | N | Y | Y | Y | Y | Y | Y | Y |
| G1-026 | N | Y | Y | Y | Y | Y | N | Y |
| G1-027 | N | Y | Y | Y | Y | Y | Y | Y |
| G1-028 | Y | Y | Y | Y | Y | Y | Y | Y |
| G1-029 | N | Y | Y | Y | Y | Y | N | N |
| G1-030 | N | N | Y | N | N | Y | N | N |
| G2-001 | N | N | Y | Y | Y | Y | Y | Y |
| G2-002 | N | N | Y | Y | Y | Y | N | N |
| G2-003 | N | N | Y | Y | Y | N | Y | N |
| G2-004 | N | Y | N | N | Y | Y | Y | Y |
| G2-005 | N | N | N | N | Y | N | N | N |
| G2-006 | N | N | N | N | N | N | N | N |
| G2-007 | N | Y | Y | Y | Y | Y | N | Y |
| G2-008 | N | Y | Y | Y | Y | N | N | Y |
| G2-009 | N | Y | Y | Y | Y | Y | Y | Y |
| G2-010 | N | Y | N | N | N | N | Y | Y |
| G2-011 | N | Y | N | N | N | N | N | Y |
| G2-012 | N | N | N | N | N | N | N | N |
| G2-013 | N | Y | N | N | N | N | Y | Y |
| G2-014 | N | Y | N | N | N | N | Y | N |
| G2-015 | N | Y | N | N | N | N | N | Y |
| G2-016 | N | N | N | N | N | N | Y | N |
| G2-017 | N | Y | N | N | N | N | N | Y |
| G2-018 | N | N | N | N | N | N | N | N |
| G2-019 | N | N | N | N | N | N | N | N |
| G2-020 | N | N | N | N | Y | N | N | Y |
| G2-021 | N | Y | N | N | N | N | N | Y |
| G2-022 | N | N | N | N | N | N | N | N |
| G2-023 | N | Y | N | N | N | N | Y | Y |
| G2-024 | N | N | N | N | N | N | Y | N |
| G2-025 | N | N | N | N | N | N | Y | Y |
| G2-026 | N | N | Y | Y | N | N | N | N |
| G2-027 | N | N | N | N | N | N | Y | N |
| G2-028 | N | N | N | N | N | N | Y | N |
| G2-029 | N | N | N | N | N | N | Y | N |
| G2-030 | N | N | Y | Y | N | Y | Y | N |
| G2-031 | N | Y | Y | Y | Y | N | Y | Y |
| G2-032 | N | N | N | N | N | N | N | N |
| G2-033 | N | N | N | N | N | N | N | N |
| G2-034 | N | N | N | N | N | N | Y | N |
| G2-035 | N | N | N | N | N | N | N | N |
| G2-036 | N | N | N | N | N | N | Y | N |
| G2-037 | N | N | N | N | N | N | Y | N |
| G2-038 | N | N | Y | Y | Y | N | N | Y |
| G2-039 | N | N | N | N | N | N | Y | N |
| G2-040 | N | Y | N | N | N | N | Y | Y |
| G3-001 | N | N | N | N | N | N | N | N |
| G3-002 | N | N | N | Y | N | Y | N | Y |
| G3-003 | N | N | N | N | N | N | N | N |
| G3-004 | N | N | N | Y | N | Y | N | Y |
| G3-005 | N | N | N | N | N | N | N | N |
| G3-006 | N | N | N | N | N | N | N | N |
| G3-007 | N | N | N | N | N | N | N | N |
| G3-008 | N | N | N | Y | N | Y | N | Y |
| G3-009 | N | N | N | N | N | N | N | N |
| G3-010 | N | N | N | N | N | N | N | N |
| G3-011 | N | N | N | N | N | N | N | N |
| G3-012 | N | N | N | N | N | N | N | N |
| G3-013 | N | N | N | N | N | N | N | N |
| G3-014 | N | N | N | N | N | N | N | N |
| G3-015 | N | N | N | N | N | N | N | N |
| G3-016 | N | N | N | N | N | N | N | N |
| G3-017 | N | N | N | N | N | N | N | N |
| G3-018 | N | N | N | N | N | N | N | N |
| G3-019 | N | N | N | N | N | N | N | N |
| G3-020 | N | N | N | Y | N | Y | N | Y |
| G3-021 | N | N | N | N | N | N | N | N |
| G3-022 | N | N | N | N | N | N | N | N |
| G3-023 | N | N | N | N | N | N | N | N |
| G3-024 | N | N | N | N | N | N | N | N |
| G3-025 | N | N | N | N | N | N | N | N |
| G3-026 | N | N | N | N | N | N | N | N |
| G3-027 | N | N | N | N | N | N | N | N |
| G3-028 | N | N | N | N | N | N | N | N |
| G3-029 | N | N | N | N | N | N | N | N |
| G3-030 | N | N | N | N | N | N | N | N |
