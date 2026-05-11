"use client";

import { useAtom } from "jotai";
import {
	ChevronDown,
	Crown,
	Dot,
	File as FileIcon,
	FolderOpen,
	Upload,
	X,
	Zap,
} from "lucide-react";

import { useTranslations } from "next-intl";
import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { uploadDocumentMutationAtom } from "@/atoms/documents/document-mutation.atoms";
import { EmbeddingModelSelector } from "@/components/sources/EmbeddingModelSelector";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import type { ChunkingStrategy, ProcessingMode } from "@/contracts/types/document.types";
import { useElectronAPI } from "@/hooks/use-platform";
import { documentsApiService } from "@/lib/apis/documents-api.service";
import { getBearerToken } from "@/lib/auth-utils";
import { BACKEND_URL, ETL_SERVICE } from "@/lib/env-config";
import {
	trackDocumentUploadFailure,
	trackDocumentUploadStarted,
	trackDocumentUploadSuccess,
} from "@/lib/posthog/events";
import {
	getAcceptedFileTypes,
	getSupportedExtensions,
	getSupportedExtensionsSet,
} from "@/lib/supported-extensions";

type EtlServiceOption = "DOCLING" | "MINERU" | "UNSTRUCTURED" | "LLAMACLOUD";
type UploadedPipelineJob = {
	document_id: number;
	pipeline_id: string;
	job_name: string;
	etl_service?: string;
	chunking_strategy?: string | null;
	chunk_size?: number | null;
	embedding_models?: string[];
};

interface DocumentUploadTabProps {
	searchSpaceId: string;
	onSuccess?: () => void;
	onAccordionStateChange?: (isExpanded: boolean) => void;
}

interface FileWithId {
	id: string;
	file: File;
}

interface FolderEntry {
	id: string;
	file: File;
	relativePath: string;
}

interface FolderUploadData {
	folderName: string;
	entries: FolderEntry[];
}

interface FolderTreeNode {
	name: string;
	isFolder: boolean;
	size?: number;
	children: FolderTreeNode[];
}

function buildFolderTree(entries: FolderEntry[]): FolderTreeNode[] {
	const root: FolderTreeNode = { name: "", isFolder: true, children: [] };

	for (const entry of entries) {
		const parts = entry.relativePath.split("/");
		let current = root;

		for (let i = 0; i < parts.length - 1; i++) {
			let child = current.children.find((c) => c.name === parts[i] && c.isFolder);
			if (!child) {
				child = { name: parts[i], isFolder: true, children: [] };
				current.children.push(child);
			}
			current = child;
		}

		current.children.push({
			name: parts[parts.length - 1],
			isFolder: false,
			size: entry.file.size,
			children: [],
		});
	}

	function sortNodes(node: FolderTreeNode) {
		node.children.sort((a, b) => {
			if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
			return a.name.localeCompare(b.name);
		});
		for (const child of node.children) sortNodes(child);
	}
	sortNodes(root);

	return root.children;
}

function flattenTree(
	nodes: FolderTreeNode[],
	depth = 0
): { name: string; isFolder: boolean; depth: number; size?: number }[] {
	const items: { name: string; isFolder: boolean; depth: number; size?: number }[] = [];
	for (const node of nodes) {
		items.push({ name: node.name, isFolder: node.isFolder, depth, size: node.size });
		if (node.isFolder && node.children.length > 0) {
			items.push(...flattenTree(node.children, depth + 1));
		}
	}
	return items;
}

const FOLDER_BATCH_SIZE_BYTES = 20 * 1024 * 1024;
const FOLDER_BATCH_MAX_FILES = 10;

const MAX_FILE_SIZE_MB = 500;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const toggleRowClass =
	"flex items-center justify-between rounded-lg bg-slate-400/5 dark:bg-white/5 p-3";

const CHUNK_STRATEGY_OPTIONS: ChunkingStrategy[] = [
	"chunk_text",
	"sandwitch_chunk",
	"chunk_hybrid",
	"chunk_recursive",
];
const CHUNK_SIZE_OPTIONS = [256, 512, 1024, 2048];

