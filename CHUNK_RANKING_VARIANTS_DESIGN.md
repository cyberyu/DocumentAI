# Chunk Ranking Variants — Design & Experiment Plan

## Goal
Design a practical set of chunk ranking variants that extend the current retrieval stack (vector, BM25, hybrid RRF) and can be tested systematically for quality, latency, and cost.

## Current Baseline (in this repo)
- **Vector-only**: embedding similarity ranking.
- **Lexical-only**: BM25 / `ts_rank_cd` ranking.
- **Hybrid RRF**: rank fusion of vector and lexical branches.
- **Multi-model hybrid RRF**: BM25 + multiple embedding model branches fused with RRF.
- **Optional reranker**: second-stage rerank after retrieval.

---

## Variant Catalog

## V1 — Lexical BM25+
**Intent**: strengthen exact-match and phrase-heavy questions.

**Core**
- BM25 search on chunk text.
- Add phrase/proximity boosts (`match_phrase`, slop control).
- Add numeric token boosts (currency, percentages, dates).

**Score sketch**
\[
S = BM25 + b_1\cdot PhraseBoost + b_2\cdot NumericMatch
\]

**Best for**
- “What was X in Q1 2026?”
- exact wording or keyword-heavy lookup.

---

## V2 — Vector Semantic (Single Model)
**Intent**: maximize semantic recall on paraphrased questions.

**Core**
- k-NN ranking from one embedding model.
- optional min similarity threshold.

**Score sketch**
\[
S = cosine(q, c)
\]

**Best for**
- paraphrased and conceptual queries.

---

## V3 — Hybrid Weighted Score Fusion
**Intent**: combine lexical precision with semantic recall using calibrated weights.

**Core**
- Retrieve candidates from BM25 + vector.
- Normalize branch scores (z-score or min-max) per query.
- Weighted sum.

**Score sketch**
\[
S = \alpha\cdot Z_{vec} + \beta\cdot Z_{bm25} + \gamma\cdot EntityMatch + \delta\cdot StructureBoost
\]

**Notes**
- Keep fallback to RRF if normalization unstable.
- Start with `alpha=0.55, beta=0.35, gamma=0.05, delta=0.05`.

---

## V4 — Hybrid RRF+ (Calibrated RRF)
**Intent**: keep robust RRF behavior while adding lightweight priors.

**Core**
- Standard RRF branch fusion.
- Add small additive priors for entity match, section/title match, recency.

**Score sketch**
\[
S = \sum_{m \in branches} \frac{1}{k_m + rank_m} + p_{entity} + p_{structure} + p_{recency}
\]

**Notes**
- Lower risk than full weighted score fusion.
- Good production-safe incremental upgrade.

---

## V5 — Intent-Adaptive Hybrid Router
**Intent**: choose fusion policy per query type.

**Query classes (initial)**
- Numeric/table lookup
- Definition/explanation
- Temporal/comparison
- Procedure/how-to

**Policy examples**
- Numeric/table: lexical-heavy (`beta > alpha`)
- Definition/paraphrase: semantic-heavy (`alpha > beta`)

**Score sketch**
\[
S = \alpha(t)\cdot Z_{vec} + \beta(t)\cdot Z_{bm25} + ...\quad t=Intent(query)
\]

---

## V6 — Multi-Embedding Weighted Fusion
**Intent**: exploit complementary embedding models.

**Core**
- One vector branch per model + BM25 branch.
- Weighted fusion by model reliability.

**Score sketch**
\[
S = \beta\cdot Z_{bm25} + \sum_i w_i\cdot Z_{vec_i}
\]

**Initial model weighting strategy**
- equal weights first, then tune by validation slices.

---

## V7 — Structure-Aware Ranker
**Intent**: prioritize chunks with useful document structure.

**Signals**
- heading or section-title overlap
- table caption proximity
- footnote relevance
- chunk position within section

**Score sketch**
\[
S = S_{base} + \lambda_1\cdot HeadingMatch + \lambda_2\cdot TableContext + \lambda_3\cdot SectionPrior
\]

---

## V8 — Diversity & Coverage-Aware Ranker
**Intent**: reduce redundant chunks and improve evidence breadth.

**Core**
- Maximal Marginal Relevance (MMR)-style reranking on retrieved set.
- Cap per-document/per-section concentration.

**Score sketch**
\[
S'(c)=\lambda\cdot Rel(c,q) - (1-\lambda)\cdot \max_{s\in Selected} Sim(c,s)
\]

