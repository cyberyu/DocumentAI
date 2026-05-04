# Mode B1 Benchmark: gemma431b_vllm_B1_256chunk_controlled_v1

Generated: 2026-05-04T19:15:28Z  
Mode: B1 (direct pgvector, no SurfSense API)  
Chunk size: 256  
LLM: google/gemma-4-31b-it  

## Overall

| Metric | Value |
|---|---|
| Overall correct | 39/100 (39%) |
| Number match | 41/100 (41%) |
| Unit match | 51/100 (51%) |
| Mean token F1 | 0.3330 |
| Request failures | 0 |

## Per Group

| Group | Correct | Num Match | Unit Match | F1 |
|---|---|---|---|---|
| Group1 | 30/30 (100%) | 100% | 100% | 0.877 |
| Group2 | 6/40 (15%) | 20% | 38% | 0.155 |
| Group3 | 3/30 (10%) | 10% | 20% | 0.027 |

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
