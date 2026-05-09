"""
Base Adapter Classes - The Foundation of Adaptability

These abstract base classes define the interfaces that ALL adapters must implement.
This enables any component to be swapped without breaking the system.

Design Principles:
1. **Dependency Inversion**: Depend on abstractions, not concrete implementations
2. **Liskov Substitution**: Any adapter can replace another of the same type
3. **Interface Segregation**: Small, focused interfaces
4. **Open/Closed**: Open for extension (new adapters), closed for modification (base interfaces)

Software Stack Support:
- Python SDKs: Direct integration (MinerU, FastEmbed, FlashRank)
- REST APIs: HTTP client wrappers (OpenAI, Cohere, Voyage)
- gRPC: Proto-based clients (if needed)
- CLI tools: Subprocess wrappers (if needed)
- Docker services: Network calls (OpenSearch, PostgreSQL)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, BinaryIO
from pathlib import Path

from adapter_dataflow_models import (
    RawDocument,
    Chunk,
    EmbeddedChunk,
    Query,
    SearchResult,
    RerankedResult,
    RetrievalContext,
    IndexingJob,
    AdapterError,
    ETLAdapterError,
    EmbeddingAdapterError,
    StorageAdapterError,
    RetrievalAdapterError,
    RerankAdapterError,
)


# ============================================================================
# ETL ADAPTERS - From files to RawDocument
# ============================================================================

class ETLAdapter(ABC):
    """
    Base class for all ETL providers.
    
    Adapts different document extraction libraries/services:
    - MinerU (Python SDK): Advanced PDF table/formula extraction
    - Docling (Python SDK): Fast multi-format conversion
    - Unstructured (Python SDK/API): Broad format support
    
    Contract: Any file_path/binary input → RawDocument output
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_name = self.__class__.__name__.replace("Adapter", "").lower()
    
    @abstractmethod
    def extract_from_file(self, file_path: Path, **kwargs) -> RawDocument:
        """
        Extract content from a file on disk.
        
        Args:
            file_path: Path to document file
            **kwargs: Provider-specific options
            
        Returns:
            RawDocument with extracted content
            
        Raises:
            ETLAdapterError: If extraction fails
        """
        pass
    
    @abstractmethod
    def extract_from_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        **kwargs
    ) -> RawDocument:
        """
        Extract content from bytes (for uploaded files).
        
        Args:
            file_bytes: Raw file bytes
            filename: Original filename (for format detection)
            **kwargs: Provider-specific options
            
        Returns:
            RawDocument with extracted content
        """
        pass
    
    @abstractmethod
    def supported_formats(self) -> List[str]:
        """
        Return list of supported file extensions.
        
        Returns:
            List like [".pdf", ".docx", ".html"]
        """
        pass
    
    def can_handle(self, file_path: Path) -> bool:
        """Check if this adapter can handle the file"""
        return file_path.suffix.lower() in self.supported_formats()
    
    @abstractmethod
    def estimate_cost(self, file_path: Path) -> float:
        """
        Estimate processing cost in USD.
        
        Returns 0.0 for local/free providers.
        For API-based providers, estimate based on file size/pages.
        """
        pass
    
    def cleanup(self):
        """Override to clean up resources (temp files, connections)"""
        pass


# ============================================================================
# CHUNKING ADAPTERS - From RawDocument to Chunks
# ============================================================================

