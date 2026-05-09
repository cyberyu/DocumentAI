"use client";

/**
 * BENCHMARK DEBUG PAGE
 * Single hardcoded candidate: sandwitch_chunk / fastembed/all-MiniLM-L6-v2 / tok256 / hybrid_weighted
 * Shows every poll result as raw JSON so we can pinpoint any UI freeze.
 */

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { getBearerToken } from "@/lib/auth-utils";

const BACKEND = process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL || "";

// ── single candidate config ────────────────────────────────────────────────
const CANDIDATE = {
  chunking_strategies: ["sandwitch_chunk"],
  embedding_models: ["fastembed/all-MiniLM-L6-v2"],
  chunk_sizes: [256],
  ranking_variants: ["hybrid_weighted"],
};

interface PollEntry {
  ts: string;
  ok: boolean;
  ms: number;
  status?: string;
  progress?: number;
  message?: string;
  error?: string;
  raw?: string;
}

export default function BenchDebugPage() {
  const params = useParams();
  const rawId = params.search_space_id;
  const searchSpaceId = Number(Array.isArray(rawId) ? rawId[0] : rawId);

  const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [finalStatus, setFinalStatus] = useState<string | null>(null);
  const [log, setLog] = useState<PollEntry[]>([]);
  const cancelledRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const addLog = (entry: PollEntry) =>
    setLog((prev) => [...prev, entry]);

  // ── start job ─────────────────────────────────────────────────────────────
  const startJob = async () => {
    if (!benchmarkFile) return alert("Pick a benchmark JSON file first.");
    setStarting(true);
    setLog([]);
    setProgress(0);
    setFinalStatus(null);
    cancelledRef.current = false;

    const token = getBearerToken();
    const fd = new FormData();
    fd.append("benchmark_file", benchmarkFile);
    fd.append("search_space_id", String(searchSpaceId));
    fd.append("chunking_strategies", JSON.stringify(CANDIDATE.chunking_strategies));
    fd.append("embedding_models", JSON.stringify(CANDIDATE.embedding_models));
    fd.append("chunk_sizes", JSON.stringify(CANDIDATE.chunk_sizes));
    fd.append("ranking_variants", JSON.stringify(CANDIDATE.ranking_variants));
    fd.append("max_questions", "5");
    fd.append("start_question", "1");
    fd.append("subagent_workers", "1");
    fd.append("benchmark_workers", "1");
    fd.append("request_timeout", "180");
    fd.append("sanitize_questions", "false");
    fd.append("cleanup_documents", "false");

    try {
      const res = await fetch(`${BACKEND}/api/v1/benchmark/jobs`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) {
        addLog({ ts: now(), ok: false, ms: 0, error: JSON.stringify(data) });
        setStarting(false);
        return;
      }
      const id: string = data.job_id;
      setJobId(id);
      addLog({ ts: now(), ok: true, ms: 0, status: "created", message: `Job started: ${id}` });
      setStarting(false);
      schedulePoll(id);
    } catch (e: any) {
      addLog({ ts: now(), ok: false, ms: 0, error: String(e) });
      setStarting(false);
    }
  };

  // ── polling ───────────────────────────────────────────────────────────────
  const schedulePoll = (id: string, delay = 2000) => {
    if (cancelledRef.current) return;
    timerRef.current = setTimeout(() => poll(id), delay);
  };

  const poll = async (id: string) => {
    if (cancelledRef.current) return;
    const token = getBearerToken();
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), 15000);
    const t0 = Date.now();
    try {
      const res = await fetch(`${BACKEND}/api/v1/benchmark/jobs/${id}?t=${Date.now()}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      clearTimeout(abortTimer);
      const ms = Date.now() - t0;
      const raw = await res.text();
      let data: any = {};
      try { data = JSON.parse(raw); } catch (_) {}

      const entry: PollEntry = {
        ts: now(),
        ok: res.ok,
        ms,
        status: data.status,
        progress: data.progress_percent,
        message: data.message,
        error: data.error,
        raw: raw.length > 400 ? raw.slice(0, 400) + "…" : raw,
      };
      addLog(entry);

      if (data.progress_percent !== undefined) setProgress(data.progress_percent);

      if (data.status === "completed" || data.status === "failed") {
        setFinalStatus(data.status);
        setProgress(data.status === "completed" ? 100 : progress);
        return; // stop polling
      }
      schedulePoll(id, 2000);
    } catch (e: any) {
      clearTimeout(abortTimer);
      const ms = Date.now() - t0;
      const isTimeout = e?.name === "AbortError";
      addLog({
        ts: now(),
        ok: false,
        ms,
        error: isTimeout ? "FETCH TIMED OUT (>15s)" : String(e),
      });
      schedulePoll(id, 3000); // retry after error
    }
  };

  const stop = () => {
    cancelledRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    setFinalStatus("cancelled");
  };

  return (
    <div style={{ padding: 24, fontFamily: "monospace", maxWidth: 900 }}>
      <h1 style={{ fontSize: 18, fontWeight: "bold", marginBottom: 16 }}>
        Benchmark Debug — single candidate
      </h1>

      <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 12, borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
        <strong>Candidate:</strong> sandwitch_chunk / fastembed/all-MiniLM-L6-v2 / tok256 / hybrid_weighted
        <br />
        <strong>Search space:</strong> {searchSpaceId}
        <br />
        <strong>Backend:</strong> {BACKEND}
      </div>

      {/* File picker + start */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <input
          type="file"
          accept=".json"
          onChange={(e) => setBenchmarkFile(e.target.files?.[0] ?? null)}
          style={{ color: "white" }}
        />
        <button
          onClick={startJob}
          disabled={starting || !!jobId && !finalStatus}
          style={{ padding: "6px 16px", background: starting ? "#555" : "#2563eb", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}
        >
          {starting ? "Starting…" : "▶ Run"}
        </button>
        {jobId && !finalStatus && (
          <button onClick={stop} style={{ padding: "6px 16px", background: "#dc2626", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>
            ■ Stop
          </button>
        )}
        {jobId && (
          <button
            onClick={() => { setJobId(null); setFinalStatus(null); setLog([]); setProgress(0); cancelledRef.current = true; }}
            style={{ padding: "6px 16px", background: "#374151", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}
          >
            Reset
          </button>
        )}
      </div>

      {/* Progress bar */}
      {jobId && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 13 }}>
            <span>Job: <strong>{jobId}</strong></span>
            <span style={{ color: finalStatus === "completed" ? "#22c55e" : finalStatus === "failed" ? "#ef4444" : "#60a5fa" }}>
              {finalStatus ? finalStatus.toUpperCase() : "running…"} — {progress}%
            </span>
          </div>
          <div style={{ background: "#374151", borderRadius: 4, height: 20, overflow: "hidden" }}>
            <div style={{ width: `${progress}%`, height: "100%", background: finalStatus === "failed" ? "#ef4444" : "#2563eb", transition: "width 0.3s" }} />
          </div>
        </div>
      )}

      {/* Poll log */}
      <div
        ref={logRef}
        style={{ background: "#111", color: "#ccc", padding: 12, borderRadius: 6, height: 480, overflowY: "auto", fontSize: 12, lineHeight: 1.6 }}
      >
        {log.length === 0 && <span style={{ color: "#555" }}>— no polls yet —</span>}
        {log.map((entry, i) => (
          <div key={i} style={{ marginBottom: 8, borderBottom: "1px solid #222", paddingBottom: 6 }}>
            <span style={{ color: "#888" }}>[{entry.ts}]</span>{" "}
            <span style={{ color: entry.ok ? "#22c55e" : "#ef4444", fontWeight: "bold" }}>
              {entry.ok ? "OK" : "ERR"}
            </span>{" "}
            <span style={{ color: "#60a5fa" }}>{entry.ms}ms</span>
            {entry.status && <span style={{ color: "#a78bfa" }}> status={entry.status}</span>}
            {entry.progress !== undefined && <span style={{ color: "#fbbf24" }}> {entry.progress}%</span>}
            {entry.message && <span style={{ color: "#d4d4d4" }}> • {entry.message}</span>}
            {entry.error && <span style={{ color: "#f87171" }}> ⚠ {entry.error}</span>}
            {entry.raw && (
              <div style={{ color: "#6b7280", marginTop: 2, wordBreak: "break-all" }}>{entry.raw}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function now() {
  return new Date().toISOString().slice(11, 23); // HH:MM:SS.mmm
}
