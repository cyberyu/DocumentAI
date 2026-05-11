"use client";

import { useAtomValue, useSetAtom } from "jotai";
import {
	Check,
	Copy,
	Download,
	FileQuestionMark,
	FileText,
	FlaskConical,
	Pencil,
	RefreshCw,
	Search,
	Trash2,
	XIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { closeEditorPanelAtom, editorPanelAtom, consumePendingPipelineVariants, type PipelineVariant } from "@/atoms/editor/editor-panel.atom";
import { VersionHistoryButton } from "@/components/documents/version-history";
import { SourceCodeEditor } from "@/components/editor/source-code-editor";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerHandle, DrawerTitle } from "@/components/ui/drawer";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useElectronAPI } from "@/hooks/use-platform";
import { authenticatedFetch, getBearerToken, redirectToLogin } from "@/lib/auth-utils";
import { inferMonacoLanguageFromPath } from "@/lib/editor-language";
import { ETL_SERVICE } from "@/lib/env-config";

const PlateEditor = dynamic(
	() => import("@/components/editor/plate-editor").then((m) => ({ default: m.PlateEditor })),
	{ ssr: false, loading: () => <EditorPanelSkeleton /> }
);

const LARGE_DOCUMENT_THRESHOLD = 2 * 1024 * 1024; // 2MB

interface PipelineInfo {
	embeddingModels: string[];
	chunkingStrategies: string[];
	chunkSize?: number;
	embeddingMode?: string;
}

function getPipelineInfo(
	metadata?: Record<string, unknown>,
	title?: string
): PipelineInfo | null {
	// Prefer structured metadata stored during indexing
	if (metadata) {
		const hasEmbedding = Array.isArray(metadata.embedding_models) && (metadata.embedding_models as string[]).length > 0;
		const hasStrategy = Array.isArray(metadata.chunking_strategies) && (metadata.chunking_strategies as string[]).length > 0;
		const hasSize = metadata.chunk_size !== undefined && metadata.chunk_size !== null;
		if (hasEmbedding || hasStrategy || hasSize) {
			return {
				embeddingModels: hasEmbedding ? (metadata.embedding_models as string[]) : [],
				chunkingStrategies: hasStrategy ? (metadata.chunking_strategies as string[]) : [],
				chunkSize: hasSize ? (metadata.chunk_size as number) : undefined,
				embeddingMode: metadata.embedding_mode as string | undefined,
			};
		}
	}
	// Fallback: parse from benchmark document title (format: source__strategy__model__tokN__ranking)
	if (title && title.includes("__")) {
		// Strip file extension from the last part before parsing (e.g. "tok256.docx" → "tok256")
		const rawParts = title.split("__");
		const parts = rawParts.map((p, i) =>
			i === rawParts.length - 1 ? p.replace(/\.[^.]+$/, "") : p
		);
		const sizeSlug = parts.find((p) => /^tok\d+$/i.test(p));
		const chunkSize = sizeSlug ? parseInt(sizeSlug.replace(/^tok/i, ""), 10) : undefined;
		// Strategy is typically the part containing 'chunk'
		const strategy = parts.find((p) => p.toLowerCase().includes("chunk"));
		// Ranking variant keywords
		const rankingKeywords = ["hybrid", "weighted", "rrf", "semantic", "lexical"];
		// Everything that isn't the source (first), strategy, size slug, or a pure ranking term
		const modelParts = parts.slice(1).filter(
			(p) =>
				p !== sizeSlug &&
				p !== strategy &&
				!rankingKeywords.some((k) => p.toLowerCase().includes(k))
		);
		if (strategy || chunkSize !== undefined || modelParts.length > 0) {
			return {
				embeddingModels: modelParts.length > 0 ? [modelParts.join("/")] : [],
				chunkingStrategies: strategy ? [strategy] : [],
				chunkSize,
			};
		}
	}
	return null;
}

function PipelineDetailsBar({
	docId,
	pipeline,
}: {
	docId?: number;
	pipeline: PipelineInfo | null;
}) {
	if (!pipeline && docId === undefined) return null;
	return (
		<div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t px-4 py-2 text-xs text-muted-foreground">
			{docId !== undefined && (
				<span className="flex items-center gap-1 shrink-0">
					<span className="font-medium">ID</span>
					<Badge variant="outline" className="h-4 px-1.5 text-[10px] font-mono">
						#{docId}
					</Badge>
				</span>
			)}
			{pipeline?.embeddingModels && pipeline.embeddingModels.length > 0 && (
				<span className="flex items-center gap-1 flex-wrap">
					<span className="font-medium shrink-0">Embedding</span>
					{pipeline.embeddingModels.map((m) => (
						<Badge key={m} variant="secondary" className="h-4 px-1.5 text-[10px]">
							{m}
						</Badge>
					))}
				</span>
			)}
			{pipeline?.chunkingStrategies && pipeline.chunkingStrategies.length > 0 && (
				<span className="flex items-center gap-1 flex-wrap">
					<span className="font-medium shrink-0">Chunking</span>
					{pipeline.chunkingStrategies.map((s) => (
						<Badge key={s} variant="secondary" className="h-4 px-1.5 text-[10px]">
							{s}
						</Badge>
					))}
				</span>
			)}
			{pipeline?.chunkSize !== undefined && (
				<span className="flex items-center gap-1 shrink-0">
					<span className="font-medium">Chunk Size</span>
					<Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
						{pipeline.chunkSize} tok
					</Badge>
				</span>
			)}
		</div>
	);
}

interface EditorContent {
	document_id: number;
	title: string;
	document_type?: string;
	source_markdown: string;
	content_size_bytes?: number;
	chunk_count?: number;
	truncated?: boolean;
	document_metadata?: Record<string, unknown>;
}

const EDITABLE_DOCUMENT_TYPES = new Set(["FILE", "NOTE"]);
type EditorRenderMode = "rich_markdown" | "source_code";

type AgentFilesystemMount = {
	mount: string;
	rootPath: string;
};

function normalizeLocalVirtualPathForEditor(
	candidatePath: string,
	mounts: AgentFilesystemMount[]
): string {
	const normalizedCandidate = candidatePath.trim().replace(/\\/g, "/").replace(/\/+/g, "/");
	if (!normalizedCandidate) return candidatePath;
	const defaultMount = mounts[0]?.mount;
	if (!defaultMount) {
		return normalizedCandidate.startsWith("/")
			? normalizedCandidate
			: `/${normalizedCandidate.replace(/^\/+/, "")}`;
	}

	const mountNames = new Set(mounts.map((entry) => entry.mount));
	if (normalizedCandidate.startsWith("/")) {
		const relative = normalizedCandidate.replace(/^\/+/, "");
		const [firstSegment] = relative.split("/", 1);
		if (mountNames.has(firstSegment)) {
			return `/${relative}`;
		}
		return `/${defaultMount}/${relative}`;
	}

	const relative = normalizedCandidate.replace(/^\/+/, "");
	const [firstSegment] = relative.split("/", 1);
	if (mountNames.has(firstSegment)) {
		return `/${relative}`;
	}
	return `/${defaultMount}/${relative}`;
}

