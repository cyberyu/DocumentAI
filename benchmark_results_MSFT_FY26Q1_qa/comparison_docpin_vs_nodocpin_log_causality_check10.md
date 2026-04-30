# Log-Based Causality: docpin vs no-docpin (Gemma4 E4B, 10Q)

This note uses backend PERF logs for thread pairs:
- no-docpin run: chat_id `889-898`
- docpin run: chat_id `919-928`

## Verified Input-Path Differences

1. `mentioned` flag flips at retrieval stage
- no-docpin is mostly `mentioned=0`
- docpin is consistently `mentioned=1`
- This confirms different retrieval context construction before the model call.

2. Planner rewrites differ materially for the same question
- docpin run often injects stricter temporal constraints (`start/end` windows) or different optimized rewrites.
- no-docpin run more often uses unconstrained rewrites for the same question.

3. Retrieval hit behavior diverges for matched question IDs
- Several docpin questions produce `hybrid_search ... results=0` while no-docpin for the same question produces `results=30`.
- This is direct evidence that model inputs differed due to retrieval outputs, not just generation randomness.

## Concrete Examples (same benchmark IDs)

- `G1-002` (chat `890` vs `920`)
  - no-docpin (`890`): `results=30`, `total=1`
  - docpin (`920`): `results=0`, with strict `start=end=2025-09-30`, then `total=1`
  - Interpretation: docpin path changed planner constraints; retrieval candidates collapsed.

- `G1-005` (chat `893` vs `923`)
  - no-docpin (`893`): `results=30`, `total=1`
  - docpin (`923`): `results=0`, rewritten to a strict "three months ended" time window
  - Interpretation: docpin path induced a narrower query window and zero-hit retrieval.

- `G1-003` (chat `891` vs `921`)
  - both have `results=30`
  - output quality still drops in docpin run
  - Interpretation: even when retrieval count matches, docpin changes upstream prompt/context packaging (`mentioned=1`) and downstream model behavior.

## Timing Signal (supports input/context complexity change)

For multiple matched questions, docpin run has much longer agent completion:
- `G1-001`: ~`19.1s` (no-docpin) vs ~`56.0s` (docpin)
- `G1-005`: ~`27.7s` (no-docpin) vs ~`41.1s` (docpin)
- `G1-006`: ~`11.3s` (no-docpin) vs ~`27.9s` (docpin)

This is consistent with changed prompt/retrieval context and longer reasoning trajectories.

## Conclusion

The prediction gap is causally linked to **input-side differences** introduced by docpin mode:
- retrieval context flag (`mentioned`) changes,
- planner rewrite/constraint behavior changes,
- and, in key questions, retrieval hits drop from `30` to `0`.

So this is not just output variance from the same input; docpin materially altered the model input pipeline.

## Scope Note

Token-usage telemetry table was unavailable/zero in DB for these threads, so this conclusion is grounded on backend PERF retrieval/planner logs and matched thread IDs.