class ChunkingAdapter(ABC):
    """
    Base class for chunking strategies.
    
    Adapts different chunking approaches:
    - Hybrid Sandwich: Context-aware with prefix/suffix
    - Recursive: Character-based with overlap
    - Semantic: Sentence-boundary aware
    - Code-aware: Respects code structure
    
    Contract: RawDocument → List[Chunk]
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.chunk_size = config.get("chunk_size", 512)
        self.overlap = config.get("overlap", 50)
        self.strategy_name = self.__class__.__name__.replace("Chunker", "").lower()
    
    @abstractmethod
    def chunk_document(self, document: RawDocument) -> List[Chunk]:
        """
        Split document into chunks.
        
        Args:
            document: RawDocument to chunk
            
        Returns:
            List of Chunk objects
        """
        pass
    
    def estimate_chunk_count(self, document: RawDocument) -> int:
        """Estimate how many chunks will be created (for cost estimation)"""
        text_length = len(document.content)
        return max(1, text_length // self.chunk_size)


# ============================================================================
# EMBEDDING ADAPTERS - From Chunks to EmbeddedChunks
# ============================================================================

class EmbeddingAdapter(ABC):
    """
    Base class for embedding providers.
    
    Adapts different embedding services/libraries:
    - OpenAI (REST API): text-embedding-3-large (3072 dims)
    - Voyage (REST API): voyage-finance-2 (32K context)
    - Cohere (REST API): embed-english-v3.0 (binary compression)
    - FastEmbed (Python SDK): Local, free models
    - Google (REST API): text-embedding-004
    - Jina (REST API): jina-embeddings-v3
    
    Contract: List[Chunk] → List[EmbeddedChunk]
    
    Software Stack Handling:
    - REST APIs: Use requests/httpx with retry logic
    - Python SDKs: Direct import and method calls
    - Batch optimization: Group requests to minimize API calls
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model", "")
        self.dimensions = config.get("dimensions", 0)
        self.provider_name = self.__class__.__name__.replace("Adapter", "").lower()
        self.batch_size = config.get("batch_size", 100)
    
    @abstractmethod
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """
        Generate embeddings for chunks.
        
        Args:
            chunks: List of Chunk objects
            
        Returns:
            List of EmbeddedChunk objects with embeddings
            
        Raises:
            EmbeddingAdapterError: If embedding fails
            
        Notes:
            - Should handle batching internally for efficiency
            - Should include cost tracking in EmbeddedChunk
            - Should handle rate limits with exponential backoff
        """
        pass
    
    @abstractmethod
    def embed_query(self, query_text: str) -> List[float]:
        """
        Generate embedding for a single query.
        
        Args:
            query_text: Query string
            
        Returns:
            Embedding vector (list of floats)
        """
        pass
    
    @abstractmethod
    def get_dimensions(self) -> int:
        """Return embedding dimensions for this model"""
        pass
    
    @abstractmethod
    def estimate_cost(self, num_tokens: int) -> float:
        """
        Estimate embedding cost in USD.
        
        Args:
            num_tokens: Number of tokens to embed
            
        Returns:
            Cost in USD (0.0 for local/free models)
        """
        pass
    
    def supports_batching(self) -> bool:
        """Whether this adapter supports batch embedding"""
        return True
    
    def cleanup(self):
        """Override to clean up resources (close connections, free GPU memory)"""
        pass


# ============================================================================
# STORAGE ADAPTERS - From EmbeddedChunks to persistent storage
# ============================================================================

