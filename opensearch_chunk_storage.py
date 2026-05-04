"""
OpenSearch-backed Chunk Storage Service

Replaces PostgreSQL pgvector for storing and retrieving chunk embeddings.
PostgreSQL is still used for relational data (users, documents, search spaces).

Architecture:
- One OpenSearch index per search space for tenant isolation
- k-NN (HNSW) index for vector similarity search
- BM25 inverted index for full-text search
- RRF fusion for hybrid search
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from opensearchpy import AsyncOpenSearch
from opensearchpy.helpers import async_bulk

logger = logging.getLogger(__name__)


class OpenSearchChunkStorage:
    """
    Manages chunk embeddings in OpenSearch.
    
    Features:
    - Per-search-space indices for isolation
    - k-NN vector search with HNSW algorithm
    - BM25 full-text search
    - Hybrid RRF (Reciprocal Rank Fusion)
    - Bulk indexing with batching
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
        """
        Initialize OpenSearch client.

        Args:
            hosts: List of OpenSearch host URLs (e.g., ["http://localhost:9200"])
            index_prefix: Prefix for index names (default: "surfsense")
            use_ssl: Whether to use SSL/TLS
            verify_certs: Whether to verify SSL certificates
            username: Basic auth username (optional)
            password: Basic auth password (optional)
        """
        client_kwargs = {
            "hosts": hosts,
            "use_ssl": use_ssl,
            "verify_certs": verify_certs,
        }

        if username and password:
            client_kwargs["http_auth"] = (username, password)

        self.client = AsyncOpenSearch(**client_kwargs)
        self.index_prefix = index_prefix
        logger.info(f"Initialized OpenSearch client with hosts: {hosts}")

    def _get_index_name(self, search_space_id: int) -> str:
        """
        Get index name for a search space.

        Args:
            search_space_id: The search space ID

        Returns:
            Index name (e.g., "surfsense_chunks_123")
        """
        return f"{self.index_prefix}_chunks_{search_space_id}"

    async def create_index(
        self,
        search_space_id: int,
        embedding_dimensions: int = 384,
        ef_construction: int = 128,
        m: int = 16,
    ):
        """
        Create OpenSearch index with k-NN and BM25 support.

        Args:
            search_space_id: The search space ID
            embedding_dimensions: Vector embedding dimensions
            ef_construction: HNSW ef_construction parameter (higher = better quality, slower indexing)
            m: HNSW m parameter (connections per node, higher = better recall, more memory)

        Index Mapping:
        - chunk_id: Unique chunk identifier (keyword)
        - document_id: Parent document ID (keyword) for filtering
        - content: Chunk text content (text field for BM25)
        - embedding: Dense vector (knn_vector with HNSW)
        - metadata: Additional data (object field)
        - indexed_at: Timestamp (date field)
        """
        index_name = self._get_index_name(search_space_id)

        # Check if index already exists
        if await self.client.indices.exists(index=index_name):
            logger.info(f"Index {index_name} already exists")
            return

        # Index settings and mapping
        index_body = {
            "settings": {
                "index": {
                    "knn": True,  # Enable k-NN plugin
                    "knn.algo_param.ef_search": 100,  # Search-time HNSW parameter
                    "number_of_shards": 1,  # Single shard for small-medium datasets
                    "number_of_replicas": 0,  # No replicas for development (set 1+ in prod)
                },
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},  # Exact match
                    "document_id": {"type": "keyword"},  # For filtering by document
                    "content": {
                        "type": "text",  # Full-text search with BM25
                        "analyzer": "english",  # English stemming and stopwords
                    },
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": embedding_dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",  # Cosine similarity (same as pgvector)
                            "engine": "faiss",  # Use FAISS for performance
                            "parameters": {
                                "ef_construction": ef_construction,
                                "m": m,
                            },
                        },
                    },
                    "metadata": {
                        "type": "object",
                        "enabled": True,
                    },
                    "indexed_at": {"type": "date"},
                }
            },
        }

        await self.client.indices.create(index=index_name, body=index_body)
        logger.info(
            f"Created index {index_name} with {embedding_dimensions}D embeddings"
        )

    async def index_chunks(
        self,
        chunks: List[Dict[str, Any]],
        search_space_id: int,
        batch_size: int = 100,
    ) -> Tuple[int, int]:
        """
        Bulk index chunks to OpenSearch.

        Args:
            chunks: List of chunk dictionaries with keys:
                - chunk_id: Unique identifier
                - document_id: Parent document ID
                - content: Text content
                - embedding: Vector embedding (list of floats)
                - metadata: Optional metadata dict
                - indexed_at: Optional timestamp (defaults to now)
            search_space_id: The search space ID
            batch_size: Number of chunks per bulk request

        Returns:
            Tuple of (success_count, failed_count)
        """
        index_name = self._get_index_name(search_space_id)

        # Prepare bulk actions
        actions = []
        for chunk in chunks:
            action = {
                "_index": index_name,
                "_id": chunk["chunk_id"],
                "_source": {
                    "chunk_id": chunk["chunk_id"],
                    "document_id": str(chunk["document_id"]),
                    "content": chunk["content"],
                    "embedding": chunk["embedding"],
                    "metadata": chunk.get("metadata", {}),
                    "indexed_at": chunk.get("indexed_at", datetime.utcnow().isoformat()),
                },
            }
            actions.append(action)

        # Bulk index with error handling
        try:
            success, failed = await async_bulk(
                self.client,
                actions,
                chunk_size=batch_size,
                raise_on_error=False,
            )
            logger.info(
                f"Indexed {success} chunks to {index_name}, failed: {len(failed)}"
            )
            return success, len(failed)
        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return 0, len(chunks)

    async def vector_search(
        self,
        query_embedding: List[float],
        search_space_id: int,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform k-NN vector similarity search.

        Args:
            query_embedding: Query vector embedding
            search_space_id: The search space ID
            top_k: Number of results to return
            document_ids: Optional list of document IDs to filter by
            min_score: Optional minimum similarity score threshold

        Returns:
            List of chunk dictionaries with keys:
                - chunk_id
                - document_id
                - content
                - metadata
                - vector_score (cosine similarity)
        """
        index_name = self._get_index_name(search_space_id)

        # Build k-NN query
        query_body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "content", "metadata"],
        }

        # Add filters if provided
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
                }
                for hit in response["hits"]["hits"]
            ]

            logger.debug(
                f"Vector search returned {len(results)} results from {index_name}"
            )
            return results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def full_text_search(
        self,
        query_text: str,
        search_space_id: int,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None,
        min_score: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform BM25 full-text search.

        Args:
            query_text: Search query text
            search_space_id: The search space ID
            top_k: Number of results to return
            document_ids: Optional list of document IDs to filter by
            min_score: Optional minimum BM25 score threshold

        Returns:
            List of chunk dictionaries with keys:
                - chunk_id
                - document_id
                - content
                - metadata
                - bm25_score
        """
        index_name = self._get_index_name(search_space_id)

        # Build BM25 query
        query_body = {
            "size": top_k,
            "query": {
                "match": {
                    "content": {
                        "query": query_text,
                        "operator": "or",  # Any term match (OR semantics)
                    }
                }
            },
            "_source": ["chunk_id", "document_id", "content", "metadata"],
        }

        # Add filters if provided
        if document_ids or min_score:
            filters = []
            if document_ids:
                filters.append({"terms": {"document_id": document_ids}})
            if min_score:
                query_body["min_score"] = min_score

            if document_ids:
                query_body["query"] = {
                    "bool": {
                        "must": [query_body["query"]],
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
                    "bm25_score": hit["_score"],
                }
                for hit in response["hits"]["hits"]
            ]

            logger.debug(
                f"Full-text search returned {len(results)} results from {index_name}"
            )
            return results

        except Exception as e:
            logger.error(f"Full-text search failed: {e}")
            return []

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: List[float],
        search_space_id: int,
        top_k: int = 20,
        document_ids: Optional[List[str]] = None,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search using RRF (Reciprocal Rank Fusion).

        Combines vector similarity and BM25 scores using RRF algorithm:
        score(chunk) = 1/(k + vector_rank) + 1/(k + bm25_rank)

        Args:
            query_text: Search query text
            query_embedding: Query vector embedding
            search_space_id: The search space ID
            top_k: Number of final results to return
            document_ids: Optional list of document IDs to filter by
            rrf_k: RRF constant (default 60, standard value)

        Returns:
            List of chunk dictionaries with keys:
                - chunk_id
                - document_id
                - content
                - metadata
                - rrf_score (combined score)
                - vector_score (optional)
                - bm25_score (optional)
        """
        # Fetch more candidates for better fusion
        n_results = top_k * 5

        # Execute vector and text search in parallel
        vector_results, text_results = await asyncio.gather(
            self.vector_search(
                query_embedding, search_space_id, n_results, document_ids
            ),
            self.full_text_search(query_text, search_space_id, n_results, document_ids),
        )

        # RRF fusion
        chunk_scores = {}
        chunk_data = {}

        # Add vector search scores
        for rank, result in enumerate(vector_results, start=1):
            chunk_id = result["chunk_id"]
            rrf_score = 1.0 / (rrf_k + rank)
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0.0) + rrf_score
            chunk_data[chunk_id] = result
            chunk_data[chunk_id]["vector_rank"] = rank

        # Add BM25 search scores
        for rank, result in enumerate(text_results, start=1):
            chunk_id = result["chunk_id"]
            rrf_score = 1.0 / (rrf_k + rank)
            chunk_scores[chunk_id] = chunk_scores.get(chunk_id, 0.0) + rrf_score

            if chunk_id not in chunk_data:
                chunk_data[chunk_id] = result
            chunk_data[chunk_id]["bm25_rank"] = rank
            chunk_data[chunk_id]["bm25_score"] = result.get("bm25_score")

        # Sort by RRF score and return top_k
        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )[:top_k]

        results = [
            {
                **chunk_data[chunk_id],
                "rrf_score": score,
            }
            for chunk_id, score in sorted_chunks
        ]

        logger.debug(
            f"Hybrid search returned {len(results)} results "
            f"(vector: {len(vector_results)}, text: {len(text_results)})"
        )
        return results

    async def delete_by_document_id(
        self, document_id: str, search_space_id: int
    ) -> int:
        """
        Delete all chunks for a document.

        Args:
            document_id: The document ID
            search_space_id: The search space ID

        Returns:
            Number of chunks deleted
        """
        index_name = self._get_index_name(search_space_id)

        query = {"query": {"term": {"document_id": document_id}}}

        try:
            response = await self.client.delete_by_query(index=index_name, body=query)
            deleted = response.get("deleted", 0)
            logger.info(f"Deleted {deleted} chunks for document {document_id}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete chunks: {e}")
            return 0

    async def delete_index(self, search_space_id: int):
        """
        Delete entire index for a search space.

        Args:
            search_space_id: The search space ID
        """
        index_name = self._get_index_name(search_space_id)

        try:
            if await self.client.indices.exists(index=index_name):
                await self.client.indices.delete(index=index_name)
                logger.info(f"Deleted index {index_name}")
        except Exception as e:
            logger.error(f"Failed to delete index: {e}")

    async def get_index_stats(self, search_space_id: int) -> Dict[str, Any]:
        """
        Get statistics for an index.

        Args:
            search_space_id: The search space ID

        Returns:
            Dictionary with index statistics
        """
        index_name = self._get_index_name(search_space_id)

        try:
            stats = await self.client.indices.stats(index=index_name)
            index_stats = stats["indices"].get(index_name, {})

            return {
                "index_name": index_name,
                "document_count": index_stats.get("total", {})
                .get("docs", {})
                .get("count", 0),
                "store_size_bytes": index_stats.get("total", {})
                .get("store", {})
                .get("size_in_bytes", 0),
            }
        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            return {}

    async def close(self):
        """Close the OpenSearch client connection."""
        await self.client.close()
        logger.info("Closed OpenSearch client")
