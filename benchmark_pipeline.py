"""
Parallel Benchmark Pipeline - Test All RAG Configurations

Features:
1. Parallel configuration testing (multi-processing)
2. Golden Q&A evaluation (F1, precision, recall)
3. Component ablation studies
4. Performance profiling (latency breakdown)
5. Cost tracking (per component, per configuration)
6. Result comparison and ranking

Usage:
    python benchmark_pipeline.py --configs production_cloud,production_local --dataset msft_fy26q1
"""

import asyncio
import json
import time
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import yaml
import argparse
from datetime import datetime

# Adapter imports
from adapter_base_classes import AdapterFactory
from adapter_examples import register_example_adapters
from adapter_dataflow_models import Query, RetrievalContext
from rag_orchestrator import RAGOrchestrator
from rag_config_manager import RAGConfigManager


# ============================================================================
# BENCHMARK DATA MODELS
# ============================================================================

@dataclass
class BenchmarkQuestion:
    """Single Q&A pair for evaluation"""
    question_id: str
    question: str
    ground_truth_answer: str
    ground_truth_chunks: List[str] = field(default_factory=list)  # Expected chunk IDs
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Result of answering one question"""
    question_id: str
    question: str
    
    # Generated answer
    generated_answer: str
    retrieved_chunks: List[str] = field(default_factory=list)  # Retrieved chunk IDs
    
    # Metrics
    f1_score: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    exact_match: bool = False
    
    # Performance
    total_latency_ms: float = 0.0
    component_latency_ms: Dict[str, float] = field(default_factory=dict)
    
    # Cost
    total_cost_usd: float = 0.0
    component_cost_usd: Dict[str, float] = field(default_factory=dict)
    
    # Context
    context_length_tokens: int = 0
    num_chunks_retrieved: int = 0
    
    # Errors
    error: Optional[str] = None


@dataclass
class ConfigBenchmarkResult:
    """Aggregate results for one configuration"""
    config_name: str
    config: Dict[str, Any]
    
    # Aggregate metrics
    avg_f1: float = 0.0
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    exact_match_pct: float = 0.0
    
    # Performance
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Cost
    total_cost_usd: float = 0.0
    cost_per_query_usd: float = 0.0
    cost_per_1k_queries_usd: float = 0.0
    
    # Per-component breakdown
    component_latency_breakdown: Dict[str, float] = field(default_factory=dict)
    component_cost_breakdown: Dict[str, float] = field(default_factory=dict)
    
    # Individual results
    question_results: List[BenchmarkResult] = field(default_factory=list)
    
    # Errors
    error_count: int = 0
    error_rate_pct: float = 0.0
    
    # Timestamp
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================================
# EVALUATION METRICS
# ============================================================================

def compute_f1_score(prediction: str, ground_truth: str) -> Tuple[float, float, float]:
    """
    Compute token-level F1 score between prediction and ground truth.
    
    Returns:
        (f1, precision, recall)
    """
    pred_tokens = set(prediction.lower().split())
    truth_tokens = set(ground_truth.lower().split())
    
    if len(pred_tokens) == 0 or len(truth_tokens) == 0:
        return (0.0, 0.0, 0.0)
    
    common = pred_tokens & truth_tokens
    
    if len(common) == 0:
        return (0.0, 0.0, 0.0)
    
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(truth_tokens)
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return (f1, precision, recall)


def compute_exact_match(prediction: str, ground_truth: str) -> bool:
    """Check if prediction matches ground truth (case-insensitive, whitespace-normalized)"""
    pred_norm = " ".join(prediction.lower().split())
    truth_norm = " ".join(ground_truth.lower().split())
    return pred_norm == truth_norm


def compute_chunk_recall(retrieved_chunks: List[str], ground_truth_chunks: List[str]) -> float:
    """Fraction of ground truth chunks that were retrieved"""
    if not ground_truth_chunks:
        return 1.0  # No expected chunks = perfect recall
    
    retrieved_set = set(retrieved_chunks)
    truth_set = set(ground_truth_chunks)
    overlap = retrieved_set & truth_set
    
    return len(overlap) / len(truth_set)


# ============================================================================
# BENCHMARK RUNNER
# ============================================================================

class BenchmarkRunner:
    """Run benchmarks for a single configuration"""
    
    def __init__(self, config_name: str, config_path: str, dataset_path: str):
        self.config_name = config_name
        self.config_path = config_path
        self.dataset_path = dataset_path
        
        # Load config
        self.config_manager = RAGConfigManager(config_path)
        self.config = self.config_manager.get_active_config()
        
        # Initialize orchestrator
        register_example_adapters()
        self.orchestrator = RAGOrchestrator(self.config_manager)
        
        # Load dataset
        self.dataset = self._load_dataset(dataset_path)
    
    def _load_dataset(self, path: str) -> List[BenchmarkQuestion]:
        """Load benchmark Q&A dataset"""
        with open(path, 'r') as f:
            data = json.load(f)
        
        questions = []
        for item in data:
            questions.append(BenchmarkQuestion(
                question_id=item['id'],
                question=item['question'],
                ground_truth_answer=item['answer'],
                ground_truth_chunks=item.get('expected_chunks', []),
                metadata=item.get('metadata', {})
            ))
        
        return questions
    
    async def run_single_question(self, question: BenchmarkQuestion) -> BenchmarkResult:
        """Run RAG pipeline for one question"""
        start_time = time.time()
        
        try:
            # Create query
            query = Query(
                query_text=question.question,
                user_id="benchmark_user",
                session_id="benchmark_session"
            )
            
            # Run retrieval pipeline
            context = await self.orchestrator.retrieve(query)
            
            # Extract answer (simplified - in production, call LLM)
            # For benchmarking, we'll use the top chunk as "answer"
            generated_answer = context.chunks[0].content if context.chunks else ""
            
            # Compute metrics
            f1, precision, recall = compute_f1_score(
                generated_answer,
                question.ground_truth_answer
            )
            exact_match = compute_exact_match(
                generated_answer,
                question.ground_truth_answer
            )
            
            # Extract retrieved chunk IDs
            retrieved_chunks = [chunk.chunk_id for chunk in context.chunks]
            
            # Total latency
            total_latency = (time.time() - start_time) * 1000  # ms
            
            # Component latency (from context metadata)
            component_latency = {}
            component_cost = {}
            
            for chunk in context.chunks:
                # Aggregate latency from chunk metadata
                if 'retrieval_latency_ms' in chunk.metadata:
                    component_latency['retrieval'] = chunk.metadata['retrieval_latency_ms']
                if 'embedding_latency_ms' in chunk.metadata:
                    component_latency['embedding'] = chunk.metadata['embedding_latency_ms']
            
            # Cost tracking
            total_cost = context.total_cost_usd
            
            result = BenchmarkResult(
                question_id=question.question_id,
                question=question.question,
                generated_answer=generated_answer,
                retrieved_chunks=retrieved_chunks,
                f1_score=f1,
                precision=precision,
                recall=recall,
                exact_match=exact_match,
                total_latency_ms=total_latency,
                component_latency_ms=component_latency,
                total_cost_usd=total_cost,
                component_cost_usd=component_cost,
                context_length_tokens=sum(chunk.token_count for chunk in context.chunks),
                num_chunks_retrieved=len(context.chunks),
                error=None
            )
            
        except Exception as e:
            result = BenchmarkResult(
                question_id=question.question_id,
                question=question.question,
                generated_answer="",
                error=str(e),
                total_latency_ms=(time.time() - start_time) * 1000
            )
        
        return result
    
    async def run_benchmark(self) -> ConfigBenchmarkResult:
        """Run benchmark for all questions in dataset"""
        print(f"[{self.config_name}] Running benchmark on {len(self.dataset)} questions...")
        
        results = []
        
        # Run questions sequentially (could parallelize with semaphore)
        for i, question in enumerate(self.dataset):
            print(f"[{self.config_name}] Question {i+1}/{len(self.dataset)}: {question.question_id}")
            result = await self.run_single_question(question)
            results.append(result)
        
        # Aggregate metrics
        successful_results = [r for r in results if r.error is None]
        
        if not successful_results:
            return ConfigBenchmarkResult(
                config_name=self.config_name,
                config=self.config,
                error_count=len(results),
                error_rate_pct=100.0
            )
        
        # Compute aggregates
        avg_f1 = sum(r.f1_score for r in successful_results) / len(successful_results)
        avg_precision = sum(r.precision for r in successful_results) / len(successful_results)
        avg_recall = sum(r.recall for r in successful_results) / len(successful_results)
        exact_match_pct = sum(r.exact_match for r in successful_results) / len(successful_results) * 100
        
        # Latency statistics
        latencies = sorted([r.total_latency_ms for r in successful_results])
        avg_latency = sum(latencies) / len(latencies)
        p50_latency = latencies[len(latencies) // 2]
        p95_latency = latencies[int(len(latencies) * 0.95)]
        p99_latency = latencies[int(len(latencies) * 0.99)]
        
        # Cost
        total_cost = sum(r.total_cost_usd for r in successful_results)
        cost_per_query = total_cost / len(successful_results)
        cost_per_1k = cost_per_query * 1000
        
        # Component breakdown
        component_latency_breakdown = {}
        component_cost_breakdown = {}
        
        for result in successful_results:
            for component, latency in result.component_latency_ms.items():
                component_latency_breakdown[component] = component_latency_breakdown.get(component, 0) + latency
        
        # Average component latencies
        for component in component_latency_breakdown:
            component_latency_breakdown[component] /= len(successful_results)
        
        benchmark_result = ConfigBenchmarkResult(
            config_name=self.config_name,
            config=self.config,
            avg_f1=avg_f1,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            exact_match_pct=exact_match_pct,
            avg_latency_ms=avg_latency,
            p50_latency_ms=p50_latency,
            p95_latency_ms=p95_latency,
            p99_latency_ms=p99_latency,
            total_cost_usd=total_cost,
            cost_per_query_usd=cost_per_query,
            cost_per_1k_queries_usd=cost_per_1k,
            component_latency_breakdown=component_latency_breakdown,
            component_cost_breakdown=component_cost_breakdown,
            question_results=results,
            error_count=len(results) - len(successful_results),
            error_rate_pct=(len(results) - len(successful_results)) / len(results) * 100 if results else 0.0
        )
        
        print(f"[{self.config_name}] Benchmark complete!")
        print(f"  Avg F1: {avg_f1:.3f}")
        print(f"  Avg Latency: {avg_latency:.0f}ms")
        print(f"  Cost per 1K queries: ${cost_per_1k:.2f}")
        
        return benchmark_result


# ============================================================================
# PARALLEL BENCHMARK COORDINATOR
# ============================================================================

class ParallelBenchmarkCoordinator:
    """Coordinate parallel benchmarking of multiple configurations"""
    
    def __init__(
        self,
        config_names: List[str],
        config_dir: str = "./configs",
        dataset_path: str = "./msft_fy26q1_qa_benchmark_100_sanitized.json",
        max_parallel: int = 4
    ):
        self.config_names = config_names
        self.config_dir = Path(config_dir)
        self.dataset_path = dataset_path
        self.max_parallel = max_parallel
    
    def run_config_benchmark(self, config_name: str) -> ConfigBenchmarkResult:
        """Run benchmark for single config (called in subprocess)"""
        config_path = str(self.config_dir / f"{config_name}.yaml")
        
        runner = BenchmarkRunner(
            config_name=config_name,
            config_path=config_path,
            dataset_path=self.dataset_path
        )
        
        # Run async benchmark in sync context
        result = asyncio.run(runner.run_benchmark())
        return result
    
    def run_parallel(self) -> List[ConfigBenchmarkResult]:
        """Run benchmarks for all configs in parallel"""
        print(f"\n{'='*80}")
        print(f"PARALLEL BENCHMARK: {len(self.config_names)} configurations")
        print(f"Max parallel: {self.max_parallel}")
        print(f"Dataset: {self.dataset_path}")
        print(f"{'='*80}\n")
        
        results = []
        
        with ProcessPoolExecutor(max_workers=self.max_parallel) as executor:
            # Submit all configs
            future_to_config = {
                executor.submit(self.run_config_benchmark, config_name): config_name
                for config_name in self.config_names
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_config):
                config_name = future_to_config[future]
                try:
                    result = future.result()
                    results.append(result)
                    print(f"\n✅ [{config_name}] Completed!")
                except Exception as e:
                    print(f"\n❌ [{config_name}] Failed: {e}")
        
        return results
    
    def save_results(self, results: List[ConfigBenchmarkResult], output_dir: str = "./benchmark_results"):
        """Save benchmark results to disk"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        for result in results:
            # Save individual config result
            filename = f"{result.config_name}_{timestamp}.json"
            filepath = output_path / filename
            
            with open(filepath, 'w') as f:
                json.dump(asdict(result), f, indent=2)
            
            print(f"Saved: {filepath}")
        
        # Save comparison summary
        self._save_comparison(results, output_path / f"comparison_{timestamp}.md")
    
    def _save_comparison(self, results: List[ConfigBenchmarkResult], filepath: Path):
        """Generate markdown comparison table"""
        # Sort by F1 score
        sorted_results = sorted(results, key=lambda r: r.avg_f1, reverse=True)
        
        with open(filepath, 'w') as f:
            f.write(f"# Benchmark Comparison - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            
            f.write("## Summary Table\n\n")
            f.write("| Rank | Config | F1 | Precision | Recall | Latency (p50) | Cost/1K | Errors |\n")
            f.write("|------|--------|----|-----------| -------|---------------|---------|--------|\n")
            
            for i, result in enumerate(sorted_results, 1):
                f.write(
                    f"| {i} | **{result.config_name}** | "
                    f"{result.avg_f1:.3f} | {result.avg_precision:.3f} | {result.avg_recall:.3f} | "
                    f"{result.p50_latency_ms:.0f}ms | ${result.cost_per_1k_queries_usd:.2f} | "
                    f"{result.error_count} ({result.error_rate_pct:.1f}%) |\n"
                )
            
            f.write("\n## Detailed Results\n\n")
            
            for result in sorted_results:
                f.write(f"### {result.config_name}\n\n")
                f.write(f"**Quality Metrics:**\n")
                f.write(f"- F1 Score: {result.avg_f1:.3f}\n")
                f.write(f"- Precision: {result.avg_precision:.3f}\n")
                f.write(f"- Recall: {result.avg_recall:.3f}\n")
                f.write(f"- Exact Match: {result.exact_match_pct:.1f}%\n\n")
                
                f.write(f"**Performance:**\n")
                f.write(f"- Average Latency: {result.avg_latency_ms:.0f}ms\n")
                f.write(f"- P50 Latency: {result.p50_latency_ms:.0f}ms\n")
                f.write(f"- P95 Latency: {result.p95_latency_ms:.0f}ms\n")
                f.write(f"- P99 Latency: {result.p99_latency_ms:.0f}ms\n\n")
                
                f.write(f"**Cost:**\n")
                f.write(f"- Total Cost: ${result.total_cost_usd:.4f}\n")
                f.write(f"- Cost per Query: ${result.cost_per_query_usd:.6f}\n")
                f.write(f"- Cost per 1K Queries: ${result.cost_per_1k_queries_usd:.2f}\n\n")
                
                f.write(f"**Component Latency Breakdown:**\n")
                for component, latency in result.component_latency_breakdown.items():
                    f.write(f"- {component}: {latency:.0f}ms\n")
                f.write("\n")
                
                f.write(f"**Errors:**\n")
                f.write(f"- Error Count: {result.error_count}\n")
                f.write(f"- Error Rate: {result.error_rate_pct:.1f}%\n\n")
                
                f.write("---\n\n")
        
        print(f"\nComparison table saved: {filepath}")


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Parallel RAG Benchmark Pipeline")
    
    parser.add_argument(
        "--configs",
        type=str,
        required=True,
        help="Comma-separated list of config names (e.g., 'production_cloud,production_local')"
    )
    
    parser.add_argument(
        "--config-dir",
        type=str,
        default="./configs",
        help="Directory containing config YAML files"
    )
    
    parser.add_argument(
        "--dataset",
        type=str,
        default="./msft_fy26q1_qa_benchmark_100_sanitized.json",
        help="Path to benchmark Q&A dataset (JSON)"
    )
    
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum parallel config benchmarks"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./benchmark_results_MSFT_FY26Q1_qa",
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    # Parse config names
    config_names = [name.strip() for name in args.configs.split(',')]
    
    # Create coordinator
    coordinator = ParallelBenchmarkCoordinator(
        config_names=config_names,
        config_dir=args.config_dir,
        dataset_path=args.dataset,
        max_parallel=args.max_parallel
    )
    
    # Run parallel benchmarks
    results = coordinator.run_parallel()
    
    # Save results
    coordinator.save_results(results, output_dir=args.output_dir)
    
    print(f"\n{'='*80}")
    print("BENCHMARK COMPLETE!")
    print(f"Tested {len(config_names)} configurations")
    print(f"Results saved to: {args.output_dir}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