class StorageAdapter(ABC):
    """
    Base class for vector storage providers.
    
    Adapts different storage backends:
    - OpenSearch (Docker service): k-NN + BM25, multiple embeddings
    - PostgreSQL (Docker service): pgvector extension
    - Qdrant (Docker service/Cloud): Specialized vector DB
    - Weaviate (Docker service/Cloud): GraphQL API
    
    Contract: Store EmbeddedChunks, retrieve by vector/keyword/hybrid
    
    Software Stack Handling:
    - Docker services: HTTP/TCP clients (opensearch-py, psycopg2)
    - Cloud services: SDK clients with authentication
    - Connection pooling for efficiency
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider_name = self.__class__.__name__.replace("Adapter", "").lower()
        self.index_name = config.get("index_name", "rag_chunks")
    
    @abstractmethod
    def create_index(self, embedding_dimensions: int, **kwargs):
        """
        Create/configure index for storage.
        
        Args:
            embedding_dimensions: Dimension of embedding vectors
            **kwargs: Provider-specific configuration
        """
        pass
    
    @abstractmethod
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int = 100):
        """
        Store embedded chunks in index.
        
        Args:
            chunks: List of EmbeddedChunk objects
            batch_size: Batch size for bulk indexing
            
        Raises:
            StorageAdapterError: If indexing fails
        """
        pass
    
    @abstractmethod
    def delete_by_doc_id(self, doc_id: str):
        """Delete all chunks belonging to a document"""
        pass
    
    @abstractmethod
    def clear_index(self):
        """Delete all data from index"""
        pass
    
    def get_index_stats(self) -> Dict[str, Any]:
        """Return index statistics (count, size, etc.)"""
        return {}
    
    def cleanup(self):
        """Override to close connections"""
        pass


# ============================================================================
# RETRIEVAL ADAPTERS - From Query to SearchResults
# ============================================================================

class RetrievalAdapter(ABC):
    """
    Base class for retrieval strategies.
    
    Adapts different search approaches:
    - Hybrid RRF: Combines vector + BM25 with Reciprocal Rank Fusion
    - Vector-only: Pure semantic search
    - BM25-only: Pure keyword search
    - Multi-stage: Fast filtering → precise ranking
    
    Contract: Query → List[SearchResult]
    """
    
    def __init__(self, config: Dict[str, Any], storage: StorageAdapter, embedding: EmbeddingAdapter):
        self.config = config
        self.storage = storage
        self.embedding = embedding
        self.strategy_name = self.__class__.__name__.replace("Retriever", "").lower()
    
    @abstractmethod
    def search(self, query: Query, top_k: int = 10) -> List[SearchResult]:
        """
        Execute search and return results.
        
        Args:
            query: Query object (may include pre-computed embedding)
            top_k: Number of results to return
            
        Returns:
            List of SearchResult objects, sorted by score (descending)
        """
        pass
    
    def prepare_query_embedding(self, query: Query) -> Query:
        """
        Helper to compute query embedding if not present.
        
        Args:
            query: Query object
            
        Returns:
            Query with embedding populated
        """
        if query.embedding is None:
            embedding_vector = self.embedding.embed_query(query.text)
            query.embedding = {self.embedding.model_name: embedding_vector}
        return query


# ============================================================================
# RERANKING ADAPTERS - From SearchResults to RerankedResults
# ============================================================================

class RerankingAdapter(ABC):
    """
    Base class for reranking models.
    
    Adapts different rerankers:
    - FlashRank (Python SDK): Fast local reranking (ms-marco models)
    - Cohere (REST API): rerank-english-v3.0 API
    - Voyage (REST API): rerank-lite-1 API
    - Cross-encoders (Python SDK): Sentence-transformers models
    
    Contract: Query + List[SearchResult] → List[RerankedResult]
    
    Software Stack Handling:
    - Local models: Direct inference
    - API services: HTTP calls with batching
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model", "")
        self.provider_name = self.__class__.__name__.replace("Reranker", "").lower()
    
    @abstractmethod
    def rerank(
        self,
        query: Query,
        results: List[SearchResult],
        top_k: Optional[int] = None
    ) -> List[RerankedResult]:
        """
        Rerank search results.
        
        Args:
            query: Original query
            results: Initial search results
            top_k: Number of top results to return (None = return all)
            
        Returns:
            List of RerankedResult objects, sorted by rerank_score (descending)
        """
        pass
    
    @abstractmethod
    def estimate_cost(self, num_pairs: int) -> float:
        """
        Estimate reranking cost in USD.
        
        Args:
            num_pairs: Number of (query, document) pairs to rerank
            
        Returns:
            Cost in USD (0.0 for local models)
        """
        pass


# ============================================================================
# ADAPTER FACTORY - Dynamic loading based on configuration
# ============================================================================