function EditorPanelSkeleton() {
	return (
		<div className="space-y-6 p-6">
			<div className="h-6 w-3/4 rounded-md bg-muted/60 animate-pulse" />
			<div className="space-y-2.5">
				<div className="h-3 w-full rounded-md bg-muted/60 animate-pulse" />
				<div className="h-3 w-[95%] rounded-md bg-muted/60 animate-pulse [animation-delay:100ms]" />
				<div className="h-3 w-[88%] rounded-md bg-muted/60 animate-pulse [animation-delay:200ms]" />
				<div className="h-3 w-[60%] rounded-md bg-muted/60 animate-pulse [animation-delay:300ms]" />
			</div>
			<div className="h-5 w-2/5 rounded-md bg-muted/60 animate-pulse [animation-delay:400ms]" />
			<div className="space-y-2.5">
				<div className="h-3 w-full rounded-md bg-muted/60 animate-pulse [animation-delay:500ms]" />
				<div className="h-3 w-[92%] rounded-md bg-muted/60 animate-pulse [animation-delay:600ms]" />
				<div className="h-3 w-[75%] rounded-md bg-muted/60 animate-pulse [animation-delay:700ms]" />
			</div>
		</div>
	);
}

// Stable color palettes for each config dimension
const STRATEGY_COLORS: Record<string, string> = {};
const STRATEGY_PALETTE = [
	"bg-blue-500/15 text-blue-400 border-blue-500/30",
	"bg-violet-500/15 text-violet-400 border-violet-500/30",
	"bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
	"bg-teal-500/15 text-teal-400 border-teal-500/30",
];
const EMBEDDING_COLORS: Record<string, string> = {};
const EMBEDDING_PALETTE = [
	"bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
	"bg-orange-500/15 text-orange-400 border-orange-500/30",
	"bg-pink-500/15 text-pink-400 border-pink-500/30",
	"bg-amber-500/15 text-amber-400 border-amber-500/30",
];

function getStrategyColor(s: string) {
	if (!STRATEGY_COLORS[s]) {
		const idx = Object.keys(STRATEGY_COLORS).length % STRATEGY_PALETTE.length;
		STRATEGY_COLORS[s] = STRATEGY_PALETTE[idx];
	}
	return STRATEGY_COLORS[s];
}
function getEmbeddingColor(m: string) {
	if (!EMBEDDING_COLORS[m]) {
		const idx = Object.keys(EMBEDDING_COLORS).length % EMBEDDING_PALETTE.length;
		EMBEDDING_COLORS[m] = EMBEDDING_PALETTE[idx];
	}
	return EMBEDDING_COLORS[m];
}

interface ChunkViewState {
	variantId: number;
	variantTitle: string;
	pipelineId?: string;
	query: string;
	chunks: Array<{ id: number; index: number; content: string }>;
	total: number;
	loading: boolean;
	error: string | null;
}

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

function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function buildSmartSplitVariants(query: string): string[] {
	if (!/^[A-Za-z0-9]{6,}$/.test(query)) return [];
	const variants: string[] = [];
	for (let idx = 3; idx < query.length - 2; idx += 1) {
		variants.push(`${query.slice(0, idx)} ${query.slice(idx)}`);
		if (variants.length >= 12) break;
	}
	return variants;
}

function highlightChunkContent(
	content: string,
	query: string,
	caseInsensitive: boolean,
	smartMatch: boolean
) {
	const trimmed = query.trim();
	if (!trimmed) return content;

	const terms = new Set<string>([trimmed]);
	if (smartMatch) {
		for (const variant of buildSmartSplitVariants(trimmed)) {
			terms.add(variant);
		}
	}

	const escapedTerms = [...terms]
		.filter((term) => term.length > 0)
		.sort((a, b) => b.length - a.length)
		.map((term) => escapeRegExp(term));

	if (escapedTerms.length === 0) return content;

	const pattern = new RegExp(`(${escapedTerms.join("|")})`, caseInsensitive ? "gi" : "g");
	const parts = content.split(pattern);

	if (parts.length <= 1) return content;

	return (
		<>
			{parts.map((part, index) =>
				index % 2 === 1 ? (
					<mark key={`${part}-${index}`} className="rounded bg-yellow-300 px-0.5 font-semibold text-black dark:bg-yellow-400">
						{part}
					</mark>
				) : (
					<span key={`${part}-${index}`}>{part}</span>
				)
			)}
		</>
	);
}

