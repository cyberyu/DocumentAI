import asyncio
import contextlib
import time
from datetime import datetime

from app.utils.perf import get_perf_logger
from app.storage.opensearch_chunk_storage import OpenSearchChunkStorage

_MAX_FETCH_CHUNKS_PER_DOC = 20


class ChucksHybridSearchRetriever:
    def __init__(self, db_session):
        """
        Initialize the hybrid search retriever with a database session.

        Args:
            db_session: SQLAlchemy AsyncSession from FastAPI dependency injection
        """
        self.db_session = db_session
        self.opensearch_storage = OpenSearchChunkStorage()

    async def vector_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list:
        """
        Perform vector similarity search on chunks using OpenSearch.

        Args:
            query_text: The search query text
            top_k: Number of results to return
            search_space_id: The search space ID to search within
            start_date: Optional start date for filtering documents by updated_at
            end_date: Optional end date for filtering documents by updated_at

        Returns:
            List of chunks sorted by vector similarity
        """
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.config import config
        from app.db import Chunk, Document

        perf = get_perf_logger()
        t0 = time.perf_counter()

        # Get embedding for the query
        embedding_model = config.embedding_model_instance
        t_embed = time.perf_counter()
        query_embedding = await asyncio.to_thread(embedding_model.embed, query_text)
        perf.debug(
            "[chunk_search] vector_search embedding in %.3fs",
            time.perf_counter() - t_embed,
        )

        # Search OpenSearch for vector similarity
        t_search = time.perf_counter()
        os_results = await self.opensearch_storage.vector_search(
            search_space_id=search_space_id,
            query_embedding=query_embedding,
            top_k=top_k,
            start_date=start_date,
            end_date=end_date,
        )
        perf.info(
            "[chunk_search] OpenSearch vector_search in %.3fs results=%d space=%d",
            time.perf_counter() - t_search,
            len(os_results),
            search_space_id,
        )

        # Hydrate with full chunk and document data from PostgreSQL
        if not os_results:
            return []

        chunk_ids = [hit["chunk_id"] for hit in os_results]
        query = (
            select(Chunk)
            .options(joinedload(Chunk.document).joinedload(Document.search_space))
            .where(Chunk.id.in_(chunk_ids))
        )
        
        result = await self.db_session.execute(query)
        chunks_dict = {chunk.id: chunk for chunk in result.scalars().all()}
        
        # Return chunks in the order of OpenSearch results
        chunks = [chunks_dict[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_dict]
        
        perf.info(
            "[chunk_search] vector_search TOTAL in %.3fs results=%d space=%d",
            time.perf_counter() - t0,
            len(chunks),
            search_space_id,
        )
        return chunks

    async def full_text_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list:
        """
        Perform full-text keyword search on chunks using OpenSearch BM25.

        Args:
            query_text: The search query text
            top_k: Number of results to return
            search_space_id: The search space ID to search within
            start_date: Optional start date for filtering documents by updated_at
            end_date: Optional end date for filtering documents by updated_at

        Returns:
            List of chunks sorted by text relevance
        """
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from app.db import Chunk, Document

        perf = get_perf_logger()
        t0 = time.perf_counter()

        # Search OpenSearch using BM25
        os_results = await self.opensearch_storage.full_text_search(
            search_space_id=search_space_id,
            query_text=query_text,
            top_k=top_k,
            start_date=start_date,
            end_date=end_date,
        )
        perf.info(
            "[chunk_search] OpenSearch full_text_search in %.3fs results=%d space=%d",
            time.perf_counter() - t0,
            len(os_results),
            search_space_id,
        )

        # Hydrate with full chunk and document data from PostgreSQL
        if not os_results:
            return []

        chunk_ids = [hit["chunk_id"] for hit in os_results]
        query = (
            select(Chunk)
            .options(joinedload(Chunk.document).joinedload(Document.search_space))
            .where(Chunk.id.in_(chunk_ids))
        )
        
        result = await self.db_session.execute(query)
        chunks_dict = {chunk.id: chunk for chunk in result.scalars().all()}
        
        # Return chunks in the order of OpenSearch results
        chunks = [chunks_dict[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_dict]
        
        return chunks

    async def hybrid_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        document_type: str | list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        query_embedding: list | None = None,
    ) -> list:
        """
        Hybrid search that returns **documents** (not individual chunks) using OpenSearch RRF.

        Each returned item is a document-grouped dict that preserves real DB chunk IDs so
        downstream agents can cite with `[citation:<chunk_id>]`.

        Args:
            query_text: The search query text
            top_k: Number of documents to return
            search_space_id: The search space ID to search within
            document_type: Optional document type to filter results (e.g., "FILE", "CRAWLED_URL")
            start_date: Optional start date for filtering documents by updated_at
            end_date: Optional end date for filtering documents by updated_at
            query_embedding: Pre-computed embedding vector. If None, will be computed here.

        Returns:
            List of dictionaries containing document data and relevance scores. Each dict contains:
              - chunk_id: a "primary" chunk id for compatibility (best-ranked chunk for the doc)
              - content: concatenated chunk content (useful for reranking)
              - chunks: list[{chunk_id, content}] for citation-aware prompting
              - document: {id, title, document_type, metadata}
        """
        from sqlalchemy import select, func, or_
        from sqlalchemy.orm import joinedload
        from app.config import config
        from app.db import Chunk, Document, DocumentType

        perf = get_perf_logger()
        t0 = time.perf_counter()

        if query_embedding is None:
            embedding_model = config.embedding_model_instance
            t_embed = time.perf_counter()
            query_embedding = await asyncio.to_thread(embedding_model.embed, query_text)
            perf.debug(
                "[chunk_search] hybrid_search embedding in %.3fs",
                time.perf_counter() - t_embed,
            )

        # Use OpenSearch hybrid search with RRF
        # Fetch more chunks than needed for document-level grouping
        n_results = top_k * 5
        
        t_search = time.perf_counter()
        os_results = await self.opensearch_storage.hybrid_search(
            search_space_id=search_space_id,
            query_text=query_text,
            query_embedding=query_embedding,
            top_k=n_results,
            start_date=start_date,
            end_date=end_date,
        )
        perf.info(
            "[chunk_search] OpenSearch hybrid_search in %.3fs results=%d space=%d",
            time.perf_counter() - t_search,
            len(os_results),
            search_space_id,
        )

        if not os_results:
            return []

        # Extract chunk IDs and scores
        chunk_ids = [hit["chunk_id"] for hit in os_results]
        chunk_scores = {hit["chunk_id"]: hit["score"] for hit in os_results}

        # Fetch chunk and document data from PostgreSQL
        t_hydrate = time.perf_counter()
        
        # Get base document filter conditions
        base_conditions = [
            Document.search_space_id == search_space_id,
            func.coalesce(Document.status["state"].astext, "ready") != "deleting",
        ]

        # Add document type filter if provided
        if document_type is not None:
            type_list = (
                document_type if isinstance(document_type, list) else [document_type]
            )
            doc_type_enums = []
            for dt in type_list:
                if isinstance(dt, str):
                    with contextlib.suppress(KeyError):
                        doc_type_enums.append(DocumentType[dt])
                else:
                    doc_type_enums.append(dt)
            if not doc_type_enums:
                return []
            if len(doc_type_enums) == 1:
                base_conditions.append(Document.document_type == doc_type_enums[0])
            else:
                base_conditions.append(Document.document_type.in_(doc_type_enums))

        # Add time-based filtering if provided
        if start_date is not None:
            base_conditions.append(Document.updated_at >= start_date)
        if end_date is not None:
            base_conditions.append(Document.updated_at <= end_date)

        # Fetch chunks with documents
        query = (
            select(Chunk)
            .options(joinedload(Chunk.document))
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(chunk_ids))
            .where(*base_conditions)
        )
        
        result = await self.db_session.execute(query)
        chunks = result.scalars().all()
        
        perf.debug(
            "[chunk_search] PostgreSQL hydration in %.3fs rows=%d",
            time.perf_counter() - t_hydrate,
            len(chunks),
        )

        # Build serialized results maintaining OpenSearch order
        serialized_chunk_results: list[dict] = []
        chunks_dict = {chunk.id: chunk for chunk in chunks}
        
        for chunk_id in chunk_ids:
            if chunk_id not in chunks_dict:
                continue
            chunk = chunks_dict[chunk_id]
            score = chunk_scores.get(chunk_id, 0.0)
            
            serialized_chunk_results.append(
                {
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "score": float(score),
                    "document": {
                        "id": chunk.document.id,
                        "title": chunk.document.title,
                        "document_type": chunk.document.document_type.value
                        if hasattr(chunk.document, "document_type")
                        else None,
                        "metadata": chunk.document.document_metadata,
                    },
                }
            )

        # Group by document, preserving ranking order by best chunk rank
        doc_scores: dict[int, float] = {}
        doc_order: list[int] = []
        for item in serialized_chunk_results:
            doc_id = item.get("document", {}).get("id")
            if doc_id is None:
                continue
            if doc_id not in doc_scores:
                doc_scores[doc_id] = item.get("score", 0.0)
                doc_order.append(doc_id)
            else:
                # Use the best score as doc score
                doc_scores[doc_id] = max(doc_scores[doc_id], item.get("score", 0.0))

        # Keep only top_k documents by initial rank order
        doc_ids = doc_order[:top_k]
        if not doc_ids:
            return []

        # Collect document metadata from hydrated chunks
        matched_chunk_ids: set[int] = {
            item["chunk_id"] for item in serialized_chunk_results
        }
        doc_meta_cache: dict[int, dict] = {}
        for item in serialized_chunk_results:
            did = item["document"]["id"]
            if did not in doc_meta_cache:
                doc_meta_cache[did] = item["document"]

        # Fetch additional chunks for each document (up to _MAX_FETCH_CHUNKS_PER_DOC)
        numbered = (
            select(
                Chunk.id.label("chunk_id"),
                func.row_number()
                .over(partition_by=Chunk.document_id, order_by=Chunk.id)
                .label("rn"),
            )
            .where(Chunk.document_id.in_(doc_ids))
            .subquery("numbered")
        )

        matched_list = list(matched_chunk_ids)
        if matched_list:
            chunk_filter = or_(
                numbered.c.rn <= _MAX_FETCH_CHUNKS_PER_DOC,
                Chunk.id.in_(matched_list),
            )
        else:
            chunk_filter = numbered.c.rn <= _MAX_FETCH_CHUNKS_PER_DOC

        # Select only the columns we need
        chunk_query = (
            select(Chunk.id, Chunk.content, Chunk.document_id)
            .join(numbered, Chunk.id == numbered.c.chunk_id)
            .where(chunk_filter)
            .order_by(Chunk.document_id, Chunk.id)
        )

        t_fetch = time.perf_counter()
        chunks_result = await self.db_session.execute(chunk_query)
        fetched_chunks = chunks_result.all()
        perf.debug(
            "[chunk_search] chunk fetch in %.3fs rows=%d",
            time.perf_counter() - t_fetch,
            len(fetched_chunks),
        )

        # Assemble final doc-grouped results
        doc_map: dict[int, dict] = {
            doc_id: {
                "document_id": doc_id,
                "content": "",
                "score": float(doc_scores.get(doc_id, 0.0)),
                "chunks": [],
                "matched_chunk_ids": [],
                "document": doc_meta_cache.get(doc_id, {}),
                "source": (doc_meta_cache.get(doc_id) or {}).get("document_type"),
            }
            for doc_id in doc_ids
        }

        for row in fetched_chunks:
            doc_id = row.document_id
            if doc_id not in doc_map:
                continue
            doc_entry = doc_map[doc_id]
            doc_entry["chunks"].append({"chunk_id": row.id, "content": row.content})
            if row.id in matched_chunk_ids:
                doc_entry["matched_chunk_ids"].append(row.id)

        # Fill concatenated content
        final_docs: list[dict] = []
        for doc_id in doc_ids:
            entry = doc_map[doc_id]
            entry["content"] = "\n\n".join(
                c["content"] for c in entry.get("chunks", []) if c.get("content")
            )
            final_docs.append(entry)

        perf.info(
            "[chunk_search] hybrid_search TOTAL in %.3fs docs=%d space=%d type=%s",
            time.perf_counter() - t0,
            len(final_docs),
            search_space_id,
            document_type,
        )
        return final_docs