class AdapterFactory:
    """
    Factory for creating adapter instances based on configuration.
    
    This enables dynamic component swapping at runtime without code changes.
    """
    
    # Registry: Maps provider names to adapter classes
    etl_adapters: Dict[str, type] = {}
    chunking_adapters: Dict[str, type] = {}
    embedding_adapters: Dict[str, type] = {}
    storage_adapters: Dict[str, type] = {}
    retrieval_adapters: Dict[str, type] = {}
    reranking_adapters: Dict[str, type] = {}
    
    @classmethod
    def register_etl(cls, name: str, adapter_class: type):
        """Register an ETL adapter"""
        cls.etl_adapters[name] = adapter_class
    
    @classmethod
    def register_chunking(cls, name: str, adapter_class: type):
        """Register a chunking adapter"""
        cls.chunking_adapters[name] = adapter_class
    
    @classmethod
    def register_embedding(cls, name: str, adapter_class: type):
        """Register an embedding adapter"""
        cls.embedding_adapters[name] = adapter_class
    
    @classmethod
    def register_storage(cls, name: str, adapter_class: type):
        """Register a storage adapter"""
        cls.storage_adapters[name] = adapter_class
    
    @classmethod
    def register_retrieval(cls, name: str, adapter_class: type):
        """Register a retrieval adapter"""
        cls.retrieval_adapters[name] = adapter_class
    
    @classmethod
    def register_reranking(cls, name: str, adapter_class: type):
        """Register a reranking adapter"""
        cls.reranking_adapters[name] = adapter_class
    
    @classmethod
    def create_etl(cls, provider: str, config: Dict[str, Any]) -> ETLAdapter:
        """Create ETL adapter instance"""
        if provider not in cls.etl_adapters:
            raise ValueError(f"Unknown ETL provider: {provider}. Available: {list(cls.etl_adapters.keys())}")
        return cls.etl_adapters[provider](config)
    
    @classmethod
    def create_embedding(cls, provider: str, config: Dict[str, Any]) -> EmbeddingAdapter:
        """Create embedding adapter instance"""
        if provider not in cls.embedding_adapters:
            raise ValueError(f"Unknown embedding provider: {provider}")
        return cls.embedding_adapters[provider](config)
    
    @classmethod
    def create_storage(cls, provider: str, config: Dict[str, Any]) -> StorageAdapter:
        """Create storage adapter instance"""
        if provider not in cls.storage_adapters:
            raise ValueError(f"Unknown storage provider: {provider}")
        return cls.storage_adapters[provider](config)
    
    @classmethod
    def create_retrieval(
        cls,
        strategy: str,
        config: Dict[str, Any],
        storage: StorageAdapter,
        embedding: EmbeddingAdapter
    ) -> RetrievalAdapter:
        """Create retrieval adapter instance"""
        if strategy not in cls.retrieval_adapters:
            raise ValueError(f"Unknown retrieval strategy: {strategy}")
        return cls.retrieval_adapters[strategy](config, storage, embedding)
    
    @classmethod
    def create_reranking(cls, provider: str, config: Dict[str, Any]) -> RerankingAdapter:
        """Create reranking adapter instance"""
        if provider not in cls.reranking_adapters:
            raise ValueError(f"Unknown reranking provider: {provider}")
        return cls.reranking_adapters[provider](config)


# ============================================================================
# UTILITY ADAPTERS - For special cases
# ============================================================================

class TransformationAdapter(ABC):
    """
    Base class for post-ETL transformations.
    
    Applied between ETL and chunking to normalize/enhance content:
    - clean_whitespace, normalize_headers, merge_split_sentences, etc.
    
    Contract: RawDocument → RawDocument (transformed)
    """
    
    @abstractmethod
    def transform(self, document: RawDocument) -> RawDocument:
        """Apply transformation to document"""
        pass


class FilterAdapter(ABC):
    """
    Base class for filtering logic (metadata-based, score-based).
    
    Contract: List[T] → List[T] (filtered subset)
    """
    
    @abstractmethod
    def filter(self, items: List[Any], criteria: Dict[str, Any]) -> List[Any]:
        """Apply filter to items"""
        pass
