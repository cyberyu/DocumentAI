"""
Standard Data Models for Adapter Dataflow

These models define the data contracts between all components in the RAG pipeline.
This ensures any component can be swapped without breaking the system.

Design Principles:
1. Software-stack agnostic: Works with Python SDKs, REST APIs, gRPC, CLI tools
2. Immutable where possible: Prevents side effects across component boundaries
3. Rich metadata: Supports debugging, lineage tracking, cost accounting
4. Forward compatible: Optional fields allow gradual migration
"""

from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid


# ============================================================================
# CORE DATA TYPES - Flow through the entire pipeline
# ============================================================================

@dataclass
class RawDocument:
    """
    Output from ETL providers (MinerU, Docling, Unstructured).
    Input to Chunkers.
    
    Represents a document after extraction but before chunking.
    Software-stack agnostic: Whether extracted via Python SDK, REST API, or CLI.
    """
    # Identity
    doc_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_path: str = ""  # Original file path or URL
    
    # Content
    content: str = ""  # Main text content (markdown, plain text, HTML)
    metadata: Dict[str, Any] = field(default_factory=dict)  # arbitrary key-value pairs
    
    # Structure (optional, provider-specific)
    sections: List[Dict[str, Any]] = field(default_factory=list)  # Hierarchical sections
    tables: List[Dict[str, Any]] = field(default_factory=list)  # Extracted table data
    images: List[Dict[str, Any]] = field(default_factory=list)  # Image metadata + base64/URLs
    formulas: List[str] = field(default_factory=list)  # LaTeX formulas (MinerU)
    code_blocks: List[Dict[str, str]] = field(default_factory=list)  # {language, code}
    
    # Lineage
    etl_provider: str = ""  # "mineru", "docling", "unstructured"
    extraction_timestamp: datetime = field(default_factory=datetime.utcnow)
    extraction_metadata: Dict[str, Any] = field(default_factory=dict)  # provider-specific info
    
    def __post_init__(self):
        """Ensure doc_id is always present"""
        if not self.doc_id:
            self.doc_id = str(uuid.uuid4())


@dataclass
class Chunk:
    """
    Output from Chunkers (hybrid_sandwich, recursive, semantic).
    Input to Embedding providers.
    
    Represents a piece of document suitable for embedding and retrieval.
    """
    # Identity
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str = ""  # Parent document ID
    
    # Content
    text: str = ""  # The actual chunk text
    token_count: int = 0  # Approximate token count
    
    # Position
    char_start: int = 0  # Character offset in original document
    char_end: int = 0
    chunk_index: int = 0  # Sequential index within document
    
    # Context (for sandwich chunking)
    prefix_context: str = ""  # Text before chunk (e.g., section headers)
    suffix_context: str = ""  # Text after chunk (e.g., next paragraph start)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)  # From parent doc + chunk-specific
    
    # Lineage
    chunking_strategy: str = ""  # "hybrid_sandwich", "recursive", etc.
    chunking_params: Dict[str, Any] = field(default_factory=dict)  # chunk_size, overlap, etc.
    
    def get_full_context(self) -> str:
        """Get chunk with surrounding context (for embedding)"""
        return f"{self.prefix_context}\n{self.text}\n{self.suffix_context}".strip()


@dataclass
class EmbeddedChunk:
    """
    Output from Embedding providers (OpenAI, Voyage, Cohere, FastEmbed).
    Input to Storage providers (OpenSearch, PostgreSQL).
    
    Represents a chunk with its vector embedding(s).
    """
    # From Chunk
    chunk: Chunk
    
    # Embeddings (can have multiple for hybrid strategies)
    embeddings: Dict[str, List[float]] = field(default_factory=dict)
    # Key: embedding_model_name (e.g., "text-embedding-3-large")
    # Value: vector (e.g., 3072-dim list)
    
    # Embedding metadata
    embedding_provider: str = ""  # "openai", "voyage", "cohere", etc.
    embedding_models: List[str] = field(default_factory=list)  # Models used
    embedding_dimensions: Dict[str, int] = field(default_factory=dict)  # {model: dim}
    
    # Cost tracking
    embedding_cost_usd: float = 0.0
    embedding_latency_ms: float = 0.0
    embedding_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Full-text search support
    searchable_text: str = ""  # Text for BM25 (may differ from chunk.text for optimization)
    
    def get_embedding(self, model_name: Optional[str] = None) -> List[float]:
        """Get embedding vector. If model_name is None, return first available."""
        if model_name:
            return self.embeddings.get(model_name, [])
        elif self.embeddings:
            return next(iter(self.embeddings.values()))
        return []


