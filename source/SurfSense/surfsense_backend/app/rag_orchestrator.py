"""
Adaptable RAG Orchestrator

Central orchestrator that:
1. Loads configuration from RAGConfigManager
2. Dynamically instantiates pipeline components via AdapterFactory
3. Executes the full RAG workflow using standardized adapters
4. Tracks metrics and enables optimization
5. Supports agent-driven configuration selection

Key Design:
- USES ADAPTERS: All components accessed through adapter interfaces
- SOFTWARE-STACK AGNOSTIC: Doesn't know if using Python SDK, REST API, Docker service
- DUAL MODE: Supports both optimization (evaluation) and production (query answering)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rag_config_manager import RAGConfigManager, RAGProfile
from adapter_base_classes import (
    ETLAdapter,
    ChunkingAdapter,
    EmbeddingAdapter,
    StorageAdapter,
    RetrievalAdapter,
    RerankingAdapter,
    AdapterFactory,
)
from adapter_dataflow_models import (
    RawDocument,
    Chunk,
    EmbeddedChunk,
    Query,
    SearchResult,
    RerankedResult,
    RetrievalContext,
    IndexingJob,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class RAGRequest:
    """Request for RAG pipeline execution"""
    query: str
    search_space_id: int
    user_id: Optional[str] = None
    document_type: Optional[str | List[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    # Agent context
    conversation_id: Optional[str] = None
    matched_chunk_ids: Optional[List[int]] = None
    
    # Configuration overrides
    profile_name: Optional[str] = None
    config_overrides: Optional[Dict[str, Any]] = None
    user_preferences: Optional[Dict[str, Any]] = None
    
    # Behavioral flags
    enable_reranking: Optional[bool] = None
    max_chunks: Optional[int] = None


@dataclass
class RAGResult:
    """Result from RAG pipeline execution"""
    chunks: List[Dict[str, Any]]
    documents: List[Dict[str, Any]]
    context: str
    
    # Metadata
    profile_used: str
    retrieval_strategy: str
    chunks_retrieved: int
    documents_retrieved: int
    reranking_applied: bool
    
    # Performance metrics
    retrieval_latency_ms: float
    embedding_latency_ms: float
    reranking_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    
    # Quality metrics (if available)
    avg_relevance_score: Optional[float] = None
    coverage_score: Optional[float] = None
    
    # For debugging/optimization
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Component Interfaces
# ============================================================================


class EmbeddingInterface:
    """Abstract interface for embedding providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    async def embed(self, text: str) -> List[float]:
        """Generate embedding for text"""
        raise NotImplementedError
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for batch of texts"""
        raise NotImplementedError


class RetrieverInterface:
    """Abstract interface for retrieval strategies"""
    
    def __init__(self, db_session, config: Dict[str, Any]):
        self.db_session = db_session
        self.config = config
    
    async def retrieve(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        search_space_id: int,
        top_k: int,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant chunks"""
        raise NotImplementedError


