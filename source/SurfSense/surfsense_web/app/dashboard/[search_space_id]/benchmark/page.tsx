"use client";

import { useAtomValue, useSetAtom } from "jotai";
import { AlertTriangle, CheckCircle2, Circle, Clock, Loader2, Play, RotateCcw, Settings, XCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { toast } from "sonner";
import {
	type BenchmarkCandidateStatus,
} from "@/contracts/types/benchmark.types";
import type { ChunkingStrategy } from "@/contracts/types/document.types";
import {
	globalNewLLMConfigsAtom,
	llmPreferencesAtom,
} from "@/atoms/new-llm-config/new-llm-config-query.atoms";
import { searchSpaceSettingsDialogAtom } from "@/atoms/settings/settings-dialog.atoms";
import { EmbeddingModelSelector } from "@/components/sources/EmbeddingModelSelector";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { benchmarkApiService } from "@/lib/apis/benchmark-api.service";
import { getBearerToken } from "@/lib/auth-utils";

const CHUNK_METHODS: ChunkingStrategy[] = [
	"chunk_text",
	"sandwitch_chunk",
	"chunk_hybrid",
	"chunk_recursive",
];
const CHUNK_SIZES = [256, 512, 1024, 2048];
const RANKING_VARIANTS = ["hybrid_rrf_plus", "hybrid_weighted"];

export default function BenchmarkPage() {
	const params = useParams();
	const searchSpaceId = Number(params.search_space_id);
	const setSearchSpaceSettingsDialog = useSetAtom(searchSpaceSettingsDialogAtom);
	const { data: preferences = {}, isFetching: preferencesLoading } = useAtomValue(llmPreferencesAtom);
	const { data: globalConfigs = [], isFetching: globalConfigsLoading } =
		useAtomValue(globalNewLLMConfigsAtom);

	const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
	const [selectedEmbeddingModels, setSelectedEmbeddingModels] = useState<string[]>([
		"fastembed/bge-base-en-v1.5",
	]);
	const [selectedChunkMethods, setSelectedChunkMethods] = useState<ChunkingStrategy[]>([
		"chunk_text",
		"sandwitch_chunk",
	]);
	const [selectedChunkSizes, setSelectedChunkSizes] = useState<number[]>([256, 1024]);
	const [selectedRankingVariants, setSelectedRankingVariants] = useState<string[]>([
		"hybrid_rrf_plus",
		"hybrid_weighted",
	]);
	const [maxQuestions, setMaxQuestions] = useState(5);
	const [isRunning, setIsRunning] = useState<boolean>(() => {
		if (typeof window !== "undefined") {
			return sessionStorage.getItem("benchmark_job_running") === "true";
		}
		return false;
	});
	const [jobId, setJobId] = useState<string | null>(() => {
		if (typeof window !== "undefined") {
			return sessionStorage.getItem("benchmark_job_id") ?? null;
		}
		return null;
	});
	const [progressPercent, setProgressPercent] = useState(0);
	const [progressMessage, setProgressMessage] = useState(() => {
		if (typeof window !== "undefined" && sessionStorage.getItem("benchmark_job_id")) {
			return "Resuming benchmark status tracking...";
		}
		return "Idle";
	});
	const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
	const [rankedReports, setRankedReports] = useState<Record<string, any>[]>([]);
	const [candidatesStatus, setCandidatesStatus] = useState<BenchmarkCandidateStatus[]>([]);

	const agentLlmId = preferences.agent_llm_id;
	const docSummaryLlmId = preferences.document_summary_llm_id;
	const isAgentAutoMode = agentLlmId === 0;
	const isDocSummaryAutoMode = docSummaryLlmId === 0;
	const hasGlobalConfigs = globalConfigs.length > 0;
	const hasAgentLLM =
		agentLlmId !== null &&
		agentLlmId !== undefined &&
		(!isAgentAutoMode || hasGlobalConfigs);
	const hasDocumentSummaryLLM =
		docSummaryLlmId !== null &&
		docSummaryLlmId !== undefined &&
		(!isDocSummaryAutoMode || hasGlobalConfigs);
	const hasBenchmarkLLM = hasAgentLLM || hasDocumentSummaryLLM;
	const isLoading = preferencesLoading || globalConfigsLoading;

	const totalCandidates =
		selectedEmbeddingModels.length *
		selectedChunkMethods.length *
		selectedChunkSizes.length *
		selectedRankingVariants.length;

	const canRun =
		!!benchmarkFile &&
		hasBenchmarkLLM &&
		selectedEmbeddingModels.length > 0 &&
		selectedChunkMethods.length > 0 &&
		selectedChunkSizes.length > 0 &&
		selectedRankingVariants.length > 0 &&
		maxQuestions > 0;

	const disabledReason: string | null = isRunning
		? null // handled separately via Reset button
		: !benchmarkFile
		? "Upload a benchmark .json file to proceed"
		: !hasBenchmarkLLM
		? "Configure an Agent or Document Summary LLM in Settings"
		: selectedEmbeddingModels.length === 0
		? "Select at least one embedding model"
		: selectedChunkMethods.length === 0
		? "Select at least one chunk method"
		: selectedChunkSizes.length === 0
		? "Select at least one chunk size"
		: selectedRankingVariants.length === 0
		? "Select at least one ranking variant"
		: maxQuestions <= 0
		? "Max questions must be > 0"
		: null;

	const handleResetRunningState = () => {
		if (typeof window !== "undefined") {
			sessionStorage.removeItem("benchmark_job_id");
			sessionStorage.removeItem("benchmark_job_running");
		}
		setIsRunning(false);
		setJobId(null);
		setProgressPercent(0);
		setProgressMessage("Idle");
		setEtaSeconds(null);
		setCandidatesStatus([]);
		toast.info("Running state cleared — you can start a new benchmark");
	};

	useEffect(() => {
		if (!jobId) return;
		let cancelled = false;
		let timeoutId: ReturnType<typeof setTimeout>;
		const backendBase = process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL || "";

		const poll = async () => {
			const controller = new AbortController();
			const abortTimer = setTimeout(() => controller.abort(), 15000);
			try {
				// Use raw fetch (no service layer) to avoid CORS preflights from custom
				// headers, 401-refresh redirects, and posthog dynamic imports that can
				// all interfere with polling during long-running benchmark jobs.
				const token = getBearerToken() || "";
				const res = await fetch(
					`${backendBase}/api/v1/benchmark/jobs/${jobId}?t=${Date.now()}`,
					{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
				);
				clearTimeout(abortTimer);
				if (cancelled) return;
				if (res.status === 404) {
					setIsRunning(false);
					setJobId(null);
					setProgressMessage("Job not found on server. Ready to run a new benchmark.");
					if (typeof window !== "undefined") {
						sessionStorage.removeItem("benchmark_job_id");
						sessionStorage.removeItem("benchmark_job_running");
					}
					toast.warning("Benchmark job not found. You can start a new run.");
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
				setEtaSeconds(typeof status.eta_seconds === "number" ? status.eta_seconds : null);
				if (Array.isArray(status.candidates_status)) {
					setCandidatesStatus(status.candidates_status);
				}

				if (status.status === "completed") {
					setProgressPercent(100);
					setIsRunning(false);
					if (Array.isArray(status.ranked_subagent_reports)) {
						setRankedReports(status.ranked_subagent_reports as Record<string, any>[]);
					}
					if (typeof window !== "undefined") {
						sessionStorage.removeItem("benchmark_job_id");
						sessionStorage.removeItem("benchmark_job_running");
					}
					toast.success("Benchmark completed");
					return;
				}

				if (status.status === "failed") {
					setIsRunning(false);
					if (typeof window !== "undefined") {
						sessionStorage.removeItem("benchmark_job_id");
						sessionStorage.removeItem("benchmark_job_running");
					}
					toast.error(status.error || "Benchmark failed");
					return;
				}

				// Still running — schedule next poll
				if (!cancelled) timeoutId = setTimeout(poll, 2000);
			} catch (err) {
				clearTimeout(abortTimer);
				if (cancelled) return;
				const isAbort = err instanceof DOMException && err.name === "AbortError";
				setProgressMessage(
					isAbort
						? "Backend poll timed out (>15s), retrying..."
						: err instanceof Error && err.message
							? `Backend temporarily unreachable (${err.message}), retrying...`
							: "Backend temporarily unreachable, retrying..."
				);
				if (!cancelled) timeoutId = setTimeout(poll, 3000);
			}
		};

		poll();
		return () => {
			cancelled = true;
			clearTimeout(timeoutId);
		};
	}, [jobId]);

	const topRows = useMemo(() => rankedReports.slice(0, 24), [rankedReports]);

	const toggleString = <T extends string>(
		setter: Dispatch<SetStateAction<T[]>>,
		current: T[],
		value: T
	) => {
		if (current.includes(value)) {
			if (current.length === 1) return;
			setter(current.filter((item) => item !== value));
			return;
		}
		setter([...current, value]);
	};

	const toggleNumber = (
		setter: Dispatch<SetStateAction<number[]>>,
		current: number[],
		value: number
	) => {
		if (current.includes(value)) {
			if (current.length === 1) return;
			setter(current.filter((item) => item !== value));
			return;
		}
		setter([...current, value].sort((a, b) => a - b));
	};

	const handleRun = async () => {
		if (!benchmarkFile || !canRun || isRunning) return;
		setIsRunning(true);
		setProgressPercent(1);
		setProgressMessage("Queueing benchmark job...");
		setEtaSeconds(null);
		setRankedReports([]);
		try {
			const response = await benchmarkApiService.startJob({
				benchmark_file: benchmarkFile,
				search_space_id: searchSpaceId,
				chunking_strategies: selectedChunkMethods,
				embedding_models: selectedEmbeddingModels,
				chunk_sizes: selectedChunkSizes,
				ranking_variants: selectedRankingVariants,
				max_questions: maxQuestions,
				start_question: 1,
				subagent_workers: 4,
				benchmark_workers: 1,
				request_timeout: 240,
				sanitize_questions: true,
				cleanup_documents: true,
				run_prefix: `benchmark_ui_${Date.now()}`,
				output_dir: "benchmark_results_master_agent",
			});
			if (typeof window !== "undefined") {
				sessionStorage.setItem("benchmark_job_id", response.job_id);
				sessionStorage.setItem("benchmark_job_running", "true");
			}
			setJobId(response.job_id);
			setProgressMessage("Benchmark job started");
		} catch (error) {
			setIsRunning(false);
			toast.error(error instanceof Error ? error.message : "Failed to start benchmark");
		}
	};

	return (
		<div className="p-4 sm:p-6 space-y-4">
			<Card>
				<CardHeader>
					<CardTitle>Benchmark</CardTitle>
					<CardDescription>
						Run master/subagent benchmark with selected embeddings, chunking methods, chunk sizes,
						and ranking variants.
					</CardDescription>
				</CardHeader>
				<CardContent className="space-y-4">
					{!isLoading && !hasBenchmarkLLM && (
						<Alert variant="destructive">
							<AlertTriangle className="h-4 w-4" />
							<AlertTitle>LLM Configuration Required</AlertTitle>
							<AlertDescription>
								<div className="flex items-center justify-between gap-2">
									<span>
										Configure model settings first. Benchmark accepts either Agent LLM
										or Document Summary LLM from search-space Settings → Models.
									</span>
									<Button
										size="sm"
										variant="outline"
										onClick={() =>
											setSearchSpaceSettingsDialog({ open: true, initialTab: "models" })
										}
									>
										<Settings className="mr-2 h-4 w-4" />
										Open Settings
									</Button>
								</div>
							</AlertDescription>
						</Alert>
					)}

					<div className="space-y-2">
						<p className="text-sm font-medium">Benchmark dataset (.json)</p>
						<input
							type="file"
							accept="application/json,.json"
							onChange={(e) => setBenchmarkFile(e.target.files?.[0] ?? null)}
							className="text-sm"
						/>
					</div>

					<div className="space-y-2">
						<p className="text-sm font-medium">Max questions (testing)</p>
						<input
							type="number"
							min={1}
							value={maxQuestions}
							onChange={(e) => setMaxQuestions(Math.max(1, Number(e.target.value || 1)))}
							className="h-9 w-24 rounded-md border border-input bg-background px-2 text-sm"
						/>
					</div>

					<EmbeddingModelSelector
						selectedModels={selectedEmbeddingModels}
						onSelectionChange={setSelectedEmbeddingModels}
						estimatedTokens={10000}
					/>

					<div className="space-y-2">
						<p className="text-sm font-medium">Chunk methods</p>
						<div className="grid grid-cols-2 gap-2">
							{CHUNK_METHODS.map((method) => {
								const active = selectedChunkMethods.includes(method);
								return (
									<Button
										key={method}
										type="button"
										variant={active ? "default" : "outline"}
										onClick={() => toggleString(setSelectedChunkMethods, selectedChunkMethods, method)}
									>
										{method}
									</Button>
								);
							})}
						</div>
					</div>

					<div className="space-y-2">
						<p className="text-sm font-medium">Chunk sizes</p>
						<div className="flex flex-wrap gap-2">
							{CHUNK_SIZES.map((size) => {
								const active = selectedChunkSizes.includes(size);
								return (
									<Button
										key={size}
										type="button"
										variant={active ? "default" : "outline"}
										onClick={() => toggleNumber(setSelectedChunkSizes, selectedChunkSizes, size)}
									>
										{size}
									</Button>
								);
							})}
						</div>
					</div>

					<div className="space-y-2">
						<p className="text-sm font-medium">Ranking variants</p>
						<div className="flex flex-wrap gap-2">
							{RANKING_VARIANTS.map((variant) => {
								const active = selectedRankingVariants.includes(variant);
								return (
									<Button
										key={variant}
										type="button"
										variant={active ? "default" : "outline"}
										onClick={() =>
											toggleString(
												setSelectedRankingVariants,
												selectedRankingVariants,
												variant
											)
										}
									>
										{variant}
									</Button>
								);
							})}
						</div>
					</div>

					<div className="rounded-lg border border-border p-3 space-y-3">
						{/* Master job header */}
						<div className="flex items-center justify-between text-sm">
							<span className="font-medium">Overall Progress</span>
							<span className="font-medium">{progressPercent}%</span>
						</div>
						<Progress value={progressPercent} className="h-2" />
						<p className="text-xs text-muted-foreground">{progressMessage}</p>
						{etaSeconds !== null && etaSeconds > 0 && (
							<p className="text-xs text-muted-foreground">ETA: {etaSeconds}s remaining</p>
						)}
						{jobId && (
							<p className="text-xs font-mono text-muted-foreground/50 truncate select-all" title={jobId}>
								Job ID: {jobId}
							</p>
						)}

						{/* Per-candidate rows */}
						{candidatesStatus.length > 0 && (
							<div className="space-y-1 pt-1 border-t border-border">
								<p className="text-xs font-medium text-muted-foreground pb-1">
									Subagents ({candidatesStatus.filter(c => c.status === "completed").length}/{candidatesStatus.length} done)
								</p>
								{candidatesStatus.map((c) => {
									const pct =
										c.status === "completed" || c.status === "failed" ? 100
										: c.status === "running" ? 50
										: 0;
									return (
										<div key={c.pipeline_id} className="space-y-0.5">
											<div className="flex items-center gap-1.5 text-xs">
												{c.status === "completed" ? (
													<CheckCircle2 className="h-3 w-3 text-green-500 shrink-0" />
												) : c.status === "failed" ? (
													<XCircle className="h-3 w-3 text-destructive shrink-0" />
												) : c.status === "running" ? (
													<Loader2 className="h-3 w-3 text-blue-500 animate-spin shrink-0" />
												) : (
													<Circle className="h-3 w-3 text-muted-foreground/40 shrink-0" />
												)}
												<span className="font-mono truncate flex-1 text-muted-foreground" title={c.pipeline_id}>
													{c.pipeline_id}
												</span>
												{c.status === "completed" && c.overall_correct_rate != null && (
													<span className="shrink-0 font-medium text-green-600">
														{(c.overall_correct_rate * 100).toFixed(0)}%
													</span>
												)}
												{c.status === "completed" && c.elapsed_seconds != null && (
													<span className="shrink-0 text-muted-foreground/60 flex items-center gap-0.5">
														<Clock className="h-2.5 w-2.5" />{c.elapsed_seconds.toFixed(0)}s
													</span>
												)}
												{c.status === "failed" && (
													<span className="shrink-0 text-destructive text-xs">failed</span>
												)}
											</div>
											<Progress
												value={pct}
												className={`h-1 ${c.status === "failed" ? "[&>div]:bg-destructive" : c.status === "running" ? "[&>div]:bg-blue-500" : ""}`}
											/>
										</div>
									);
								})}
							</div>
						)}
					</div>

					{isRunning && jobId && (
						<Button
							variant="outline"
							size="sm"
							className="w-full"
							onClick={async () => {
								if (!jobId) return;
								try {
									const status = await benchmarkApiService.getJob(jobId);
									setProgressPercent(status.progress_percent ?? 0);
									setProgressMessage(status.message ?? "Running...");
									setEtaSeconds(typeof status.eta_seconds === "number" ? status.eta_seconds : null);
									if (Array.isArray(status.candidates_status)) {
										setCandidatesStatus(status.candidates_status);
									}
									if (status.status === "completed") {
										setProgressPercent(100);
										setIsRunning(false);
										const reports = status.ranked_subagent_reports;
										if (Array.isArray(reports)) {
											setRankedReports(reports as Record<string, any>[]);
										}
										if (typeof window !== "undefined") {
											sessionStorage.removeItem("benchmark_job_id");
											sessionStorage.removeItem("benchmark_job_running");
										}
										toast.success("Benchmark completed");
									} else if (status.status === "failed") {
										setIsRunning(false);
										if (typeof window !== "undefined") {
											sessionStorage.removeItem("benchmark_job_id");
											sessionStorage.removeItem("benchmark_job_running");
										}
										toast.error(status.error || "Benchmark failed");
									} else {
										toast.info("Status synced");
									}
								} catch (err) {
									toast.error(err instanceof Error ? err.message : "Failed to sync status");
								}
							}}
						>
							Force Sync Status
						</Button>
					)}

					{isRunning && (
						<Button
							variant="ghost"
							size="sm"
							className="w-full text-muted-foreground"
							onClick={handleResetRunningState}
						>
							<RotateCcw className="mr-2 h-3 w-3" />
							Reset running state
						</Button>
					)}
					<Button onClick={handleRun} disabled={!canRun || isRunning} className="w-full">
						<Play className="mr-2 h-4 w-4" />
						{isRunning ? "Running benchmark..." : "Run Benchmark"}
					</Button>
					{!isRunning && disabledReason && (
						<p className="text-xs text-muted-foreground text-center">{disabledReason}</p>
					)}
				</CardContent>
			</Card>

			{topRows.length > 0 && (
				<Card>
					<CardHeader>
						<CardTitle>Benchmark Results</CardTitle>
						<CardDescription>Ranked candidate performance summary</CardDescription>
					</CardHeader>
					<CardContent className="overflow-auto">
						<table className="w-full text-sm">
							<thead>
								<tr className="text-left border-b border-border">
									<th className="py-2 pr-2">Rank</th>
									<th className="py-2 pr-2">Pipeline</th>
									<th className="py-2 pr-2">Overall</th>
									<th className="py-2 pr-2">Number</th>
									<th className="py-2 pr-2">F1</th>
									<th className="py-2">Score</th>
								</tr>
							</thead>
							<tbody>
								{topRows.map((row, index) => (
									<tr key={`${row.pipeline_id ?? index}`} className="border-b border-border/40">
										<td className="py-2 pr-2">{index + 1}</td>
										<td className="py-2 pr-2 break-all">{String(row.pipeline_id ?? "")}</td>
										<td className="py-2 pr-2">
											{(Number(row.overall_correct_rate ?? 0) * 100).toFixed(0)}%
										</td>
										<td className="py-2 pr-2">
											{(Number(row.number_match_rate ?? 0) * 100).toFixed(0)}%
										</td>
										<td className="py-2 pr-2">{Number(row.mean_token_f1 ?? 0).toFixed(4)}</td>
										<td className="py-2">{Number(row.score ?? 0).toFixed(4)}</td>
									</tr>
								))}
							</tbody>
						</table>
					</CardContent>
				</Card>
			)}
		</div>
	);
}