function PipelineListView({
	variants,
	searchSpaceId,
	sourceTitle,
	onClose,
}: {
	variants: PipelineVariant[];
	searchSpaceId?: number;
	sourceTitle: string | null;
	onClose?: () => void;
}) {
	const [activeStrategies, setActiveStrategies] = useState<Set<string>>(new Set());
	const [activeEmbeddings, setActiveEmbeddings] = useState<Set<string>>(new Set());
	const [chunkView, setChunkView] = useState<ChunkViewState | null>(null);
	const [chunkSearchInput, setChunkSearchInput] = useState("");
	const [chunkCaseInsensitive, setChunkCaseInsensitive] = useState(true);
	const [chunkSmartMatch, setChunkSmartMatch] = useState(true);
	const sourceDocumentId = variants[0]?.id;
	const [benchmarkItems, setBenchmarkItems] = useState<BenchmarkDatasetSummary[]>([]);
	const [benchmarkLoading, setBenchmarkLoading] = useState(false);
	const [benchmarkError, setBenchmarkError] = useState<string | null>(null);
	const [benchmarkUploadOpen, setBenchmarkUploadOpen] = useState(false);
	const [benchmarkUploading, setBenchmarkUploading] = useState(false);
	const [benchmarkDeletingId, setBenchmarkDeletingId] = useState<number | null>(null);
	const [benchmarkDownloadingId, setBenchmarkDownloadingId] = useState<number | null>(null);
	const [benchmarkPendingDelete, setBenchmarkPendingDelete] = useState<BenchmarkDatasetSummary | null>(null);
	const [benchmarkTaskType, setBenchmarkTaskType] = useState("qa");
	const [benchmarkTaskNum, setBenchmarkTaskNum] = useState("1");
	const [benchmarkFile, setBenchmarkFile] = useState<File | null>(null);
	const defaultEtlLabel = ETL_SERVICE.toUpperCase() === "MINERU" ? "MinerU" : "Docling";

	const resolveVariantEtlLabel = useCallback((variant: PipelineVariant): string => {
		const explicit = variant.etlService?.toUpperCase();
		if (explicit === "MINERU") return "MinerU";
		if (explicit === "DOCLING") return "Docling";
		if (explicit === "UNSTRUCTURED") return "Unstructured";
		if (explicit === "LLAMACLOUD") return "LlamaCloud";

		const sepIdx = variant.title.indexOf("__");
		if (sepIdx >= 0) {
			const suffix = variant.title.slice(sepIdx + 2);
			const firstSegment = suffix.split("__", 1)[0]?.trim().toUpperCase();
			if (firstSegment === "MINERU") return "MinerU";
			if (firstSegment === "DOCLING") return "Docling";
			if (firstSegment === "UNSTRUCTURED") return "Unstructured";
			if (firstSegment === "LLAMACLOUD") return "LlamaCloud";
		}

		return defaultEtlLabel;
	}, [defaultEtlLabel]);

	const fetchVariantChunks = useCallback(async (
		variantId: number,
		query: string,
		options?: { caseinsensitive?: boolean; smartMatch?: boolean; pipelineId?: string }
	) => {
		const params = new URLSearchParams();
		const trimmedQuery = query.trim();
		if (trimmedQuery) params.set("q", trimmedQuery);
		if (options?.pipelineId) params.set("pipeline_id", options.pipelineId);
		params.set("caseinsensitive", String(options?.caseinsensitive ?? true));
		params.set("smart_match", String(options?.smartMatch ?? true));
		const queryString = params.toString();
		const url = `${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/search-spaces/${searchSpaceId}/documents/${variantId}/chunks${queryString ? `?${queryString}` : ""}`;
		const res = await authenticatedFetch(url, { method: "GET" });
		if (!res.ok) {
			const err = await res.json().catch(() => ({ detail: "Failed to load chunks" }));
			throw new Error(err.detail ?? "Failed to load chunks");
		}
		return res.json();
	}, [searchSpaceId]);

	const openChunkView = useCallback(async (v: PipelineVariant) => {
		setChunkSearchInput("");
		setChunkView({ variantId: v.id, variantTitle: v.title, pipelineId: v.pipelineId, query: "", chunks: [], total: 0, loading: true, error: null });
		try {
			const data = await fetchVariantChunks(v.id, "", { pipelineId: v.pipelineId });
			setChunkView({
				variantId: v.id,
				variantTitle: v.title,
				pipelineId: v.pipelineId,
				query: "",
				chunks: data.chunks ?? [],
				total: data.total ?? 0,
				loading: false,
				error: null,
			});
		} catch (e) {
			setChunkView((prev) => prev ? { ...prev, loading: false, error: String(e) } : null);
		}
	}, [fetchVariantChunks]);

	const runChunkSearch = useCallback(async () => {
		if (!chunkView) return;
		const query = chunkSearchInput.trim();
		setChunkView((prev) => (prev ? { ...prev, query, loading: true, error: null } : prev));
		try {
			const data = await fetchVariantChunks(chunkView.variantId, query, {
				caseinsensitive: chunkCaseInsensitive,
				smartMatch: chunkSmartMatch,
				pipelineId: chunkView.pipelineId,
			});
			setChunkView((prev) =>
				prev
					? {
							...prev,
							query,
							chunks: data.chunks ?? [],
							total: data.total ?? 0,
							loading: false,
							error: null,
						}
					: prev
			);
		} catch (e) {
			setChunkView((prev) => (prev ? { ...prev, loading: false, error: String(e) } : prev));
		}
	}, [chunkSearchInput, chunkView, fetchVariantChunks, chunkCaseInsensitive, chunkSmartMatch]);

	const loadBenchmarkDatasets = useCallback(async () => {
		if (!sourceDocumentId) {
			setBenchmarkItems([]);
			setBenchmarkError(null);
			return;
		}

		setBenchmarkLoading(true);
		setBenchmarkError(null);
		try {
			const response = await authenticatedFetch(
				`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${sourceDocumentId}/benchmark-data`,
				{ method: "GET" }
			);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: "Failed to load benchmark datasets" }));
				throw new Error(err.detail ?? "Failed to load benchmark datasets");
			}
			const payload = (await response.json()) as { items?: BenchmarkDatasetSummary[] };
			setBenchmarkItems(payload.items ?? []);
		} catch (error) {
			setBenchmarkError(error instanceof Error ? error.message : "Failed to load benchmark datasets");
		} finally {
			setBenchmarkLoading(false);
		}
	}, [sourceDocumentId]);

	useEffect(() => {
		void loadBenchmarkDatasets();
	}, [loadBenchmarkDatasets]);

	const submitBenchmarkUpload = useCallback(async () => {
		if (!sourceDocumentId) {
			toast.error("Missing source document context");
			return;
		}
		if (!benchmarkFile) {
			toast.error("Choose a benchmark dataset file first");
			return;
		}
		const normalizedTaskType = benchmarkTaskType.trim();
		if (!normalizedTaskType) {
			toast.error("Task type is required");
			return;
		}
		const parsedTaskNum = Number.parseInt(benchmarkTaskNum, 10);
		if (!Number.isFinite(parsedTaskNum) || parsedTaskNum < 1) {
			toast.error("Task number must be at least 1");
			return;
		}

		setBenchmarkUploading(true);
		try {
			const formData = new FormData();
			formData.append("benchmark_file", benchmarkFile);
			formData.append("task_type", normalizedTaskType);
			formData.append("task_num", String(parsedTaskNum));

			const response = await authenticatedFetch(
				`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${sourceDocumentId}/benchmark-data`,
				{ method: "POST", body: formData }
			);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: "Failed to upload benchmark dataset" }));
				throw new Error(err.detail ?? "Failed to upload benchmark dataset");
			}

			toast.success("Benchmark dataset associated");
			setBenchmarkFile(null);
			setBenchmarkUploadOpen(false);
			await loadBenchmarkDatasets();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to upload benchmark dataset");
		} finally {
			setBenchmarkUploading(false);
		}
	}, [sourceDocumentId, benchmarkFile, benchmarkTaskType, benchmarkTaskNum, loadBenchmarkDatasets]);

	const handleBenchmarkDownload = useCallback(async (item: BenchmarkDatasetSummary) => {
		if (!sourceDocumentId) return;
		setBenchmarkDownloadingId(item.benchmarkdata_id);
		try {
			const response = await authenticatedFetch(
				`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${sourceDocumentId}/benchmark-data/${item.benchmarkdata_id}/download`,
				{ method: "GET" }
			);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: "Failed to download benchmark dataset" }));
				throw new Error(err.detail ?? "Failed to download benchmark dataset");
			}

			const blob = await response.blob();
			const objectUrl = URL.createObjectURL(blob);
			const anchor = document.createElement("a");
			anchor.href = objectUrl;
			anchor.download = item.dataset_filename || `benchmark-${item.benchmarkdata_id}.txt`;
			document.body.appendChild(anchor);
			anchor.click();
			anchor.remove();
			URL.revokeObjectURL(objectUrl);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to download benchmark dataset");
		} finally {
			setBenchmarkDownloadingId(null);
		}
	}, [sourceDocumentId]);

	const executeBenchmarkDelete = useCallback(async (item: BenchmarkDatasetSummary) => {
		if (!sourceDocumentId) return;
		setBenchmarkDeletingId(item.benchmarkdata_id);
		try {
			const response = await authenticatedFetch(
				`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/documents/${sourceDocumentId}/benchmark-data/${item.benchmarkdata_id}`,
				{ method: "DELETE" }
			);
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: "Failed to delete benchmark dataset" }));
				throw new Error(err.detail ?? "Failed to delete benchmark dataset");
			}

			toast.success("Benchmark dataset removed");
			await loadBenchmarkDatasets();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to delete benchmark dataset");
		} finally {
			setBenchmarkDeletingId(null);
		}
	}, [sourceDocumentId, loadBenchmarkDatasets]);

	const confirmBenchmarkDelete = useCallback(async () => {
		if (!benchmarkPendingDelete) return;
		await executeBenchmarkDelete(benchmarkPendingDelete);
		setBenchmarkPendingDelete(null);
	}, [benchmarkPendingDelete, executeBenchmarkDelete]);

	// Collect all unique values across variants
	const allStrategies = useMemo(() => {
		const s = new Set<string>();
		for (const v of variants) {
			const info = getPipelineInfo(undefined, v.title);
			info?.chunkingStrategies.forEach((x) => s.add(x));
		}
		return [...s].sort();
	}, [variants]);

	const allEmbeddings = useMemo(() => {
		const s = new Set<string>();
		for (const v of variants) {
			const info = getPipelineInfo(undefined, v.title);
			info?.embeddingModels.forEach((x) => s.add(x));
		}
		return [...s].sort();
	}, [variants]);

	const filteredVariants = useMemo(() => {
		return variants.filter((v) => {
			const info = getPipelineInfo(undefined, v.title);
			if (activeStrategies.size > 0 && !info?.chunkingStrategies.some((s) => activeStrategies.has(s))) return false;
			if (activeEmbeddings.size > 0 && !info?.embeddingModels.some((m) => activeEmbeddings.has(m))) return false;
			return true;
		});
	}, [variants, activeStrategies, activeEmbeddings]);

	function toggleFilter<T>(set: Set<T>, val: T, setter: (s: Set<T>) => void) {
		const next = new Set(set);
		if (next.has(val)) next.delete(val); else next.add(val);
		setter(next);
	}

	const hasFilters = activeStrategies.size > 0 || activeEmbeddings.size > 0;

	// ── Chunk view rendering ─────────────────────────────────────────────────
	if (chunkView !== null) {
		return (
			<div className="flex flex-col h-full overflow-hidden">
				{/* Chunk view header */}
				<div className="flex items-center justify-between px-4 py-3 border-b shrink-0 gap-2">
					<div className="flex items-center gap-2 min-w-0">
						<Button
							variant="ghost"
							size="sm"
							className="h-6 px-2 text-xs shrink-0 gap-1"
							onClick={() => setChunkView(null)}
						>
							← Back
						</Button>
						<span className="text-[11px] text-muted-foreground truncate hidden sm:block">{chunkView.variantTitle}</span>
					</div>
					{onClose && (
						<Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onClose}>
							<XIcon className="h-4 w-4" />
						</Button>
					)}
				</div>

				{/* Chunk content */}
				<div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
					<div className="flex items-center gap-2">
						<div className="relative flex-1">
							<Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
							<Input
								placeholder="Search words/phrases in chunks"
								value={chunkSearchInput}
								onChange={(e) => setChunkSearchInput(e.target.value)}
								onKeyDown={(e) => {
									if (e.key === "Enter") {
										e.preventDefault();
										void runChunkSearch();
									}
								}}
								className="h-8 pl-8 text-xs"
							/>
						</div>
						<Button size="sm" className="h-8" onClick={() => void runChunkSearch()} disabled={chunkView.loading}>
							Search
						</Button>
						{chunkView.query && (
							<Button
								variant="ghost"
								size="sm"
								className="h-8"
								onClick={() => {
									setChunkSearchInput("");
									setChunkView((prev) => (prev ? { ...prev, query: "" } : prev));
									void fetchVariantChunks(chunkView.variantId, "", {
										caseinsensitive: chunkCaseInsensitive,
										smartMatch: chunkSmartMatch,
										pipelineId: chunkView.pipelineId,
									})
										.then((data) => {
											setChunkView((prev) =>
												prev
													? {
														...prev,
														query: "",
														chunks: data.chunks ?? [],
														total: data.total ?? 0,
														loading: false,
														error: null,
													}
													: prev
											);
										})
										.catch((e) => {
											setChunkView((prev) =>
												prev ? { ...prev, loading: false, error: String(e) } : prev
											);
										});
								}}
							>
								Clear
							</Button>
						)}
					</div>
					<div className="flex items-center gap-2">
						<Button
							variant={chunkCaseInsensitive ? "default" : "outline"}
							size="sm"
							className="h-7 text-[11px]"
							onClick={() => setChunkCaseInsensitive((prev) => !prev)}
						>
							Caseinsensitive
						</Button>
						<Button
							variant={chunkSmartMatch ? "default" : "outline"}
							size="sm"
							className="h-7 text-[11px]"
							onClick={() => setChunkSmartMatch((prev) => !prev)}
						>
							Smart Match
						</Button>
					</div>
					{chunkView.loading && (
						<div className="flex items-center justify-center py-12">
							<Spinner className="h-5 w-5 text-muted-foreground" />
						</div>
					)}
					{!chunkView.loading && chunkView.error && (
						<Alert variant="destructive" className="mt-4">
							<AlertDescription>{chunkView.error}</AlertDescription>
						</Alert>
					)}
					{!chunkView.loading && !chunkView.error && (
						<>
							<p className="text-[11px] text-muted-foreground">
								{chunkView.total} chunk{chunkView.total !== 1 ? "s" : ""}
								{chunkView.query ? ` matched for “${chunkView.query}”` : ""}
							</p>
							{chunkView.chunks.map((chunk, i) => (
								<div key={chunk.id} className="rounded-lg border bg-card px-3 py-2.5 space-y-1">
									<p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Chunk {i + 1}</p>
									<p className="text-xs whitespace-pre-wrap leading-relaxed">
										{highlightChunkContent(
											chunk.content,
											chunkView.query,
											chunkCaseInsensitive,
											chunkSmartMatch
										)}
									</p>
								</div>
							))}
							{chunkView.chunks.length === 0 && (
								<p className="text-xs text-muted-foreground text-center py-6">No chunks found for this variant.</p>
							)}
						</>
					)}
				</div>
			</div>
		);
	}

	// ── Variant list rendering ────────────────────────────────────────────────
	return (
		<div className="flex flex-col h-full overflow-hidden">
			{/* Header */}
			<div className="flex items-center justify-between px-4 py-3 border-b shrink-0 gap-2">
				<div className="flex items-center gap-2 min-w-0">
					<FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
					<span className="font-semibold text-sm truncate">{sourceTitle || "Document"}</span>
				</div>
				<div className="flex items-center gap-1.5 shrink-0">
					<Button
						variant="outline"
						size="sm"
						className="h-7 px-2 text-xs"
						onClick={() => setBenchmarkUploadOpen((prev) => !prev)}
						disabled={!sourceDocumentId || benchmarkUploading}
					>
						<FlaskConical className="h-3.5 w-3.5 mr-1" />
						Add Task Benchmark
					</Button>
					{onClose && (
						<Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
							<XIcon className="h-4 w-4" />
						</Button>
					)}
				</div>
			</div>

			<div className="px-4 py-2.5 border-b shrink-0 space-y-2">
				<div className="flex items-center justify-between gap-2">
					<p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Associated Benchmarks</p>
					<Button
						variant="ghost"
						size="sm"
						className="h-6 px-2 text-[10px]"
						onClick={() => void loadBenchmarkDatasets()}
						disabled={benchmarkLoading}
					>
						Refresh
					</Button>
				</div>
				{benchmarkLoading && (
					<div className="flex items-center gap-2 text-xs text-muted-foreground">
						<Spinner className="h-3.5 w-3.5" />
						Loading benchmark datasets...
					</div>
				)}
				{!benchmarkLoading && benchmarkError && (
					<p className="text-xs text-destructive">{benchmarkError}</p>
				)}
				{!benchmarkLoading && !benchmarkError && benchmarkItems.length === 0 && (
					<p className="text-xs text-muted-foreground">No benchmark dataset associated yet.</p>
				)}
				{!benchmarkLoading && !benchmarkError && benchmarkItems.length > 0 && (
					<div className="space-y-1.5 max-h-28 overflow-y-auto pr-1">
						{benchmarkItems.map((item) => (
							<div
								key={item.benchmarkdata_id}
								className="rounded border bg-card px-2 py-1.5 text-[11px] flex items-center justify-between gap-2"
							>
								<div className="min-w-0">
									<p className="truncate font-medium">{item.dataset_filename}</p>
									<p className="text-muted-foreground truncate">
										{item.task_type} · Task {item.task_num}
									</p>
								</div>
								<div className="flex items-center gap-1 shrink-0">
									<span className="text-muted-foreground">
										{new Date(item.created_date).toLocaleDateString()}
									</span>
									<Button
										variant="ghost"
										size="icon"
										className="h-6 w-6"
										onClick={() => void handleBenchmarkDownload(item)}
										disabled={benchmarkDownloadingId === item.benchmarkdata_id}
										title="Download dataset"
									>
										{benchmarkDownloadingId === item.benchmarkdata_id ? (
											<Spinner className="h-3 w-3" />
										) : (
											<Download className="h-3.5 w-3.5" />
										)}
									</Button>
									<Button
										variant="ghost"
										size="icon"
										className="h-6 w-6 text-destructive hover:text-destructive"
										onClick={() => setBenchmarkPendingDelete(item)}
										disabled={benchmarkDeletingId === item.benchmarkdata_id}
										title="Delete dataset"
									>
										{benchmarkDeletingId === item.benchmarkdata_id ? (
											<Spinner className="h-3 w-3" />
										) : (
											<Trash2 className="h-3.5 w-3.5" />
										)}
									</Button>
								</div>
							</div>
						))}
					</div>
				)}

				<AlertDialog
					open={benchmarkPendingDelete !== null}
					onOpenChange={(open) => {
						if (!open) setBenchmarkPendingDelete(null);
					}}
				>
					<AlertDialogContent>
						<AlertDialogHeader>
							<AlertDialogTitle>Delete benchmark dataset?</AlertDialogTitle>
							<AlertDialogDescription>
								This will permanently remove
								 {benchmarkPendingDelete?.dataset_filename || "this dataset"}
								 from this document.
							</AlertDialogDescription>
						</AlertDialogHeader>
						<AlertDialogFooter>
							<AlertDialogCancel disabled={benchmarkDeletingId !== null}>Cancel</AlertDialogCancel>
							<AlertDialogAction
								onClick={(event) => {
									event.preventDefault();
									void confirmBenchmarkDelete();
								}}
								disabled={benchmarkDeletingId !== null}
							>
								{benchmarkDeletingId !== null ? "Deleting..." : "Delete"}
							</AlertDialogAction>
						</AlertDialogFooter>
					</AlertDialogContent>
				</AlertDialog>

				{benchmarkUploadOpen && (
					<div className="rounded-md border bg-card px-2.5 py-2 space-y-2">
						<div className="grid grid-cols-2 gap-2">
							<div className="space-y-1">
								<p className="text-[10px] text-muted-foreground uppercase tracking-wide">Task Type</p>
								<Input
									value={benchmarkTaskType}
									onChange={(e) => setBenchmarkTaskType(e.target.value)}
									className="h-7 text-xs"
									placeholder="qa"
								/>
							</div>
							<div className="space-y-1">
								<p className="text-[10px] text-muted-foreground uppercase tracking-wide">Task Num</p>
								<Input
									type="number"
									min={1}
									value={benchmarkTaskNum}
									onChange={(e) => setBenchmarkTaskNum(e.target.value)}
									className="h-7 text-xs"
								/>
							</div>
						</div>
						<Input
							type="file"
							className="h-8 text-xs"
							onChange={(e) => {
								const nextFile = e.target.files?.[0] ?? null;
								setBenchmarkFile(nextFile);
							}}
						/>
						<div className="flex justify-end gap-2">
							<Button
								variant="ghost"
								size="sm"
								className="h-7 px-2 text-xs"
								onClick={() => setBenchmarkUploadOpen(false)}
								disabled={benchmarkUploading}
							>
								Cancel
							</Button>
							<Button
								size="sm"
								className="h-7 px-2 text-xs"
								onClick={() => void submitBenchmarkUpload()}
								disabled={benchmarkUploading || !benchmarkFile}
							>
								{benchmarkUploading ? "Uploading..." : "Upload & Associate"}
							</Button>
						</div>
					</div>
				)}
			</div>

			{/* Filters */}
			<div className="px-4 py-2.5 border-b shrink-0 space-y-2">
				{allStrategies.length > 0 && (
					<div className="flex flex-wrap items-center gap-1.5">
						<span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide shrink-0 w-16">Strategy</span>
						{allStrategies.map((s) => {
							const active = activeStrategies.has(s);
							const colorBase = getStrategyColor(s);
							return (
								<button
									key={s}
									type="button"
									onClick={() => toggleFilter(activeStrategies, s, setActiveStrategies)}
									className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium transition-opacity cursor-pointer ${colorBase} ${active ? "opacity-100 ring-1 ring-current" : "opacity-50 hover:opacity-80"}`}
								>
									{s}
								</button>
							);
						})}
					</div>
				)}
				{allEmbeddings.length > 0 && (
					<div className="flex flex-wrap items-center gap-1.5">
						<span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide shrink-0 w-16">Embedding</span>
						{allEmbeddings.map((m) => {
							const active = activeEmbeddings.has(m);
							const colorBase = getEmbeddingColor(m);
							return (
								<button
									key={m}
									type="button"
									onClick={() => toggleFilter(activeEmbeddings, m, setActiveEmbeddings)}
									className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium transition-opacity cursor-pointer ${colorBase} ${active ? "opacity-100 ring-1 ring-current" : "opacity-50 hover:opacity-80"}`}
								>
									{m.replace(/^fastembed_/, "")}
								</button>
							);
						})}
					</div>
				)}
				{hasFilters && (
					<button
						type="button"
						onClick={() => { setActiveStrategies(new Set()); setActiveEmbeddings(new Set()); }}
						className="text-[10px] text-muted-foreground hover:text-foreground underline"
					>
						Clear filters
					</button>
				)}
			</div>

			{/* Variant list */}
			<div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
				<p className="text-[11px] text-muted-foreground mb-2">
					{filteredVariants.length} of {variants.length} pipeline variant{variants.length !== 1 ? "s" : ""}
				</p>
				{filteredVariants.map((v) => {
					const info = getPipelineInfo(undefined, v.title);
					const etlLabel = resolveVariantEtlLabel(v);
					return (
						<div
							key={`${v.id}:${v.pipelineId ?? v.title}`}
							className="rounded-lg border bg-card px-3 py-2.5 flex items-center justify-between gap-2"
						>
							<div className="flex flex-wrap gap-1.5 min-w-0 flex-1">
								{/* ID */}
								<span className="inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-mono bg-muted/40 text-muted-foreground shrink-0">
									#{v.id}
								</span>
								{/* Stage 1 — ETL/Parse */}
								<span className="inline-flex items-center gap-1 rounded-full border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-[10px] font-medium text-orange-400">
									<span className="inline-block h-1.5 w-1.5 rounded-full bg-orange-500 shrink-0" />
									{etlLabel}
								</span>
								{/* Stage 2 — Chunking Strategy */}
								{info?.chunkingStrategies.map((s) => (
									<span key={s} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${getStrategyColor(s)}`}>
										<span className="inline-block h-1.5 w-1.5 rounded-full bg-current shrink-0 opacity-80" />
										{s}
									</span>
								))}
								{/* Stage 3 — Chunk Size */}
								{info?.chunkSize !== undefined && (
									<span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
										<span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
										tok{info.chunkSize}
									</span>
								)}
								{/* Stage 4 — Embeddings */}
								{info?.embeddingModels.map((m) => (
									<span key={m} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${getEmbeddingColor(m)}`}>
										<span className="inline-block h-1.5 w-1.5 rounded-full bg-current shrink-0 opacity-80" />
										{m.replace(/^fastembed_/, "")}
									</span>
								))}
							</div>
							<Button
								variant="outline"
								size="sm"
								className="h-6 px-2.5 text-xs shrink-0"
								onClick={() => openChunkView(v)}
							>
								Open
							</Button>
						</div>
					);
				})}
				{filteredVariants.length === 0 && (
					<p className="text-xs text-muted-foreground text-center py-6">No variants match the current filters.</p>
				)}
			</div>
		</div>
	);
}