export function DocumentUploadTab({
	searchSpaceId,
	onSuccess,
	onAccordionStateChange,
}: DocumentUploadTabProps) {
	const t = useTranslations("upload_documents");
	const [files, setFiles] = useState<FileWithId[]>([]);
	const [uploadProgress, setUploadProgress] = useState(0);
	const [accordionValue, setAccordionValue] = useState<string>("");
	const [shouldSummarize, setShouldSummarize] = useState(false);
	const [useVisionLlm, setUseVisionLlm] = useState(false);
	const [processingMode, setProcessingMode] = useState<ProcessingMode>("basic");
	const [chunkingStrategy, setChunkingStrategy] = useState<ChunkingStrategy>("chunk_text");
	const [selectedEtlServices, setSelectedEtlServices] = useState<EtlServiceOption[]>(() => {
		const normalized = ETL_SERVICE.toUpperCase();
		if (
			normalized === "DOCLING" ||
			normalized === "MINERU" ||
			normalized === "UNSTRUCTURED" ||
			normalized === "LLAMACLOUD"
		) {
			return [normalized];
		}
		return ["DOCLING"];
	});
	const [generateVariants, setGenerateVariants] = useState(false);
	const [selectedChunkingStrategies, setSelectedChunkingStrategies] = useState<ChunkingStrategy[]>([
		"chunk_text",
		"sandwitch_chunk",
	]);
	const [selectedChunkSizes, setSelectedChunkSizes] = useState<number[]>([256, 1024]);
	const [selectedEmbeddingModels, setSelectedEmbeddingModels] = useState<string[]>([
		"fastembed/bge-base-en-v1.5", // Default to free local model
	]);
	const [uploadDocumentMutation] = useAtom(uploadDocumentMutationAtom);
	const { mutate: uploadDocuments, isPending: isUploading } = uploadDocumentMutation;
	const fileInputRef = useRef<HTMLInputElement>(null);
	const folderInputRef = useRef<HTMLInputElement>(null);
	const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const [folderUpload, setFolderUpload] = useState<FolderUploadData | null>(null);
	const [isFolderUploading, setIsFolderUploading] = useState(false);
	const [indexingProgress, setIndexingProgress] = useState(0);
	const [indexingStatusMessage, setIndexingStatusMessage] = useState("");
	const [indexingEtaSeconds, setIndexingEtaSeconds] = useState<number | null>(null);
	const [isIndexing, setIsIndexing] = useState(false);
	const [variantStatuses, setVariantStatuses] = useState<
		Array<{ id: string | number; title: string; state: string; reason?: string }>
	>([]);

	useEffect(() => {
		return () => {
			if (progressIntervalRef.current) {
				clearInterval(progressIntervalRef.current);
			}
			if (pollTimeoutRef.current) {
				clearTimeout(pollTimeoutRef.current);
			}
		};
	}, []);

	const electronAPI = useElectronAPI();
	const isElectron = !!electronAPI?.browseFiles;

	const acceptedFileTypes = useMemo(() => getAcceptedFileTypes(), []);
	const supportedExtensions = useMemo(
		() => getSupportedExtensions(acceptedFileTypes),
		[acceptedFileTypes]
	);
	const supportedExtensionsSet = useMemo(
		() => getSupportedExtensionsSet(acceptedFileTypes),
		[acceptedFileTypes]
	);

	const addFiles = useCallback(
		(incoming: File[]) => {
			const oversized = incoming.filter((f) => f.size > MAX_FILE_SIZE_BYTES);
			if (oversized.length > 0) {
				toast.error(t("file_too_large"), {
					description: t("file_too_large_desc", {
						name: oversized[0].name,
						maxMB: MAX_FILE_SIZE_MB,
					}),
				});
			}
			const valid = incoming.filter((f) => f.size <= MAX_FILE_SIZE_BYTES);
			if (valid.length === 0) return;

			setFolderUpload(null);
			setFiles((prev) => {
				const newEntries = valid.map((f) => ({
					id: crypto.randomUUID?.() ?? `file-${Date.now()}-${Math.random().toString(36)}`,
					file: f,
				}));
				return [...prev, ...newEntries];
			});
		},
		[t]
	);

	const onDrop = useCallback(
		(acceptedFiles: File[]) => {
			addFiles(acceptedFiles);
		},
		[addFiles]
	);

	const { getRootProps, getInputProps, isDragActive } = useDropzone({
		onDrop,
		accept: acceptedFileTypes,
		maxSize: MAX_FILE_SIZE_BYTES,
		noClick: isElectron,
	});

	const handleFileInputClick = useCallback((e: React.MouseEvent<HTMLInputElement>) => {
		e.stopPropagation();
	}, []);

	const handleBrowseFiles = useCallback(async () => {
		if (!electronAPI?.browseFiles) return;

		const paths = await electronAPI.browseFiles();
		if (!paths || paths.length === 0) return;

		const fileDataList = await electronAPI.readLocalFiles(paths);
		const filtered = fileDataList.filter(
			(fd: { name: string; data: ArrayBuffer; mimeType: string }) => {
				const ext = fd.name.includes(".") ? `.${fd.name.split(".").pop()?.toLowerCase()}` : "";
				return ext !== "" && supportedExtensionsSet.has(ext);
			}
		);

		if (filtered.length === 0) {
			toast.error(t("no_supported_files_in_folder"));
			return;
		}

		const newFiles: FileWithId[] = filtered.map(
			(fd: { name: string; data: ArrayBuffer; mimeType: string }) => ({
				id: crypto.randomUUID?.() ?? `file-${Date.now()}-${Math.random().toString(36)}`,
				file: new File([fd.data], fd.name, { type: fd.mimeType }),
			})
		);
		setFolderUpload(null);
		setFiles((prev) => [...prev, ...newFiles]);
	}, [electronAPI, supportedExtensionsSet, t]);

	const handleFolderChange = useCallback(
		(e: ChangeEvent<HTMLInputElement>) => {
			const fileList = e.target.files;
			if (!fileList || fileList.length === 0) return;

			const allFiles = Array.from(fileList);
			const firstPath = allFiles[0]?.webkitRelativePath || "";
			const folderName = firstPath.split("/")[0];

			if (!folderName) {
				addFiles(allFiles);
				e.target.value = "";
				return;
			}

			const entries: FolderEntry[] = allFiles
				.filter((f) => {
					const ext = f.name.includes(".") ? `.${f.name.split(".").pop()?.toLowerCase()}` : "";
					return ext !== "" && supportedExtensionsSet.has(ext);
				})
				.map((f) => ({
					id: crypto.randomUUID?.() ?? `file-${Date.now()}-${Math.random().toString(36)}`,
					file: f,
					relativePath: f.webkitRelativePath.substring(folderName.length + 1),
				}));

			if (entries.length === 0) {
				toast.error(t("no_supported_files_in_folder"));
				e.target.value = "";
				return;
			}

			setFiles([]);
			setFolderUpload({ folderName, entries });
			e.target.value = "";
		},
		[addFiles, supportedExtensionsSet, t]
	);

	const formatFileSize = (bytes: number) => {
		if (bytes === 0) return "0 Bytes";
		const k = 1024;
		const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
		const i = Math.floor(Math.log(bytes) / Math.log(k));
		return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
	};

	const totalFileSize = folderUpload
		? folderUpload.entries.reduce((total, entry) => total + entry.file.size, 0)
		: files.reduce((total, entry) => total + entry.file.size, 0);

	const fileCount = folderUpload ? folderUpload.entries.length : files.length;
	const hasContent = files.length > 0 || folderUpload !== null;
	const isAnyUploading = isUploading || isFolderUploading;

	const toggleChunkStrategySelection = useCallback((strategy: ChunkingStrategy) => {
		setSelectedChunkingStrategies((prev) => {
			if (prev.includes(strategy)) {
				if (prev.length === 1) return prev;
				return prev.filter((item) => item !== strategy);
			}
			return [...prev, strategy];
		});
	}, []);

	const toggleChunkSizeSelection = useCallback((size: number) => {
		setSelectedChunkSizes((prev) => {
			if (prev.includes(size)) {
				if (prev.length === 1) return prev;
				return prev.filter((item) => item !== size);
			}
			return [...prev, size].sort((a, b) => a - b);
		});
	}, []);

	const toggleEtlServiceSelection = useCallback((etlService: EtlServiceOption) => {
		setSelectedEtlServices((prev) => {
			if (prev.includes(etlService)) {
				if (prev.length === 1) return prev;
				return prev.filter((item) => item !== etlService);
			}
			return [...prev, etlService];
		});
	}, []);

	const trackIndexingProgress = useCallback(
		(documentIds: number[], pipelineJobs?: UploadedPipelineJob[]) => {
			const normalizedJobs = (pipelineJobs ?? []).filter((job) => !!job?.pipeline_id);

			if ((!documentIds || documentIds.length === 0) && normalizedJobs.length === 0) {
				onSuccess?.();
				return;
			}

			const jobNames = normalizedJobs.map((job) => job.job_name).filter(Boolean);
			const totalVariantCount = normalizedJobs.length > 0 ? normalizedJobs.length : documentIds.length;

			setIsIndexing(true);
			setIndexingProgress(0);
			if (normalizedJobs.length > 0) {
				setVariantStatuses(
					normalizedJobs.map((job) => ({
						id: job.pipeline_id,
						title: job.job_name,
						state: "pending",
					}))
				);
			} else {
				setVariantStatuses([]);
			}
			setIndexingStatusMessage(`Queued ${totalVariantCount} document variant(s) for indexing...`);
			setIndexingEtaSeconds(null);

			const startedAt = Date.now();

			const pollByNotifications = async () => {
				const token = getBearerToken() ?? "";
				const controller = new AbortController();
				const abortTimer = setTimeout(() => controller.abort(), 15000);
				try {
					const res = await fetch(
						`${BACKEND_URL}/api/v1/notifications?search_space_id=${searchSpaceId}&category=status&limit=100&t=${Date.now()}`,
						{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
					);
					clearTimeout(abortTimer);

					if (!res.ok) {
						pollTimeoutRef.current = setTimeout(poll, 1500);
						return;
					}

					const payload = (await res.json()) as {
						items?: Array<{
							type?: string;
							title?: string;
							message?: string;
							metadata?: Record<string, unknown>;
						}>;
					};

					const statusByName = new Map<
						string,
						{ state: "pending" | "processing" | "ready" | "failed"; reason?: string }
					>();

					for (const item of payload.items ?? []) {
						if (item.type !== "document_processing") continue;
						const metadata = item.metadata ?? {};
						const documentName = typeof metadata.document_name === "string" ? metadata.document_name : undefined;
						if (!documentName || !jobNames.includes(documentName)) continue;
						if (statusByName.has(documentName)) continue;
						const rawStatus = typeof metadata.status === "string" ? metadata.status : "in_progress";
						const state =
							rawStatus === "completed"
								? "ready"
								: rawStatus === "failed"
									? "failed"
									: "processing";
						const reason =
							typeof metadata.error_message === "string"
								? metadata.error_message
								: state === "failed"
									? (item.message ?? "Processing failed")
									: undefined;
						statusByName.set(documentName, { state, reason });
					}

					let mappedStatuses = normalizedJobs.map((job) => {
						const current = statusByName.get(job.job_name);
						return {
							id: job.pipeline_id,
							title: job.job_name,
							state: current?.state ?? "pending",
							reason: current?.reason,
						};
					});

					const unresolved = mappedStatuses.filter((item) => item.state === "pending").length;
					if (unresolved > 0) {
						const uniqueDocumentIds = Array.from(
							new Set(normalizedJobs.map((job) => job.document_id))
						);
						if (uniqueDocumentIds.length > 0) {
							const statusRes = await fetch(
								`${BACKEND_URL}/api/v1/documents/status?search_space_id=${searchSpaceId}&document_ids=${uniqueDocumentIds.join(",")}&t=${Date.now()}`,
								{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
							);
							if (statusRes.ok) {
								const statusPayload = (await statusRes.json()) as {
									items?: Array<{ id: number; status: { state: string; reason?: string } }>;
								};
								const byDocId = new Map(
									(statusPayload.items ?? []).map((item) => [item.id, item.status])
								);
								mappedStatuses = mappedStatuses.map((item, idx) => {
									if (item.state !== "pending") return item;
									const job = normalizedJobs[idx];
									const docStatus = byDocId.get(job.document_id);
									if (!docStatus) return item;
									if (docStatus.state === "ready") {
										return { ...item, state: "ready", reason: undefined };
									}
									if (docStatus.state === "failed") {
										return {
											...item,
											state: "failed",
											reason: docStatus.reason,
										};
									}
									if (docStatus.state === "processing") {
										return { ...item, state: "processing" };
									}
									return item;
								});
							}
						}
					}

					setVariantStatuses(mappedStatuses);

					const total = mappedStatuses.length;
					const ready = mappedStatuses.filter((item) => item.state === "ready").length;
					const failed = mappedStatuses.filter((item) => item.state === "failed").length;
					const done = ready + failed;
					const percent = total > 0 ? Math.round((done / total) * 100) : 0;
					setIndexingProgress(percent);

					const elapsedSec = Math.max((Date.now() - startedAt) / 1000, 1);
					if (done > 0 && done < total) {
						const rate = done / elapsedSec;
						const eta = Math.max(0, Math.round((total - done) / Math.max(rate, 0.001)));
						setIndexingEtaSeconds(eta);
					} else {
						setIndexingEtaSeconds(0);
					}

					setIndexingStatusMessage(
						`Indexing: ${done}/${total} complete (${ready} ready, ${failed} failed)`
					);

					if (done >= total) {
						setIsIndexing(false);
						if (failed > 0) {
							toast.warning(`Indexing finished with ${failed} failed variant(s).`);
						} else {
							toast.success("All document variants indexed successfully.");
						}
						onSuccess?.();
						return;
					}

					pollTimeoutRef.current = setTimeout(pollByNotifications, 2000);
				} catch {
					clearTimeout(abortTimer);
					pollTimeoutRef.current = setTimeout(poll, 1500);
				}
			};

			const poll = async () => {
				const token = getBearerToken() ?? "";
				const controller = new AbortController();
				const abortTimer = setTimeout(() => controller.abort(), 15000);
				try {
					const res = await fetch(
						`${BACKEND_URL}/api/v1/documents/status?search_space_id=${searchSpaceId}&document_ids=${documentIds.join(",")}&t=${Date.now()}`,
						{ headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }
					);
					clearTimeout(abortTimer);

					if (!res.ok) {
						// Non-OK response — reschedule, never freeze
						pollTimeoutRef.current = setTimeout(poll, 3000);
						return;
					}
					const status: { items: Array<{ id: number; title: string; status: { state: string; reason?: string } }> } =
						await res.json();

					const items = status.items ?? [];
					setVariantStatuses(
						items.map((item) => ({
							id: item.id,
							title: item.title,
							state: item.status.state,
							reason: item.status.reason,
						}))
					);

					const total = items.length;
					const ready = items.filter((item) => item.status.state === "ready").length;
					const failed = items.filter((item) => item.status.state === "failed").length;
					const done = ready + failed;
					const percent = total > 0 ? Math.round((done / total) * 100) : 0;
					setIndexingProgress(percent);

					const elapsedSec = Math.max((Date.now() - startedAt) / 1000, 1);
					if (done > 0 && done < total) {
						const rate = done / elapsedSec;
						const eta = Math.max(0, Math.round((total - done) / Math.max(rate, 0.001)));
						setIndexingEtaSeconds(eta);
					} else {
						setIndexingEtaSeconds(0);
					}

					setIndexingStatusMessage(
						`Indexing: ${done}/${total} complete (${ready} ready, ${failed} failed)`
					);

					if (done >= total) {
						setIsIndexing(false);
						if (failed > 0) {
							toast.warning(`Indexing finished with ${failed} failed variant(s).`);
						} else {
							toast.success("All document variants indexed successfully.");
						}
						onSuccess?.();
						return;
					}

					pollTimeoutRef.current = setTimeout(poll, 2000);
				} catch (error) {
					clearTimeout(abortTimer);
					// Always reschedule — never let one error freeze the poll loop
					pollTimeoutRef.current = setTimeout(poll, 3000);
				}
			};

			if (normalizedJobs.length > 0) {
				void pollByNotifications();
				return;
			}

			void poll();
		},
		[onSuccess, searchSpaceId, setIndexingEtaSeconds]
	);

	const folderTreeItems = useMemo(() => {
		if (!folderUpload) return [];
		return flattenTree(buildFolderTree(folderUpload.entries));
	}, [folderUpload]);

	const handleAccordionChange = useCallback(
		(value: string) => {
			setAccordionValue(value);
			onAccordionStateChange?.(value === "supported-file-types");
		},
		[onAccordionStateChange]
	);

	const handleFolderUpload = async () => {
		if (!folderUpload) return;

		setUploadProgress(0);
		setIsFolderUploading(true);
		const total = folderUpload.entries.length;
		trackDocumentUploadStarted(Number(searchSpaceId), total, totalFileSize);

		try {
			const batches: FolderEntry[][] = [];
			let currentBatch: FolderEntry[] = [];
			let currentSize = 0;

			for (const entry of folderUpload.entries) {
				const size = entry.file.size;

				if (size >= FOLDER_BATCH_SIZE_BYTES) {
					if (currentBatch.length > 0) {
						batches.push(currentBatch);
						currentBatch = [];
						currentSize = 0;
					}
					batches.push([entry]);
					continue;
				}

				if (
					currentBatch.length >= FOLDER_BATCH_MAX_FILES ||
					currentSize + size > FOLDER_BATCH_SIZE_BYTES
				) {
					batches.push(currentBatch);
					currentBatch = [];
					currentSize = 0;
				}

				currentBatch.push(entry);
				currentSize += size;
			}

			if (currentBatch.length > 0) {
				batches.push(currentBatch);
			}

			let rootFolderId: number | null = null;
			let uploaded = 0;

			for (const batch of batches) {
				const result = await documentsApiService.folderUploadFiles(
					batch.map((e) => e.file),
					{
						folder_name: folderUpload.folderName,
						search_space_id: Number(searchSpaceId),
						relative_paths: batch.map((e) => e.relativePath),
						root_folder_id: rootFolderId,
						enable_summary: shouldSummarize,
						use_vision_llm: useVisionLlm,
						processing_mode: processingMode,
						embedding_models: selectedEmbeddingModels,
						chunking_strategy: chunkingStrategy,
					}
				);

				if (result.root_folder_id && !rootFolderId) {
					rootFolderId = result.root_folder_id;
				}

				uploaded += batch.length;
				setUploadProgress(Math.round((uploaded / total) * 100));
			}

			trackDocumentUploadSuccess(Number(searchSpaceId), total);
			toast(t("upload_initiated"), { description: t("upload_initiated_desc") });
			setFolderUpload(null);
			onSuccess?.();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Upload failed";
			trackDocumentUploadFailure(Number(searchSpaceId), message);
			toast(t("upload_error"), {
				description: `${t("upload_error_desc")}: ${message}`,
			});
		} finally {
			setIsFolderUploading(false);
			setUploadProgress(0);
		}
	};

	const handleUpload = async () => {
		if (folderUpload) {
			await handleFolderUpload();
			return;
		}

		const shouldGenerateVariants = generateVariants || selectedEtlServices.length > 1;

		setUploadProgress(0);
		trackDocumentUploadStarted(Number(searchSpaceId), files.length, totalFileSize);

		progressIntervalRef.current = setInterval(() => {
			setUploadProgress((prev) => (prev >= 90 ? prev : prev + Math.random() * 10));
		}, 200);

		const rawFiles = files.map((entry) => entry.file);
		uploadDocuments(
			{
				files: rawFiles,
				search_space_id: Number(searchSpaceId),
				should_summarize: shouldSummarize,
				use_vision_llm: useVisionLlm,
				processing_mode: processingMode,
				etl_services: shouldGenerateVariants ? selectedEtlServices : undefined,
				embedding_models: selectedEmbeddingModels,
				chunking_strategy: shouldGenerateVariants ? chunkingStrategy : (selectedChunkingStrategies[0] ?? chunkingStrategy),
				chunking_strategies: shouldGenerateVariants ? selectedChunkingStrategies : undefined,
				chunk_sizes: shouldGenerateVariants ? selectedChunkSizes : undefined,
				generate_variants: shouldGenerateVariants,
			},
			{
				onSuccess: (result) => {
					if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
					setUploadProgress(100);
					trackDocumentUploadSuccess(Number(searchSpaceId), files.length);
					const queuedCount =
						result.pending_files ??
						result.pipeline_jobs?.length ??
						result.document_ids?.length ??
						0;
					const skippedCount = result.skipped_duplicates ?? 0;

					if (queuedCount > 0) {
						toast(t("upload_initiated"), { description: t("upload_initiated_desc") });
					} else if (skippedCount > 0) {
						toast.info("No new processing queued", {
							description: `Skipped ${skippedCount} duplicate file${skippedCount === 1 ? "" : "s"}.`,
						});
					} else {
						toast.info("No new processing queued");
					}
					trackIndexingProgress(result.document_ids ?? [], result.pipeline_jobs ?? []);
				},
				onError: (error: unknown) => {
					if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
					setUploadProgress(0);
					const message = error instanceof Error ? error.message : "Upload failed";
					trackDocumentUploadFailure(Number(searchSpaceId), message);
					toast(t("upload_error"), {
						description: `${t("upload_error_desc")}: ${message}`,
					});
				},
			}
		);
	};

	const renderBrowseButton = (options?: { compact?: boolean; fullWidth?: boolean }) => {
		const { compact, fullWidth } = options ?? {};
		const sizeClass = compact ? "h-7" : "h-8";
		const widthClass = fullWidth ? "w-full" : "";

		if (isElectron) {
			return (
				<DropdownMenu>
					<DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
						<Button
							variant="ghost"
							size="sm"
							className={`text-xs gap-1 bg-neutral-700/50 hover:bg-neutral-600/50 ${sizeClass} ${widthClass}`}
						>
							Browse
							<ChevronDown className="h-3 w-3 opacity-60" />
						</Button>
					</DropdownMenuTrigger>
					<DropdownMenuContent
						align="center"
						className="dark:bg-neutral-800"
						onClick={(e) => e.stopPropagation()}
					>
						<DropdownMenuItem onClick={handleBrowseFiles}>
							<FileIcon className="h-4 w-4 mr-2" />
							Files
						</DropdownMenuItem>
						<DropdownMenuItem onClick={() => folderInputRef.current?.click()}>
							<FolderOpen className="h-4 w-4 mr-2" />
							Folder
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			);
		}

		return (
			<DropdownMenu>
				<DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
					<Button
						variant="ghost"
						size="sm"
						className={`text-xs gap-1 bg-neutral-700/50 hover:bg-neutral-600/50 ${sizeClass} ${widthClass}`}
					>
						Browse
						<ChevronDown className="h-3 w-3 opacity-60" />
					</Button>
				</DropdownMenuTrigger>
				<DropdownMenuContent
					align="center"
					className="dark:bg-neutral-800"
					onClick={(e) => e.stopPropagation()}
				>
					<DropdownMenuItem onClick={() => fileInputRef.current?.click()}>
						<FileIcon className="h-4 w-4 mr-2" />
						{t("browse_files")}
					</DropdownMenuItem>
					<DropdownMenuItem onClick={() => folderInputRef.current?.click()}>
						<FolderOpen className="h-4 w-4 mr-2" />
						{t("browse_folder")}
					</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
		);
	};

	return (
		<div className="space-y-2 w-full mx-auto">
			{/* Hidden file input */}
			<input
				{...getInputProps()}
				ref={fileInputRef}
				className="hidden"
				onClick={handleFileInputClick}
			/>

			{/* Hidden folder input for web folder browsing */}
			<input
				ref={folderInputRef}
				type="file"
				className="hidden"
				onChange={handleFolderChange}
				multiple
				{...({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)}
			/>

			{/* MOBILE DROP ZONE */}
			<div className="sm:hidden">
				{hasContent ? (
					isElectron ? (
						<div className="w-full">{renderBrowseButton({ compact: true, fullWidth: true })}</div>
					) : (
						<button
							type="button"
							className="w-full text-xs h-8 flex items-center justify-center gap-1.5 rounded-md border border-dashed border-muted-foreground/30 text-muted-foreground hover:text-foreground hover:border-foreground/50 transition-colors"
							onClick={() => fileInputRef.current?.click()}
						>
							Add more files
						</button>
					)
				) : (
					// biome-ignore lint/a11y/useSemanticElements: cannot use <button> here because the contents include nested interactive elements (renderBrowseButton renders a Button), which would be invalid HTML.
					<div
						role="button"
						tabIndex={0}
						className="flex flex-col items-center gap-4 py-12 px-4 cursor-pointer w-full bg-transparent outline-none select-none"
						onClick={() => {
							if (!isElectron) fileInputRef.current?.click();
						}}
						onKeyDown={(e) => {
							if (e.key === "Enter" || e.key === " ") {
								e.preventDefault();
								if (!isElectron) fileInputRef.current?.click();
							}
						}}
					>
						<Upload className="h-10 w-10 text-muted-foreground" />
						<div className="text-center space-y-1.5">
							<p className="text-base font-medium">
								{isElectron ? t("select_files_or_folder") : t("tap_select_files_or_folder")}
							</p>
							<p className="text-sm text-muted-foreground">{t("file_size_limit")}</p>
						</div>
						<fieldset
							className="w-full mt-1 border-none p-0 m-0"
							onClick={(e) => e.stopPropagation()}
							onKeyDown={(e) => e.stopPropagation()}
						>
							{renderBrowseButton({ fullWidth: true })}
						</fieldset>
					</div>
				)}
			</div>

			{/* DESKTOP DROP ZONE */}
			<div
				{...getRootProps()}
				className={`hidden sm:block border-2 border-dashed rounded-lg transition-colors border-muted-foreground/30 hover:border-foreground/70 cursor-pointer ${hasContent ? "p-3" : "py-20 px-4"}`}
			>
				{hasContent ? (
					<div className="flex items-center gap-3">
						<Upload className="h-4 w-4 text-muted-foreground shrink-0" />
						<span className="text-xs text-muted-foreground flex-1 truncate">
							{isDragActive ? t("drop_files") : t("drag_drop_more")}
						</span>
						{renderBrowseButton({ compact: true })}
					</div>
				) : (
					<div className="relative">
						{isDragActive && (
							<div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
								<Upload className="h-8 w-8 text-primary" />
								<p className="text-sm font-medium text-primary">{t("drop_files")}</p>
							</div>
						)}
						<div className={`flex flex-col items-center gap-2 ${isDragActive ? "invisible" : ""}`}>
							<Upload className="h-8 w-8 text-muted-foreground" />
							<p className="text-sm font-medium">{t("drag_drop")}</p>
							<p className="text-xs text-muted-foreground">{t("file_size_limit")}</p>
							<div className="mt-1">{renderBrowseButton()}</div>
						</div>
					</div>
				)}
			</div>

			{/* FILES SELECTED */}
			{hasContent && (
				<div className="rounded-lg border border-border p-3 space-y-2">
					<div className="flex items-center justify-between">
						<p className="text-sm font-medium">
							{folderUpload ? (
								<>
									<FolderOpen className="inline h-4 w-4 mr-1 -mt-0.5" />
									{folderUpload.folderName}
									<Dot className="inline h-4 w-4" />
									{folderUpload.entries.length}{" "}
									{folderUpload.entries.length === 1 ? "file" : "files"}
									<Dot className="inline h-4 w-4" />
									{formatFileSize(totalFileSize)}
								</>
							) : (
								<>
									{t("selected_files", { count: files.length })}
									<Dot className="inline h-4 w-4" />
									{formatFileSize(totalFileSize)}
								</>
							)}
						</p>
						<Button
							variant="ghost"
							size="sm"
							className="h-7 text-xs text-muted-foreground hover:text-foreground"
							onClick={() => {
								setFiles([]);
								setFolderUpload(null);
							}}
							disabled={isAnyUploading}
						>
							{t("clear_all")}
						</Button>
					</div>

					<div className="max-h-[160px] sm:max-h-[200px] overflow-y-auto -mx-1">
						{folderUpload
							? folderTreeItems.map((item, i) => (
									<div
										key={`${item.depth}-${i}-${item.name}`}
										className="flex items-center gap-1.5 py-0.5 px-2"
										style={{ paddingLeft: `${item.depth * 16 + 8}px` }}
									>
										{item.isFolder ? (
											<FolderOpen className="h-3.5 w-3.5 text-blue-400 shrink-0" />
										) : (
											<FileIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
										)}
										<span className="text-sm truncate flex-1 min-w-0">{item.name}</span>
										{!item.isFolder && item.size != null && (
											<span className="text-xs text-muted-foreground shrink-0">
												{formatFileSize(item.size)}
											</span>
										)}
									</div>
								))
							: files.map((entry) => (
									<div
										key={entry.id}
										className="flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-slate-400/5 dark:hover:bg-white/5 group"
									>
										<span className="text-[10px] font-medium uppercase leading-none bg-muted px-1.5 py-0.5 rounded text-muted-foreground shrink-0">
											{entry.file.name.split(".").pop() || "?"}
										</span>
										<span className="text-sm truncate flex-1 min-w-0">{entry.file.name}</span>
										<span className="text-xs text-muted-foreground shrink-0">
											{formatFileSize(entry.file.size)}
										</span>
										<Button
											variant="ghost"
											size="icon"
											className="h-6 w-6 shrink-0"
											onClick={() => setFiles((prev) => prev.filter((e) => e.id !== entry.id))}
											disabled={isAnyUploading}
										>
											<X className="h-3 w-3" />
										</Button>
									</div>
								))}
					</div>

					{isAnyUploading && (
						<div className="space-y-1">
							<div className="flex items-center justify-between text-xs">
								<span>{folderUpload ? t("uploading_folder") : t("uploading_files")}</span>
								<span>{Math.round(uploadProgress)}%</span>
							</div>
							<Progress value={uploadProgress} className="h-1.5" />
						</div>
					)}

					<div className={toggleRowClass}>
						<div className="space-y-0.5">
							<p className="font-medium text-sm">Generate Pipeline Variants</p>
							<p className="text-xs text-muted-foreground">
								Create one pipeline per embedding × chunk method × chunk size
							</p>
						</div>
						<Switch checked={generateVariants} onCheckedChange={setGenerateVariants} />
					</div>

						{/* Enable AI Summary — hidden for now
					<div className={toggleRowClass}>
						<div className="space-y-0.5">
							<p className="font-medium text-sm">Enable AI Summary</p>
							<p className="text-xs text-muted-foreground">Improves search quality but adds latency</p>
						</div>
						<Switch checked={shouldSummarize} onCheckedChange={setShouldSummarize} />
					</div>
					*/}

					{/* Enable Vision LLM — hidden for now
					<div className={toggleRowClass}>
						<div className="space-y-0.5">
							<p className="font-medium text-sm">Enable Vision LLM</p>
							<p className="text-xs text-muted-foreground">Describes images using AI vision (costly, slower)</p>
						</div>
						<Switch checked={useVisionLlm} onCheckedChange={setUseVisionLlm} />
					</div>
					*/}

					{/* Processing Mode (Basic / Premium) — hidden for now
					<div className="space-y-1.5">
						<p className="font-medium text-sm px-1">{t("processing_mode")}</p>
						... basic / premium buttons ...
					</div>
					*/}

					{/* Pipeline settings — interactive only when Generate Pipeline Variants is on */}
					<div
						className={`space-y-3 rounded-lg border border-border p-3 transition-opacity ${
							generateVariants ? "" : "opacity-50 pointer-events-none select-none"
						}`}
					>
						{/* Pipeline Settings header */}
					<div className="flex items-center justify-between mb-1">
						<p className="font-semibold text-sm">
							Pipeline Settings
						</p>
						{!generateVariants && (
							<span className="text-[10px] font-normal uppercase tracking-wide text-muted-foreground/60 border border-muted-foreground/20 rounded px-1.5 py-0.5">
								enable variants to edit
							</span>
						)}
					</div>

					{/* Sequential pipeline flow diagram */}
					<div className="flex items-center gap-0 text-[10px] font-medium mb-3">
						{[
							{ step: "1", label: "ETL / Parse", sub: "PDF → Markdown", color: "bg-orange-500", text: "text-orange-400", border: "border-orange-500/40" },
							{ step: "2", label: "Chunking Method", sub: "Split strategy", color: "bg-violet-500", text: "text-violet-400", border: "border-violet-500/40" },
							{ step: "3", label: "Chunk Size", sub: "Token window", color: "bg-emerald-500", text: "text-emerald-400", border: "border-emerald-500/40" },
							{ step: "4", label: "Embeddings", sub: "Vectors → Index", color: "bg-blue-500", text: "text-blue-400", border: "border-blue-500/40" },
						].map((s, i) => (
							<div key={s.step} className="flex items-center">
								<div className={`flex items-center gap-1.5 rounded-md border ${s.border} bg-muted/60 px-2.5 py-1.5`}>
									<span className={`inline-flex h-4 w-4 items-center justify-center rounded-full ${s.color} text-white font-bold text-[9px] shrink-0`}>{s.step}</span>
									<div>
										<p className={`${s.text} font-semibold leading-none`}>{s.label}</p>
										<p className="text-muted-foreground/60 leading-none mt-0.5">{s.sub}</p>
									</div>
								</div>
								{i < 3 && (
									<svg className="h-3 w-5 text-muted-foreground/40 shrink-0" viewBox="0 0 20 12" fill="none">
										<path d="M0 6h16M12 1l6 5-6 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
									</svg>
								)}
							</div>
						))}
					</div>

					{/* 4-column grid: ETL/Parse | Chunking Method | Chunk Size | Embeddings */}
					<div className="grid grid-cols-4 divide-x divide-border">

						{/* Column 1 — ETL / Parse */}
						<div className="pr-4 space-y-2">
							<div className="flex items-center gap-2 pb-1 border-b border-border">
								<span className="inline-block h-2 w-2 rounded-full bg-orange-500 shrink-0" />
								<p className="font-semibold text-xs uppercase tracking-wider text-foreground">ETL / Parse</p>
							</div>
							<p className="text-[10px] text-muted-foreground leading-snug">
								Converts raw files into clean Markdown. Runs once per document — output is shared by all pipeline variants.
							</p>
							{[
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
							].map((option) => {
								const active = selectedEtlServices.includes(option.key as EtlServiceOption);
								return (
									<button
										key={option.key}
										type="button"
										onClick={() => toggleEtlServiceSelection(option.key as EtlServiceOption)}
										className={`rounded-lg border px-3 py-2 flex items-start gap-2 ${
											active
												? "border-orange-500/50 bg-orange-500/10"
												: "border-border bg-muted/40 hover:border-orange-500/30"
										}`}
									>
										<span
											className={`inline-block h-1.5 w-1.5 rounded-full mt-1 shrink-0 ${
												active ? "bg-orange-500" : "bg-muted-foreground/50"
											}`}
										/>
										<div>
											<p
												className={`text-xs font-semibold leading-none ${
													active ? "text-orange-400" : "text-muted-foreground"
												}`}
											>
												{option.label}
												{active ? " (selected)" : ""}
											</p>
											<p className="text-[10px] text-muted-foreground mt-0.5 leading-snug">
												{option.desc}
											</p>
										</div>
									</button>
								);
							})}
							<p className="text-[9px] text-muted-foreground/50 italic">
								Select one or more parsers. Pipeline variants are generated across all selected ETLs. Default comes from <span className="font-mono">NEXT_PUBLIC_ETL_SERVICE</span>.
							</p>
						</div>

						{/* Column 2 — Chunking Method */}
						<div className="px-4 space-y-2">
							<div className="flex items-center gap-2 pb-1 border-b border-border">
								<span className="inline-block h-2 w-2 rounded-full bg-violet-500 shrink-0" />
								<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Chunking Method</p>
							</div>
							<div className="grid grid-cols-1 gap-1.5">
								{CHUNK_STRATEGY_OPTIONS.map((strategy) => {
									const selected = selectedChunkingStrategies.includes(strategy);
									return (
										<button
											key={strategy}
											type="button"
											onClick={() => toggleChunkStrategySelection(strategy)}
											className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors flex items-center gap-2 ${
												selected
													? "border-violet-500 bg-violet-500/10 text-violet-400"
													: "border-border hover:border-muted-foreground/50 text-muted-foreground hover:text-foreground"
											}`}
										>
											<span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${selected ? "bg-violet-500" : "bg-muted-foreground/40"}`} />
											{strategy}
										</button>
									);
								})}
							</div>
						</div>

						{/* Column 3 — Chunk Size */}
						<div className="px-4 space-y-2">
							<div className="flex items-center gap-2 pb-1 border-b border-border">
								<span className="inline-block h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
								<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Chunk Size</p>
							</div>
							<div className="grid grid-cols-2 gap-1.5">
								{CHUNK_SIZE_OPTIONS.map((size) => {
									const selected = selectedChunkSizes.includes(size);
									return (
										<button
											key={size}
											type="button"
											onClick={() => toggleChunkSizeSelection(size)}
											className={`rounded-lg border px-2 py-2 text-center text-xs font-medium transition-colors ${
												selected
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

						{/* Column 4 — Embeddings */}
						<div className="pl-4 space-y-2">
							<div className="flex items-center gap-2 pb-1 border-b border-border">
								<span className="inline-block h-2 w-2 rounded-full bg-blue-500 shrink-0" />
								<p className="font-semibold text-xs uppercase tracking-wider text-foreground">Embeddings</p>
							</div>
							<EmbeddingModelSelector
								selectedModels={selectedEmbeddingModels}
								onSelectionChange={setSelectedEmbeddingModels}
								estimatedTokens={10000}
							/>
						</div>

					</div>
				</div>

					{(isIndexing || variantStatuses.length > 0) && (
					<div className="space-y-2">
						{/* Aggregate header — only while indexing */}
						{isIndexing && (
							<>
								<div className="flex items-center justify-between text-xs">
									<span>{indexingStatusMessage || "Indexing variants..."}</span>
									<span>{Math.round(indexingProgress)}%</span>
								</div>
								<Progress value={indexingProgress} className="h-1.5" />
								{indexingEtaSeconds !== null && indexingEtaSeconds > 0 && (
									<p className="text-[11px] text-muted-foreground">
										Estimated time remaining: {indexingEtaSeconds}s
									</p>
								)}
							</>
						)}
						{!isIndexing && variantStatuses.length > 0 && (
							<p className="text-xs text-muted-foreground">{indexingStatusMessage}</p>
						)}
						{/* Per-variant progress bars */}
						{variantStatuses.length > 0 && (
							<div className="mt-2 max-h-[260px] overflow-y-auto space-y-2 pr-0.5">
								{variantStatuses.map((v) => {
									const barValue = v.state === "ready" ? 100 : v.state === "failed" ? 100 : v.state === "processing" ? 60 : 0;
									const barColor =
										v.state === "ready"
											? "[&>div]:bg-emerald-500"
											: v.state === "failed"
												? "[&>div]:bg-red-500"
												: v.state === "processing"
													? "[&>div]:bg-blue-500"
													: "[&>div]:bg-muted-foreground/30";
									const pulse = v.state === "processing" ? "[&>div]:animate-pulse" : "";
									return (
										<div key={v.id} className="space-y-1">
											<div className="flex items-center justify-between gap-2">
												<span className="text-[11px] text-muted-foreground truncate flex-1 min-w-0" title={v.title}>
													{v.title}
												</span>
												<span
													className={`shrink-0 text-[10px] font-medium rounded-full px-1.5 py-0.5 ${
														v.state === "ready"
															? "bg-emerald-500/15 text-emerald-400"
															: v.state === "failed"
																? "bg-red-500/15 text-red-400"
																: v.state === "processing"
																	? "bg-blue-500/15 text-blue-400"
																	: "bg-muted text-muted-foreground"
													}`}
												>
													{v.state}
												</span>
											</div>
											<Progress value={barValue} className={`h-1 ${barColor} ${pulse}`} />
											{v.reason && (
												<p className="text-[10px] text-red-400 truncate" title={v.reason}>{v.reason}</p>
											)}
										</div>
									);
								})}
							</div>
						)}
					</div>
				)}

					<Button
						className="w-full relative"
						onClick={handleUpload}
						disabled={isAnyUploading || isIndexing || fileCount === 0}
					>
						<span className={isAnyUploading ? "opacity-0" : ""}>
							{folderUpload
								? t("upload_folder_button", { count: fileCount })
								: t("upload_button", { count: fileCount })}
						</span>
						{isAnyUploading && <Spinner size="sm" className="absolute" />}
					</Button>
				</div>
			)}

			{/* SUPPORTED FORMATS */}
			<Accordion
				type="single"
				collapsible
				value={accordionValue}
				onValueChange={handleAccordionChange}
				className="w-full mt-5"
			>
				<AccordionItem value="supported-file-types" className="border border-border rounded-lg">
					<AccordionTrigger className="px-3 py-2.5 hover:no-underline !items-center [&>svg]:!translate-y-0">
						<span className="text-xs sm:text-sm text-muted-foreground font-normal">
							{t("supported_file_types")}
						</span>
					</AccordionTrigger>
					<AccordionContent className="px-3 pb-3">
						<div className="flex flex-wrap gap-1.5">
							{supportedExtensions.map((ext) => (
								<Badge
									key={ext}
									variant="secondary"
									className="rounded border-0 bg-neutral-200/80 dark:bg-neutral-700/60 text-muted-foreground text-[10px] px-2 py-0.5 font-normal"
								>
									{ext}
								</Badge>
							))}
						</div>
					</AccordionContent>
				</AccordionItem>
			</Accordion>
		</div>
	);
}
