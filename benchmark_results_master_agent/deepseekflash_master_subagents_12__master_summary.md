# Self-Adaptive Master Agent Summary

- Generated: 2026-05-06T02:14:28Z
- LLM: deepseek-v4-flash
- Source document: MSFT_FY26Q1_10Q.docx
- Benchmark: msft_fy26q1_qa_benchmark_100_sanitized.json
- Chunk sizes: [256, 1024]

## Ranked Subagents

| Rank | Pipeline ID | Strategy | Embedding | TokenLen | Success | Overall | Number | Mean F1 | Score |
|---|---|---|---|---:|---|---:|---:|---:|---:|
| 1 | chunk_text__fastembed_all_minilm_l6_v2__tok256 | chunk_text | fastembed/all-MiniLM-L6-v2 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 2 | chunk_text__fastembed_all_minilm_l6_v2__tok1024 | chunk_text | fastembed/all-MiniLM-L6-v2 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 3 | chunk_text__fastembed_bge_base_en_v1_5__tok256 | chunk_text | fastembed/bge-base-en-v1.5 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 4 | chunk_text__fastembed_bge_base_en_v1_5__tok1024 | chunk_text | fastembed/bge-base-en-v1.5 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 5 | chunk_text__fastembed_bge_large_en_v1_5__tok256 | chunk_text | fastembed/bge-large-en-v1.5 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 6 | chunk_text__fastembed_bge_large_en_v1_5__tok1024 | chunk_text | fastembed/bge-large-en-v1.5 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 7 | sandwitch_chunk__fastembed_all_minilm_l6_v2__tok256 | sandwitch_chunk | fastembed/all-MiniLM-L6-v2 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 8 | sandwitch_chunk__fastembed_all_minilm_l6_v2__tok1024 | sandwitch_chunk | fastembed/all-MiniLM-L6-v2 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 9 | sandwitch_chunk__fastembed_bge_base_en_v1_5__tok256 | sandwitch_chunk | fastembed/bge-base-en-v1.5 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 10 | sandwitch_chunk__fastembed_bge_base_en_v1_5__tok1024 | sandwitch_chunk | fastembed/bge-base-en-v1.5 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 11 | sandwitch_chunk__fastembed_bge_large_en_v1_5__tok256 | sandwitch_chunk | fastembed/bge-large-en-v1.5 | 256 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
| 12 | sandwitch_chunk__fastembed_bge_large_en_v1_5__tok1024 | sandwitch_chunk | fastembed/bge-large-en-v1.5 | 1024 | N | 0.00% | 0.00% | 0.0000 | -1.0000 |
