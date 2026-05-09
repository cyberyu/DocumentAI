"""
Multi-Embedding Document Processor

Generates multiple embeddings per chunk in parallel and stores them in OpenSearch.

Integration with existing SurfSense pipeline:
1. User selects embedding models during upload
2. Document is chunked (existing chunker)
3. Multiple embeddings generated in parallel (this module)
4. All embeddings stored in OpenSearch (multi-embedding storage)
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from adapter_base_classes import EmbeddingAdapter
from adapter_dataflow_models import Chunk, EmbeddedChunk
from adapter_examples import FastEmbedAdapter, OpenAIEmbeddingAdapter
from opensearch_multi_embedding_storage import (
    EMBEDDING_MODELS,
    MultiEmbeddingOpenSearchStorage,
)

logger = logging.getLogger(__name__)


class MultiEmbeddingProcessor:
    """
    Generate and store multiple embeddings per chunk.
    
    Supports:
    - Parallel embedding generation
    - Progress tracking
    - Cost calculation
    - Error handling per model
    """

    def __init__(self, opensearch_storage: MultiEmbeddingOpenSearchStorage):
        """Initialize with OpenSearch storage."""
        self.storage = opensearch_storage
        self._embedding_adapters: Dict[str, EmbeddingAdapter] = {}

    @staticmethod
    def _normalize_model_key(model_key: str) -> str:
        aliases = {
            "sentence-transformers/all-MiniLM-L6-v2": "fastembed/all-MiniLM-L6-v2",
            "BAAI/bge-small-en-v1.5": "fastembed/bge-base-en-v1.5",
        }
        return aliases.get(model_key, model_key)

    @staticmethod
    def _resolve_fastembed_model_name(model_key: str) -> str:
        fastembed_model_names = {
            "fastembed/all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
            "fastembed/bge-base-en-v1.5": "BAAI/bge-base-en-v1.5",
            "fastembed/bge-large-en-v1.5": "BAAI/bge-large-en-v1.5",
        }
        return fastembed_model_names.get(model_key, model_key.split("/", 1)[-1])

    @staticmethod
    def _normalize_chunks(chunks: List[Any], document_id: int) -> List[Chunk]:
        normalized_chunks: List[Chunk] = []
        for idx, chunk in enumerate(chunks):
            if isinstance(chunk, Chunk):
                normalized_chunks.append(chunk)
                continue

            if isinstance(chunk, dict):
                text = chunk.get("text") or chunk.get("content") or ""
                metadata = chunk.get("metadata") or {}
                doc_id = str(
                    chunk.get("doc_id")
                    or chunk.get("document_id")
                    or metadata.get("document_id")
                    or document_id
                )
                normalized_chunks.append(
                    Chunk(
                        chunk_id=str(chunk.get("chunk_id") or f"{document_id}_{idx}"),
                        doc_id=doc_id,
                        text=text,
                        token_count=int(chunk.get("token_count") or len(text.split())),
                        chunk_index=int(chunk.get("chunk_index") or idx),
                        metadata=metadata,
                    )
                )
                continue

            raise TypeError(f"Unsupported chunk type: {type(chunk)}")

        return normalized_chunks

    def _get_adapter(self, model_key: str) -> Optional[EmbeddingAdapter]:
        """
        Get or create embedding adapter for a model.
        
        Args:
            model_key: Model identifier (e.g., "openai/text-embedding-3-large")
            
        Returns:
            EmbeddingAdapter instance or None if unsupported
        """
        model_key = self._normalize_model_key(model_key)

        if model_key in self._embedding_adapters:
            return self._embedding_adapters[model_key]

        if model_key not in EMBEDDING_MODELS:
            logger.error(f"Unknown embedding model: {model_key}")
            return None

        model_info = EMBEDDING_MODELS[model_key]
        provider = model_info["provider"]
        model_name = model_key.split("/", 1)[1]  # Extract model name from key

        try:
            if provider == "fastembed":
                adapter = FastEmbedAdapter(
                    {
                        "model": self._resolve_fastembed_model_name(model_key),
                        "cache_dir": "./models",
                    }
                )
            elif provider == "openai":
                adapter = OpenAIEmbeddingAdapter(
                    {
                        "api_key": None,  # Will use env var OPENAI_API_KEY
                        "model": model_name,
                    }
                )
            elif provider == "voyage":
                # TODO: Add VoyageEmbeddingAdapter
                logger.warning(f"Voyage adapter not yet implemented, skipping {model_key}")
                return None
            elif provider == "cohere":
                # TODO: Add CohereEmbeddingAdapter
                logger.warning(f"Cohere adapter not yet implemented, skipping {model_key}")
                return None
            elif provider == "google":
                # TODO: Add GoogleEmbeddingAdapter
                logger.warning(f"Google adapter not yet implemented, skipping {model_key}")
                return None
            elif provider == "jina":
                # TODO: Add JinaEmbeddingAdapter
                logger.warning(f"Jina adapter not yet implemented, skipping {model_key}")
                return None
            else:
                logger.error(f"Unsupported provider: {provider}")
                return None

            self._embedding_adapters[model_key] = adapter
            logger.info(f"Created adapter for {model_key}")
            return adapter

        except Exception as e:
            logger.error(f"Failed to create adapter for {model_key}: {e}")
            return None

    async def embed_chunks_parallel(
        self,
        chunks: List[Chunk],
        model_keys: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Generate embeddings for chunks using multiple models in parallel.

        Args:
            chunks: List of Chunk objects
            model_keys: List of embedding model keys to use

        Returns:
            List of dicts ready for OpenSearch indexing:
            [
                {
                    "chunk_id": "abc123",
                    "document_id": 1,
                    "content": "Revenue was $65.6B...",
                    "embeddings": {
                        "openai/text-embedding-3-large": [0.023, ...],
                        "voyage/voyage-finance-2": [0.012, ...],
                    },
                    "metadata": {...}
                },
                ...
            ]
        """
        logger.info(f"Generating embeddings for {len(chunks)} chunks using {len(model_keys)} models")
        
        # Create tasks for parallel embedding
        tasks = []
        task_model_keys = []
        for model_key in model_keys:
            adapter = self._get_adapter(model_key)
            if adapter:
                task = self._embed_with_model(chunks, model_key, adapter)
                tasks.append(task)
                task_model_keys.append(model_key)

        if not tasks:
            logger.warning("No valid embedding adapters available for requested models")
            return []
        
        # Run all embeddings in parallel
        start_time = time.time()
        all_embedded_results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = (time.time() - start_time) * 1000  # ms
        
        # Combine results
        chunks_with_embeddings = []
        total_cost = 0.0
        successful_models = []

        # Initialize result structure
        for i, chunk in enumerate(chunks):
            chunks_with_embeddings.append({
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.doc_id,
                "content": chunk.text,
                "embeddings": {},
                "metadata": chunk.metadata or {},
            })

        # Merge embeddings from each model
        for model_key, result in zip(task_model_keys, all_embedded_results):
            if isinstance(result, Exception):
                logger.error(f"Embedding failed for {model_key}: {result}")
                continue
            
            if not result or "embeddings" not in result:
                logger.warning(f"No embeddings returned for {model_key}")
                continue

            # Add embeddings to chunks
            for i, embedded_chunk in enumerate(result["embeddings"]):
                chunks_with_embeddings[i]["embeddings"][model_key] = embedded_chunk.get_embedding()
            
            total_cost += result.get("cost", 0.0)
            successful_models.append(model_key)

        logger.info(
            f"Multi-embedding complete: {len(successful_models)}/{len(model_keys)} models succeeded, "
            f"total cost: ${total_cost:.4f}, total time: {total_time:.0f}ms"
        )

        return chunks_with_embeddings

    async def _embed_with_model(
        self,
        chunks: List[Chunk],
        model_key: str,
        adapter: EmbeddingAdapter,
    ) -> Dict[str, Any]:
        """
        Generate embeddings for chunks using a single model.

        Returns:
            {
                "model_key": "openai/text-embedding-3-large",
                "embeddings": [EmbeddedChunk, ...],
                "cost": 0.0013,
                "latency_ms": 245.3
            }
        """
        start_time = time.time()
        
        try:
            # Generate embeddings (adapter handles batching)
            embedded_chunks = adapter.embed_chunks(chunks)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Calculate total cost
            total_cost = sum(ec.embedding_cost_usd for ec in embedded_chunks)
            
            logger.info(
                f"  {model_key}: {len(embedded_chunks)} chunks, "
                f"${total_cost:.4f}, {latency_ms:.0f}ms"
            )
            
            return {
                "model_key": model_key,
                "embeddings": embedded_chunks,
                "cost": total_cost,
                "latency_ms": latency_ms,
            }
            
        except Exception as e:
            logger.error(f"Embedding failed for {model_key}: {e}")
            raise

    async def process_and_store_document(
        self,
        chunks: List[Any],
        model_keys: List[str],
        document_id: int,
        search_space_id: int,
        chunking_strategy: str | None = None,
        pipeline_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Full pipeline: Generate embeddings + Store in OpenSearch.

        Args:
            chunks: Chunked document
            model_keys: Embedding models to use
            document_id: Document ID
            search_space_id: Search space ID

        Returns:
            Processing summary with metrics
        """
        normalized_chunks = self._normalize_chunks(chunks, document_id=document_id)
        normalized_model_keys = []
        for model_key in model_keys:
            normalized_key = self._normalize_model_key(model_key)
            if normalized_key in EMBEDDING_MODELS:
                normalized_model_keys.append(normalized_key)
            else:
                logger.warning(f"Unknown embedding model after normalization: {model_key}")

        # Step 1: Ensure index exists with selected models
        await self.storage.create_index_multi_embedding(
            search_space_id=search_space_id,
            embedding_models=normalized_model_keys,
            chunking_strategy=chunking_strategy,
        )

        # Step 2: Generate embeddings in parallel
        chunks_with_embeddings = await self.embed_chunks_parallel(
            normalized_chunks,
            normalized_model_keys,
        )

        # Step 3: Store in OpenSearch (inject pipeline_id into each chunk)
        if pipeline_id:
            for c in chunks_with_embeddings:
                c["pipeline_id"] = pipeline_id
        success, failed = await self.storage.index_chunks_multi_embedding(
            chunks=chunks_with_embeddings,
            search_space_id=search_space_id,
            chunking_strategy=chunking_strategy,
        )

        # Calculate metrics
        total_cost = sum(
            EMBEDDING_MODELS[mk]["cost_per_1m_tokens"] * sum(len(c["content"].split()) for c in chunks_with_embeddings) / 1_000_000
            for mk in normalized_model_keys
            if mk in EMBEDDING_MODELS
        )

        summary = {
            "document_id": document_id,
            "search_space_id": search_space_id,
            "chunking_strategy": chunking_strategy,
            "chunks_processed": len(normalized_chunks),
            "embedding_models_used": normalized_model_keys,
            "chunks_indexed": success,
            "chunks_failed": failed,
            "total_cost_usd": total_cost,
            "status": "success" if failed == 0 else "partial_success",
        }

        logger.info(f"Document {document_id} processed: {summary}")
        return summary


# Example usage function
async def example_multi_embedding_workflow():
    """Example of using multi-embedding processor."""
    
    # Initialize storage
    storage = MultiEmbeddingOpenSearchStorage(
        hosts=["http://localhost:9200"],
        index_prefix="surfsense"
    )
    
    # Initialize processor
    processor = MultiEmbeddingProcessor(storage)
    
    # Example chunks (normally from document chunker)
    chunks = [
        Chunk(
            chunk_id="chunk_001",
            document_id=1,
            text="Microsoft reported Q1 FY26 revenue of $65.6 billion, up 16% year-over-year.",
            token_count=20,
            chunk_index=0,
        ),
        Chunk(
            chunk_id="chunk_002",
            document_id=1,
            text="Intelligent Cloud revenue was $28.5 billion, representing 20% growth.",
            token_count=15,
            chunk_index=1,
        ),
    ]
    
    # User selected these embedding models during upload
    selected_models = [
        "fastembed/bge-base-en-v1.5",           # FREE
        "openai/text-embedding-3-large",        # Best quality
        "voyage/voyage-finance-2",              # Domain-specific
    ]
    
    # Process and store
    summary = await processor.process_and_store_document(
        chunks=chunks,
        model_keys=selected_models,
        document_id=1,
        search_space_id=1,
    )
    
    print(f"Processing complete: {summary}")


if __name__ == "__main__":
    asyncio.run(example_multi_embedding_workflow())
