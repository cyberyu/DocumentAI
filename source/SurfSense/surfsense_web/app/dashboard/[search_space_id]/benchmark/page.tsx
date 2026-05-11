"use client";

import { useAtomValue, useSetAtom } from "jotai";
import { AlertTriangle, CheckCircle2, Circle, Clock, Loader2, Play, RotateCcw, Settings, XCircle } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { benchmarkApiService } from "@/lib/apis/benchmark-api.service";
import { documentsApiService } from "@/lib/apis/documents-api.service";
import { getBearerToken } from "@/lib/auth-utils";

type EtlServiceOption = "DOCLING" | "MINERU" | "UNSTRUCTURED" | "LLAMACLOUD";

const ETL_SERVICE_OPTIONS: Array<{ key: EtlServiceOption; label: string; desc: string }> = [
	{
		key: "DOCLING",
		label: "Docling",
		desc: "Multi-format local parser for PDF/Office documents.",
	},
	{
		key: "MINERU",
		label: "MinerU",
		desc: "Layout parser for PDFs; MinerU v3+ also supports DOCX/PPTX/XLSX.",
	},
	{
		key: "UNSTRUCTURED",
		label: "Unstructured",
		desc: "General-purpose parser for mixed file types.",
	},
	{
		key: "LLAMACLOUD",
		label: "LlamaCloud",
		desc: "Cloud parsing pipeline for complex document layouts.",
	},
];

const CHUNK_METHODS: ChunkingStrategy[] = [
	"chunk_text",
	"sandwitch_chunk",
	"chunk_hybrid",
	"chunk_recursive",
];
const CHUNK_SIZES = [256, 512, 1024, 2048];
const RANKING_VARIANTS = ["hybrid_rrf_plus", "hybrid_weighted"];

interface BenchmarkDatasetSummary {
	benchmarkdata_id: number;
	doc_id: number;
	task_type: string;
	task_num: number;
	created_date: string;
	dataset_filename: string;
	dataset_mime_type?: string | null;
	dataset_size_bytes: number;
}

