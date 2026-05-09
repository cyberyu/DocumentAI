# Benchmark UI Progress Stuck — Incident Record (Resolved)

## Summary

The benchmark progress bar repeatedly appeared stuck (at 5%, 83%, or any intermediate
value) while the backend had already finished, or appeared to never advance at all for
the last candidate in any N-task run. All root causes have been identified and fixed.
The UI now works correctly end-to-end.

---

## Symptom Pattern

| Scenario | Observed behaviour |
|---|---|
| N=8 tasks | 7 complete, 1 stuck forever |
| N=4 tasks | 3 complete, 1 stuck forever |
| N=2 tasks | 1 complete, 1 stuck forever |
| N=1 task | The single task stuck forever |
| Debug page (raw fetch) | Same single task completes correctly |

The pattern "always exactly the last one hangs regardless of N" — and "even N=1
hangs" — ruled out all inter-task contention theories (Redis races, semaphores,
saturation) and pointed squarely at the **frontend**, not the backend.

Redis confirmed on every stuck run: all candidates were `status: completed` with valid
scores. The backend was never actually hanging.

---

## Root Causes (in order of discovery)

### 1. WebSocket + `inFlight` guard permanently blocking polls

**File:** `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/benchmark/page.tsx`

The original frontend used a WebSocket-first + polling-fallback design with guards:
`inFlight`, `alive`, `terminalHandled`. If a WebSocket message arrived while an HTTP
poll was in flight, `terminalHandled` was set and all subsequent polls were gated out.
Race conditions between WS and HTTP paths left the UI permanently frozen on whatever
progress value was last set.

**Fix:** Removed WebSocket entirely. Replaced with a simple recursive `setTimeout`
poll — no guards, no `inFlight`, no `alive` flags.

---

### 2. Redis Lua script read-modify-write race condition

**File:** `source/SurfSense/surfsense_backend/app/routes/benchmark_routes.py`

The original Redis storage used Lua scripts that read the full job JSON blob, modified
it in Python, and wrote it back — a classic read-modify-write race when multiple
candidate threads updated simultaneously. Updates from one thread would overwrite
updates from another.

**Fix:** Migrated to Redis Hash storage:
- Main job fields → `HSET surfsense:benchmark_job:{job_id}` (one field per key)
- Per-candidate state → separate Hash `surfsense:benchmark_job:{job_id}:c:{pipeline_id}`
- `HSET` is atomic per-field; concurrent updates to different candidates never conflict

---

### 3. `fetch()` with no timeout freezing the recursive poll loop

**File:** `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/benchmark/page.tsx`

The simplified polling used `setTimeout` but `fetch()` had no timeout. If a single
fetch hung (connection accepted but no data), `await fetch(...)` would never resolve.
Since polls are recursive (`setTimeout` is only scheduled after `await` returns),
one frozen fetch = no future polls ever fire. The UI freezes permanently.

**Fix:** Added `AbortController` with 15-second timeout to every poll:

```tsx
const controller = new AbortController();
const abortTimer = setTimeout(() => controller.abort(), 15000);
try {
    const res = await fetch(url, { headers, signal: controller.signal });
    clearTimeout(abortTimer);
    ...
} catch (err) {
    clearTimeout(abortTimer);
    const isTimeout = err instanceof DOMException && err.name === "AbortError";
    setProgressMessage(isTimeout ? "Backend poll timed out (>15s), retrying..." : ...);
    timeoutId = setTimeout(poll, 3000); // always reschedule on any error
}
```

---

### 4. CORS preflight on every poll due to custom request header ← **final root cause**

**File:** `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/benchmark/page.tsx`

The main page's polling went through `benchmarkApiService.getJob()` →
`baseApiService.get()` which automatically added the custom header
`X-SurfSense-Client-Platform` to every request. Any non-standard header causes the
browser to send a CORS **preflight OPTIONS** request before the actual GET.

