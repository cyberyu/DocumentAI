"""Task dispatcher abstraction for background document processing.

Decouples the upload endpoint from Celery so tests can swap in a
synchronous (inline) implementation that needs only PostgreSQL.
"""

from __future__ import annotations

from typing import Any, Protocol


class TaskDispatcher(Protocol):
    async def dispatch_file_processing(
        self,
        *,
        document_id: int,
        temp_path: str,
        filename: str,
        search_space_id: int,
        user_id: str,
        should_summarize: bool = False,
        use_vision_llm: bool = False,
        processing_mode: str = "basic",
        embedding_config: Any = None,
        chunking_strategy: str | None = None,
        chunking_strategies: list[str] | None = None,
        chunk_size: int | None = None,
        etl_service_override: str | None = None,
        pipeline_id: str | None = None,
    ) -> None: ...


class CeleryTaskDispatcher:
    """Production dispatcher — fires Celery tasks via Redis broker."""

    async def dispatch_file_processing(
        self,
        *,
        document_id: int,
        temp_path: str,
        filename: str,
        search_space_id: int,
        user_id: str,
        should_summarize: bool = False,
        use_vision_llm: bool = False,
        processing_mode: str = "basic",
        embedding_config: Any = None,
        chunking_strategy: str | None = None,
        chunking_strategies: list[str] | None = None,
        chunk_size: int | None = None,
        etl_service_override: str | None = None,
        pipeline_id: str | None = None,
    ) -> None:
        from app.tasks.celery_tasks.document_tasks import (
            process_file_upload_with_document_task,
        )

        process_file_upload_with_document_task.delay(
            document_id=document_id,
            temp_path=temp_path,
            filename=filename,
            search_space_id=search_space_id,
            user_id=user_id,
            should_summarize=should_summarize,
            use_vision_llm=use_vision_llm,
            processing_mode=processing_mode,
            embedding_config=embedding_config,
            chunking_strategy=chunking_strategy,
            chunking_strategies=chunking_strategies,
            chunk_size=chunk_size,
            etl_service_override=etl_service_override,
            pipeline_id=pipeline_id,
        )


async def get_task_dispatcher() -> TaskDispatcher:
    return CeleryTaskDispatcher()