export function EditorPanelContent({
	kind = "document",
	documentId,
	localFilePath,
	searchSpaceId,
	title,
	onClose,
	pipelineVariants,
}: {
	kind?: "document" | "local_file";
	documentId?: number;
	localFilePath?: string;
	searchSpaceId?: number;
	title: string | null;
	onClose?: () => void;
	pipelineVariants?: PipelineVariant[];
}) {
	const electronAPI = useElectronAPI();
	// Read pipeline variants from the module-level side-channel (bypasses Jotai multi-instance issue).
	// Re-read whenever documentId changes (i.e. a new document is opened).
	const [localPipelineVariants, setLocalPipelineVariants] = useState<PipelineVariant[] | null>(
		() => consumePendingPipelineVariants()
	);
	useEffect(() => {
		setLocalPipelineVariants(consumePendingPipelineVariants());
	}, [documentId]);
	const effectivePipelineVariants = localPipelineVariants ?? pipelineVariants ?? null;
	const [editorDoc, setEditorDoc] = useState<EditorContent | null>(null);
	const [isLoading, setIsLoading] = useState(!(effectivePipelineVariants && effectivePipelineVariants.length > 0));
	const [error, setError] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [downloading, setDownloading] = useState(false);
	const [isEditing, setIsEditing] = useState(false);

	const [editedMarkdown, setEditedMarkdown] = useState<string | null>(null);
	const [localFileContent, setLocalFileContent] = useState("");
	const [hasCopied, setHasCopied] = useState(false);
	const markdownRef = useRef<string>("");
	const copyResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const initialLoadDone = useRef(false);
	const changeCountRef = useRef(0);
	const [displayTitle, setDisplayTitle] = useState(title || "Untitled");
	const isLocalFileMode = kind === "local_file";
	const editorRenderMode: EditorRenderMode = isLocalFileMode ? "source_code" : "rich_markdown";

	const resolveLocalVirtualPath = useCallback(
		async (candidatePath: string): Promise<string> => {
			if (!electronAPI?.getAgentFilesystemMounts) {
				return candidatePath;
			}
			try {
				const mounts = (await electronAPI.getAgentFilesystemMounts(
					searchSpaceId
				)) as AgentFilesystemMount[];
				return normalizeLocalVirtualPathForEditor(candidatePath, mounts);
			} catch {
				return candidatePath;
			}
		},
		[electronAPI, searchSpaceId]
	);

	const isLargeDocument = (editorDoc?.content_size_bytes ?? 0) > LARGE_DOCUMENT_THRESHOLD;

	useEffect(() => {
		const controller = new AbortController();
		// Skip fetching when showing the pipeline list view
		if (effectivePipelineVariants && effectivePipelineVariants.length > 0) {
			setIsLoading(false);
			return;
		}
		setIsLoading(true);
		setError(null);
		setEditorDoc(null);
		setEditedMarkdown(null);
		setLocalFileContent("");
		setHasCopied(false);
		setIsEditing(false);
		initialLoadDone.current = false;
		changeCountRef.current = 0;

		const doFetch = async () => {
			try {
				if (isLocalFileMode) {
					if (!localFilePath) {
						throw new Error("Missing local file path");
					}
					if (!electronAPI?.readAgentLocalFileText) {
						throw new Error("Local file editor is available only in desktop mode.");
					}
					const resolvedLocalPath = await resolveLocalVirtualPath(localFilePath);
					const readResult = await electronAPI.readAgentLocalFileText(
						resolvedLocalPath,
						searchSpaceId
					);
					if (!readResult.ok) {
						throw new Error(readResult.error || "Failed to read local file");
					}
					const inferredTitle = resolvedLocalPath.split("/").pop() || resolvedLocalPath;
					const content: EditorContent = {
						document_id: -1,
						title: inferredTitle,
						document_type: "NOTE",
						source_markdown: readResult.content,
					};
					markdownRef.current = content.source_markdown;
					setLocalFileContent(content.source_markdown);
					setDisplayTitle(title || inferredTitle);
					setEditorDoc(content);
					initialLoadDone.current = true;
					return;
				}
				if (!documentId || !searchSpaceId) {
					throw new Error("Missing document context");
				}
				const token = getBearerToken();
				if (!token) {
					redirectToLogin();
					return;
				}

				const url = new URL(
					`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/search-spaces/${searchSpaceId}/documents/${documentId}/editor-content`
				);
				url.searchParams.set("max_length", String(LARGE_DOCUMENT_THRESHOLD));

				const response = await authenticatedFetch(url.toString(), { method: "GET" });

				if (controller.signal.aborted) return;

				if (!response.ok) {
					const errorData = await response
						.json()
						.catch(() => ({ detail: "Failed to fetch document" }));
					throw new Error(errorData.detail || "Failed to fetch document");
				}

				const data = await response.json();

				if (data.source_markdown === undefined || data.source_markdown === null) {
					setError(
						"This document does not have editable content. Please re-upload to enable editing."
					);
					setIsLoading(false);
					return;
				}

				markdownRef.current = data.source_markdown;
				setDisplayTitle(data.title || title || "Untitled");
				setEditorDoc(data);
				initialLoadDone.current = true;
			} catch (err) {
				if (controller.signal.aborted) return;
				console.error("Error fetching document:", err);
				setError(err instanceof Error ? err.message : "Failed to fetch document");
			} finally {
				if (!controller.signal.aborted) setIsLoading(false);
			}
		};

		doFetch().catch(() => {});
		return () => controller.abort();
	}, [
		documentId,
		electronAPI,
		isLocalFileMode,
		localFilePath,
		resolveLocalVirtualPath,
		searchSpaceId,
		title,
		localPipelineVariants,
	]);

	useEffect(() => {
		return () => {
			if (copyResetTimeoutRef.current) {
				clearTimeout(copyResetTimeoutRef.current);
			}
		};
	}, []);

	const handleMarkdownChange = useCallback((md: string) => {
		markdownRef.current = md;
		if (!initialLoadDone.current) return;
		changeCountRef.current += 1;
		if (changeCountRef.current <= 1) return;
		setEditedMarkdown(md);
	}, []);

	const handleCopy = useCallback(async () => {
		try {
			const textToCopy = markdownRef.current ?? editorDoc?.source_markdown ?? "";
			await navigator.clipboard.writeText(textToCopy);
			setHasCopied(true);
			if (copyResetTimeoutRef.current) {
				clearTimeout(copyResetTimeoutRef.current);
			}
			copyResetTimeoutRef.current = setTimeout(() => {
				setHasCopied(false);
			}, 1400);
		} catch (err) {
			console.error("Error copying content:", err);
		}
	}, [editorDoc?.source_markdown]);

	const handleSave = useCallback(
		async (options?: { silent?: boolean }) => {
			setSaving(true);
			try {
				if (isLocalFileMode) {
					if (!localFilePath) {
						throw new Error("Missing local file path");
					}
					if (!electronAPI?.writeAgentLocalFileText) {
						throw new Error("Local file editor is available only in desktop mode.");
					}
					const resolvedLocalPath = await resolveLocalVirtualPath(localFilePath);
					const contentToSave = markdownRef.current;
					const writeResult = await electronAPI.writeAgentLocalFileText(
						resolvedLocalPath,
						contentToSave,
						searchSpaceId
					);
					if (!writeResult.ok) {
						throw new Error(writeResult.error || "Failed to save local file");
					}
					setEditorDoc((prev) => (prev ? { ...prev, source_markdown: contentToSave } : prev));
					setEditedMarkdown(markdownRef.current === contentToSave ? null : markdownRef.current);
					return true;
				}
				if (!searchSpaceId || !documentId) {
					throw new Error("Missing document context");
				}
				const token = getBearerToken();
				if (!token) {
					toast.error("Please login to save");
					redirectToLogin();
					return;
				}
				const response = await authenticatedFetch(
					`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/search-spaces/${searchSpaceId}/documents/${documentId}/save`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({ source_markdown: markdownRef.current }),
					}
				);

				if (!response.ok) {
					const errorData = await response
						.json()
						.catch(() => ({ detail: "Failed to save document" }));
					throw new Error(errorData.detail || "Failed to save document");
				}

				setEditorDoc((prev) => (prev ? { ...prev, source_markdown: markdownRef.current } : prev));
				setEditedMarkdown(null);
				if (!options?.silent) {
					toast.success("Document saved! Reindexing in background...");
				}
				return true;
			} catch (err) {
				console.error("Error saving document:", err);
				if (!options?.silent) {
					toast.error(err instanceof Error ? err.message : "Failed to save document");
				}
				return false;
			} finally {
				setSaving(false);
			}
		},
		[
			documentId,
			electronAPI,
			isLocalFileMode,
			localFilePath,
			resolveLocalVirtualPath,
			searchSpaceId,
		]
	);

	const isEditableType = editorDoc
		? (editorRenderMode === "source_code" ||
				EDITABLE_DOCUMENT_TYPES.has(editorDoc.document_type ?? "")) &&
			!isLargeDocument
		: false;
	// Render through PlateEditor for editable doc types (FILE/NOTE).
	// Everything else (large docs, non-editable types) falls back to the
	// lightweight `MarkdownViewer` — Plate is heavy on multi-MB docs and
	// non-editable types don't benefit from its editing UX.
	const renderInPlateEditor = isEditableType;
	const hasUnsavedChanges = editedMarkdown !== null;
	const showDesktopHeader = !!onClose;
	const showEditingActions = isEditableType && isEditing;
	const localFileLanguage = inferMonacoLanguageFromPath(localFilePath);
	const pipelineInfo = getPipelineInfo(
		editorDoc?.document_metadata,
		editorDoc?.title ?? title ?? undefined
	);

	const handleCancelEditing = useCallback(() => {
		const savedContent = editorDoc?.source_markdown ?? "";
		markdownRef.current = savedContent;
		setLocalFileContent(savedContent);
		setEditedMarkdown(null);
		changeCountRef.current = 0;
		setIsEditing(false);
	}, [editorDoc?.source_markdown]);

	const handleDownloadMarkdown = useCallback(async () => {
		if (!searchSpaceId || !documentId) return;
		setDownloading(true);
		try {
			const response = await authenticatedFetch(
				`${process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL}/api/v1/search-spaces/${searchSpaceId}/documents/${documentId}/download-markdown`,
				{ method: "GET" }
			);
			if (!response.ok) throw new Error("Download failed");
			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			const disposition = response.headers.get("content-disposition");
			const match = disposition?.match(/filename="(.+)"/);
			a.download = match?.[1] ?? `${editorDoc?.title || "document"}.md`;
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
			toast.success("Download started");
		} catch {
			toast.error("Failed to download document");
		} finally {
			setDownloading(false);
		}
	}, [documentId, editorDoc?.title, searchSpaceId]);

	const largeDocAlert = isLargeDocument && !isLocalFileMode && editorDoc && (
		<Alert className="mb-4">
			<FileText className="size-4" />
			<AlertDescription className="flex items-center justify-between gap-4">
				<span>
					This document is too large for the editor (
					{Math.round((editorDoc.content_size_bytes ?? 0) / 1024 / 1024)}MB,{" "}
					{editorDoc.chunk_count ?? 0} chunks). Showing a preview below.
				</span>
				<Button
					variant="outline"
					size="sm"
					className="relative shrink-0"
					disabled={downloading}
					onClick={handleDownloadMarkdown}
				>
					<span className={`flex items-center gap-1.5 ${downloading ? "opacity-0" : ""}`}>
						<Download className="size-3.5" />
						Download .md
					</span>
					{downloading && <Spinner size="sm" className="absolute" />}
				</Button>
			</AlertDescription>
		</Alert>
	);

	if (effectivePipelineVariants && effectivePipelineVariants.length > 0) {
		return (
			<PipelineListView
				variants={effectivePipelineVariants}
				searchSpaceId={searchSpaceId}
				sourceTitle={title}
				onClose={onClose}
			/>
		);
	}

	return (
		<>
			{showDesktopHeader ? (
				<div className="shrink-0 border-b">
					<div className="flex h-14 items-center justify-between px-4">
						<h2 className="text-lg font-medium text-muted-foreground select-none">File</h2>
						<div className="flex items-center gap-1 shrink-0">
							<Button variant="ghost" size="icon" onClick={onClose} className="size-7 shrink-0">
								<XIcon className="size-4" />
								<span className="sr-only">Close editor panel</span>
							</Button>
						</div>
					</div>
					<div className="flex h-10 items-center justify-between gap-2 border-t px-4">
						<div className="min-w-0 flex flex-1 items-center gap-2">
							<p className="truncate text-sm text-muted-foreground">{displayTitle}</p>
						</div>
						<div className="flex items-center gap-1 shrink-0">
							{showEditingActions ? (
								<>
									<Button
										variant="ghost"
										size="sm"
										className="h-6 px-2 text-xs"
										onClick={handleCancelEditing}
										disabled={saving}
									>
										Cancel
									</Button>
									<Button
										variant="secondary"
										size="sm"
										className="relative h-6 w-[56px] px-0 text-xs"
										onClick={async () => {
											const saveSucceeded = await handleSave({ silent: true });
											if (saveSucceeded) setIsEditing(false);
										}}
										disabled={saving || !hasUnsavedChanges}
									>
										<span className={saving ? "opacity-0" : ""}>Save</span>
										{saving && <Spinner size="xs" className="absolute" />}
									</Button>
								</>
							) : (
								<>
									{!isLocalFileMode && editorDoc?.document_type && documentId && (
										<VersionHistoryButton
											documentId={documentId}
											documentType={editorDoc.document_type}
										/>
									)}
									<Button
										variant="ghost"
										size="icon"
										className="size-6"
										onClick={() => {
											void handleCopy();
										}}
										disabled={isLoading || !editorDoc}
									>
										{hasCopied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
										<span className="sr-only">
											{hasCopied ? "Copied file contents" : "Copy file contents"}
										</span>
									</Button>
									{isEditableType && (
										<Button
											variant="ghost"
											size="icon"
											className="size-6"
											onClick={() => {
												changeCountRef.current = 0;
												setEditedMarkdown(null);
												setIsEditing(true);
											}}
										>
											<Pencil className="size-3.5" />
											<span className="sr-only">Edit document</span>
										</Button>
									)}
								</>
							)}
						</div>
					</div>
					<PipelineDetailsBar docId={documentId} pipeline={pipelineInfo} />
				</div>
			) : (
				<div className="flex h-14 items-center justify-between border-b px-4 shrink-0">
					<div className="flex flex-1 min-w-0 items-center gap-2">
						<h2 className="text-sm font-semibold truncate">{displayTitle}</h2>
					</div>
					<div className="flex items-center gap-1 shrink-0">
						{showEditingActions ? (
							<>
								<Button
									variant="ghost"
									size="sm"
									className="h-6 px-2 text-xs"
									onClick={handleCancelEditing}
									disabled={saving}
								>
									Cancel
								</Button>
								<Button
									variant="secondary"
									size="sm"
									className="relative h-6 w-[56px] px-0 text-xs"
									onClick={async () => {
										const saveSucceeded = await handleSave({ silent: true });
										if (saveSucceeded) setIsEditing(false);
									}}
									disabled={saving || !hasUnsavedChanges}
								>
									<span className={saving ? "opacity-0" : ""}>Save</span>
									{saving && <Spinner size="xs" className="absolute" />}
								</Button>
							</>
						) : (
							<>
								{!isLocalFileMode && editorDoc?.document_type && documentId && (
									<VersionHistoryButton
										documentId={documentId}
										documentType={editorDoc.document_type}
									/>
								)}
								<Button
									variant="ghost"
									size="icon"
									className="size-6"
									onClick={() => {
										void handleCopy();
									}}
									disabled={isLoading || !editorDoc}
								>
									{hasCopied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
									<span className="sr-only">
										{hasCopied ? "Copied file contents" : "Copy file contents"}
									</span>
								</Button>
								{isEditableType && (
									<Button
										variant="ghost"
										size="icon"
										className="size-6"
										onClick={() => {
											changeCountRef.current = 0;
											setEditedMarkdown(null);
											setIsEditing(true);
										}}
									>
										<Pencil className="size-3.5" />
										<span className="sr-only">Edit document</span>
									</Button>
								)}
							</>
						)}
					</div>
				</div>
			)}

			<div className="flex-1 overflow-hidden">
				{isLoading ? (
					<EditorPanelSkeleton />
				) : error || !editorDoc ? (
					<div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
						{error?.toLowerCase().includes("still being processed") ? (
							<div className="rounded-full bg-muted/50 p-3">
								<RefreshCw className="size-6 text-muted-foreground animate-spin" />
							</div>
						) : (
							<div className="rounded-full bg-muted/50 p-3">
								<FileQuestionMark className="size-6 text-muted-foreground" />
							</div>
						)}
						<div className="space-y-1 max-w-xs">
							<p className="font-medium text-foreground">
								{error?.toLowerCase().includes("still being processed")
									? "Document is processing"
									: "Document unavailable"}
							</p>
							<p className="text-sm text-muted-foreground">
								{error || "An unknown error occurred"}
							</p>
						</div>
					</div>
				) : editorRenderMode === "source_code" ? (
					<div className="h-full overflow-hidden">
						<SourceCodeEditor
							path={localFilePath ?? "local-file.txt"}
							language={localFileLanguage}
							value={localFileContent}
							onSave={() => {
								void handleSave({ silent: true });
							}}
							readOnly={!isEditing}
							onChange={(next) => {
								markdownRef.current = next;
								setLocalFileContent(next);
								if (!initialLoadDone.current) return;
								setEditedMarkdown(next === (editorDoc?.source_markdown ?? "") ? null : next);
							}}
						/>
					</div>
				) : isLargeDocument && !isLocalFileMode ? (
					// Large doc — fast Streamdown preview + download CTA.
					// Plate is heavy on multi-MB docs.
					<div className="h-full overflow-y-auto px-5 py-4">
						{largeDocAlert}
						<MarkdownViewer content={editorDoc.source_markdown} enableCitations />
					</div>
				) : renderInPlateEditor ? (
					// Editable doc (FILE/NOTE) — Plate editing UX.
					<div className="flex h-full min-h-0 flex-col">
						<div className="flex-1 min-h-0 overflow-hidden">
							<PlateEditor
								key={`${isLocalFileMode ? (localFilePath ?? "local-file") : documentId}-${isEditing ? "editing" : "viewing"}`}
								preset="full"
								markdown={editorDoc.source_markdown}
								onMarkdownChange={handleMarkdownChange}
								readOnly={!isEditing}
								placeholder="Start writing..."
								editorVariant="default"
								allowModeToggle={false}
								reserveToolbarSpace
								defaultEditing={isEditing}
								className="**:[[role=toolbar]]:bg-sidebar!"
								// Render `[citation:N]` badges in view mode only.
								// Edit mode keeps raw text so the user can edit/delete
								// tokens directly. `local_file` never reaches this branch
								// (handled by the source_code editor above).
								enableCitations={!isEditing && !isLocalFileMode}
							/>
						</div>
					</div>
				) : (
					<div className="h-full overflow-y-auto px-5 py-4">
						<MarkdownViewer content={editorDoc.source_markdown} enableCitations />
					</div>
				)}
			</div>
		</>
	);
}

function DesktopEditorPanel() {
	const panelState = useAtomValue(editorPanelAtom);
	const closePanel = useSetAtom(closeEditorPanelAtom);

	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") closePanel();
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [closePanel]);

	const hasTarget =
		panelState.kind === "document"
			? !!panelState.documentId && !!panelState.searchSpaceId
			: !!panelState.localFilePath;
	if (!panelState.isOpen || !hasTarget) return null;

	return (
		<div className="flex w-[50%] max-w-[700px] min-w-[380px] flex-col border-l bg-sidebar text-sidebar-foreground animate-in slide-in-from-right-4 duration-300 ease-out">
			<EditorPanelContent
				kind={panelState.kind}
				documentId={panelState.documentId ?? undefined}
				localFilePath={panelState.localFilePath ?? undefined}
				searchSpaceId={panelState.searchSpaceId ?? undefined}
				title={panelState.title}
				onClose={closePanel}
				pipelineVariants={panelState.pipelineVariants ?? undefined}
			/>
		</div>
	);
}