During a benchmark run, uvicorn handles multiple concurrent SSE streams from the
benchmark's internal `/api/v1/new_chat` calls (~20s each × 5 questions). This fills
uvicorn's accept queue. The OPTIONS preflight would stall waiting for a slot, causing
the subsequent GET to also stall — triggering the indefinite fetch hang described
in Root Cause 3.

The debug page used raw `fetch` with only `Authorization` — no custom headers, no
preflight — and worked perfectly every time on the exact same candidate.

**Fix:** Replaced the service-layer poll call with a direct `fetch`:

```tsx
// Before (broken — triggers CORS preflight via X-SurfSense-Client-Platform header)
const status = await benchmarkApiService.getJob(jobId, controller.signal);

// After (fixed — no custom headers, no preflight)
const token = getBearerToken() || "";
const res = await fetch(
    `${backendBase}/api/v1/benchmark/jobs/${jobId}?t=${Date.now()}`,
    { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
);
const status = await res.json();
```

This is the fix that resolved the issue. Both tasks in a 2-task run now complete
successfully on the main benchmark page.

---

## Additional Observations

### Backend execution was never actually hanging

On every "stuck" run, Redis showed the backend had completed normally:
- `status: completed`, `progress_percent: 100`
- `completed_candidates == total_candidates`
- `score`, `elapsed_seconds`, `overall_correct_rate` all populated correctly

No candidate (including `hybrid_rrf_plus` or `sandwitch_chunk`) ever hung in the
backend.

### Internal benchmark HTTP calls to same uvicorn

`SurfSenseClient` in `scripts/run_surfsense_benchmark.py` uses
`urllib.request.urlopen` (blocking stdlib, no connection pooling) to POST to
`/api/v1/new_chat` (SSE endpoint) on the same uvicorn process. With 5 questions × ~20s
per LLM call, this holds connections open for the entire benchmark duration — the
mechanism that fills the accept queue and causes preflights to stall.

### Postgres is still used (document metadata only)

Chunks and embeddings are fully stored in OpenSearch. Postgres is queried once per
search: `SELECT * FROM documents WHERE id IN (...)` to hydrate document titles and
types. All other data (threads, messages, users, search spaces) also remains in Postgres.

---

## Files Changed

| File | Change |
|---|---|
| `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/benchmark/page.tsx` | Replaced service-layer poll with raw `fetch` + `Authorization` only; added `AbortController` 15s timeout; removed WebSocket, `inFlight`, `alive`, `terminalHandled` guards |
| `source/SurfSense/surfsense_backend/app/routes/benchmark_routes.py` | Migrated Redis storage from Lua/JSON-blob read-modify-write to Hash-per-field + per-candidate Hash keys |
| `docker-compose-adaptable-rag.yml` | Added `UVICORN_LIMIT_CONCURRENCY=200`, `UVICORN_TIMEOUT_KEEP_ALIVE=75` |
| `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/bench-debug/page.tsx` | Debug page: hardcoded single candidate, raw poll log — used to isolate Root Cause 4 |

---

## Debug Page

A minimal debug page was created at:

```
http://localhost:3929/dashboard/{search_space_id}/bench-debug
```

It runs a single hardcoded candidate (`sandwitch_chunk / fastembed/all-MiniLM-L6-v2 /
tok256 / hybrid_weighted`, 5 questions) and logs every poll with timestamp, OK/ERR,
latency in ms, status, progress%, and truncated raw JSON. Useful for future regression
testing of the polling path.

---

## Useful Validation Command (check backend truth directly)

```bash
JOB_ID=your_job_id_here
curl -s "http://localhost:8929/api/v1/benchmark/jobs/${JOB_ID}" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('status:', d.get('status'))
print('progress:', d.get('progress_percent'))
print('completed_candidates:', d.get('completed_candidates'))
print('total_candidates:', d.get('total_candidates'))
print('message:', d.get('message'))
"
```
