# Mode B1 Benchmark: deepseekflash_B1_256chunk_controlled_v1

Generated: 2026-05-04T15:21:17Z  
Mode: B1 (direct pgvector, no SurfSense API)  
Chunk size: 256  
LLM: deepseek-v4-flash (thinking=high)  

## Overall

| Metric | Value |
|---|---|
| Overall correct | 42/100 (42%) |
| Number match | 43/100 (43%) |
| Unit match | 51/100 (51%) |
| Mean token F1 | 0.3310 |
| Request failures | 0 |

## Per Group

| Group | Correct | Num Match | Unit Match | F1 |
|---|---|---|---|---|
| Group1 | 30/30 (100%) | 100% | 100% | 0.877 |
| Group2 | 7/40 (18%) | 20% | 32% | 0.125 |
| Group3 | 5/30 (17%) | 17% | 27% | 0.060 |

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