function MobileEditorDrawer() {
	const panelState = useAtomValue(editorPanelAtom);
	const closePanel = useSetAtom(closeEditorPanelAtom);

	if (panelState.kind === "local_file") return null;

	const hasTarget =
		panelState.kind === "document"
			? !!panelState.documentId && !!panelState.searchSpaceId
			: !!panelState.localFilePath;
	if (!hasTarget) return null;

	return (
		<Drawer
			open={panelState.isOpen}
			onOpenChange={(open) => {
				if (!open) closePanel();
			}}
			shouldScaleBackground={false}
		>
			<DrawerContent
				className="h-[90vh] max-h-[90vh] z-80 bg-sidebar overflow-hidden"
				overlayClassName="z-80"
			>
				<DrawerHandle />
				<DrawerTitle className="sr-only">{panelState.title || "Editor"}</DrawerTitle>
				<div className="min-h-0 flex-1 flex flex-col overflow-hidden">
					<EditorPanelContent
						kind={panelState.kind}
						documentId={panelState.documentId ?? undefined}
						localFilePath={panelState.localFilePath ?? undefined}
						searchSpaceId={panelState.searchSpaceId ?? undefined}
						title={panelState.title}
						pipelineVariants={panelState.pipelineVariants ?? undefined}
					/>
				</div>
			</DrawerContent>
		</Drawer>
	);
}

export function EditorPanel() {
	const panelState = useAtomValue(editorPanelAtom);
	const isDesktop = useMediaQuery("(min-width: 1024px)");
	const hasTarget =
		panelState.kind === "document"
			? !!panelState.documentId && !!panelState.searchSpaceId
			: !!panelState.localFilePath;

	if (!panelState.isOpen || !hasTarget) return null;
	if (!isDesktop && panelState.kind === "local_file") return null;

	if (isDesktop) {
		return <DesktopEditorPanel />;
	}

	return <MobileEditorDrawer />;
}

export function MobileEditorPanel() {
	const panelState = useAtomValue(editorPanelAtom);
	const isDesktop = useMediaQuery("(min-width: 1024px)");
	const hasTarget =
		panelState.kind === "document"
			? !!panelState.documentId && !!panelState.searchSpaceId
			: !!panelState.localFilePath;

	if (isDesktop || !panelState.isOpen || !hasTarget || panelState.kind === "local_file")
		return null;

	return <MobileEditorDrawer />;
}