class RerankerInterface:
    """Abstract interface for reranking providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    async def rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """Rerank chunks by relevance"""
        raise NotImplementedError


# ============================================================================
# RAG Orchestrator
# ============================================================================


class RAGOrchestrator:
    """
    Central orchestrator for the adaptable RAG system.
    
    Responsibilities:
    - Load and manage configurations
    - Instantiate pipeline components dynamically
    - Execute RAG workflow with selected strategy
    - Track performance metrics
    - Support A/B testing and optimization
    """
    
    def __init__(
        self,
        config_manager: RAGConfigManager,
        db_session_factory=None
    ):
        """
        Initialize RAG orchestrator
        
        Args:
            config_manager: Configuration manager instance
            db_session_factory: Factory for creating DB sessions
        """
        self.config_manager = config_manager
        self.db_session_factory = db_session_factory
        
        # Component cache
        self._embedding_cache: Dict[str, EmbeddingInterface] = {}
        self._retriever_cache: Dict[str, RetrieverInterface] = {}
        self._reranker_cache: Dict[str, RerankerInterface] = {}
        
        # Metrics storage
        self._metrics_history: List[Dict[str, Any]] = []
        
        logger.info("RAG Orchestrator initialized")
    
    async def execute(self, request: RAGRequest) -> RAGResult:
        """
        Execute full RAG pipeline
        
        Args:
            request: RAG request with query and parameters
        
        Returns:
            RAG result with chunks, context, and metrics
        """
        t_start = time.perf_counter()
        
        # Step 1: Select configuration profile
        profile = await self._select_profile(request)
        logger.info(f"Selected profile: {profile.name}")
        
        # Step 2: Get embedding component
        embedding_provider = await self._get_embedding_provider(profile)
        
        # Step 3: Generate query embedding
        t_embed_start = time.perf_counter()
        query_embedding = await embedding_provider.embed(request.query)
        embedding_latency_ms = (time.perf_counter() - t_embed_start) * 1000
        
        # Step 4: Retrieve chunks
        t_retrieval_start = time.perf_counter()
        retriever = await self._get_retriever(profile)
        
        top_k = request.max_chunks or profile.retrieval.config.get("total_chunks_limit", 30)
        
        chunks = await retriever.retrieve(
            query_text=request.query,
            query_embedding=query_embedding,
            search_space_id=request.search_space_id,
            top_k=top_k,
            document_type=request.document_type,
            start_date=request.start_date,
            end_date=request.end_date,
            matched_chunk_ids=request.matched_chunk_ids
        )
        retrieval_latency_ms = (time.perf_counter() - t_retrieval_start) * 1000
        
        logger.info(f"Retrieved {len(chunks)} chunks in {retrieval_latency_ms:.1f}ms")
        
        # Step 5: Optional reranking
        reranking_latency_ms = 0.0
        reranking_applied = False
        
        should_rerank = (
            request.enable_reranking if request.enable_reranking is not None
            else profile.reranking.enabled
        )
        
        if should_rerank and len(chunks) > 0:
            t_rerank_start = time.perf_counter()
            reranker = await self._get_reranker(profile)
            rerank_top_k = profile.reranking.config.get("top_k", top_k)
            chunks = await reranker.rerank(request.query, chunks, rerank_top_k)
            reranking_latency_ms = (time.perf_counter() - t_rerank_start) * 1000
            reranking_applied = True
            logger.info(f"Reranked to {len(chunks)} chunks in {reranking_latency_ms:.1f}ms")
        
        # Step 6: Build context
        context, documents = await self._build_context(
            chunks=chunks,
            profile=profile,
            matched_chunk_ids=request.matched_chunk_ids
        )
        
        # Step 7: Calculate metrics
        total_latency_ms = (time.perf_counter() - t_start) * 1000
        
        result = RAGResult(
            chunks=chunks,
            documents=documents,
            context=context,
            profile_used=profile.name,
            retrieval_strategy=profile.retrieval.strategy,
            chunks_retrieved=len(chunks),
            documents_retrieved=len(documents),
            reranking_applied=reranking_applied,
            retrieval_latency_ms=retrieval_latency_ms,
            embedding_latency_ms=embedding_latency_ms,
            reranking_latency_ms=reranking_latency_ms,
            total_latency_ms=total_latency_ms,
            metadata={
                "chunk_size": profile.chunking.config.get("chunk_size"),
                "rrf_k": profile.retrieval.config.get("rrf_k"),
                "max_chunks_per_doc": profile.retrieval.config.get("max_chunks_per_document")
            }
        )
        
        # Step 8: Track metrics if enabled
        if profile.optimization.track_metrics:
            await self._track_metrics(request, result, profile)
        
        return result
    
    async def _select_profile(self, request: RAGRequest) -> RAGProfile:
        """Select configuration profile based on request"""
        
        # Explicit profile override
        if request.profile_name:
            profile = self.config_manager.get_profile(request.profile_name)
        else:
            # Agent routing - dynamic selection based on query
            # Get document count (requires DB access)
            document_count = await self._get_document_count(request.search_space_id)
            
            profile = self.config_manager.apply_agent_routing(
                query=request.query,
                document_count=document_count,
                user_preferences=request.user_preferences
            )
        
        # Apply request-level config overrides if provided
        if request.config_overrides:
            profile_dict = profile.dict()
            self.config_manager._apply_overrides(profile_dict, request.config_overrides)
            from rag_config_manager import RAGProfile
            profile = RAGProfile(**profile_dict)
        
        return profile
    
    async def _get_document_count(self, search_space_id: int) -> int:
        """Get document count for search space"""
        # Placeholder - implement based on your DB schema
        # For now, return a reasonable default
        return 15
    
    async def _get_embedding_provider(self, profile: RAGProfile) -> EmbeddingInterface:
        """Get or create embedding provider"""
        cache_key = f"{profile.embedding.provider}:{profile.embedding.model}"
        
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        
        # Dynamic loading based on provider
        if profile.embedding.provider == "fastembed":
            from fastembed import TextEmbedding
            
            class FastEmbedAdapter(EmbeddingInterface):
                def __init__(self, config):
                    super().__init__(config)
                    self.model = TextEmbedding(config.get("model_name"))
                
                async def embed(self, text: str) -> List[float]:
                    # FastEmbed expects list input
                    result = list(self.model.embed([text]))
                    return result[0].tolist()
                
                async def embed_batch(self, texts: List[str]) -> List[List[float]]:
                    results = list(self.model.embed(texts))
                    return [r.tolist() for r in results]
            
            config = {
                "model_name": profile.embedding.model,
                **profile.embedding.config
            }
            provider = FastEmbedAdapter(config)
            self._embedding_cache[cache_key] = provider
            return provider
        
        else:
            raise NotImplementedError(f"Embedding provider not implemented: {profile.embedding.provider}")
    
    async def _get_retriever(self, profile: RAGProfile) -> RetrieverInterface:
        """Get or create retriever"""
        cache_key = profile.retrieval.strategy
        
        if cache_key in self._retriever_cache:
            return self._retriever_cache[cache_key]
        
        # Get DB session
        if self.db_session_factory:
            db_session = self.db_session_factory()
        else:
            db_session = None
        
        # Dynamic loading based on strategy
        if profile.retrieval.strategy == "hybrid_rrf":
            # Import existing implementation
            from chunks_hybrid_search_patched import ChucksHybridSearchRetriever
            
            class HybridRRFAdapter(RetrieverInterface):
                def __init__(self, db_session, config):
                    super().__init__(db_session, config)
                    self.retriever = ChucksHybridSearchRetriever(db_session)
                
                async def retrieve(
                    self,
                    query_text: str,
                    query_embedding: Optional[List[float]],
                    search_space_id: int,
                    top_k: int,
                    **kwargs
                ) -> List[Dict[str, Any]]:
                    # Call existing hybrid search
                    chunks = await self.retriever.hybrid_search(
                        query_text=query_text,
                        top_k=top_k,
                        search_space_id=search_space_id,
                        document_type=kwargs.get("document_type"),
                        start_date=kwargs.get("start_date"),
                        end_date=kwargs.get("end_date"),
                        query_embedding=query_embedding
                    )
                    
                    # Convert to dict format
                    return [
                        {
                            "id": chunk.id,
                            "content": chunk.content,
                            "document_id": chunk.document_id,
                            "score": getattr(chunk, "score", 0.0)
                        }
                        for chunk in chunks
                    ]
            
            retriever = HybridRRFAdapter(db_session, profile.retrieval.config)
            self._retriever_cache[cache_key] = retriever
            return retriever
        
        else:
            raise NotImplementedError(f"Retrieval strategy not implemented: {profile.retrieval.strategy}")
    
    async def _get_reranker(self, profile: RAGProfile) -> RerankerInterface:
        """Get or create reranker"""
        cache_key = f"{profile.reranking.provider}:{profile.reranking.model}"
        
        if cache_key in self._reranker_cache:
            return self._reranker_cache[cache_key]
        
        if profile.reranking.provider == "flashrank":
            from rerankers import Reranker
            
            class FlashRankAdapter(RerankerInterface):
                def __init__(self, config):
                    super().__init__(config)
                    model_name = config.get("model_name", "ms-marco-MiniLM-L-12-v2")
                    self.reranker = Reranker(model_name)
                
                async def rerank(
                    self,
                    query: str,
                    chunks: List[Dict[str, Any]],
                    top_k: int
                ) -> List[Dict[str, Any]]:
                    # Prepare documents for reranking
                    texts = [chunk["content"] for chunk in chunks]
                    
                    # Rerank
                    results = self.reranker.rank(query, texts)
                    
                    # Map back to chunks with updated scores
                    reranked = []
                    for result in results[:top_k]:
                        chunk = chunks[result.doc_id]
                        chunk["rerank_score"] = result.score
                        reranked.append(chunk)
                    
                    return reranked
            
            config = {
                "model_name": profile.reranking.model,
                **profile.reranking.config
            }
            reranker = FlashRankAdapter(config)
            self._reranker_cache[cache_key] = reranker
            return reranker
        
        else:
            raise NotImplementedError(f"Reranking provider not implemented: {profile.reranking.provider}")
    
    async def _build_context(
        self,
        chunks: List[Dict[str, Any]],
        profile: RAGProfile,
        matched_chunk_ids: Optional[List[int]] = None
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Build context string from chunks"""
        
        context_format = profile.context_building.format
        
        if context_format == "xml_filesystem":
            # Use existing XML builder
            # This would integrate with your existing _build_document_xml logic
            context = self._build_xml_context(chunks, profile, matched_chunk_ids)
            
            # Extract unique documents
            doc_ids = list(set(chunk["document_id"] for chunk in chunks))
            documents = [{"id": doc_id} for doc_id in doc_ids]
            
            return context, documents
        
        elif context_format == "markdown_sections":
            # Simple markdown format
            sections = []
            for i, chunk in enumerate(chunks, 1):
                sections.append(f"## Chunk {i}\n\n{chunk['content']}\n")
            
            context = "\n".join(sections)
            doc_ids = list(set(chunk["document_id"] for chunk in chunks))
            documents = [{"id": doc_id} for doc_id in doc_ids]
            
            return context, documents
        
        else:
            raise NotImplementedError(f"Context format not implemented: {context_format}")
    
    def _build_xml_context(
        self,
        chunks: List[Dict[str, Any]],
        profile: RAGProfile,
        matched_chunk_ids: Optional[List[int]] = None
    ) -> str:
        """Build XML filesystem context (simplified version)"""
        # This is a placeholder - integrate with your existing implementation
        config = profile.context_building.config
        
        doc_chunks: Dict[int, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            doc_id = chunk["document_id"]
            if doc_id not in doc_chunks:
                doc_chunks[doc_id] = []
            doc_chunks[doc_id].append(chunk)
        
        # Build XML
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<filesystem>']
        
        for doc_id, doc_chunks_list in doc_chunks.items():
            matched_attr = ""
            if matched_chunk_ids:
                has_match = any(c["id"] in matched_chunk_ids for c in doc_chunks_list)
                if has_match:
                    matched_attr = ' matched="true"'
            
            lines.append(f'  <file id="{doc_id}"{matched_attr}>')
            
            for chunk in doc_chunks_list[:20]:  # Limit chunks per doc
                chunk_matched = ""
                if matched_chunk_ids and chunk["id"] in matched_chunk_ids:
                    chunk_matched = ' matched="true"'
                
                # Escape XML
                content = chunk["content"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f'    <chunk id="{chunk["id"]}"{chunk_matched}>{content}</chunk>')
            
            lines.append('  </file>')
        
        lines.append('</filesystem>')
        
        return "\n".join(lines)
    
    async def _track_metrics(
        self,
        request: RAGRequest,
        result: RAGResult,
        profile: RAGProfile
    ):
        """Track metrics for optimization"""
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "query": request.query,
            "profile": result.profile_used,
            "retrieval_strategy": result.retrieval_strategy,
            "chunks_retrieved": result.chunks_retrieved,
            "documents_retrieved": result.documents_retrieved,
            "reranking_applied": result.reranking_applied,
            "retrieval_latency_ms": result.retrieval_latency_ms,
            "embedding_latency_ms": result.embedding_latency_ms,
            "reranking_latency_ms": result.reranking_latency_ms,
            "total_latency_ms": result.total_latency_ms,
            "chunk_size": result.metadata.get("chunk_size"),
            "rrf_k": result.metadata.get("rrf_k"),
        }
        
        self._metrics_history.append(metrics)
        
        # Log to monitoring system
        if profile.optimization.log_retrieval_results:
            logger.info(f"RAG Metrics: {metrics}")
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of tracked metrics"""
        if not self._metrics_history:
            return {}
        
        import statistics
        
        latencies = [m["total_latency_ms"] for m in self._metrics_history]
        chunks_counts = [m["chunks_retrieved"] for m in self._metrics_history]
        
        return {
            "total_queries": len(self._metrics_history),
            "avg_latency_ms": statistics.mean(latencies),
            "p95_latency_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) > 1 else latencies[0],
            "avg_chunks_retrieved": statistics.mean(chunks_counts),
            "profiles_used": list(set(m["profile"] for m in self._metrics_history))
        }


# ============================================================================
# Factory Function
# ============================================================================


def create_rag_orchestrator(
    config_path: Optional[str] = None,
    db_session_factory=None
) -> RAGOrchestrator:
    """
    Create RAG orchestrator with configuration
    
    Args:
        config_path: Path to configuration file
        db_session_factory: Factory for creating DB sessions
    
    Returns:
        Configured RAG orchestrator
    """
    from rag_config_manager import get_rag_config
    
    config_manager = get_rag_config(config_path)
    return RAGOrchestrator(config_manager, db_session_factory)


# ============================================================================
# Usage Example
# ============================================================================


async def main():
    """Example usage"""
    # Create orchestrator
    orchestrator = create_rag_orchestrator("rag_config_schema.yaml")
    
    # Create request
    request = RAGRequest(
        query="What was Microsoft's revenue in Q1 FY26?",
        search_space_id=1,
        user_id="user123"
    )
    
    # Execute RAG pipeline
    result = await orchestrator.execute(request)
    
    # Display results
    print(f"\nProfile used: {result.profile_used}")
    print(f"Strategy: {result.retrieval_strategy}")
    print(f"Chunks retrieved: {result.chunks_retrieved}")
    print(f"Documents: {result.documents_retrieved}")
    print(f"Reranking: {result.reranking_applied}")
    print(f"\nLatency breakdown:")
    print(f"  Embedding: {result.embedding_latency_ms:.1f}ms")
    print(f"  Retrieval: {result.retrieval_latency_ms:.1f}ms")
    print(f"  Reranking: {result.reranking_latency_ms:.1f}ms")
    print(f"  Total: {result.total_latency_ms:.1f}ms")
    
    # Get metrics summary
    summary = orchestrator.get_metrics_summary()
    print(f"\nMetrics summary: {summary}")


if __name__ == "__main__":
    asyncio.run(main())