@dataclass
class Query:
    """
    Input to Retriever.
    Represents a user query with optional parameters.
    """
    # Query
    text: str = ""
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Search parameters (optional, may be overridden by config)
    top_k: Optional[int] = None
    min_score: Optional[float] = None
    filters: Dict[str, Any] = field(default_factory=dict)  # Metadata filters
    
    # Embedding (may be pre-computed or computed on-the-fly)
    embedding: Optional[Dict[str, List[float]]] = None  # {model: vector}
    
    # Context
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SearchResult:
    """
    Output from Retriever (hybrid RRF, vector-only, BM25-only).
    Input to Reranker.
    
    Represents a retrieved chunk with its relevance score.
    """
    # Content
    chunk: Chunk
    
    # Scores
    score: float = 0.0  # Combined score (from retrieval or reranking)
    vector_score: Optional[float] = None  # Raw vector similarity
    bm25_score: Optional[float] = None  # Raw BM25 score
    rrf_score: Optional[float] = None  # RRF combined score
    
    # Ranking
    rank: int = 0  # Position in results (1-indexed)
    
    # Metadata
    retrieval_method: str = ""  # "hybrid_rrf", "vector_only", "bm25_only"
    retrieval_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankedResult:
    """
    Output from Reranker (FlashRank, Cohere, Voyage).
    Input to Agent/LLM.
    
    Represents final ranked results ready for context assembly.
    """
    # From SearchResult
    search_result: SearchResult
    
    # Reranking
    rerank_score: float = 0.0  # Score from reranker
    rerank_rank: int = 0  # New position after reranking
    
    # Metadata
    reranker: str = ""  # "flashrank", "cohere", "voyage"
    reranker_model: str = ""  # Specific model used
    rerank_latency_ms: float = 0.0
    rerank_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalContext:
    """
    Final assembled context for LLM.
    Contains all retrieved + reranked results with metadata.
    """
    # Query
    query: Query
    
    # Results
    results: List[RerankedResult] = field(default_factory=list)
    
    # Performance metrics
    total_latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    rerank_latency_ms: float = 0.0
    
    # Cost tracking
    total_cost_usd: float = 0.0
    
    # Metadata
    retrieval_timestamp: datetime = field(default_factory=datetime.utcnow)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)  # Config used
    
    def format_for_llm(self, max_chunks: Optional[int] = None) -> str:
        """Format results as context string for LLM prompt"""
        results_to_use = self.results[:max_chunks] if max_chunks else self.results
        
        context_parts = []
        for i, reranked in enumerate(results_to_use, 1):
            chunk = reranked.search_result.chunk
            context_parts.append(
                f"[{i}] (score: {reranked.rerank_score:.3f})\n"
                f"{chunk.text}\n"
                f"Source: {chunk.metadata.get('source', 'N/A')}\n"
            )
        
        return "\n---\n".join(context_parts)
    
    def get_citations(self) -> List[Dict[str, Any]]:
        """Extract citation metadata for each result"""
        citations = []
        for reranked in self.results:
            chunk = reranked.search_result.chunk
            citations.append({
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "source": chunk.metadata.get("source", ""),
                "page": chunk.metadata.get("page"),
                "section": chunk.metadata.get("section"),
                "score": reranked.rerank_score,
            })
        return citations


# ============================================================================
# INDEXING PIPELINE DATA
# ============================================================================

@dataclass
class IndexingJob:
    """
    Represents a batch of documents being indexed.
    Used for tracking progress and debugging.
    """
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    documents: List[RawDocument] = field(default_factory=list)
    
    # Progress
    status: str = "pending"  # pending, running, completed, failed
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_stored: int = 0
    
    # Performance
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_cost_usd: float = 0.0
    
    # Errors
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    # Config
    config_snapshot: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ERROR HANDLING
# ============================================================================

class AdapterError(Exception):
    """Base exception for adapter-related errors"""
    pass


class ETLAdapterError(AdapterError):
    """Errors from ETL providers (file format, extraction failures)"""
    pass


class EmbeddingAdapterError(AdapterError):
    """Errors from embedding providers (API failures, rate limits)"""
    pass


class StorageAdapterError(AdapterError):
    """Errors from storage providers (connection, indexing failures)"""
    pass


class RetrievalAdapterError(AdapterError):
    """Errors from retrieval (search failures, timeout)"""
    pass


class RerankAdapterError(AdapterError):
    """Errors from rerankers"""
    pass


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_chunk_from_text(
    text: str,
    doc_id: str,
    chunk_index: int,
    metadata: Optional[Dict[str, Any]] = None,
    strategy: str = "manual"
) -> Chunk:
    """Helper to create a chunk from raw text"""
    return Chunk(
        text=text,
        doc_id=doc_id,
        chunk_index=chunk_index,
        token_count=len(text.split()),  # Rough approximation
        metadata=metadata or {},
        chunking_strategy=strategy,
    )


def merge_metadata(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to merge metadata dicts (override wins)"""
    result = base.copy()
    result.update(override)
    return result
