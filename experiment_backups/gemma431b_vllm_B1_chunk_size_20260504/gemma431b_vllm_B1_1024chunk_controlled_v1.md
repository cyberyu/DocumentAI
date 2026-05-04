# Mode B1 Benchmark: gemma431b_vllm_B1_1024chunk_controlled_v1

Generated: 2026-05-04T18:42:36Z  
Mode: B1 (direct pgvector, no SurfSense API)  
Chunk size: 1024  
LLM: google/gemma-4-31b-it  

## Overall

| Metric | Value |
|---|---|
| Overall correct | 72/100 (72%) |
| Number match | 72/100 (72%) |
| Unit match | 77/100 (77%) |
| Mean token F1 | 0.3970 |
| Request failures | 0 |

## Per Group

| Group | Correct | Num Match | Unit Match | F1 |
|---|---|---|---|---|
| Group1 | 26/30 (87%) | 87% | 90% | 0.770 |
| Group2 | 24/40 (60%) | 60% | 65% | 0.235 |
| Group3 | 22/30 (73%) | 73% | 80% | 0.240 |

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
