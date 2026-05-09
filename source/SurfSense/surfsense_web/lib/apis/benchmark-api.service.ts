import {
	type BenchmarkJobCreateRequest,
	benchmarkJobCreateRequest,
	benchmarkJobCreateResponse,
	benchmarkJobStatusResponse,
} from "@/contracts/types/benchmark.types";
import { getBearerToken } from "@/lib/auth-utils";
import { ValidationError } from "@/lib/error";
import { baseApiService } from "./base-api.service";

class BenchmarkApiService {
	startJob = async (request: BenchmarkJobCreateRequest) => {
		const parsed = benchmarkJobCreateRequest.safeParse(request);
		if (!parsed.success) {
			const errorMessage = parsed.error.issues.map((issue) => issue.message).join(", ");
			throw new ValidationError(`Invalid benchmark request: ${errorMessage}`);
		}

		const formData = new FormData();
		formData.append("benchmark_file", parsed.data.benchmark_file);
		formData.append("search_space_id", String(parsed.data.search_space_id));
		if (parsed.data.source_doc_path) formData.append("source_doc_path", parsed.data.source_doc_path);
		formData.append("chunking_strategies", JSON.stringify(parsed.data.chunking_strategies));
		formData.append("embedding_models", JSON.stringify(parsed.data.embedding_models));
		formData.append("chunk_sizes", JSON.stringify(parsed.data.chunk_sizes));
		formData.append("ranking_variants", JSON.stringify(parsed.data.ranking_variants));
		formData.append("max_questions", String(parsed.data.max_questions));
		formData.append("start_question", String(parsed.data.start_question));
		formData.append("subagent_workers", String(parsed.data.subagent_workers));
		formData.append("benchmark_workers", String(parsed.data.benchmark_workers));
		formData.append("request_timeout", String(parsed.data.request_timeout));
		formData.append("sanitize_questions", String(parsed.data.sanitize_questions));
		formData.append("cleanup_documents", String(parsed.data.cleanup_documents));
		if (parsed.data.run_prefix) formData.append("run_prefix", parsed.data.run_prefix);
		if (parsed.data.output_dir) formData.append("output_dir", parsed.data.output_dir);

		return baseApiService.postFormData(
			"/api/v1/benchmark/jobs",
			benchmarkJobCreateResponse,
			{ body: formData }
		);
	};

	getJob = async (jobId: string, signal?: AbortSignal) => {
		return baseApiService.get(
			`/api/v1/benchmark/jobs/${jobId}?t=${Date.now()}`,
			benchmarkJobStatusResponse,
			{ signal }
		);
	};

	getJobWebSocketUrl = (jobId: string) => {
		const backendBase = process.env.NEXT_PUBLIC_FASTAPI_BACKEND_URL || "";
		const wsBase = backendBase.replace(/^http/, "ws");
		const token = getBearerToken();
		const params = new URLSearchParams({ t: String(Date.now()) });
		if (token) {
			params.set("token", token);
		}
		return `${wsBase}/api/v1/benchmark/jobs/${jobId}/ws?${params.toString()}`;
	};
}

export const benchmarkApiService = new BenchmarkApiService();
