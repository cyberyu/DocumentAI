# Mode B1 Benchmark: deepseekflash_B1_1024chunk_controlled_v1

Generated: 2026-05-04T15:46:50Z  
Mode: B1 (direct pgvector, no SurfSense API)  
Chunk size: 1024  
LLM: deepseek-v4-flash (thinking=high)  

## Overall

| Metric | Value |
|---|---|
| Overall correct | 71/100 (71%) |
| Number match | 74/100 (74%) |
| Unit match | 78/100 (78%) |
| Mean token F1 | 0.4130 |
| Request failures | 0 |

## Per Group

| Group | Correct | Num Match | Unit Match | F1 |
|---|---|---|---|---|
| Group1 | 25/30 (83%) | 83% | 90% | 0.730 |
| Group2 | 24/40 (60%) | 62% | 65% | 0.255 |
| Group3 | 22/30 (73%) | 80% | 83% | 0.307 |

## Config

| Setting | Value |
|---|---|
| rrf_k | 60 |
| top_k | 10 |
| max_chunks_per_doc | 50 |
| matched_markers | True |
| query_rewrite | True |
| date_filter | none |
| embed_model | sentence-transformers/all-MiniLM-L6-v2 |
