# Project Notes for Claude

Engineering decisions, patterns, and lessons learned for this codebase.

---

## Progress Bar / Long-Running Job Polling Pattern

### TL;DR

Always use **raw `fetch` with only `Authorization`** for polling. Never route polling
through a service layer that adds custom headers.

---

### The Pattern (copy this exactly)

```tsx
useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    const backendBase = process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL || "";

    const poll = async () => {
        const controller = new AbortController();
        const abortTimer = setTimeout(() => controller.abort(), 15000); // 15s hard timeout
        try {
            const token = getBearerToken() || "";
            const res = await fetch(
                `${backendBase}/api/v1/your-jobs-endpoint/${jobId}?t=${Date.now()}`,
                { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
            );
            clearTimeout(abortTimer);
            if (cancelled) return;

            if (res.status === 404) {
                // job expired or never existed
                setIsRunning(false);
                setJobId(null);
                return;
            }
            if (!res.ok) {
                setProgressMessage(`Poll error ${res.status}, retrying...`);
                if (!cancelled) timeoutId = setTimeout(poll, 3000);
                return;
            }

            const status = await res.json();
            if (cancelled) return;

            setProgressPercent(status.progress_percent ?? 0);
            setProgressMessage(status.message ?? "Running...");

            if (status.status === "completed") {
                setProgressPercent(100);
                setIsRunning(false);
                // handle results from status payload
                return; // stop polling
            }
            if (status.status === "failed") {
                setIsRunning(false);
                return; // stop polling
            }

            // still running — reschedule
            if (!cancelled) timeoutId = setTimeout(poll, 2000);
        } catch (err) {
            clearTimeout(abortTimer);
            if (cancelled) return;
            const isTimeout = err instanceof DOMException && err.name === "AbortError";
            setProgressMessage(
                isTimeout
                    ? "Request timed out (>15s), retrying..."
                    : `Unreachable (${err instanceof Error ? err.message : err}), retrying...`
            );
            if (!cancelled) timeoutId = setTimeout(poll, 3000); // retry on any error
        }
    };

    poll(); // start immediately
    return () => {
        cancelled = true;
        clearTimeout(timeoutId);
    };
}, [jobId]);
```

Required import:
```tsx
import { getBearerToken } from "@/lib/auth-utils";
```

---

### Why raw `fetch`, not `baseApiService.get()`

`baseApiService` (and any API service wrapper in this project) adds the custom header
`X-SurfSense-Client-Platform` to every request. Any non-standard header triggers a
**CORS preflight OPTIONS request** from the browser before the actual GET.

During long-running backend jobs, uvicorn is busy handling concurrent SSE streams
from internal `/api/v1/new_chat` calls. The preflight OPTIONS requests queue up and
stall. This causes the `fetch()` to hang indefinitely — and since the poll is
recursive (`setTimeout` is only scheduled after `await` returns), **one hung fetch
= all future polls never fire**. The progress bar freezes permanently.

Raw `fetch` with only `Authorization` is a CORS-safelisted header — no preflight,
no stalling.

**Never route polling through `baseApiService` or any wrapper that adds custom headers.**

---

### Why `AbortController` with 15s timeout is mandatory

`urllib` / `fetch` socket timeouts only trigger on *idle* connections. If the server
has accepted the TCP connection but is slow to respond (e.g. uvicorn queue backed up),
the timeout never fires. The fetch hangs indefinitely at the OS level.

`AbortController` enforces a wall-clock deadline regardless of TCP state. 15 seconds
is long enough for a healthy response but short enough to recover quickly.

Without it, a single stalled fetch permanently kills the poll loop.

---

### Why no WebSocket for progress

WebSocket was tried and removed. The problems:

1. **Race condition with HTTP polling fallback** — if a WS message arrived while an
   HTTP poll was in-flight, state guards (`inFlight`, `alive`, `terminalHandled`)
   could be set in a combination that permanently blocked all future polls.
2. **More moving parts** — reconnect logic, heartbeat, WS auth token expiry.
3. **No benefit** — polling every 2s is imperceptible to users, and the backend job
   state is Redis Hash (millisecond reads). There is no streaming data, only status.

Polling is simpler, more reliable, and sufficient.

---

### Backend contract (what the polling endpoint must return)

```json
{
    "status": "running" | "completed" | "failed",
    "progress_percent": 0-100,
    "message": "human readable status string",
    "error": null | "error message if failed",
    ... any job-specific result fields ...
}
```

Return HTTP 404 when the job ID is not found (expired TTL or never existed).  
Return HTTP 200 for all other states including `failed` (encode failure in the payload).

---

### Storing job ID across page reloads

If you want the progress bar to survive a page refresh (e.g. user navigates away and
back), persist the job ID in `sessionStorage`:

```tsx
// on job start:
sessionStorage.setItem("my_job_id", response.job_id);
sessionStorage.setItem("my_job_running", "true");

// on mount (useState initialiser):
const [jobId, setJobId] = useState<string | null>(() =>
    typeof window !== "undefined" ? sessionStorage.getItem("my_job_id") : null
);

// on job completion/failure/cancel:
sessionStorage.removeItem("my_job_id");
sessionStorage.removeItem("my_job_running");
```

Use `sessionStorage` (not `localStorage`) so the job tracking clears when the browser
tab is closed.

---

### Debug page for testing progress bars in isolation

A minimal single-candidate debug page exists at:

```
http://localhost:3929/dashboard/{search_space_id}/bench-debug
```

Source: `source/SurfSense/surfsense_web/app/dashboard/[search_space_id]/bench-debug/page.tsx`

It uses raw `fetch`, logs every poll as a timestamped line (OK/ERR, latency ms, status,
progress%, truncated raw JSON), and has an AbortController timeout. Copy this as a
starting template when adding a new long-running job progress UI.

---

## Terminal / Command Execution Rules

- **Never run commands in the background** (`isBackground=true`) unless the user explicitly asks for a background/watch process (e.g. a dev server). Installs, builds, and any command where output matters must run in the foreground.
- **Never tail output** — do not append `| tail -N` or `2>&1 | tail` to commands. Always show full output so nothing is hidden.
- **Never redirect output** (`> file`, `2>&1`, `&> file`, `tee`) unless the user explicitly requests it.
- **Never open a new terminal session** when an existing terminal is available. Always reuse the existing terminal.
- When activating a conda environment, use `conda activate <env>` on its own line first, then run the Python command on a separate line — do **not** use `conda run -n <env> python ...` (it suppresses debug output).
