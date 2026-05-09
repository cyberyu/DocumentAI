import asyncio
import contextlib
import os
import time
from datetime import datetime

from app.utils.perf import get_perf_logger
from opensearch_chunk_storage import OpenSearchChunkStorage

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

        if not os_results:
            return []

        # Content is already in OpenSearch — return as lightweight dicts.
        # No PostgreSQL chunk lookup needed.
        results = [
            {
                "chunk_id": hit["chunk_id"],
                "document_id": hit.get("document_id"),
                "content": hit.get("content", ""),
                "metadata": hit.get("metadata", {}),
                "vector_score": hit.get("vector_score", hit.get("score", 0.0)),
            }
            for hit in os_results
        ]

        perf.info(
            "[chunk_search] vector_search TOTAL in %.3fs results=%d space=%d",
            time.perf_counter() - t0,
            len(results),
            search_space_id,
        )
        return results

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

        if not os_results:
            return []

        # Content is already in OpenSearch — no PostgreSQL chunk lookup needed.
        return [
            {
                "chunk_id": hit["chunk_id"],
                "document_id": hit.get("document_id"),
                "content": hit.get("content", ""),
                "metadata": hit.get("metadata", {}),
                "bm25_score": hit.get("bm25_score", hit.get("score", 0.0)),
            }
            for hit in os_results
        ]

    async def hybrid_search(
        self,
        query_text: str,
        top_k: int,
        search_space_id: int,
        document_type: str | list[str] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        query_embedding: list | None = None,
        ranking_variant: str | None = None,
        vector_weight: float | None = None,
        keyword_weight: float | None = None,
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
        from app.config import config

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
        resolved_variant = (
            ranking_variant
            or os.getenv("CHUNK_RANKING_VARIANT", "hybrid_rrf")
            or "hybrid_rrf"
        ).strip().lower()
        
        t_search = time.perf_counter()
        os_results = await self.opensearch_storage.hybrid_search(
            search_space_id=search_space_id,
            query_text=query_text,
            query_embedding=query_embedding,
            top_k=n_results,
            start_date=start_date,
            end_date=end_date,
            ranking_variant=resolved_variant,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
        perf.info(
            "[chunk_search] OpenSearch hybrid_search variant=%s in %.3fs results=%d space=%d",
            resolved_variant,
            time.perf_counter() - t_search,
            len(os_results),
            search_space_id,
        )

        if not os_results:
            return []

        # ── Build per-document scoring from OpenSearch hits ──────────────────
        # Chunk IDs in OpenSearch are composite strings ("{doc_id}_{idx}"), not
        # PostgreSQL integer PKs.  We group by integer document_id and keep the
        # best relevance score per document, preserving first-seen rank order.
        doc_scores_os: dict[int, float] = {}
        doc_order_os: list[int] = []
        # chunk_id → {content, score} for every hit
        os_hits_by_doc: dict[int, list[dict]] = {}

        for hit in os_results:
            raw_doc_id = hit.get("document_id")
            try:
                doc_id_int = int(raw_doc_id)
            except (TypeError, ValueError):
                try:
                    doc_id_int = int(str(hit.get("chunk_id", "")).split("_")[0])
                except (ValueError, IndexError):
                    continue

            score = float(hit.get("score", hit.get("rrf_score",
                          hit.get("bm25_score", hit.get("vector_score", 0.0)))))

            if doc_id_int not in doc_scores_os:
                doc_scores_os[doc_id_int] = score
                doc_order_os.append(doc_id_int)
                os_hits_by_doc[doc_id_int] = []
            else:
                doc_scores_os[doc_id_int] = max(doc_scores_os[doc_id_int], score)

            os_hits_by_doc[doc_id_int].append({
                "chunk_id": hit.get("chunk_id", ""),
                "content": hit.get("content", ""),
            })

        # ── Single PostgreSQL query: documents table only ─────────────────────
        t_hydrate = time.perf_counter()
        from sqlalchemy import select, func
        from app.db import Document, DocumentType

        doc_conditions = [
            Document.id.in_(doc_order_os),
            Document.search_space_id == search_space_id,
            func.coalesce(Document.status["state"].astext, "ready") != "deleting",
        ]

        if document_type is not None:
            type_list = document_type if isinstance(document_type, list) else [document_type]
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
                doc_conditions.append(Document.document_type == doc_type_enums[0])
            else:
                doc_conditions.append(Document.document_type.in_(doc_type_enums))

        if start_date is not None:
            doc_conditions.append(Document.updated_at >= start_date)
        if end_date is not None:
            doc_conditions.append(Document.updated_at <= end_date)

        doc_result = await self.db_session.execute(
            select(Document).where(*doc_conditions)
        )
        doc_by_id: dict[int, Document] = {
            d.id: d for d in doc_result.scalars().all()
        }

        perf.debug(
            "[chunk_search] PostgreSQL documents lookup in %.3fs rows=%d",
            time.perf_counter() - t_hydrate,
            len(doc_by_id),
        )

        # ── Assemble final doc-grouped results ────────────────────────────────
        final_docs: list[dict] = []
        for doc_id in doc_order_os[:top_k]:
            doc = doc_by_id.get(doc_id)
            if doc is None:
                continue   # filtered out by document_type / date / deleting

            hits = os_hits_by_doc.get(doc_id, [])
            combined_content = "\n\n".join(
                h["content"] for h in hits if h.get("content")
            )

            final_docs.append({
                "document_id": doc_id,
                "chunk_id": hits[0]["chunk_id"] if hits else f"{doc_id}_0",
                "content": combined_content,
                "score": float(doc_scores_os.get(doc_id, 0.0)),
                "chunks": [{"chunk_id": h["chunk_id"], "content": h["content"]} for h in hits],
                "matched_chunk_ids": [h["chunk_id"] for h in hits],
                "document": {
                    "id": doc.id,
                    "title": doc.title,
                    "document_type": doc.document_type.value
                        if hasattr(doc, "document_type") else None,
                    "metadata": doc.document_metadata,
                },
                "source": doc.document_type.value
                    if hasattr(doc, "document_type") else None,
            })

        perf.info(
            "[chunk_search] hybrid_search TOTAL in %.3fs docs=%d space=%d type=%s",
            time.perf_counter() - t0,
            len(final_docs),
            search_space_id,
            document_type,
        )
        return final_docs
