import { z } from "zod";
import { chunkingStrategyEnum } from "@/contracts/types/document.types";

export const benchmarkJobStatusEnum = z.enum(["queued", "running", "completed", "failed"]);

export const benchmarkJobCreateRequest = z.object({
	benchmark_file: z.instanceof(File),
	search_space_id: z.number(),
	source_doc_path: z.string().optional(),
	chunking_strategies: z.array(chunkingStrategyEnum),
	embedding_models: z.array(z.string()).min(1),
	chunk_sizes: z.array(z.number().int().positive()).min(1),
	ranking_variants: z.array(z.string()).min(1),
	max_questions: z.number().int().positive().default(5),
	start_question: z.number().int().positive().default(1),
	subagent_workers: z.number().int().positive().default(4),
	benchmark_workers: z.number().int().positive().default(1),
	request_timeout: z.number().positive().default(240),
	sanitize_questions: z.boolean().default(true),
	cleanup_documents: z.boolean().default(true),
	run_prefix: z.string().min(1).optional(),
	output_dir: z.string().min(1).optional(),
});

export const benchmarkJobCreateResponse = z.object({
	job_id: z.string(),
	status: benchmarkJobStatusEnum,
});

export const benchmarkCandidateStatus = z.object({
	pipeline_id: z.string(),
	status: z.enum(["queued", "running", "completed", "failed"]),
	score: z.number().nullable().optional(),
	overall_correct_rate: z.number().nullable().optional(),
	elapsed_seconds: z.number().nullable().optional(),
	error: z.string().nullable().optional(),
	started_at: z.string().nullable().optional(),
	completed_at: z.string().nullable().optional(),
});

export const benchmarkJobStatusResponse = z.object({
	job_id: z.string(),
	status: benchmarkJobStatusEnum,
	stage: z.string(),
	message: z.string(),
	progress_percent: z.number().int(),
	total_candidates: z.number().int().default(0),
	completed_candidates: z.number().int().default(0),
	eta_seconds: z.number().int().nullable().optional(),
	run_prefix: z.string().nullable().optional(),
	output_dir: z.string().nullable().optional(),
	summary_json_path: z.string().nullable().optional(),
	summary_md_path: z.string().nullable().optional(),
	recommended_pipeline_id: z.string().nullable().optional(),
	ranked_subagent_reports: z.array(z.record(z.any())).nullable().optional(),
	candidates_status: z.array(benchmarkCandidateStatus).nullable().optional(),
	error: z.string().nullable().optional(),
	started_at: z.string().nullable().optional(),
	completed_at: z.string().nullable().optional(),
});

export const benchmarkJobStartPollRequest = z.object({
	job_id: z.string(),
});

export type BenchmarkJobCreateRequest = z.infer<typeof benchmarkJobCreateRequest>;
export type BenchmarkJobCreateResponse = z.infer<typeof benchmarkJobCreateResponse>;
export type BenchmarkJobStatusResponse = z.infer<typeof benchmarkJobStatusResponse>;
export type BenchmarkCandidateStatus = z.infer<typeof benchmarkCandidateStatus>;
