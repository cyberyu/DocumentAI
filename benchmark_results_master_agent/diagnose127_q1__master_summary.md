# Self-Adaptive Master Agent Summary

- Generated: 2026-05-06T20:51:45Z
- LLM: deepseek-v4-flash
- Source document: MSFT_FY26Q1_10Q.docx
- Document ID (stable): docsha256_fba0e3883b2f01df
- Benchmark: msft_fy26q1_qa_benchmark_100_sanitized.json
- Chunk sizes: [256]
- Ranking variants: ['hybrid_rrf_plus']

## Recommendation

- Best pipeline: chunk_text + fastembed/all-MiniLM-L6-v2 + hybrid_rrf_plus
- Overall correct: 100.00%
- Number match: 100.00%
- Mean token F1: 0.0096
- Composite score: 0.9010

## Ranked Subagents

| Rank | Pipeline ID | Strategy | Embedding | Ranking | TokenLen | Success | Overall | Number | Mean F1 | Score |
|---|---|---|---|---|---:|---|---:|---:|---:|---:|
| 1 | chunk_text__fastembed_all_minilm_l6_v2__tok256__hybrid_rrf_plus | chunk_text | fastembed/all-MiniLM-L6-v2 | hybrid_rrf_plus | 256 | Y | 100.00% | 100.00% | 0.0096 | 0.9010 |
