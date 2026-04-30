# Input-Side Telemetry Comparison (Gemma4 E4B, 10Q)

This compares input-side backend telemetry for two runs:
- A: `docker_gemma4e4b_global_noweb_nodocpin_check10_repro.json`
- B: `docker_gemma4e4b_global_docpin_noweb_check10_fix1.json`

Both used `sanitize_questions=true`; key difference is `mentioned_document_ids` (docpin) in B.

- Avg prompt tokens/question: A=0.0, B=0.0
- Avg model calls/question: A=0.00, B=0.00

## Per Question Telemetry

| ID | A thread | A prompt tokens | A calls | B thread | B prompt tokens | B calls | Delta prompt (B-A) |
|---|---:|---:|---:|---:|---:|---:|---:|
| G1-001 | 889 | 0 | 0 | 919 | 0 | 0 | 0 |
| G1-002 | 890 | 0 | 0 | 920 | 0 | 0 | 0 |
| G1-003 | 891 | 0 | 0 | 921 | 0 | 0 | 0 |
| G1-004 | 892 | 0 | 0 | 922 | 0 | 0 | 0 |
| G1-005 | 893 | 0 | 0 | 923 | 0 | 0 | 0 |
| G1-006 | 894 | 0 | 0 | 924 | 0 | 0 | 0 |
| G1-007 | 895 | 0 | 0 | 925 | 0 | 0 | 0 |
| G1-008 | 896 | 0 | 0 | 926 | 0 | 0 | 0 |
| G1-009 | 897 | 0 | 0 | 927 | 0 | 0 | 0 |
| G1-010 | 898 | 0 | 0 | 928 | 0 | 0 | 0 |