---

## V9 — Two-Stage Retriever + Cross-Encoder Reranker
**Intent**: maximize precision@top-k for final answer context.

**Core**
1. Stage-1 retriever (one of V3–V6) with broad recall.
2. Stage-2 cross-encoder rerank top-N to top-K.

**Notes**
- Highest quality potential.
- Highest latency/cost; consider small N (e.g. 40 → 12).

---

## V10 — Financial-Entity Focused Ranker
**Intent**: improve annual/quarterly report QA.

**Signals**
- normalized entity extraction: metric, period, unit, ticker.
- hard/soft match boosts for mandatory entities.

**Score sketch**
\[
S = S_{base} + \eta_1\cdot MetricMatch + \eta_2\cdot PeriodMatch + \eta_3\cdot UnitMatch
\]

---

## OpenSearch Implementation Hooks
- **Lexical tuning**: analyzers, `match_phrase`, `minimum_should_match`, fuzziness per field.
- **Hybrid**: keep RRF as stable baseline branch.
- **Script score**: custom weighted fusion when needed.
- **Field-aware mapping**: separate fields for title, heading, body, table text.
- **Rank features**: recency/authority priors as `rank_feature`.

---

## Recommended Build Order
1. **V4 (RRF+)** — low risk, quick gain.
2. **V3 (weighted fusion)** — controlled calibration.
3. **V5 (intent-adaptive routing)** — query-type gains.
4. **V6 (multi-embedding weighted)** — leverage current multi-model setup.
5. **V9 (cross-encoder rerank)** — quality push if latency budget allows.

---

## Evaluation Plan (Ablation Matrix)
## Datasets / Slices
- Numeric fact queries
- Table aggregation queries
- Definition/explanatory queries
- Temporal/comparative queries

## Metrics
- Answer accuracy (`overall_correct_rate`)
- Number fidelity (`number_match_rate`)
- Chunk recall@k
- Citation correctness
- Latency p50/p95
- Cost per query

## Experiment table template
| Variant | Numeric | Table | Definition | Temporal | Overall | p95 Latency | Cost | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| RRF Baseline |  |  |  |  |  |  |  |  |
| V4 RRF+ |  |  |  |  |  |  |  |  |
| V3 Weighted |  |  |  |  |  |  |  |  |
| V5 Adaptive |  |  |  |  |  |  |  |  |
| V6 Multi-Emb |  |  |  |  |  |  |  |  |
| V9 + Reranker |  |  |  |  |  |  |  |  |

---

## Integration Notes for This Repo
- Keep existing `hybrid_rrf` path as baseline strategy.
- Add new strategy keys in retrieval config (e.g., `hybrid_weighted`, `hybrid_adaptive`, `hybrid_rrf_plus`).
- Preserve `pipeline_id` and stable `document_id` tracking in benchmark harness.
- Emit per-branch diagnostics in result metadata (vector rank/score, bm25 rank/score, fusion score, applied boosts).

---

## Risks & Guardrails
- **Overfitting to benchmark**: tune by slice, verify on holdout.
- **Score calibration drift**: prefer rank-based fallback when branch score scales change.
- **Latency creep**: cap candidates and stage-2 rerank volume.
- **Keyword branch noise**: keep normalized query-term filtering and stopword controls.

---

## Minimal Next Step (MVP)
Implement two new selectable strategies first:
1. `hybrid_rrf_plus`
2. `hybrid_weighted`

Then run existing 12-pipeline framework with both strategies added to compare against current RRF baseline.

---

## Implemented Now (Code Toggle)
The active backend chunk retriever now supports these strategy values:
- `hybrid_rrf` (existing baseline)
- `hybrid_rrf_plus` (RRF + normalized lexical branch)
- `hybrid_weighted` (weighted rank-fusion of semantic and lexical branches)

Runtime configuration (environment variables):
- `CHUNK_RANKING_VARIANT` = `hybrid_rrf` | `hybrid_rrf_plus` | `hybrid_weighted`
- `CHUNK_WEIGHTED_VECTOR_WEIGHT` (default `0.60`)
- `CHUNK_WEIGHTED_KEYWORD_WEIGHT` (default `0.40`)

Notes:
- `hybrid_rrf_plus` and `hybrid_weighted` both use keyword-query normalization to reduce prompt-noise terms.
- `hybrid_weighted` currently uses weighted reciprocal-rank scores (rank-fusion) for stable cross-branch calibration.
