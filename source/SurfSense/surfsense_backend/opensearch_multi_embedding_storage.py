"""
OpenSearch Multi-Embedding Storage

Extension of opensearch_chunk_storage.py that supports storing multiple
embeddings per chunk for A/B testing and model comparison.

Features:
- Multiple knn_vector fields per document (one per embedding model)
- Dynamic index creation based on selected models
- Parallel embedding generation
- Model performance comparison
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import RequestError
from opensearchpy.helpers import async_bulk

logger = logging.getLogger(__name__)


# Available embedding models with metadata
EMBEDDING_MODELS = {
    # Local (FastEmbed) - FREE
    "fastembed/all-MiniLM-L6-v2": {
        "provider": "fastembed",
        "dimensions": 384,
        "cost_per_1m_tokens": 0.0,
        "max_seq_length": 256,
        "description": "Fast, general-purpose, offline"
    },
    "fastembed/bge-base-en-v1.5": {
        "provider": "fastembed",
        "dimensions": 768,
        "cost_per_1m_tokens": 0.0,
        "max_seq_length": 512,
        "description": "Balanced quality/speed"
    },
    "fastembed/bge-large-en-v1.5": {
        "provider": "fastembed",
        "dimensions": 1024,
        "cost_per_1m_tokens": 0.0,
        "max_seq_length": 512,
        "description": "Best local quality"
    },
    
    # OpenAI - High Quality
    "openai/text-embedding-3-small": {
        "provider": "openai",
        "dimensions": 1536,
        "cost_per_1m_tokens": 0.02,
        "max_seq_length": 8192,
        "description": "Cost-effective cloud"
    },
    "openai/text-embedding-3-large": {
        "provider": "openai",
        "dimensions": 3072,
        "cost_per_1m_tokens": 0.13,
        "max_seq_length": 8192,
        "description": "Highest quality (3K dims!)"
    },
    
    # Voyage - Domain-Specific
    "voyage/voyage-finance-2": {
        "provider": "voyage",
        "dimensions": 1024,
        "cost_per_1m_tokens": 0.12,
        "max_seq_length": 32000,
        "description": "Financial documents (32K context)"
    },
    "voyage/voyage-law-2": {
        "provider": "voyage",
        "dimensions": 1024,
        "cost_per_1m_tokens": 0.12,
        "max_seq_length": 16000,
        "description": "Legal documents"
    },
    "voyage/voyage-code-2": {
        "provider": "voyage",
        "dimensions": 1536,
        "cost_per_1m_tokens": 0.12,
        "max_seq_length": 16000,
        "description": "Code/technical"
    },
    
    # Cohere - Compression
    "cohere/embed-english-v3.0": {
        "provider": "cohere",
        "dimensions": 1024,
        "cost_per_1m_tokens": 0.10,
        "max_seq_length": 512,
        "description": "Binary compression"
    },
    
    # Google - Cost-Effective
    "google/text-embedding-004": {
        "provider": "google",
        "dimensions": 768,
        "cost_per_1m_tokens": 0.01,
        "max_seq_length": 2048,
        "description": "Very cheap"
    },
    
    # Jina - Long Context
    "jina/jina-embeddings-v2-base": {
        "provider": "jina",
        "dimensions": 768,
        "cost_per_1m_tokens": 0.02,
        "max_seq_length": 8192,
        "description": "Long context"
    },
}


class MultiEmbeddingOpenSearchStorage:
    """
    OpenSearch storage supporting multiple embeddings per chunk.
    
    Each embedding model gets its own knn_vector field in the index schema.
    This enables:
    - A/B testing different embedding models
    - Model comparison on same corpus
    - Retrieval strategy experimentation
    """

    def __init__(
        self,
        hosts: List[str],
        index_prefix: str = "surfsense",
        use_ssl: bool = False,
        verify_certs: bool = False,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize OpenSearch client."""
        client_kwargs = {
            "hosts": hosts,
            "use_ssl": use_ssl,
            "verify_certs": verify_certs,
        }

        if username and password:
            client_kwargs["http_auth"] = (username, password)

        self.client = AsyncOpenSearch(**client_kwargs)
        self.index_prefix = index_prefix
        logger.info(f"Initialized Multi-Embedding OpenSearch client with hosts: {hosts}")

    async def close(self) -> None:
        """Close underlying AsyncOpenSearch client/session."""
        await self.client.close()

    @staticmethod
    def _normalize_strategy_name(chunking_strategy: str) -> str:
        strategy_aliases = {
            "sandwich_chunk": "sandwitch_chunk",
            "hybrid_sandwich": "sandwitch_chunk",
        }
        normalized = (chunking_strategy or "chunk_text").strip().lower()
        normalized = strategy_aliases.get(normalized, normalized)
        return normalized.replace("-", "_")

    def _get_index_name(
        self,
        search_space_id: int,
        chunking_strategy: str | None = None,
    ) -> str:
        """Get index name for a search space and optional chunking strategy."""
        if not chunking_strategy:
            return f"{self.index_prefix}_chunks_{search_space_id}"

        strategy_suffix = self._normalize_strategy_name(chunking_strategy)
        return f"{self.index_prefix}_chunks_{search_space_id}_{strategy_suffix}"
    
    def _get_field_name(self, model_key: str) -> str:
        """
        Convert model key to OpenSearch field name.
        
        Example: "openai/text-embedding-3-large" → "embedding_openai_3_large"
        """
        # Replace / and - with _
        field_name = model_key.replace("/", "_").replace("-", "_")
        return f"embedding_{field_name}"

    async def create_index_multi_embedding(
        self,
        search_space_id: int,
        embedding_models: List[str],
        chunking_strategy: str | None = None,
        ef_construction: int = 128,
        m: int = 16,
    ):
        """
        Create OpenSearch index with multiple knn_vector fields.

        Args:
            search_space_id: The search space ID
            embedding_models: List of model keys (e.g., ["openai/text-embedding-3-large", "voyage/voyage-finance-2"])
            ef_construction: HNSW ef_construction parameter
            m: HNSW m parameter

        Index Schema Example:
        {
            "chunk_id": "abc123",
            "document_id": 1,
            "content": "Revenue was $65.6B...",
            "embedding_openai_text_embedding_3_large": [0.023, -0.145, ...],  # 3072 dims
            "embedding_voyage_voyage_finance_2": [0.012, -0.089, ...],        # 1024 dims
            "embedding_fastembed_bge_base_en_v1_5": [0.001, -0.234, ...],    # 768 dims
            "metadata": {...},
            "indexed_at": "2026-05-04T..."
        }
        """
        index_name = self._get_index_name(search_space_id, chunking_strategy)

        # Check if index already exists
        if await self.client.indices.exists(index=index_name):
            logger.info(f"Index {index_name} already exists")
            return

        # Build properties with multiple embedding fields
        properties = {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "pipeline_id": {"type": "keyword"},
            "chunking_strategy": {"type": "keyword"},
            "chunk_size": {"type": "integer"},
            "embedding_models": {"type": "keyword"},
            "embedding_model_count": {"type": "integer"},
            "content": {
                "type": "text",
                "analyzer": "english",
            },
            "metadata": {
                "type": "object",
                "enabled": True,
            },
            "indexed_at": {"type": "date"},
        }

        # Add knn_vector field for each embedding model
        for model_key in embedding_models:
            if model_key not in EMBEDDING_MODELS:
                logger.warning(f"Unknown embedding model: {model_key}, skipping")
                continue
            
            model_info = EMBEDDING_MODELS[model_key]
            field_name = self._get_field_name(model_key)
            
            properties[field_name] = {
                "type": "knn_vector",
                "dimension": model_info["dimensions"],
                "method": {
                    "name": "hnsw",
                    "space_type": "innerproduct",
                    "engine": "faiss",
                    "parameters": {
                        "ef_construction": ef_construction,
                        "m": m,
                    },
                },
            }
            logger.info(
                f"  Added embedding field: {field_name} ({model_info['dimensions']} dims)"
            )

        # Create index
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100,
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                },
            },
            "mappings": {"properties": properties},
        }

        try:
            await self.client.indices.create(index=index_name, body=index_body)
            logger.info(
                f"Created multi-embedding index {index_name} with {len(embedding_models)} embedding models"
            )
        except RequestError as exc:
            if getattr(exc, "error", None) == "resource_already_exists_exception":
                logger.info(
                    "Index %s was created concurrently by another worker", index_name
                )
                return
            raise

    async def index_chunks_multi_embedding(
        self,
        chunks: List[Dict[str, Any]],
        search_space_id: int,
        chunking_strategy: str | None = None,
        batch_size: int = 100,
    ) -> Tuple[int, int]:
        """
        Bulk index chunks with multiple embeddings.

        Args:
            chunks: List of chunk dictionaries with keys:
                - chunk_id: Unique identifier
                - document_id: Parent document ID
                - content: Text content
                - embeddings: Dict[model_key, vector] e.g.,
                  {
                    "openai/text-embedding-3-large": [0.023, -0.145, ...],
                    "voyage/voyage-finance-2": [0.012, -0.089, ...],
                  }
                - metadata: Optional metadata dict
            search_space_id: The search space ID
            batch_size: Number of chunks per bulk request

        Returns:
            Tuple of (success_count, failed_count)
        """
        index_name = self._get_index_name(search_space_id, chunking_strategy)

        # Prepare bulk actions
        actions = []
        for chunk in chunks:
            metadata = chunk.get("metadata", {}) or {}
            chunk_strategy = (
                chunking_strategy
                or metadata.get("chunking_strategy")
                or "unknown"
            )
            embeddings = chunk.get("embeddings", {}) or {}
            embedding_models = sorted(embeddings.keys())

            # Base document
            doc = {
                "chunk_id": chunk["chunk_id"],
                "document_id": str(chunk["document_id"]),
                "pipeline_id": chunk.get("pipeline_id") or str(chunk["document_id"]),
                "chunking_strategy": chunk_strategy,
                "chunk_size": metadata.get("chunk_size"),
                "embedding_models": embedding_models,
                "embedding_model_count": len(embedding_models),
                "content": chunk["content"],
                "metadata": metadata,
                "indexed_at": chunk.get("indexed_at", datetime.utcnow().isoformat()),
            }
            
            # Add each embedding as a separate field
            for model_key, vector in embeddings.items():
                field_name = self._get_field_name(model_key)
                doc[field_name] = vector
            
            action = {
                "_index": index_name,
                "_id": chunk["chunk_id"],
                "_source": doc,
            }
            actions.append(action)

        # Bulk index
        try:
            success, failed = await async_bulk(
                self.client,
                actions,
                chunk_size=batch_size,
                raise_on_error=False,
            )
            logger.info(
                f"Indexed {success} chunks with multi-embeddings to {index_name}, failed: {len(failed)}"
            )
            return success, len(failed)
        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return 0, len(chunks)

    async def vector_search_multi_model(
        self,
        query_embedding: List[float],
        search_space_id: int,
        model_key: str,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform k-NN vector search using a specific embedding model.

        Args:
            query_embedding: Query vector
            search_space_id: The search space ID
            model_key: Which embedding field to search (e.g., "openai/text-embedding-3-large")
            top_k: Number of results
            document_ids: Optional document filter
            min_score: Optional minimum score

        Returns:
            List of chunk dictionaries with vector_score
        """
        index_name = self._get_index_name(search_space_id)
        field_name = self._get_field_name(model_key)

        # Build k-NN query
        query_body = {
            "size": top_k,
            "query": {
                "knn": {
                    field_name: {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "content", "metadata"],
        }

        # Add filters
        if document_ids or min_score:
            filters = []
            if document_ids:
                filters.append({"terms": {"document_id": document_ids}})
            if min_score:
                filters.append({"range": {"_score": {"gte": min_score}}})

            query_body["query"] = {
                "bool": {
                    "must": [{"knn": query_body["query"]["knn"]}],
                    "filter": filters,
                }
            }

        try:
            response = await self.client.search(index=index_name, body=query_body)

            results = [
                {
                    "chunk_id": hit["_id"],
                    "document_id": hit["_source"]["document_id"],
                    "content": hit["_source"]["content"],
                    "metadata": hit["_source"].get("metadata", {}),
                    "vector_score": hit["_score"],
                    "model_used": model_key,
                }
                for hit in response["hits"]["hits"]
            ]

            logger.debug(
                f"Vector search ({model_key}) returned {len(results)} results from {index_name}"
            )
            return results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def hybrid_search_multi_model(
        self,
        query_text: str,
        query_embeddings: Dict[str, List[float]],
        search_space_id: int,
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining BM25 + multiple vector searches with RRF fusion.

        Args:
            query_text: Query text for BM25
            query_embeddings: Dict of {model_key: vector}
            search_space_id: The search space ID
            top_k: Final number of results
            rrf_k: RRF constant

        Returns:
            Fused results with RRF scores
        """
        # BM25 full-text search
        index_name = self._get_index_name(search_space_id)
        
        try:
            bm25_response = await self.client.search(
                index=index_name,
                body={
                    "size": top_k * 2,
                    "query": {"match": {"content": query_text}},
                    "_source": ["chunk_id", "document_id", "content", "metadata"],
                }
            )
            bm25_results = {
                hit["_id"]: {
                    "chunk_id": hit["_id"],
                    "document_id": hit["_source"]["document_id"],
                    "content": hit["_source"]["content"],
                    "metadata": hit["_source"].get("metadata", {}),
                    "bm25_score": hit["_score"],
                }
                for hit in bm25_response["hits"]["hits"]
            }
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            bm25_results = {}

        # Vector searches for each model
        all_vector_results = {}
        for model_key, query_vector in query_embeddings.items():
            vector_results = await self.vector_search_multi_model(
                query_vector, search_space_id, model_key, top_k=top_k * 2
            )
            all_vector_results[model_key] = {
                r["chunk_id"]: r for r in vector_results
            }

        # RRF Fusion
        rrf_scores = {}
        
        # Add BM25 scores
        for rank, chunk_id in enumerate(bm25_results.keys(), start=1):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (rrf_k + rank)
        
        # Add vector scores for each model
        for model_key, results_dict in all_vector_results.items():
            for rank, chunk_id in enumerate(results_dict.keys(), start=1):
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (rrf_k + rank)

        # Sort by RRF score and build final results
        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        final_results = []
        for chunk_id, rrf_score in sorted_chunks:
            # Get chunk data from any source that has it
            chunk_data = bm25_results.get(chunk_id)
            if not chunk_data:
                for results_dict in all_vector_results.values():
                    chunk_data = results_dict.get(chunk_id)
                    if chunk_data:
                        break
            
            if chunk_data:
                chunk_data["rrf_score"] = rrf_score
                chunk_data["models_contributed"] = [
                    model_key for model_key, results in all_vector_results.items()
                    if chunk_id in results
                ]
                final_results.append(chunk_data)

        logger.info(
            f"Hybrid multi-model search: BM25 + {len(query_embeddings)} vector models → {len(final_results)} results"
        )
        return final_results


def get_available_embedding_models() -> List[Dict[str, Any]]:
    """
    Get list of available embedding models for UI display.
    
    Returns:
        List of dicts with model info for frontend
    """
    return [
        {
            "key": key,
            "provider": info["provider"],
            "dimensions": info["dimensions"],
            "cost_per_1m_tokens": info["cost_per_1m_tokens"],
            "max_seq_length": info["max_seq_length"],
            "description": info["description"],
            "is_free": info["cost_per_1m_tokens"] == 0.0,
        }
        for key, info in EMBEDDING_MODELS.items()
    ]