export default function BenchmarkPage() {
	const params = useParams();
	const searchParams = useSearchParams();
	const searchSpaceId = Number(params.search_space_id);
	const focusedDocIdParam = Number(searchParams.get("doc_id"));
	const focusedDocId = Number.isFinite(focusedDocIdParam) && focusedDocIdParam > 0 ? focusedDocIdParam : null;
	const setSearchSpaceSettingsDialog = useSetAtom(searchSpaceSettingsDialogAtom);
	const { data: preferences = {}, isFetching: preferencesLoading } = useAtomValue(llmPreferencesAtom);
	const { data: globalConfigs = [], isFetching: globalConfigsLoading } =
		useAtomValue(globalNewLLMConfigsAtom);

	const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
	const [selectedEtlServices, setSelectedEtlServices] = useState<EtlServiceOption[]>([
		"DOCLING",
	]);
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
	const [focusedBenchmarkDataset, setFocusedBenchmarkDataset] = useState<BenchmarkDatasetSummary | null>(null);
	const [autoFocusLoading, setAutoFocusLoading] = useState(false);
	const [variantMappingLoading, setVariantMappingLoading] = useState(false);
	const [variantMappingLoaded, setVariantMappingLoaded] = useState(false);
	const [variantMappingSource, setVariantMappingSource] = useState<string | null>(null);
	const [variantPipelineIdCount, setVariantPipelineIdCount] = useState<number | null>(null);
	const [availableEtlServices, setAvailableEtlServices] = useState<EtlServiceOption[]>([]);
	const [focusedPreferredEtlServices, setFocusedPreferredEtlServices] = useState<EtlServiceOption[]>([]);
	const [availableChunkMethods, setAvailableChunkMethods] = useState<ChunkingStrategy[]>([]);
	const [availableChunkSizes, setAvailableChunkSizes] = useState<number[]>([]);
	const [availableEmbeddingModels, setAvailableEmbeddingModels] = useState<string[]>([]);
	const lastAutoFocusKeyRef = useRef<string | null>(null);

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
		selectedEtlServices.length *
		selectedEmbeddingModels.length *
		selectedChunkMethods.length *
		selectedChunkSizes.length *
		selectedRankingVariants.length;

	const availableEtlServicesSet = useMemo(() => new Set(availableEtlServices), [availableEtlServices]);
	const availableChunkMethodsSet = useMemo(
		() => new Set(availableChunkMethods),
		[availableChunkMethods]
	);
	const availableChunkSizesSet = useMemo(() => new Set(availableChunkSizes), [availableChunkSizes]);
	const availableEmbeddingModelsSet = useMemo(
		() => new Set(availableEmbeddingModels),
		[availableEmbeddingModels]
	);

	const canRun =
		!!benchmarkFile &&
		hasBenchmarkLLM &&
		selectedEtlServices.length > 0 &&
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
		: selectedEtlServices.length === 0
		? "Select at least one ETL / Parse variant"
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

	useEffect(() => {
		if (!focusedDocId) {
			setFocusedPreferredEtlServices([]);
			return;
		}

		let cancelled = false;

		const loadFocusedPreferredEtl = async () => {
			try {
				const document = await documentsApiService.getDocument({ id: focusedDocId });
				if (cancelled) return;

				const etls = new Set<EtlServiceOption>();
				const metadata = document.document_metadata;

				const signatures = metadata?.pipeline_signatures;
				if (Array.isArray(signatures)) {
					for (const signature of signatures) {
						if (typeof signature !== "object" || signature === null) continue;
						const rawEtl = (signature as { etl_service?: unknown }).etl_service;
						if (typeof rawEtl !== "string") continue;
						const normalized = rawEtl.trim().toUpperCase();
						if (ETL_SERVICE_OPTIONS.some((option) => option.key === normalized)) {
							etls.add(normalized as EtlServiceOption);
						}
					}
				}

				if (etls.size === 0) {
					const raw = metadata?.ETL_SERVICE;
					if (typeof raw === "string") {
						const normalized = raw.trim().toUpperCase();
						if (ETL_SERVICE_OPTIONS.some((option) => option.key === normalized)) {
							etls.add(normalized as EtlServiceOption);
						}
					}
				}

				setFocusedPreferredEtlServices(Array.from(etls));
			} catch {
				if (!cancelled) {
					setFocusedPreferredEtlServices([]);
				}
			}
		};

		void loadFocusedPreferredEtl();

		return () => {
			cancelled = true;
		};
	}, [focusedDocId]);

	useEffect(() => {
		if (!searchSpaceId) return;

		let cancelled = false;

		const loadVariantMapping = async () => {
			setVariantMappingLoading(true);
			setVariantMappingSource(null);
			setVariantPipelineIdCount(null);
			try {
				const options = await benchmarkApiService.getAvailableOptions(
					searchSpaceId,
					focusedDocId ?? undefined
				);

				if (cancelled) return;

				setAvailableChunkMethods(
					CHUNK_METHODS.filter((method) => options.chunking_strategies.includes(method))
				);
				setAvailableEtlServices(
					ETL_SERVICE_OPTIONS.map((option) => option.key).filter((key) => {
						const normalizedOptions = options.etl_services.map((value) => value.trim().toUpperCase());
						return normalizedOptions.includes(key);
					})
				);
				setAvailableChunkSizes(
					CHUNK_SIZES.filter((size) => options.chunk_sizes.includes(size))
				);
				setAvailableEmbeddingModels(options.embedding_models);
				setVariantMappingSource(options.source ?? null);
				setVariantPipelineIdCount(Array.isArray(options.pipeline_ids) ? options.pipeline_ids.length : 0);
				setVariantMappingLoaded(true);
			} catch (error) {
				if (!cancelled) {
					setVariantMappingLoaded(false);
					setVariantMappingSource(null);
					setVariantPipelineIdCount(null);
					toast.error(
						error instanceof Error
							? error.message
							: "Failed to load pipeline variant mapping"
					);
				}
			} finally {
				if (!cancelled) setVariantMappingLoading(false);
			}
		};

		void loadVariantMapping();

		return () => {
			cancelled = true;
		};
	}, [searchSpaceId, focusedDocId]);

	useEffect(() => {
		if (!variantMappingLoaded) return;

		if (focusedDocId !== null) {
			setSelectedEtlServices(availableEtlServices);
			setSelectedChunkMethods(availableChunkMethods);
			setSelectedChunkSizes(availableChunkSizes);
			setSelectedEmbeddingModels(availableEmbeddingModels);
			return;
		}

		setSelectedEtlServices((previous) =>
			{
				const preferredAvailable = focusedPreferredEtlServices.filter((etl) =>
					availableEtlServicesSet.has(etl)
				);
				if (preferredAvailable.length > 0) {
					return preferredAvailable;
				}
				const filtered = previous.filter((etlService) => availableEtlServicesSet.has(etlService));
				if (filtered.length > 0) return filtered;
				return availableEtlServices.length > 0 ? [availableEtlServices[0]] : filtered;
			}
		);

		setSelectedChunkMethods((previous) =>
			{
				const filtered = previous.filter((method) => availableChunkMethodsSet.has(method));
				if (filtered.length > 0) return filtered;
				return availableChunkMethods.length > 0 ? [availableChunkMethods[0]] : filtered;
			}
		);
		setSelectedChunkSizes((previous) =>
			{
				const filtered = previous.filter((size) => availableChunkSizesSet.has(size));
				if (filtered.length > 0) return filtered;
				return availableChunkSizes.length > 0 ? [availableChunkSizes[0]] : filtered;
			}
		);
		setSelectedEmbeddingModels((previous) =>
			{
				const filtered = previous.filter((model) => availableEmbeddingModelsSet.has(model));
				if (filtered.length > 0) return filtered;
				return availableEmbeddingModels.length > 0 ? [availableEmbeddingModels[0]] : filtered;
			}
		);
	}, [
		variantMappingLoaded,
		focusedPreferredEtlServices,
		availableEtlServices,
		availableEtlServicesSet,
		availableChunkMethods,
		availableChunkMethodsSet,
		availableChunkSizes,
		availableChunkSizesSet,
		availableEmbeddingModels,
		availableEmbeddingModelsSet,
		focusedDocId,
	]);

	useEffect(() => {
		if (!focusedDocId || !searchSpaceId) {
			setFocusedBenchmarkDataset(null);
			return;
		}

		const focusKey = `${searchSpaceId}:${focusedDocId}`;
		if (lastAutoFocusKeyRef.current === focusKey) return;
		lastAutoFocusKeyRef.current = focusKey;

		let cancelled = false;
		const controller = new AbortController();

		const loadFocusedBenchmark = async () => {
			setAutoFocusLoading(true);
			try {
				const token = getBearerToken() || "";
				const listResponse = await fetch(
					`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${focusedDocId}/benchmark-data`,
					{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
				);
				if (!listResponse.ok) {
					throw new Error("Failed to load focused benchmark datasets");
				}

				const listPayload = (await listResponse.json()) as {
					items?: BenchmarkDatasetSummary[];
				};
				const items = listPayload.items ?? [];
				if (cancelled) return;

				if (items.length === 0) {
					setFocusedBenchmarkDataset(null);
					toast.info("No benchmark dataset found for selected document");
					return;
				}

				const selected = items[0];
				setFocusedBenchmarkDataset(selected);

				const downloadResponse = await fetch(
					`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${focusedDocId}/benchmark-data/${selected.benchmarkdata_id}/download`,
					{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
				);
				if (!downloadResponse.ok) {
					throw new Error("Failed to load focused benchmark data file");
				}
				const blob = await downloadResponse.blob();
				if (cancelled) return;

				const filename = selected.dataset_filename || `benchmark-${selected.benchmarkdata_id}.json`;
				const file = new File([blob], filename, {
					type: selected.dataset_mime_type || blob.type || "application/json",
					lastModified: Date.now(),
				});
				setBenchmarkFile(file);
			} catch (error) {
				if (controller.signal.aborted || cancelled) return;
				setFocusedBenchmarkDataset(null);
				toast.error(
					error instanceof Error
						? error.message
						: "Failed to auto-focus benchmark data"
				);
			} finally {
				if (!cancelled) setAutoFocusLoading(false);
			}
		};

		void loadFocusedBenchmark();

		return () => {
			cancelled = true;
			controller.abort();
		};
	}, [focusedDocId, searchSpaceId]);

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
				etl_services: selectedEtlServices,
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
						{focusedBenchmarkDataset && (
							<p className="text-xs text-muted-foreground">
								Focused document #{focusedBenchmarkDataset.doc_id} · using {focusedBenchmarkDataset.dataset_filename}
								 {focusedBenchmarkDataset.task_num ? `(Task ${focusedBenchmarkDataset.task_num})` : ""}
							</p>
						)}
						{autoFocusLoading && (
							<p className="text-xs text-muted-foreground">Loading focused benchmark data...</p>
						)}
						<input
							type="file"
							accept="application/json,.json"
							onChange={(e) => setBenchmarkFile(e.target.files?.[0] ?? null)}
							className="text-sm"
						/>
					</div>

					<div className="space-y-2">
						<p className="text-xs text-muted-foreground">
							Benchmark options are mapped to existing pipeline variants; unavailable options are disabled. Chunk Ranking Variants are always available.
						</p>
						{variantMappingLoaded && variantMappingSource && (
							<div className="flex items-center gap-2">
								<span className="text-xs text-muted-foreground">Mapping source:</span>
								<Badge variant="outline" className="text-[10px] uppercase tracking-wide">
									{variantMappingSource === "opensearch" ? "OpenSearch tags" : "Metadata fallback"}
								</Badge>
								{variantPipelineIdCount !== null && (
									<span className="text-xs text-muted-foreground">
										{variantPipelineIdCount} pipeline IDs
									</span>
								)}
							</div>
						)}
						{variantMappingLoading && (
							<p className="text-xs text-muted-foreground">Loading pipeline variant availability...</p>
						)}
						{variantMappingLoaded &&
							(availableEtlServices.length === 0 ||
								availableChunkMethods.length === 0 ||
								availableChunkSizes.length === 0 ||
								availableEmbeddingModels.length === 0) && (
								<Alert>
									<AlertTriangle className="h-4 w-4" />
									<AlertTitle>Pipeline variants required</AlertTitle>
									<AlertDescription>
										Create pipeline variants first (ETL/parse, chunking, embeddings, chunk sizes), then run benchmark.
									</AlertDescription>
								</Alert>
							)}
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

					<div className="space-y-3 rounded-lg border border-border p-3">
						<div className="flex items-center justify-between mb-1">
							<p className="font-semibold text-sm">Pipeline Settings</p>
						</div>

						<div className="flex items-center gap-0 text-[10px] font-medium mb-3">
							{[
								{ step: "1", label: "ETL / Parse", sub: "PDF → Markdown", color: "bg-orange-500", text: "text-orange-400", border: "border-orange-500/40" },
								{ step: "2", label: "Chunking Method", sub: "Split strategy", color: "bg-violet-500", text: "text-violet-400", border: "border-violet-500/40" },
								{ step: "3", label: "Chunk Size", sub: "Token window", color: "bg-emerald-500", text: "text-emerald-400", border: "border-emerald-500/40" },
								{ step: "4", label: "Embeddings", sub: "Vectors → Index", color: "bg-blue-500", text: "text-blue-400", border: "border-blue-500/40" },
							].map((stage, index) => (
								<div key={stage.step} className="flex items-center">
									<div className={`flex items-center gap-1.5 rounded-md border ${stage.border} bg-muted/60 px-2.5 py-1.5`}>
										<span className={`inline-flex h-4 w-4 items-center justify-center rounded-full ${stage.color} text-white font-bold text-[9px] shrink-0`}>{stage.step}</span>
										<div>
											<p className={`${stage.text} font-semibold leading-none`}>{stage.label}</p>
											<p className="text-muted-foreground/60 leading-none mt-0.5">{stage.sub}</p>
										</div>
									</div>
									{index < 3 && (
										<svg className="h-3 w-5 text-muted-foreground/40 shrink-0" viewBox="0 0 20 12" fill="none">
											<path d="M0 6h16M12 1l6 5-6 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
										</svg>
									)}
								</div>
							))}
						</div>

						<div className="grid grid-cols-4 divide-x divide-border">
							<div className="pr-4 space-y-2">
								<div className="flex items-center gap-2 pb-1 border-b border-border">
									<span className="inline-block h-2 w-2 rounded-full bg-orange-500 shrink-0" />
									<p className="font-semibold text-xs uppercase tracking-wider text-foreground">ETL / Parse</p>
								</div>
								<p className="text-[10px] text-muted-foreground leading-snug">
									Converts raw files into clean Markdown. Runs once per document and must exist before benchmarking.
								</p>
								{ETL_SERVICE_OPTIONS.map((option) => {
									const active = selectedEtlServices.includes(option.key);
									const isAvailable = !variantMappingLoaded || availableEtlServicesSet.has(option.key);
									return (
										<button
											key={option.key}
											type="button"
											disabled={!isAvailable}
											onClick={() =>
												toggleString(setSelectedEtlServices, selectedEtlServices, option.key)
											}
											className={`rounded-lg border px-3 py-2 flex items-start gap-2 text-left ${
												!isAvailable
													? "border-border bg-muted/20 opacity-50 cursor-not-allowed"
													: active
														? "border-orange-500/50 bg-orange-500/10"
														: "border-border bg-muted/40 hover:border-orange-500/30"
											}`}
										>
											<span className={`inline-block h-1.5 w-1.5 rounded-full mt-1 shrink-0 ${active ? "bg-orange-500" : "bg-muted-foreground/50"}`} />
											<div>
												<p className={`text-xs font-semibold leading-none ${active ? "text-orange-400" : "text-muted-foreground"}`}>
													{option.label}
													{active ? " (selected)" : ""}
												</p>
												<p className="text-[10px] text-muted-foreground mt-0.5 leading-snug">{option.desc}</p>
											</div>
										</button>
									);
								})}
							</div>

							<div className="px-4 space-y-2">
								<div className="flex items-center gap-2 pb-1 border-b border-border">
									<span className="inline-block h-2 w-2 rounded-full bg-violet-500 shrink-0" />
									<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Chunking Method</p>
								</div>
								<div className="grid grid-cols-1 gap-1.5">
									{CHUNK_METHODS.map((method) => {
										const active = selectedChunkMethods.includes(method);
										const isAvailable = !variantMappingLoaded || availableChunkMethodsSet.has(method);
										return (
											<button
												key={method}
												type="button"
												disabled={!isAvailable}
												onClick={() => toggleString(setSelectedChunkMethods, selectedChunkMethods, method)}
												className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors flex items-center gap-2 ${
													!isAvailable
														? "border-border bg-muted/20 text-muted-foreground/50 opacity-50 cursor-not-allowed"
														: active
															? "border-violet-500 bg-violet-500/10 text-violet-400"
															: "border-border hover:border-muted-foreground/50 text-muted-foreground hover:text-foreground"
												}`}
											>
												<span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${active ? "bg-violet-500" : "bg-muted-foreground/40"}`} />
												{method}
											</button>
										);
									})}
								</div>
							</div>

							<div className="px-4 space-y-2">
								<div className="flex items-center gap-2 pb-1 border-b border-border">
									<span className="inline-block h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
									<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Chunk Size</p>
								</div>
								<div className="grid grid-cols-2 gap-1.5">
									{CHUNK_SIZES.map((size) => {
										const active = selectedChunkSizes.includes(size);
										const isAvailable = !variantMappingLoaded || availableChunkSizesSet.has(size);
										return (
											<button
												key={size}
												type="button"
												disabled={!isAvailable}
												onClick={() => toggleNumber(setSelectedChunkSizes, selectedChunkSizes, size)}
												className={`rounded-lg border px-2 py-2 text-center text-xs font-medium transition-colors ${
													!isAvailable
														? "border-border bg-muted/20 text-muted-foreground/50 opacity-50 cursor-not-allowed"
														: active
															? "border-emerald-500 bg-emerald-500/10 text-emerald-400"
															: "border-border hover:border-muted-foreground/50 text-muted-foreground hover:text-foreground"
												}`}
											>
												{size}
											</button>
										);
									})}
								</div>
							</div>

							<div className="pl-4 space-y-2">
								<div className="flex items-center gap-2 pb-1 border-b border-border">
									<span className="inline-block h-2 w-2 rounded-full bg-blue-500 shrink-0" />
									<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Embeddings</p>
								</div>
								<EmbeddingModelSelector
									selectedModels={selectedEmbeddingModels}
									onSelectionChange={setSelectedEmbeddingModels}
									availableModelIds={variantMappingLoaded ? availableEmbeddingModels : undefined}
									estimatedTokens={10000}
								/>
							</div>
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
									<th className="py-2 pr-2">Overall Ratio</th>
									<th className="py-2 pr-2">Normalized Ratio</th>
									<th className="py-2 pr-2">Number Ratio</th>
									<th className="py-2 pr-2">Unit Ratio</th>
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
											{(Number(row.normalized_exact_rate ?? 0) * 100).toFixed(0)}%
										</td>
										<td className="py-2 pr-2">
											{(Number(row.number_match_rate ?? 0) * 100).toFixed(0)}%
										</td>
										<td className="py-2 pr-2">
											{(Number(row.unit_match_rate ?? 0) * 100).toFixed(0)}%
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
