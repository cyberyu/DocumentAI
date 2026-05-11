import asyncio
import contextlib
import hashlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    NATIVE_TO_LEGACY_DOCTYPE,
    Chunk,
    Document,
    DocumentStatus,
    DocumentType,
)
from app.indexing_pipeline.connector_document import ConnectorDocument
from app.indexing_pipeline.document_chunker import chunk_with_strategy
from app.indexing_pipeline.document_embedder import embed_texts
from app.indexing_pipeline.document_hashing import (
    compute_content_hash,
    compute_identifier_hash,
    compute_unique_identifier_hash,
)
from app.indexing_pipeline.document_persistence import (
    attach_chunks_to_document,
    rollback_and_persist_failure,
)
from app.indexing_pipeline.document_summarizer import summarize_document
from app.indexing_pipeline.exceptions import (
    EMBEDDING_ERRORS,
    PERMANENT_LLM_ERRORS,
    RETRYABLE_LLM_ERRORS,
    PipelineMessages,
    embedding_message,
    llm_permanent_message,
    llm_retryable_message,
    safe_exception_message,
)
from app.indexing_pipeline.pipeline_logger import (
    PipelineLogContext,
    log_batch_aborted,
    log_chunking_overflow,
    log_doc_skipped_unknown,
    log_document_queued,
    log_document_requeued,
    log_document_updated,
    log_embedding_error,
    log_index_started,
    log_index_success,
    log_permanent_llm_error,
    log_race_condition,
    log_retryable_llm_error,
    log_unexpected_error,
)
from app.utils.perf import get_perf_logger


@dataclass
class PlaceholderInfo:
    """Minimal info to create a placeholder document row for instant UI feedback.

    These are created immediately when items are discovered (before content
    extraction) so users see them in the UI via Zero sync right away.
    """

    title: str
    document_type: DocumentType
    unique_id: str
    search_space_id: int
    connector_id: int | None
    created_by_id: str
    metadata: dict = field(default_factory=dict)


class IndexingPipelineService:
    """Single pipeline for indexing connector documents. All connectors use this service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_placeholder_documents(
        self, placeholders: list[PlaceholderInfo]
    ) -> int:
        """Create placeholder document rows with pending status for instant UI feedback.

        These rows appear immediately in the UI via Zero sync. They are later
        updated by prepare_for_indexing() when actual content is available.

        Returns the number of placeholders successfully created.
        Failures are logged but never block the main indexing flow.

        NOTE: This method commits on ``self.session`` so the rows become
        visible to Zero sync immediately.  Any pending ORM mutations on the
        session are committed together, which is consistent with how other
        mid-flow commits work in the indexing codebase (e.g. rename-only
        updates in ``_should_skip_file``, ``migrate_legacy_docs``).
        """
        if not placeholders:
            return 0

        _logger = logging.getLogger(__name__)

        uid_hashes: dict[str, PlaceholderInfo] = {}
        for p in placeholders:
            try:
                uid_hash = compute_identifier_hash(
                    p.document_type.value, p.unique_id, p.search_space_id
                )
                uid_hashes.setdefault(uid_hash, p)
            except Exception:
                _logger.debug(
                    "Skipping placeholder hash for %s", p.unique_id, exc_info=True
                )

        if not uid_hashes:
            return 0

        result = await self.session.execute(
            select(Document.unique_identifier_hash).where(
                Document.unique_identifier_hash.in_(list(uid_hashes.keys()))
            )
        )
        existing_hashes: set[str] = set(result.scalars().all())

        created = 0
        for uid_hash, p in uid_hashes.items():
            if uid_hash in existing_hashes:
                continue
            try:
                content_hash = hashlib.sha256(
                    f"placeholder:{uid_hash}".encode()
                ).hexdigest()

                document = Document(
                    title=p.title,
                    document_type=p.document_type,
                    content="Pending...",
                    content_hash=content_hash,
                    unique_identifier_hash=uid_hash,
                    document_metadata=p.metadata or {},
                    search_space_id=p.search_space_id,
                    connector_id=p.connector_id,
                    created_by_id=p.created_by_id,
                    updated_at=datetime.now(UTC),
                    status=DocumentStatus.pending(),
                )
                self.session.add(document)
                created += 1
            except Exception:
                _logger.debug("Skipping placeholder for %s", p.unique_id, exc_info=True)

        if created > 0:
            try:
                await self.session.commit()
                _logger.info(
                    "Created %d placeholder document(s) for instant UI feedback",
                    created,
                )
            except IntegrityError:
                await self.session.rollback()
                _logger.debug("Placeholder commit failed (race condition), continuing")
                created = 0

        return created

    async def migrate_legacy_docs(
        self, connector_docs: list[ConnectorDocument]
    ) -> None:
        """Migrate legacy Composio documents to their native Google type.

        For each ConnectorDocument whose document_type has a Composio equivalent
        in NATIVE_TO_LEGACY_DOCTYPE, look up the old document by legacy hash and
        update its unique_identifier_hash and document_type so that
        prepare_for_indexing() can find it under the native hash.
        """
        for doc in connector_docs:
            legacy_type = NATIVE_TO_LEGACY_DOCTYPE.get(doc.document_type.value)
            if not legacy_type:
                continue

            legacy_hash = compute_identifier_hash(
                legacy_type, doc.unique_id, doc.search_space_id
            )
            result = await self.session.execute(
                select(Document).filter(Document.unique_identifier_hash == legacy_hash)
            )
            existing = result.scalars().first()
            if existing is None:
                continue

            native_hash = compute_identifier_hash(
                doc.document_type.value, doc.unique_id, doc.search_space_id
            )
            existing.unique_identifier_hash = native_hash
            existing.document_type = doc.document_type

        await self.session.commit()

    async def index_batch(
        self, connector_docs: list[ConnectorDocument], llm
    ) -> list[Document]:
        """Convenience method: prepare_for_indexing then index each document.

        Indexers that need heartbeat callbacks or custom per-document logic
        should call prepare_for_indexing() + index() directly instead.
        """
        doc_map = {compute_unique_identifier_hash(cd): cd for cd in connector_docs}
        documents = await self.prepare_for_indexing(connector_docs)
        results: list[Document] = []
        for document in documents:
            connector_doc = doc_map.get(document.unique_identifier_hash)
            if connector_doc is None:
                continue
            result = await self.index(document, connector_doc, llm)
            results.append(result)
        return results

    async def prepare_for_indexing(
        self, connector_docs: list[ConnectorDocument], is_pipeline_variant: bool = False
    ) -> list[Document]:
        """
        Persist new documents and detect changes, returning only those that need indexing.

        When ``is_pipeline_variant`` is True the content-hash duplicate checks are
        skipped.  Pipeline variants intentionally share the same source markdown
        (same Docling output) but differ in chunking strategy / size / embedding
        model, so they must not be treated as duplicates of each other.
        """
        perf = get_perf_logger()
        t0 = time.perf_counter()

        documents = []
        seen_hashes: set[str] = set()
        batch_ctx = PipelineLogContext(
            connector_id=connector_docs[0].connector_id if connector_docs else 0,
            search_space_id=connector_docs[0].search_space_id if connector_docs else 0,
            unique_id="batch",
        )

        for connector_doc in connector_docs:
            ctx = PipelineLogContext(
                connector_id=connector_doc.connector_id,
                search_space_id=connector_doc.search_space_id,
                unique_id=connector_doc.unique_id,
            )
            try:
                unique_identifier_hash = compute_unique_identifier_hash(connector_doc)
                content_hash = compute_content_hash(connector_doc)

                if unique_identifier_hash in seen_hashes:
                    continue
                seen_hashes.add(unique_identifier_hash)

                result = await self.session.execute(
                    select(Document).filter(
                        Document.unique_identifier_hash == unique_identifier_hash
                    )
                )
                existing = result.scalars().first()

                if existing is not None:
                    if existing.content_hash == content_hash:
                        if existing.title != connector_doc.title:
                            existing.title = connector_doc.title
                            existing.updated_at = datetime.now(UTC)
                        if not DocumentStatus.is_state(
                            existing.status, DocumentStatus.READY
                        ):
                            existing.status = DocumentStatus.pending()
                            existing.updated_at = datetime.now(UTC)
                            if connector_doc.folder_id is not None:
                                existing.folder_id = connector_doc.folder_id
                            documents.append(existing)
                            log_document_requeued(ctx)
                        continue

                    if not is_pipeline_variant:
                        dup_check = await self.session.execute(
                            select(Document.id, Document.title).filter(
                                Document.content_hash == content_hash,
                                Document.id != existing.id,
                            )
                        )
                        dup_row = dup_check.first()
                        if dup_row is not None:
                            if not DocumentStatus.is_state(
                                existing.status, DocumentStatus.READY
                            ):
                                existing.status = DocumentStatus.failed(
                                    f"Duplicate content: matches '{dup_row.title}'"
                                )
                            continue

                    existing.title = connector_doc.title
                    existing.content_hash = content_hash
                    existing.source_markdown = connector_doc.source_markdown
                    existing.document_metadata = connector_doc.metadata
                    existing.updated_at = datetime.now(UTC)
                    existing.status = DocumentStatus.pending()
                    if connector_doc.folder_id is not None:
                        existing.folder_id = connector_doc.folder_id
                    documents.append(existing)
                    log_document_updated(ctx)
                    continue

                if not is_pipeline_variant:
                    duplicate = await self.session.execute(
                        select(Document).filter(Document.content_hash == content_hash)
                    )
                    if duplicate.scalars().first() is not None:
                        continue

                document = Document(
                    title=connector_doc.title,
                    document_type=connector_doc.document_type,
                    content="Pending...",
                    content_hash=content_hash,
                    unique_identifier_hash=unique_identifier_hash,
                    source_markdown=connector_doc.source_markdown,
                    document_metadata=connector_doc.metadata,
                    search_space_id=connector_doc.search_space_id,
                    connector_id=connector_doc.connector_id,
                    created_by_id=connector_doc.created_by_id,
                    updated_at=datetime.now(UTC),
                    status=DocumentStatus.pending(),
                    folder_id=connector_doc.folder_id,
                )
                self.session.add(document)
                documents.append(document)
                log_document_queued(ctx)

            except Exception as e:
                log_doc_skipped_unknown(ctx, e)

        try:
            await self.session.commit()
            perf.info(
                "[indexing] prepare_for_indexing in %.3fs input=%d output=%d",
                time.perf_counter() - t0,
                len(connector_docs),
                len(documents),
            )
            return documents
        except IntegrityError:
            log_race_condition(batch_ctx)
            await self.session.rollback()
            return []
        except Exception as e:
            log_batch_aborted(batch_ctx, e)
            await self.session.rollback()
            return []

    async def index(
        self,
        document: Document,
        connector_doc: ConnectorDocument,
        llm,
        embedding_config: dict | None = None,
        chunking_strategy: str | None = None,
        chunking_strategies: list[str] | None = None,
        chunk_size: int | None = None,
        pipeline_id: str | None = None,
    ) -> Document:
        """
        Run summarization, embedding, and chunking for a document and persist the results.
        If embedding_config specifies multi-mode, uses multi-embedding OpenSearch storage.
        """
        logger = logging.getLogger(__name__)
        
        ctx = PipelineLogContext(
            connector_id=connector_doc.connector_id,
            search_space_id=connector_doc.search_space_id,
            unique_id=connector_doc.unique_id,
            doc_id=document.id,
        )
        perf = get_perf_logger()
        t_index = time.perf_counter()
        try:
            log_index_started(ctx)
            document.status = DocumentStatus.processing()
            await self.session.commit()

            t_step = time.perf_counter()
            if connector_doc.should_summarize and llm is not None:
                content = await summarize_document(
                    connector_doc.source_markdown, llm, connector_doc.metadata
                )
                perf.info(
                    "[indexing] summarize_document doc=%d in %.3fs",
                    document.id,
                    time.perf_counter() - t_step,
                )
            elif connector_doc.should_summarize and connector_doc.fallback_summary:
                content = connector_doc.fallback_summary
            else:
                content = connector_doc.source_markdown

            await self.session.execute(
                delete(Chunk).where(Chunk.document_id == document.id)
            )

            t_step = time.perf_counter()

            requested_strategies = list(chunking_strategies or [])
            if not requested_strategies:
                requested_strategies = [chunking_strategy or "chunk_text"]

            normalized_strategy_map = {
                "sandwich_chunk": "sandwitch_chunk",
                "hybrid_sandwich": "sandwitch_chunk",
            }
            normalized_strategies: list[str] = []
            seen_strategies: set[str] = set()
            for strategy_value in requested_strategies:
                normalized = normalized_strategy_map.get(
                    (strategy_value or "chunk_text").strip().lower(),
                    (strategy_value or "chunk_text").strip().lower(),
                )
                if not normalized:
                    continue
                if normalized in seen_strategies:
                    continue
                seen_strategies.add(normalized)
                normalized_strategies.append(normalized)

            if not normalized_strategies:
                normalized_strategies = ["chunk_text"]

            # Check if multi-embedding is requested based on config
            logger.info(f"[indexing] Received embedding_config: {embedding_config}")
            use_multi_embedding = (
                embedding_config 
                and embedding_config.get("mode") in {"multi", "single"}
                and len(embedding_config.get("model_keys", [])) >= 1
            )
            logger.info(f"[indexing] use_multi_embedding={use_multi_embedding}")
            resolved_pipeline_id = pipeline_id or document.unique_identifier_hash
            
            if use_multi_embedding:
                # Use multi-embedding processor for OpenSearch
                from multi_embedding_processor import MultiEmbeddingProcessor
                from opensearch_multi_embedding_storage import MultiEmbeddingOpenSearchStorage
                
                raw_hosts = os.getenv("OPENSEARCH_HOSTS", "http://opensearch:9200")
                hosts = [host.strip() for host in raw_hosts.split(",") if host.strip()]
                storage = MultiEmbeddingOpenSearchStorage(
                    hosts=hosts,
                    index_prefix=os.getenv("OPENSEARCH_INDEX_PREFIX", "surfsense"),
                    use_ssl=os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true",
                    verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true",
                    username=os.getenv("OPENSEARCH_USERNAME") or None,
                    password=os.getenv("OPENSEARCH_PASSWORD") or None,
                )
                try:
                    processor = MultiEmbeddingProcessor(storage)

                    # Process chunks with multiple embeddings for each chunking strategy
                    model_keys = embedding_config.get("model_keys", [])

                    # Phase 1: run chunking for all strategies in bounded parallelism, without embedding.
                    raw_chunking_concurrency = os.getenv(
                        "INDEXING_STRATEGY_CHUNK_CONCURRENCY", "3"
                    )
                    try:
                        strategy_chunk_concurrency = int(raw_chunking_concurrency)
                    except ValueError:
                        strategy_chunk_concurrency = 3
                    strategy_chunk_concurrency = max(
                        1,
                        min(strategy_chunk_concurrency, len(normalized_strategies)),
                    )
                    strategy_chunk_semaphore = asyncio.Semaphore(strategy_chunk_concurrency)

                    async def _chunk_strategy(strategy_name: str) -> tuple[str, list[str]]:
                        async with strategy_chunk_semaphore:
                            strategy_chunk_texts = await asyncio.to_thread(
                                chunk_with_strategy,
                                connector_doc.source_markdown,
                                strategy=strategy_name,
                                use_code_chunker=connector_doc.should_use_code_chunker,
                                chunk_size=chunk_size,
                            )
                        return strategy_name, strategy_chunk_texts

                    chunking_results = await asyncio.gather(
                        *[_chunk_strategy(strategy_name) for strategy_name in normalized_strategies]
                    )

                    strategy_chunks: dict[str, list[str]] = {
                        strategy_name: strategy_chunk_texts
                        for strategy_name, strategy_chunk_texts in chunking_results
                    }
                    strategy_chunk_counts: dict[str, int] = {
                        strategy_name: len(strategy_chunks.get(strategy_name, []))
                        for strategy_name in normalized_strategies
                    }

                    all_chunk_texts: list[str] = []
                    for strategy_name in normalized_strategies:
                        all_chunk_texts.extend(strategy_chunks.get(strategy_name, []))

                    # Phase 2: after all chunking is done, embed/index each strategy in parallel.
                    raw_strategy_embed_concurrency = os.getenv(
                        "INDEXING_STRATEGY_EMBED_CONCURRENCY", "2"
                    )
                    try:
                        strategy_embed_concurrency = int(raw_strategy_embed_concurrency)
                    except ValueError:
                        strategy_embed_concurrency = 2
                    strategy_embed_concurrency = max(
                        1,
                        min(strategy_embed_concurrency, len(normalized_strategies)),
                    )
                    strategy_embed_semaphore = asyncio.Semaphore(strategy_embed_concurrency)

                    async def _embed_and_store_strategy(strategy_name: str) -> None:
                        strategy_chunk_texts = strategy_chunks.get(strategy_name, [])
                        chunk_records = [
                            {
                                "chunk_id": f"{resolved_pipeline_id}:{strategy_name}:{idx}",
                                "text": text,
                                "metadata": {
                                    "document_id": document.id,
                                    "pipeline_id": resolved_pipeline_id,
                                    "chunking_strategy": strategy_name,
                                    "chunk_size": chunk_size,
                                },
                            }
                            for idx, text in enumerate(strategy_chunk_texts)
                        ]
                        async with strategy_embed_semaphore:
                            await processor.process_and_store_document(
                                chunks=chunk_records,
                                model_keys=model_keys,
                                document_id=document.id,
                                pipeline_id=resolved_pipeline_id,
                                search_space_id=connector_doc.search_space_id,
                                chunking_strategy=strategy_name,
                            )

                    await asyncio.gather(
                        *[
                            _embed_and_store_strategy(strategy_name)
                            for strategy_name in normalized_strategies
                        ]
                    )

                    # Skip legacy summary embedding generation in multi-embedding mode.
                    # This avoids CUDA re-init errors in Celery prefork workers when torch is GPU-enabled.
                    summary_embedding = None

                    # Create chunks without embeddings (stored in OpenSearch already)
                    chunks = [Chunk(content=text) for text in all_chunk_texts]

                    perf.info(
                        "[indexing] multi-embed doc=%d models=%d strategies=%s total_chunks=%d strategy_chunk_concurrency=%d strategy_embed_concurrency=%d in %.3fs",
                        document.id,
                        len(model_keys),
                        strategy_chunk_counts,
                        len(chunks),
                        strategy_chunk_concurrency,
                        strategy_embed_concurrency,
                        time.perf_counter() - t_step,
                    )
                finally:
                    await storage.close()
            else:
                # Single embedding path (default)
                primary_strategy = normalized_strategies[0]
                chunk_texts = await asyncio.to_thread(
                    chunk_with_strategy,
                    connector_doc.source_markdown,
                    strategy=primary_strategy,
                    use_code_chunker=connector_doc.should_use_code_chunker,
                    chunk_size=chunk_size,
                )
                texts_to_embed = [content, *chunk_texts]
                embeddings = await asyncio.to_thread(embed_texts, texts_to_embed)
                summary_embedding, *chunk_embeddings = embeddings

                chunks = [
                    Chunk(content=text, embedding=emb)
                    for text, emb in zip(chunk_texts, chunk_embeddings, strict=False)
                ]
                perf.info(
                    "[indexing] chunk+embed doc=%d chunks=%d in %.3fs",
                    document.id,
                    len(chunks),
                    time.perf_counter() - t_step,
                )

            document.content = content
            if summary_embedding is not None:
                document.embedding = summary_embedding
            attach_chunks_to_document(document, chunks)
            document.updated_at = datetime.now(UTC)

            # Store pipeline configuration in document_metadata for UI display
            pipeline_meta: dict = dict(document.document_metadata or {})
            if embedding_config:
                model_keys = embedding_config.get("model_keys", [])
                if model_keys:
                    pipeline_meta["embedding_models"] = model_keys
                    pipeline_meta["embedding_mode"] = embedding_config.get("mode", "multi")
            if normalized_strategies:
                pipeline_meta["chunking_strategies"] = normalized_strategies
            if chunk_size is not None:
                pipeline_meta["chunk_size"] = chunk_size
            document.document_metadata = pipeline_meta
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(document, "document_metadata")

            document.status = DocumentStatus.ready()
            await self.session.commit()
            perf.info(
                "[indexing] index TOTAL doc=%d chunks=%d in %.3fs",
                document.id,
                len(chunks),
                time.perf_counter() - t_index,
            )
            log_index_success(ctx, chunk_count=len(chunks))

            await self._enqueue_ai_sort_if_enabled(document)

        except RETRYABLE_LLM_ERRORS as e:
            log_retryable_llm_error(ctx, e)
            await rollback_and_persist_failure(
                self.session, document, llm_retryable_message(e)
            )

        except PERMANENT_LLM_ERRORS as e:
            log_permanent_llm_error(ctx, e)
            await rollback_and_persist_failure(
                self.session, document, llm_permanent_message(e)
            )

        except RecursionError as e:
            log_chunking_overflow(ctx, e)
            await rollback_and_persist_failure(
                self.session, document, PipelineMessages.CHUNKING_OVERFLOW
            )

        except EMBEDDING_ERRORS as e:
            log_embedding_error(ctx, e)
            await rollback_and_persist_failure(
                self.session, document, embedding_message(e)
            )

        except Exception as e:
            log_unexpected_error(ctx, e)
            await rollback_and_persist_failure(
                self.session, document, safe_exception_message(e)
            )

        with contextlib.suppress(Exception):
            await self.session.refresh(document)

        return document

    async def _enqueue_ai_sort_if_enabled(self, document: Document) -> None:
        """Fire-and-forget: enqueue incremental AI sort if the search space has it enabled."""
        try:
            from app.db import SearchSpace

            result = await self.session.execute(
                select(SearchSpace.ai_file_sort_enabled).where(
                    SearchSpace.id == document.search_space_id
                )
            )
            enabled = result.scalar()
            if not enabled:
                return

            from app.tasks.celery_tasks.document_tasks import ai_sort_document_task

            user_id = str(document.created_by_id) if document.created_by_id else ""
            ai_sort_document_task.delay(document.search_space_id, user_id, document.id)
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to enqueue AI sort for document %s", document.id, exc_info=True
            )

    async def index_batch_parallel(
        self,
        connector_docs: list[ConnectorDocument],
        get_llm: Callable[[AsyncSession], Awaitable],
        *,
        max_concurrency: int = 4,
        on_heartbeat: Callable[[int], Awaitable[None]] | None = None,
        heartbeat_interval: float = 30.0,
    ) -> tuple[list[Document], int, int]:
        """Index documents in parallel with bounded concurrency.

        Phase 1 (serial): prepare_for_indexing using self.session.
        Phase 2 (parallel): index each document in an isolated session,
        bounded by a semaphore to avoid overwhelming APIs/DB.
        """
        logger = logging.getLogger(__name__)
        perf = get_perf_logger()
        t_total = time.perf_counter()

        doc_map = {compute_unique_identifier_hash(cd): cd for cd in connector_docs}
        documents = await self.prepare_for_indexing(connector_docs)

        if not documents:
            return [], 0, 0

        from app.tasks.celery_tasks import get_celery_session_maker

        sem = asyncio.Semaphore(max_concurrency)
        lock = asyncio.Lock()
        indexed_count = 0
        failed_count = 0
        results: list[Document] = []
        last_heartbeat = time.time()

        async def _index_one(document: Document) -> Document | Exception:
            nonlocal indexed_count, failed_count, last_heartbeat

            connector_doc = doc_map.get(document.unique_identifier_hash)
            if connector_doc is None:
                logger.warning(
                    "No matching ConnectorDocument for document %s, skipping",
                    document.id,
                )
                async with lock:
                    failed_count += 1
                return document

            async with sem:
                session_maker = get_celery_session_maker()
                async with session_maker() as isolated_session:
                    try:
                        refetched = await isolated_session.get(Document, document.id)
                        if refetched is None:
                            async with lock:
                                failed_count += 1
                            return document

                        llm = await get_llm(isolated_session)
                        iso_pipeline = IndexingPipelineService(isolated_session)
                        result = await iso_pipeline.index(refetched, connector_doc, llm)

                        async with lock:
                            if DocumentStatus.is_state(
                                result.status, DocumentStatus.READY
                            ):
                                indexed_count += 1
                            else:
                                failed_count += 1

                            if on_heartbeat:
                                now = time.time()
                                if now - last_heartbeat >= heartbeat_interval:
                                    await on_heartbeat(indexed_count)
                                    last_heartbeat = now

                        return result
                    except Exception as exc:
                        logger.error(
                            "Parallel index failed for doc %s: %s",
                            document.id,
                            exc,
                            exc_info=True,
                        )
                        async with lock:
                            failed_count += 1
                        return exc

        tasks = [_index_one(doc) for doc in documents]
        t_parallel = time.perf_counter()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        perf.info(
            "[indexing] index_batch_parallel gather docs=%d concurrency=%d "
            "indexed=%d failed=%d in %.3fs",
            len(documents),
            max_concurrency,
            indexed_count,
            failed_count,
            time.perf_counter() - t_parallel,
        )

        for outcome in outcomes:
            if isinstance(outcome, Document):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                pass

        perf.info(
            "[indexing] index_batch_parallel TOTAL input=%d prepared=%d "
            "indexed=%d failed=%d in %.3fs",
            len(connector_docs),
            len(documents),
            indexed_count,
            failed_count,
            time.perf_counter() - t_total,
        )
        return results, indexed_count, failed_count
