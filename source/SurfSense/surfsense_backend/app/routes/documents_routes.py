# Force asyncio to use standard event loop before unstructured imports
import asyncio
import io
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel as PydanticBaseModel, Field
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db import (
    BenchmarkData,
    Chunk,
    Document,
    DocumentType,
    DocumentVersion,
    Folder,
    Permission,
    SearchSpace,
    SearchSpaceMembership,
    User,
    get_async_session,
)
from app.schemas import (
    ChunkRead,
    DocumentRead,
    DocumentsCreate,
    DocumentStatusBatchResponse,
    DocumentStatusItemRead,
    DocumentStatusSchema,
    DocumentTitleRead,
    DocumentTitleSearchResponse,
    DocumentUpdate,
    DocumentWithChunksRead,
    FolderRead,
    PaginatedResponse,
)
from app.services.task_dispatcher import TaskDispatcher, get_task_dispatcher
from app.users import current_active_user
from app.utils.rbac import check_permission

try:
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
except RuntimeError as e:
    print("Error setting event loop policy", e)
    pass

import os

os.environ["UNSTRUCTURED_HAS_PATCHED_LOOP"] = "1"


router = APIRouter()

MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB per file
MAX_BENCHMARK_DATASET_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB per benchmark dataset


def _document_source_key(title: str | None) -> str:
    if not title:
        return ""
    return title.split("__", 1)[0]


class BenchmarkDataRead(PydanticBaseModel):
    benchmarkdata_id: int
    doc_id: int
    task_type: str
    task_num: int
    created_date: datetime
    dataset_filename: str
    dataset_mime_type: str | None = None
    dataset_size_bytes: int


class BenchmarkDataListResponse(PydanticBaseModel):
    items: list[BenchmarkDataRead]
    total: int


def _build_document_metadata_with_benchmark_count(
    document: Document,
    benchmark_count: int,
) -> dict[str, Any]:
    metadata = (
        dict(document.document_metadata)
        if isinstance(document.document_metadata, dict)
        else {}
    )
    metadata["has_benchmark_data"] = benchmark_count > 0
    metadata["benchmark_data_count"] = benchmark_count
    metadata["benchmark_data_updated_at"] = datetime.now(UTC).isoformat()
    return metadata


@router.post("/documents")
async def create_documents(
    request: DocumentsCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Create new documents.
    Requires DOCUMENTS_CREATE permission.
    """
    try:
        # Check permission
        await check_permission(
            session,
            user,
            request.search_space_id,
            Permission.DOCUMENTS_CREATE.value,
            "You don't have permission to create documents in this search space",
        )

        if request.document_type == DocumentType.EXTENSION:
            from app.tasks.celery_tasks.document_tasks import (
                process_extension_document_task,
            )

            for individual_document in request.content:
                # Convert document to dict for Celery serialization
                document_dict = {
                    "metadata": {
                        "VisitedWebPageTitle": individual_document.metadata.VisitedWebPageTitle,
                        "VisitedWebPageURL": individual_document.metadata.VisitedWebPageURL,
                        "BrowsingSessionId": individual_document.metadata.BrowsingSessionId,
                        "VisitedWebPageDateWithTimeInISOString": individual_document.metadata.VisitedWebPageDateWithTimeInISOString,
                        "VisitedWebPageVisitDurationInMilliseconds": individual_document.metadata.VisitedWebPageVisitDurationInMilliseconds,
                        "VisitedWebPageReffererURL": individual_document.metadata.VisitedWebPageReffererURL,
                    },
                    "pageContent": individual_document.pageContent,
                }
                process_extension_document_task.delay(
                    document_dict, request.search_space_id, str(user.id)
                )
        elif request.document_type == DocumentType.YOUTUBE_VIDEO:
            from app.tasks.celery_tasks.document_tasks import process_youtube_video_task

            for url in request.content:
                process_youtube_video_task.delay(
                    url, request.search_space_id, str(user.id)
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid document type")

        await session.commit()
        return {
            "message": "Documents queued for background processing",
            "status": "queued",
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to process documents: {e!s}"
        ) from e


@router.post("/documents/fileupload")
async def create_documents_file_upload(
    files: list[UploadFile],
    search_space_id: int = Form(...),
    should_summarize: bool = Form(False),
    use_vision_llm: bool = Form(False),
    processing_mode: str = Form("basic"),
    etl_service: Optional[str] = Form(default=None),
    etl_services: Optional[str] = Form(default=None),
    embedding_models: Optional[str] = Form(default=None),  # JSON string array
    chunking_strategy: Optional[str] = Form(default=None),
    chunking_strategies: Optional[str] = Form(default=None),
    chunk_size: int | None = Form(default=None),
    chunk_sizes: Optional[str] = Form(default=None),
    generate_variants: bool = Form(False),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
    dispatcher: TaskDispatcher = Depends(get_task_dispatcher),
):
    """
    Upload files as documents with real-time status tracking.

    Implements 2-phase document status updates for real-time UI feedback:
    - Phase 1: Create all documents with 'pending' status (visible in UI immediately via Zero)
    - Phase 2: Celery processes each file: pending → processing → ready/failed

    Requires DOCUMENTS_CREATE permission.
    """
    import json
    import os
    import shutil
    import tempfile
    import uuid
    from datetime import datetime
    from pathlib import PurePosixPath

    from app.db import DocumentStatus
    from app.etl_pipeline.file_classifier import FileCategory, classify_file
    from app.etl_pipeline.etl_document import ProcessingMode
    from app.tasks.document_processors.base import (
        check_document_by_unique_identifier,
        get_current_timestamp,
    )
    from app.utils.document_converters import generate_unique_identifier_hash
    from app.utils.file_extensions import get_document_extensions_for_service

    validated_mode = ProcessingMode.coerce(processing_mode)
    
    # Parse embedding_models if provided
    logger = logging.getLogger(__name__)
    logger.info(f"[DEBUG] embedding_models received: {repr(embedding_models)}")
    logger.info(f"[DEBUG] chunking_strategy received: {repr(chunking_strategy)}")
    logger.info(f"[DEBUG] chunking_strategies received: {repr(chunking_strategies)}")
    logger.info(f"[DEBUG] chunk_size received: {repr(chunk_size)}")
    logger.info(f"[DEBUG] chunk_sizes received: {repr(chunk_sizes)}")
    logger.info(f"[DEBUG] generate_variants received: {repr(generate_variants)}")
    logger.info(f"[DEBUG] etl_service received: {repr(etl_service)}")
    logger.info(f"[DEBUG] etl_services received: {repr(etl_services)}")

    default_etl_service = (
        etl_service.strip().upper()
        if isinstance(etl_service, str) and etl_service.strip()
        else (os.getenv("ETL_SERVICE") or "DOCLING").strip().upper()
    )
    allowed_etl_services = {"MINERU", "DOCLING", "UNSTRUCTURED", "LLAMACLOUD"}
    if default_etl_service not in allowed_etl_services:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid etl_service. Allowed values: "
                "MINERU, DOCLING, UNSTRUCTURED, LLAMACLOUD"
            ),
        )

    resolved_etl_services: list[str] = [default_etl_service]
    if isinstance(etl_services, str) and etl_services.strip():
        try:
            raw_etl_services = json.loads(etl_services.strip())
            if isinstance(raw_etl_services, str):
                raw_etl_services = [raw_etl_services]
            if not isinstance(raw_etl_services, list):
                raise ValueError("etl_services must be a JSON array")

            deduped_services: list[str] = []
            seen_services: set[str] = set()
            for raw_service in raw_etl_services:
                if not isinstance(raw_service, str) or not raw_service.strip():
                    continue
                normalized_service = raw_service.strip().upper()
                if normalized_service not in allowed_etl_services:
                    raise ValueError(
                        "Invalid etl_services value. Allowed values: "
                        "MINERU, DOCLING, UNSTRUCTURED, LLAMACLOUD"
                    )
                if normalized_service in seen_services:
                    continue
                deduped_services.append(normalized_service)
                seen_services.add(normalized_service)

            if not deduped_services:
                raise ValueError("etl_services must contain at least one valid ETL service")

            resolved_etl_services = deduped_services
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid etl_services format: {e}",
            )

    resolved_etl_service = resolved_etl_services[0]
    shared_tmp_dir = os.getenv("SHARED_TMP_DIR", "/shared_tmp")
    try:
        os.makedirs(shared_tmp_dir, exist_ok=True)
    except OSError:
        shared_tmp_dir = tempfile.gettempdir()
        os.makedirs(shared_tmp_dir, exist_ok=True)
        logger.warning("Falling back to temp dir '%s' for upload staging", shared_tmp_dir)

    if chunk_size is not None and chunk_size <= 0:
        raise HTTPException(status_code=400, detail="chunk_size must be a positive integer")

    parsed_chunk_sizes: list[int | None] = []
    if chunk_sizes:
        try:
            raw_sizes = json.loads(chunk_sizes.strip())
            if isinstance(raw_sizes, int):
                raw_sizes = [raw_sizes]
            if not isinstance(raw_sizes, list):
                raise ValueError("chunk_sizes must be a JSON array")
            seen_sizes: set[int] = set()
            for raw_size in raw_sizes:
                size = int(raw_size)
                if size <= 0:
                    raise ValueError("chunk_sizes values must be positive integers")
                if size not in seen_sizes:
                    parsed_chunk_sizes.append(size)
                    seen_sizes.add(size)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid chunk_sizes format: {e}",
            )
    elif chunk_size is not None:
        parsed_chunk_sizes = [chunk_size]
    
    embedding_config = None
    parsed_embedding_models: list[str] = []
    if embedding_models:
        try:
            raw_value = embedding_models.strip()
            parsed_models = json.loads(raw_value)
            if isinstance(parsed_models, str):
                parsed_models = [parsed_models]
            if not isinstance(parsed_models, list):
                raise ValueError("embedding_models must be a JSON array")
            parsed_models = [m.strip() for m in parsed_models if isinstance(m, str) and m.strip()]
            if not parsed_models:
                raise ValueError("embedding_models must contain at least one non-empty model key")
            parsed_embedding_models = parsed_models
            # Create embedding config for multi-embedding if multiple models provided
            if len(parsed_models) > 1:
                embedding_config = {
                    "mode": "multi",
                    "model_keys": parsed_models
                }
                logger.info(f"[DEBUG] Created MULTI-embedding config: {embedding_config}")
            elif len(parsed_models) == 1:
                embedding_config = {
                    "mode": "single",
                    "model_keys": parsed_models
                }
                logger.info(f"[DEBUG] Created SINGLE-embedding config: {embedding_config}")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"[DEBUG] Error parsing embedding_models: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid embedding_models format: {e}"
            )

    def normalize_chunking(value: str) -> str:
        normalized_strategy = value.strip().lower()
        if normalized_strategy == "sandwich_chunk":
            return "sandwitch_chunk"
        if normalized_strategy in {
            "sandwitch_chunk",
            "chunk_text",
            "chunk_hybrid",
            "chunk_recursive",
        }:
            return normalized_strategy
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid chunking strategy. Allowed values: "
                "sandwitch_chunk, chunk_text, chunk_hybrid, chunk_recursive"
            ),
        )

    resolved_chunking_strategies: list[str] = []
    if chunking_strategies:
        try:
            parsed_strategies = json.loads(chunking_strategies.strip())
            if isinstance(parsed_strategies, str):
                parsed_strategies = [parsed_strategies]
            if not isinstance(parsed_strategies, list):
                raise ValueError("chunking_strategies must be a JSON array")

            seen: set[str] = set()
            for strategy_value in parsed_strategies:
                if not isinstance(strategy_value, str) or not strategy_value.strip():
                    continue
                normalized = normalize_chunking(strategy_value)
                if normalized not in seen:
                    resolved_chunking_strategies.append(normalized)
                    seen.add(normalized)

            if not resolved_chunking_strategies:
                raise ValueError("chunking_strategies must contain at least one valid strategy")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid chunking_strategies format: {e}",
            )
    elif chunking_strategy:
        resolved_chunking_strategies = [normalize_chunking(chunking_strategy)]
    else:
        resolved_chunking_strategies = [
            "chunk_text",
            "chunk_recursive",
            "sandwitch_chunk",
        ]

    resolved_chunking_strategy = resolved_chunking_strategies[0]

    variant_specs: list[dict[str, Any]] = []
    if generate_variants:
        if not parsed_embedding_models:
            raise HTTPException(
                status_code=400,
                detail="embedding_models is required when generate_variants=true",
            )

        effective_chunk_sizes = parsed_chunk_sizes or [chunk_size or 1024]
        for etl_variant_service in resolved_etl_services:
            etl_slug = etl_variant_service.lower()
            for strategy in resolved_chunking_strategies:
                for model_key in parsed_embedding_models:
                    for size in effective_chunk_sizes:
                        model_slug = model_key.replace("/", "_").replace("-", "_")
                        size_slug = f"tok{size}" if size is not None else "tokdefault"
                        variant_specs.append(
                            {
                                "etl_service": etl_variant_service,
                                "chunking_strategy": strategy,
                                "chunking_strategies": [strategy],
                                "chunk_size": size,
                                "embedding_config": {
                                    "mode": "single",
                                    "model_keys": [model_key],
                                },
                                "variant_suffix": f"{etl_slug}__{strategy}__{model_slug}__{size_slug}",
                            }
                        )
    else:
        variant_specs = [
            {
                "etl_service": resolved_etl_service,
                "chunking_strategy": resolved_chunking_strategy,
                "chunking_strategies": resolved_chunking_strategies,
                "chunk_size": chunk_size,
                "embedding_config": embedding_config,
                "variant_suffix": None,
            }
        ]

    try:
        await check_permission(
            session,
            user,
            search_space_id,
            Permission.DOCUMENTS_CREATE.value,
            "You don't have permission to create documents in this search space",
        )

        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        for file in files:
            file_size = file.size or 0
            if file_size > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{file.filename}' ({file_size / (1024 * 1024):.1f} MB) "
                    f"exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB per-file limit.",
                )

        # ===== Read all files concurrently to avoid blocking the event loop =====
        async def _read_and_save(file: UploadFile) -> tuple[str, str, int]:
            """Read upload content and write to temp file off the event loop."""
            content = await file.read()
            file_size = len(content)
            filename = file.filename or "unknown"

            if file_size > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{filename}' ({file_size / (1024 * 1024):.1f} MB) "
                    f"exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB per-file limit.",
                )

            def _write_temp() -> str:
                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=os.path.splitext(filename)[1],
                    dir=shared_tmp_dir,
                ) as tmp:
                    tmp.write(content)
                    return tmp.name

            temp_path = await asyncio.to_thread(_write_temp)
            return temp_path, filename, file_size

        saved_files = await asyncio.gather(*(_read_and_save(f) for f in files))

        # ===== PHASE 1: Create pending documents for all files =====
        created_documents: list[Document] = []
        files_to_process: list[tuple[Document, str, str, dict[str, Any], str, str]] = []
        skipped_duplicates = 0
        duplicate_document_ids: list[int] = []

        for temp_path, filename, file_size in saved_files:
            try:
                file_stem, file_ext = os.path.splitext(filename)
                file_suffix = PurePosixPath(filename).suffix.lower()
                file_category = classify_file(filename)
                file_variant_specs: list[dict[str, Any]] = []
                for spec in variant_specs:
                    variant_etl_service = str(spec.get("etl_service") or resolved_etl_service)
                    if file_category in {
                        FileCategory.PLAINTEXT,
                        FileCategory.AUDIO,
                        FileCategory.DIRECT_CONVERT,
                    }:
                        file_variant_specs.append(spec)
                        continue
                    supported_exts = get_document_extensions_for_service(variant_etl_service)
                    if file_suffix and file_suffix not in supported_exts:
                        logger.info(
                            "[DEBUG] Skipping unsupported ETL variant for %s: etl=%s ext=%s",
                            filename,
                            variant_etl_service,
                            file_suffix,
                        )
                        continue
                    file_variant_specs.append(spec)

                if not file_variant_specs:
                    selected_etl_values = sorted(
                        {
                            str(spec.get("etl_service") or resolved_etl_service)
                            for spec in variant_specs
                        }
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"No selected ETL service supports file type '{file_suffix or file_ext or filename}'. "
                            f"Selected ETLs: {', '.join(selected_etl_values)}"
                        ),
                    )

                pipeline_variants: list[dict[str, Any]] = []
                for spec in file_variant_specs:
                    variant_suffix = spec.get("variant_suffix")
                    variant_etl_service = str(spec.get("etl_service") or resolved_etl_service)
                    variant_file_name_with_ext = (
                        f"{file_stem}__{variant_suffix}{file_ext}"
                        if variant_suffix
                        else filename
                    )

                    embedding_cfg = spec.get("embedding_config") or {}
                    pipeline_signature = {
                        "etl_service": variant_etl_service,
                        "chunking_strategy": spec.get("chunking_strategy"),
                        "chunking_strategies": spec.get("chunking_strategies") or [],
                        "chunk_size": spec.get("chunk_size"),
                        "embedding_mode": embedding_cfg.get("mode"),
                        "embedding_models": embedding_cfg.get("model_keys") or [],
                    }
                    unique_identifier_source = (
                        f"{variant_file_name_with_ext}::"
                        f"{json.dumps(pipeline_signature, sort_keys=True)}"
                    )
                    pipeline_id = generate_unique_identifier_hash(
                        DocumentType.FILE, unique_identifier_source, search_space_id
                    )
                    pipeline_variants.append(
                        {
                            "filename": variant_file_name_with_ext,
                            "etl_service": variant_etl_service,
                            "pipeline_signature": pipeline_signature,
                            "pipeline_id": pipeline_id,
                            "spec": spec,
                        }
                    )

                base_unique_identifier_hash = generate_unique_identifier_hash(
                    DocumentType.FILE, filename, search_space_id
                )
                existing_document = await check_document_by_unique_identifier(
                    session, base_unique_identifier_hash
                )

                existing_pipeline_signatures = []
                if existing_document and isinstance(existing_document.document_metadata, dict):
                    raw_signatures = existing_document.document_metadata.get("pipeline_signatures")
                    if isinstance(raw_signatures, list):
                        existing_pipeline_signatures = [
                            signature
                            for signature in raw_signatures
                            if isinstance(signature, dict)
                        ]

                is_ready_duplicate = bool(existing_document) and DocumentStatus.is_state(
                    existing_document.status, DocumentStatus.READY
                )
                is_single_variant_upload = len(file_variant_specs) == 1
                requested_single_signature = pipeline_variants[0]["pipeline_signature"]
                matches_existing_single_signature = (
                    requested_single_signature in existing_pipeline_signatures
                    if existing_pipeline_signatures
                    else True
                )
                should_skip_duplicate = (
                    is_ready_duplicate
                    and is_single_variant_upload
                    and not generate_variants
                    and matches_existing_single_signature
                )

                if should_skip_duplicate:
                    skipped_duplicates += 1
                    duplicate_document_ids.append(existing_document.id)
                    try:
                        os.unlink(temp_path)
                    except FileNotFoundError:
                        pass
                    continue

                primary_variant = pipeline_variants[0]
                pipeline_signatures = [v["pipeline_signature"] for v in pipeline_variants]
                pipeline_ids = [v["pipeline_id"] for v in pipeline_variants]

                if existing_document:
                    existing_document.status = DocumentStatus.pending()
                    existing_document.content = "Processing..."
                    existing_document.document_metadata = {
                        **(existing_document.document_metadata or {}),
                        "FILE_NAME": filename,
                        "ETL_SERVICE": primary_variant["etl_service"],
                        "file_size": file_size,
                        "upload_time": datetime.now().isoformat(),
                        "pipeline_variant_count": len(pipeline_variants),
                        "pipeline_signatures": pipeline_signatures,
                        "pipeline_ids": pipeline_ids,
                    }
                    existing_document.updated_at = get_current_timestamp()
                    document = existing_document
                else:
                    document = Document(
                        search_space_id=search_space_id,
                        title=filename if filename != "unknown" else "Uploaded File",
                        document_type=DocumentType.FILE,
                        document_metadata={
                            "FILE_NAME": filename,
                            "ETL_SERVICE": primary_variant["etl_service"],
                            "file_size": file_size,
                            "upload_time": datetime.now().isoformat(),
                            "pipeline_variant_count": len(pipeline_variants),
                            "pipeline_signatures": pipeline_signatures,
                            "pipeline_ids": pipeline_ids,
                        },
                        content="Processing...",
                        content_hash=base_unique_identifier_hash,
                        unique_identifier_hash=base_unique_identifier_hash,
                        embedding=None,
                        status=DocumentStatus.pending(),
                        updated_at=get_current_timestamp(),
                        created_by_id=str(user.id),
                    )
                    session.add(document)

                created_documents.append(document)

                for variant in pipeline_variants:
                    with tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=file_ext,
                        dir=shared_tmp_dir,
                    ) as variant_tmp:
                        await asyncio.to_thread(
                            shutil.copyfile, temp_path, variant_tmp.name
                        )
                        variant_temp_path = variant_tmp.name

                    files_to_process.append(
                        (
                            document,
                            variant_temp_path,
                            variant["filename"],
                            variant["spec"],
                            variant["etl_service"],
                            variant["pipeline_id"],
                        )
                    )

                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

            except HTTPException:
                raise
            except Exception as e:
                os.unlink(temp_path)
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to process file {filename}: {e!s}",
                ) from e

        if created_documents:
            await session.commit()
            for doc in created_documents:
                await session.refresh(doc)

        # ===== PHASE 2: Dispatch tasks for each file =====
        for document, temp_path, filename, spec, etl_service_override, pipeline_id in files_to_process:
            dispatch_embedding_config = spec.get("embedding_config")
            dispatch_chunking_strategy = spec.get("chunking_strategy")
            dispatch_chunking_strategies = spec.get("chunking_strategies")
            dispatch_chunk_size = spec.get("chunk_size")
            logger.info(
                "[DEBUG] Dispatching task for %s with embedding_config=%s chunking_strategy=%s chunk_size=%s pipeline_id=%s",
                filename,
                dispatch_embedding_config,
                dispatch_chunking_strategy,
                dispatch_chunk_size,
                pipeline_id,
            )
            await dispatcher.dispatch_file_processing(
                document_id=document.id,
                temp_path=temp_path,
                filename=filename,
                search_space_id=search_space_id,
                user_id=str(user.id),
                should_summarize=should_summarize,
                use_vision_llm=use_vision_llm,
                processing_mode=validated_mode.value,
                embedding_config=dispatch_embedding_config,
                chunking_strategy=dispatch_chunking_strategy,
                chunking_strategies=dispatch_chunking_strategies,
                chunk_size=dispatch_chunk_size,
                etl_service_override=etl_service_override,
                pipeline_id=pipeline_id,
            )

        return {
            "message": "Files uploaded for processing",
            "document_ids": list({doc.id for doc in created_documents}),
            "duplicate_document_ids": duplicate_document_ids,
            "total_files": len(files_to_process) + skipped_duplicates,
            "pending_files": len(files_to_process),
            "skipped_duplicates": skipped_duplicates,
            "variant_count": len(variant_specs),
            "pipeline_jobs": [
                {
                    "document_id": document.id,
                    "pipeline_id": pipeline_id,
                    "job_name": filename,
                    "etl_service": etl_service_override,
                    "chunking_strategy": spec.get("chunking_strategy"),
                    "chunk_size": spec.get("chunk_size"),
                    "embedding_models": (
                        (spec.get("embedding_config") or {}).get("model_keys") or []
                    ),
                }
                for document, _, filename, spec, etl_service_override, pipeline_id in files_to_process
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to upload files: {e!s}"
        ) from e


@router.get("/documents", response_model=PaginatedResponse[DocumentRead])
async def read_documents(
    skip: int | None = None,
    page: int | None = None,
    page_size: int = 50,
    search_space_id: int | None = None,
    document_types: str | None = None,
    folder_id: int | str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    List documents the user has access to, with optional filtering and pagination.
    Requires DOCUMENTS_READ permission for the search space(s).

    Args:
        skip: Absolute number of items to skip from the beginning. If provided, it takes precedence over 'page'.
        page: Zero-based page index used when 'skip' is not provided.
        page_size: Number of items per page (default: 50). Use -1 to return all remaining items after the offset.
        search_space_id: If provided, restrict results to a specific search space.
        document_types: Comma-separated list of document types to filter by (e.g., "EXTENSION,FILE,SLACK_CONNECTOR").
        session: Database session (injected).
        user: Current authenticated user (injected).

    Returns:
        PaginatedResponse[DocumentRead]: Paginated list of documents visible to the user.

    Notes:
        - If both 'skip' and 'page' are provided, 'skip' is used.
        - Results are scoped to documents in search spaces the user has membership in.
    """
    try:
        from sqlalchemy import func

        # If specific search_space_id, check permission
        if search_space_id is not None:
            await check_permission(
                session,
                user,
                search_space_id,
                Permission.DOCUMENTS_READ.value,
                "You don't have permission to read documents in this search space",
            )
            query = (
                select(Document)
                .options(selectinload(Document.created_by))
                .filter(Document.search_space_id == search_space_id)
            )
            count_query = (
                select(func.count())
                .select_from(Document)
                .filter(Document.search_space_id == search_space_id)
            )
        else:
            # Get documents from all search spaces user has membership in
            query = (
                select(Document)
                .options(selectinload(Document.created_by))
                .join(SearchSpace)
                .join(SearchSpaceMembership)
                .filter(SearchSpaceMembership.user_id == user.id)
            )
            count_query = (
                select(func.count())
                .select_from(Document)
                .join(SearchSpace)
                .join(SearchSpaceMembership)
                .filter(SearchSpaceMembership.user_id == user.id)
            )

        # Filter by document_types if provided
        if document_types is not None and document_types.strip():
            type_list = [t.strip() for t in document_types.split(",") if t.strip()]
            if type_list:
                query = query.filter(Document.document_type.in_(type_list))
                count_query = count_query.filter(Document.document_type.in_(type_list))

        # Filter by folder_id: "root" or "null" => root level (folder_id IS NULL),
        # integer => specific folder, omitted => all documents
        if folder_id is not None:
            if str(folder_id).lower() in ("root", "null"):
                query = query.filter(Document.folder_id.is_(None))
                count_query = count_query.filter(Document.folder_id.is_(None))
            else:
                fid = int(folder_id)
                query = query.filter(Document.folder_id == fid)
                count_query = count_query.filter(Document.folder_id == fid)

        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply sorting
        from sqlalchemy import asc as sa_asc, desc as sa_desc

        sort_column_map = {
            "created_at": Document.created_at,
            "title": Document.title,
            "document_type": Document.document_type,
        }
        sort_col = sort_column_map.get(sort_by, Document.created_at)
        query = query.order_by(
            sa_desc(sort_col) if sort_order == "desc" else sa_asc(sort_col)
        )

        # Calculate offset
        offset = 0
        if skip is not None:
            offset = skip
        elif page is not None:
            offset = page * page_size

        # Get paginated results
        if page_size == -1:
            result = await session.execute(query.offset(offset))
        else:
            result = await session.execute(query.offset(offset).limit(page_size))

        db_documents = result.scalars().all()

        # Convert database objects to API-friendly format
        api_documents = []
        for doc in db_documents:
            created_by_name = None
            created_by_email = None
            if doc.created_by:
                created_by_name = doc.created_by.display_name
                created_by_email = doc.created_by.email

            # Parse status from JSONB
            status_data = None
            if hasattr(doc, "status") and doc.status:
                status_data = DocumentStatusSchema(
                    state=doc.status.get("state", "ready"),
                    reason=doc.status.get("reason"),
                )

            raw_content = doc.content or ""
            api_documents.append(
                DocumentRead(
                    id=doc.id,
                    title=doc.title,
                    document_type=doc.document_type,
                    document_metadata=doc.document_metadata,
                    content="",
                    content_preview=raw_content[:300],
                    content_hash=doc.content_hash,
                    unique_identifier_hash=doc.unique_identifier_hash,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                    search_space_id=doc.search_space_id,
                    folder_id=doc.folder_id,
                    created_by_id=doc.created_by_id,
                    created_by_name=created_by_name,
                    created_by_email=created_by_email,
                    status=status_data,
                )
            )

        # Calculate pagination info
        actual_page = (
            page if page is not None else (offset // page_size if page_size > 0 else 0)
        )
        has_more = (offset + len(api_documents)) < total if page_size > 0 else False

        return PaginatedResponse(
            items=api_documents,
            total=total,
            page=actual_page,
            page_size=page_size,
            has_more=has_more,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch documents: {e!s}"
        ) from e


@router.get("/documents/search", response_model=PaginatedResponse[DocumentRead])
async def search_documents(
    title: str,
    skip: int | None = None,
    page: int | None = None,
    page_size: int = 50,
    search_space_id: int | None = None,
    document_types: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Search documents by title substring, optionally filtered by search_space_id and document_types.
    Requires DOCUMENTS_READ permission for the search space(s).

    Args:
        title: Case-insensitive substring to match against document titles. Required.
        skip: Absolute number of items to skip from the beginning. If provided, it takes precedence over 'page'. Default: None.
        page: Zero-based page index used when 'skip' is not provided. Default: None.
        page_size: Number of items per page. Use -1 to return all remaining items after the offset. Default: 50.
        search_space_id: Filter results to a specific search space. Default: None.
        document_types: Comma-separated list of document types to filter by (e.g., "EXTENSION,FILE,SLACK_CONNECTOR").
        session: Database session (injected).
        user: Current authenticated user (injected).

    Returns:
        PaginatedResponse[DocumentRead]: Paginated list of documents matching the query and filter.

    Notes:
        - Title matching uses ILIKE (case-insensitive).
        - If both 'skip' and 'page' are provided, 'skip' is used.
    """
    try:
        from sqlalchemy import func

        # If specific search_space_id, check permission
        if search_space_id is not None:
            await check_permission(
                session,
                user,
                search_space_id,
                Permission.DOCUMENTS_READ.value,
                "You don't have permission to read documents in this search space",
            )
            query = (
                select(Document)
                .options(selectinload(Document.created_by))
                .filter(Document.search_space_id == search_space_id)
            )
            count_query = (
                select(func.count())
                .select_from(Document)
                .filter(Document.search_space_id == search_space_id)
            )
        else:
            # Get documents from all search spaces user has membership in
            query = (
                select(Document)
                .options(selectinload(Document.created_by))
                .join(SearchSpace)
                .join(SearchSpaceMembership)
                .filter(SearchSpaceMembership.user_id == user.id)
            )
            count_query = (
                select(func.count())
                .select_from(Document)
                .join(SearchSpace)
                .join(SearchSpaceMembership)
                .filter(SearchSpaceMembership.user_id == user.id)
            )

        # Only search by title (case-insensitive)
        query = query.filter(Document.title.ilike(f"%{title}%"))
        count_query = count_query.filter(Document.title.ilike(f"%{title}%"))

        # Filter by document_types if provided
        if document_types is not None and document_types.strip():
            type_list = [t.strip() for t in document_types.split(",") if t.strip()]
            if type_list:
                query = query.filter(Document.document_type.in_(type_list))
                count_query = count_query.filter(Document.document_type.in_(type_list))

        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Calculate offset
        offset = 0
        if skip is not None:
            offset = skip
        elif page is not None:
            offset = page * page_size

        # Get paginated results
        if page_size == -1:
            result = await session.execute(query.offset(offset))
        else:
            result = await session.execute(query.offset(offset).limit(page_size))

        db_documents = result.scalars().all()

        # Convert database objects to API-friendly format
        api_documents = []
        for doc in db_documents:
            created_by_name = None
            created_by_email = None
            if doc.created_by:
                created_by_name = doc.created_by.display_name
                created_by_email = doc.created_by.email

            # Parse status from JSONB
            status_data = None
            if hasattr(doc, "status") and doc.status:
                status_data = DocumentStatusSchema(
                    state=doc.status.get("state", "ready"),
                    reason=doc.status.get("reason"),
                )

            raw_content = doc.content or ""
            api_documents.append(
                DocumentRead(
                    id=doc.id,
                    title=doc.title,
                    document_type=doc.document_type,
                    document_metadata=doc.document_metadata,
                    content="",
                    content_preview=raw_content[:300],
                    content_hash=doc.content_hash,
                    unique_identifier_hash=doc.unique_identifier_hash,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                    search_space_id=doc.search_space_id,
                    folder_id=doc.folder_id,
                    created_by_id=doc.created_by_id,
                    created_by_name=created_by_name,
                    created_by_email=created_by_email,
                    status=status_data,
                )
            )

        # Calculate pagination info
        actual_page = (
            page if page is not None else (offset // page_size if page_size > 0 else 0)
        )
        has_more = (offset + len(api_documents)) < total if page_size > 0 else False

        return PaginatedResponse(
            items=api_documents,
            total=total,
            page=actual_page,
            page_size=page_size,
            has_more=has_more,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search documents: {e!s}"
        ) from e


@router.get("/documents/search/titles", response_model=DocumentTitleSearchResponse)
async def search_document_titles(
    search_space_id: int,
    title: str = "",
    page: int = 0,
    page_size: int = 20,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Lightweight document title search optimized for mention picker (@mentions).

    Returns only id, title, and document_type - no content or metadata.
    Uses pg_trgm fuzzy search with similarity scoring for typo tolerance.
    Results are ordered by relevance using trigram similarity scores.

    Args:
        search_space_id: The search space to search in. Required.
        title: Search query (case-insensitive). If empty or < 2 chars, returns recent documents.
        page: Zero-based page index. Default: 0.
        page_size: Number of items per page. Default: 20.
        session: Database session (injected).
        user: Current authenticated user (injected).

    Returns:
        DocumentTitleSearchResponse: Lightweight list with has_more flag (no total count).
    """
    from sqlalchemy import desc, func, or_

    try:
        # Check permission for the search space
        await check_permission(
            session,
            user,
            search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        # Base query - only select lightweight fields
        query = select(
            Document.id,
            Document.title,
            Document.document_type,
        ).filter(Document.search_space_id == search_space_id)

        # If query is too short, return recent documents ordered by updated_at
        if len(title.strip()) < 2:
            query = query.order_by(Document.updated_at.desc().nullslast())
        else:
            # Fuzzy search using pg_trgm similarity + ILIKE fallback
            search_term = title.strip()

            # Similarity threshold for fuzzy matching (0.3 = ~30% trigram overlap)
            # Lower values = more fuzzy, higher values = stricter matching
            similarity_threshold = 0.3

            # Match documents that either:
            # 1. Have high trigram similarity (fuzzy match - handles typos)
            # 2. Contain the exact substring (ILIKE - handles partial matches)
            query = query.filter(
                or_(
                    func.similarity(Document.title, search_term) > similarity_threshold,
                    Document.title.ilike(f"%{search_term}%"),
                )
            )

            # Order by similarity score (descending) for best relevance ranking
            # Higher similarity = better match = appears first
            query = query.order_by(
                desc(func.similarity(Document.title, search_term)),
                Document.title,  # Alphabetical tiebreaker
            )

        # Fetch page_size + 1 to determine has_more without COUNT query
        offset = page * page_size
        result = await session.execute(query.offset(offset).limit(page_size + 1))
        rows = result.all()

        # Check if there are more results
        has_more = len(rows) > page_size
        items = rows[:page_size]  # Only return requested page_size

        # Convert to response format
        api_documents = [
            DocumentTitleRead(
                id=row.id,
                title=row.title,
                document_type=row.document_type,
            )
            for row in items
        ]

        return DocumentTitleSearchResponse(
            items=api_documents,
            has_more=has_more,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search document titles: {e!s}"
        ) from e


@router.get("/documents/by-virtual-path", response_model=DocumentTitleRead)
async def get_document_by_virtual_path(
    search_space_id: int,
    virtual_path: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Resolve a knowledge-base document id by exact virtual path."""
    try:
        await check_permission(
            session,
            user,
            search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        result = await session.execute(
            select(
                Document.id,
                Document.title,
                Document.document_type,
            ).filter(
                Document.search_space_id == search_space_id,
                Document.document_metadata["virtual_path"].as_string() == virtual_path,
            )
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")

        return DocumentTitleRead(
            id=row.id,
            title=row.title,
            document_type=row.document_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resolve document by virtual path: {e!s}",
        ) from e


@router.get("/documents/status", response_model=DocumentStatusBatchResponse)
async def get_documents_status(
    search_space_id: int,
    document_ids: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Batch status endpoint for documents in a search space.

    Returns lightweight status info for the provided document IDs, intended for
    polling async ETL progress in chat upload flows.
    """
    try:
        await check_permission(
            session,
            user,
            search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        # Parse comma-separated IDs (e.g. "1,2,3")
        parsed_ids = []
        for raw_id in document_ids.split(","):
            value = raw_id.strip()
            if not value:
                continue
            try:
                parsed_ids.append(int(value))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid document id: {value}",
                ) from None

        if not parsed_ids:
            return DocumentStatusBatchResponse(items=[])

        result = await session.execute(
            select(Document).filter(
                Document.search_space_id == search_space_id,
                Document.id.in_(parsed_ids),
            )
        )
        docs = result.scalars().all()

        items = [
            DocumentStatusItemRead(
                id=doc.id,
                title=doc.title,
                document_type=doc.document_type,
                status=DocumentStatusSchema(
                    state=(doc.status or {}).get("state", "ready"),
                    reason=(doc.status or {}).get("reason"),
                ),
            )
            for doc in docs
        ]
        return DocumentStatusBatchResponse(items=items)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch document status: {e!s}"
        ) from e


@router.get("/documents/type-counts")
async def get_document_type_counts(
    search_space_id: int | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Get counts of documents by type for search spaces the user has access to.
    Requires DOCUMENTS_READ permission for the search space(s).

    Args:
        search_space_id: If provided, restrict counts to a specific search space.
        session: Database session (injected).
        user: Current authenticated user (injected).

    Returns:
        Dict mapping document types to their counts.
    """
    try:
        from sqlalchemy import func

        if search_space_id is not None:
            # Check permission for specific search space
            await check_permission(
                session,
                user,
                search_space_id,
                Permission.DOCUMENTS_READ.value,
                "You don't have permission to read documents in this search space",
            )
            query = (
                select(Document.document_type, func.count(Document.id))
                .filter(Document.search_space_id == search_space_id)
                .group_by(Document.document_type)
            )
        else:
            # Get counts from all search spaces user has membership in
            query = (
                select(Document.document_type, func.count(Document.id))
                .join(SearchSpace)
                .join(SearchSpaceMembership)
                .filter(SearchSpaceMembership.user_id == user.id)
                .group_by(Document.document_type)
            )

        result = await session.execute(query)
        type_counts = dict(result.all())

        return type_counts
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch document type counts: {e!s}"
        ) from e


@router.get("/documents/by-chunk/{chunk_id}", response_model=DocumentWithChunksRead)
async def get_document_by_chunk_id(
    chunk_id: int,
    chunk_window: int = Query(
        5, ge=0, description="Number of chunks before/after the cited chunk to include"
    ),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Retrieves a document based on a chunk ID, including a window of chunks around the cited one.
    Uses SQL-level pagination to avoid loading all chunks into memory.
    """
    try:
        from sqlalchemy import and_, func, or_

        chunk_result = await session.execute(select(Chunk).filter(Chunk.id == chunk_id))
        chunk = chunk_result.scalars().first()

        if not chunk:
            raise HTTPException(
                status_code=404, detail=f"Chunk with id {chunk_id} not found"
            )

        document_result = await session.execute(
            select(Document).filter(Document.id == chunk.document_id)
        )
        document = document_result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail="Document not found",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        total_result = await session.execute(
            select(func.count())
            .select_from(Chunk)
            .filter(Chunk.document_id == document.id)
        )
        total_chunks = total_result.scalar() or 0

        cited_idx_result = await session.execute(
            select(func.count())
            .select_from(Chunk)
            .filter(
                Chunk.document_id == document.id,
                or_(
                    Chunk.created_at < chunk.created_at,
                    and_(Chunk.created_at == chunk.created_at, Chunk.id < chunk.id),
                ),
            )
        )
        cited_idx = cited_idx_result.scalar() or 0

        start = max(0, cited_idx - chunk_window)
        end = min(total_chunks, cited_idx + chunk_window + 1)

        windowed_result = await session.execute(
            select(Chunk)
            .filter(Chunk.document_id == document.id)
            .order_by(Chunk.created_at, Chunk.id)
            .offset(start)
            .limit(end - start)
        )
        windowed_chunks = windowed_result.scalars().all()

        return DocumentWithChunksRead(
            id=document.id,
            title=document.title,
            document_type=document.document_type,
            document_metadata=document.document_metadata,
            content=document.content,
            content_hash=document.content_hash,
            unique_identifier_hash=document.unique_identifier_hash,
            created_at=document.created_at,
            updated_at=document.updated_at,
            search_space_id=document.search_space_id,
            chunks=windowed_chunks,
            total_chunks=total_chunks,
            chunk_start_index=start,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve document: {e!s}"
        ) from e


@router.get("/documents/watched-folders", response_model=list[FolderRead])
async def get_watched_folders(
    search_space_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Return root folders that are marked as watched (metadata->>'watched' = 'true')."""
    await check_permission(
        session,
        user,
        search_space_id,
        Permission.DOCUMENTS_READ.value,
        "You don't have permission to read documents in this search space",
    )

    folders = (
        (
            await session.execute(
                select(Folder).where(
                    Folder.search_space_id == search_space_id,
                    Folder.parent_id.is_(None),
                    Folder.folder_metadata.isnot(None),
                    Folder.folder_metadata["watched"].astext == "true",
                )
            )
        )
        .scalars()
        .all()
    )

    return folders


@router.get(
    "/documents/{document_id}/chunks",
    response_model=PaginatedResponse[ChunkRead],
)
async def get_document_chunks_paginated(
    document_id: int,
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    start_offset: int | None = Query(
        None, ge=0, description="Direct offset; overrides page * page_size"
    ),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Paginated chunk loading for a document.
    Supports both page-based and offset-based access.
    """
    try:
        from sqlalchemy import func

        doc_result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = doc_result.scalars().first()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        total_result = await session.execute(
            select(func.count())
            .select_from(Chunk)
            .filter(Chunk.document_id == document_id)
        )
        total = total_result.scalar() or 0

        offset = start_offset if start_offset is not None else page * page_size
        chunks_result = await session.execute(
            select(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.created_at, Chunk.id)
            .offset(offset)
            .limit(page_size)
        )
        chunks = chunks_result.scalars().all()

        return PaginatedResponse(
            items=chunks,
            total=total,
            page=offset // page_size if page_size else page,
            page_size=page_size,
            has_more=(offset + len(chunks)) < total,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch chunks: {e!s}"
        ) from e


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def read_document(
    document_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Get a specific document by ID.
    Requires DOCUMENTS_READ permission for the search space.
    """
    try:
        result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404, detail=f"Document with id {document_id} not found"
            )

        # Check permission for the search space
        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        status_data = None
        if hasattr(document, "status") and document.status:
            status_data = DocumentStatusSchema(
                state=document.status.get("state", "ready"),
                reason=document.status.get("reason"),
            )

        raw_content = document.content or ""
        return DocumentRead(
            id=document.id,
            title=document.title,
            document_type=document.document_type,
            document_metadata=document.document_metadata,
            content=raw_content,
            content_preview=raw_content[:300],
            content_hash=document.content_hash,
            unique_identifier_hash=document.unique_identifier_hash,
            created_at=document.created_at,
            updated_at=document.updated_at,
            search_space_id=document.search_space_id,
            folder_id=document.folder_id,
            status=status_data,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch document: {e!s}"
        ) from e


@router.put("/documents/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: int,
    document_update: DocumentUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Update a document.
    Requires DOCUMENTS_UPDATE permission for the search space.
    """
    try:
        result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        db_document = result.scalars().first()

        if not db_document:
            raise HTTPException(
                status_code=404, detail=f"Document with id {document_id} not found"
            )

        # Check permission for the search space
        await check_permission(
            session,
            user,
            db_document.search_space_id,
            Permission.DOCUMENTS_UPDATE.value,
            "You don't have permission to update documents in this search space",
        )

        update_data = document_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_document, key, value)
        await session.commit()
        await session.refresh(db_document)

        status_data = None
        if hasattr(db_document, "status") and db_document.status:
            status_data = DocumentStatusSchema(
                state=db_document.status.get("state", "ready"),
                reason=db_document.status.get("reason"),
            )

        # Convert to DocumentRead for response
        return DocumentRead(
            id=db_document.id,
            title=db_document.title,
            document_type=db_document.document_type,
            document_metadata=db_document.document_metadata,
            content=db_document.content,
            content_hash=db_document.content_hash,
            unique_identifier_hash=db_document.unique_identifier_hash,
            created_at=db_document.created_at,
            updated_at=db_document.updated_at,
            search_space_id=db_document.search_space_id,
            folder_id=db_document.folder_id,
            status=status_data,
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update document: {e!s}"
        ) from e


@router.delete("/documents/{document_id}", response_model=dict)
async def delete_document(
    document_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Delete a document.
    Requires DOCUMENTS_DELETE permission for the search space.
    Documents in "processing" state cannot be deleted.

    Heavy cascade deletion runs asynchronously via Celery so the API
    response is fast and the deletion remains durable across API restarts.
    """
    try:
        result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404, detail=f"Document with id {document_id} not found"
            )

        # Check permission for the search space
        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_DELETE.value,
            "You don't have permission to delete documents in this search space",
        )

        source_key = _document_source_key(document.title)
        related_documents = [document]
        if source_key:
            related_result = await session.execute(
                select(Document).filter(
                    Document.search_space_id == document.search_space_id,
                    Document.document_type == document.document_type,
                    Document.id != document.id,
                    (
                        (Document.title == source_key)
                        | Document.title.like(f"{source_key}__%")
                    ),
                )
            )
            related_documents.extend(related_result.scalars().all())

        # De-duplicate IDs in case the selected document is already in related query results
        deduped_related_docs: list[Document] = []
        seen_ids: set[int] = set()
        for related_doc in related_documents:
            if related_doc.id in seen_ids:
                continue
            seen_ids.add(related_doc.id)
            deduped_related_docs.append(related_doc)

        blocking_docs = []
        already_deleting_ids: list[int] = []
        for related_doc in deduped_related_docs:
            state = (
                related_doc.status.get("state")
                if isinstance(related_doc.status, dict)
                else None
            )
            if state in ("pending", "processing"):
                blocking_docs.append(related_doc.title)
            elif state == "deleting":
                already_deleting_ids.append(related_doc.id)

        if blocking_docs:
            blocked_preview = ", ".join(blocking_docs[:3])
            if len(blocking_docs) > 3:
                blocked_preview = f"{blocked_preview}, ..."
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot delete document variants while one or more are pending/processing: "
                    f"{blocked_preview}. Please wait for processing to complete."
                ),
            )

        previous_statuses: dict[int, Any] = {
            related_doc.id: (
                dict(related_doc.status)
                if isinstance(related_doc.status, dict)
                else related_doc.status
            )
            for related_doc in deduped_related_docs
        }

        to_queue_ids: list[int] = []
        for related_doc in deduped_related_docs:
            if related_doc.id in already_deleting_ids:
                continue
            related_doc.status = {"state": "deleting"}
            to_queue_ids.append(related_doc.id)

        # Mark the document as "deleting" so it's excluded from searches,
        # then commit immediately so the user gets a fast response.
        await session.commit()

        # Dispatch durable background deletion via Celery.
        # If queue dispatch fails, revert status to avoid a stuck "deleting" document.
        try:
            from app.tasks.celery_tasks.document_tasks import delete_document_task

            for related_doc_id in to_queue_ids:
                delete_document_task.delay(related_doc_id)
        except Exception as dispatch_error:
            for related_doc in deduped_related_docs:
                related_doc.status = previous_statuses.get(related_doc.id)
            await session.commit()
            raise HTTPException(
                status_code=503,
                detail="Failed to queue background deletion. Please try again.",
            ) from dispatch_error

        return {
            "message": "Document deleted successfully",
            "queued_deletions": len(to_queue_ids),
            "already_deleting": len(already_deleting_ids),
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to delete document: {e!s}"
        ) from e


@router.get(
    "/documents/{document_id}/benchmark-data",
    response_model=BenchmarkDataListResponse,
)
async def list_document_benchmark_data(
    document_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    List benchmark datasets associated with a document.
    Requires DOCUMENTS_READ permission for the document's search space.
    """
    try:
        result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {document_id} not found",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        benchmark_result = await session.execute(
            select(BenchmarkData)
            .filter(BenchmarkData.doc_id == document_id)
            .order_by(BenchmarkData.created_date.desc(), BenchmarkData.benchmarkdata_id.desc())
        )
        rows = benchmark_result.scalars().all()

        return BenchmarkDataListResponse(
            items=[
                BenchmarkDataRead(
                    benchmarkdata_id=row.benchmarkdata_id,
                    doc_id=row.doc_id,
                    task_type=row.task_type,
                    task_num=row.task_num,
                    created_date=row.created_date,
                    dataset_filename=row.dataset_filename,
                    dataset_mime_type=row.dataset_mime_type,
                    dataset_size_bytes=row.dataset_size_bytes,
                )
                for row in rows
            ],
            total=len(rows),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list benchmark datasets: {e!s}",
        ) from e


@router.post(
    "/documents/{document_id}/benchmark-data",
    response_model=BenchmarkDataRead,
)
async def upload_document_benchmark_data(
    document_id: int,
    benchmark_file: UploadFile,
    task_type: str = Form(...),
    task_num: int = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Upload and associate a benchmark dataset with a document.
    Requires DOCUMENTS_UPDATE permission for the document's search space.
    """
    try:
        result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {document_id} not found",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_UPDATE.value,
            "You don't have permission to update documents in this search space",
        )

        cleaned_task_type = task_type.strip()
        if not cleaned_task_type:
            raise HTTPException(status_code=400, detail="task_type is required")
        if len(cleaned_task_type) > 128:
            raise HTTPException(
                status_code=400,
                detail="task_type must be 128 characters or fewer",
            )
        if task_num < 1:
            raise HTTPException(status_code=400, detail="task_num must be >= 1")

        file_content = await benchmark_file.read()
        if not file_content:
            raise HTTPException(status_code=400, detail="benchmark_file is empty")
        if len(file_content) > MAX_BENCHMARK_DATASET_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "benchmark_file exceeds maximum size of "
                    f"{MAX_BENCHMARK_DATASET_SIZE_BYTES // (1024 * 1024)} MB"
                ),
            )

        try:
            dataset_content = file_content.decode("utf-8")
        except UnicodeDecodeError as decode_error:
            raise HTTPException(
                status_code=400,
                detail="benchmark_file must be UTF-8 text (JSON/CSV/TSV/Markdown)",
            ) from decode_error

        existing_rows_result = await session.execute(
            select(BenchmarkData).where(BenchmarkData.doc_id == document_id)
        )
        existing_rows = existing_rows_result.scalars().all()
        for existing_row in existing_rows:
            await session.delete(existing_row)
        await session.flush()

        row = BenchmarkData(
            doc_id=document_id,
            task_type=cleaned_task_type,
            task_num=task_num,
            created_date=datetime.now(UTC),
            dataset_filename=benchmark_file.filename or f"benchmark-{document_id}.txt",
            dataset_content=dataset_content,
            dataset_mime_type=benchmark_file.content_type,
            dataset_size_bytes=len(file_content),
        )
        session.add(row)
        await session.flush()

        count_result = await session.execute(
            select(func.count())
            .select_from(BenchmarkData)
            .where(BenchmarkData.doc_id == document_id)
        )
        benchmark_count = int(count_result.scalar() or 0)
        document.document_metadata = _build_document_metadata_with_benchmark_count(
            document,
            benchmark_count,
        )

        await session.commit()
        await session.refresh(row)

        return BenchmarkDataRead(
            benchmarkdata_id=row.benchmarkdata_id,
            doc_id=row.doc_id,
            task_type=row.task_type,
            task_num=row.task_num,
            created_date=row.created_date,
            dataset_filename=row.dataset_filename,
            dataset_mime_type=row.dataset_mime_type,
            dataset_size_bytes=row.dataset_size_bytes,
        )
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload benchmark dataset: {e!s}",
        ) from e


@router.get("/documents/{document_id}/benchmark-data/{benchmarkdata_id}/download")
async def download_document_benchmark_data(
    document_id: int,
    benchmarkdata_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Download benchmark dataset content for a document-associated benchmark record.
    Requires DOCUMENTS_READ permission for the document's search space.
    """
    try:
        doc_result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = doc_result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {document_id} not found",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_READ.value,
            "You don't have permission to read documents in this search space",
        )

        benchmark_result = await session.execute(
            select(BenchmarkData).filter(
                BenchmarkData.benchmarkdata_id == benchmarkdata_id,
                BenchmarkData.doc_id == document_id,
            )
        )
        benchmark_row = benchmark_result.scalars().first()
        if not benchmark_row:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Benchmark dataset not found for this document"
                ),
            )

        media_type = benchmark_row.dataset_mime_type or "text/plain"
        output_filename = benchmark_row.dataset_filename or f"benchmark-{benchmarkdata_id}.txt"

        return StreamingResponse(
            io.BytesIO(benchmark_row.dataset_content.encode("utf-8")),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{output_filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to download benchmark dataset: {e!s}",
        ) from e


@router.delete("/documents/{document_id}/benchmark-data/{benchmarkdata_id}")
async def delete_document_benchmark_data(
    document_id: int,
    benchmarkdata_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """
    Delete a benchmark dataset associated with a document.
    Requires DOCUMENTS_UPDATE permission for the document's search space.
    """
    try:
        doc_result = await session.execute(
            select(Document).filter(Document.id == document_id)
        )
        document = doc_result.scalars().first()

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Document with id {document_id} not found",
            )

        await check_permission(
            session,
            user,
            document.search_space_id,
            Permission.DOCUMENTS_UPDATE.value,
            "You don't have permission to update documents in this search space",
        )

        benchmark_result = await session.execute(
            select(BenchmarkData).filter(
                BenchmarkData.benchmarkdata_id == benchmarkdata_id,
                BenchmarkData.doc_id == document_id,
            )
        )
        benchmark_row = benchmark_result.scalars().first()
        if not benchmark_row:
            raise HTTPException(
                status_code=404,
                detail="Benchmark dataset not found for this document",
            )

        await session.delete(benchmark_row)
        await session.flush()

        count_result = await session.execute(
            select(func.count())
            .select_from(BenchmarkData)
            .where(BenchmarkData.doc_id == document_id)
        )
        benchmark_count = int(count_result.scalar() or 0)
        document.document_metadata = _build_document_metadata_with_benchmark_count(
            document,
            benchmark_count,
        )

        await session.commit()
        return {
            "message": "Benchmark dataset deleted",
            "benchmarkdata_id": benchmarkdata_id,
            "remaining": benchmark_count,
        }
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete benchmark dataset: {e!s}",
        ) from e


# ====================================================================
# Version History Endpoints
# ====================================================================


@router.get("/documents/{document_id}/versions")
async def list_document_versions(
    document_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """List all versions for a document, ordered by version_number descending."""
    document = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    await check_permission(
        session, user, document.search_space_id, Permission.DOCUMENTS_READ.value
    )

    versions = (
        (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document_id)
                .order_by(DocumentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )

    return [
        {
            "version_number": v.version_number,
            "title": v.title,
            "content_hash": v.content_hash,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.get("/documents/{document_id}/versions/{version_number}")
async def get_document_version(
    document_id: int,
    version_number: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Get full version content including source_markdown."""
    document = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    await check_permission(
        session, user, document.search_space_id, Permission.DOCUMENTS_READ.value
    )

    version = (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_number == version_number,
            )
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "version_number": version.version_number,
        "title": version.title,
        "content_hash": version.content_hash,
        "source_markdown": version.source_markdown,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@router.post("/documents/{document_id}/versions/{version_number}/restore")
async def restore_document_version(
    document_id: int,
    version_number: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Restore a previous version: snapshot current state, then overwrite document content."""
    document = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    await check_permission(
        session, user, document.search_space_id, Permission.DOCUMENTS_UPDATE.value
    )

    version = (
        await session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_number == version_number,
            )
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot current state before restoring
    from app.utils.document_versioning import create_version_snapshot

    await create_version_snapshot(session, document)

    # Restore the version's content onto the document
    document.source_markdown = version.source_markdown
    document.title = version.title or document.title
    document.content_needs_reindexing = True
    await session.commit()

    from app.tasks.celery_tasks.document_reindex_tasks import reindex_document_task

    reindex_document_task.delay(document_id, str(user.id))

    return {
        "message": f"Restored version {version_number}",
        "document_id": document_id,
        "restored_version": version_number,
    }


# ===== Upload-based local folder indexing endpoints =====
# These work for ALL deployment modes (cloud, self-hosted remote, self-hosted local).
# The desktop app reads files locally and uploads them here.


class FolderMtimeCheckFile(PydanticBaseModel):
    relative_path: str
    mtime: float


_MAX_MTIME_CHECK_FILES = 10_000


class FolderMtimeCheckRequest(PydanticBaseModel):
    folder_name: str
    search_space_id: int
    files: list[FolderMtimeCheckFile] = Field(max_length=_MAX_MTIME_CHECK_FILES)


class FolderUnlinkRequest(PydanticBaseModel):
    folder_name: str
    search_space_id: int
    root_folder_id: int | None = None
    relative_paths: list[str]


class FolderSyncFinalizeRequest(PydanticBaseModel):
    folder_name: str
    search_space_id: int
    root_folder_id: int | None = None
    all_relative_paths: list[str]


@router.post("/documents/folder-mtime-check")
async def folder_mtime_check(
    request: FolderMtimeCheckRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Pre-upload optimization: check which files need uploading based on mtime.

    Returns the subset of relative paths where the file is new or has a
    different mtime, so the client can skip reading/uploading unchanged files.
    """
    from app.indexing_pipeline.document_hashing import compute_identifier_hash

    await check_permission(
        session,
        user,
        request.search_space_id,
        Permission.DOCUMENTS_CREATE.value,
        "You don't have permission to create documents in this search space",
    )

    uid_hashes = {}
    for f in request.files:
        uid = f"{request.folder_name}:{f.relative_path}"
        uid_hash = compute_identifier_hash(
            DocumentType.LOCAL_FOLDER_FILE.value, uid, request.search_space_id
        )
        uid_hashes[uid_hash] = f

    existing_docs = (
        (
            await session.execute(
                select(Document).where(
                    Document.unique_identifier_hash.in_(list(uid_hashes.keys())),
                    Document.document_type == DocumentType.LOCAL_FOLDER_FILE,
                )
            )
        )
        .scalars()
        .all()
    )

    existing_by_hash = {doc.unique_identifier_hash: doc for doc in existing_docs}

    mtime_tolerance = 1.0
    files_to_upload: list[str] = []

    for uid_hash, file_info in uid_hashes.items():
        doc = existing_by_hash.get(uid_hash)
        if doc is None:
            files_to_upload.append(file_info.relative_path)
            continue

        stored_mtime = (doc.document_metadata or {}).get("mtime")
        if stored_mtime is None:
            files_to_upload.append(file_info.relative_path)
            continue

        if abs(file_info.mtime - stored_mtime) >= mtime_tolerance:
            files_to_upload.append(file_info.relative_path)

    return {"files_to_upload": files_to_upload}


@router.post("/documents/folder-upload")
async def folder_upload(
    files: list[UploadFile],
    folder_name: str = Form(...),
    search_space_id: int = Form(...),
    relative_paths: str = Form(...),
    root_folder_id: int | None = Form(None),
    enable_summary: bool = Form(False),
    use_vision_llm: bool = Form(False),
    processing_mode: str = Form("basic"),
    embedding_models: str = Form(None),
    chunking_strategy: str | None = Form(None),
    chunk_size: int | None = Form(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Upload files from the desktop app for folder indexing.

    Files are written to temp storage and dispatched to a Celery task.
    Works for all deployment modes (no is_self_hosted guard).
    """
    import json
    import os
    import tempfile

    from app.etl_pipeline.etl_document import ProcessingMode

    validated_mode = ProcessingMode.coerce(processing_mode)
    shared_tmp_dir = os.getenv("SHARED_TMP_DIR", "/shared_tmp")
    try:
        os.makedirs(shared_tmp_dir, exist_ok=True)
    except OSError:
        shared_tmp_dir = tempfile.gettempdir()
        os.makedirs(shared_tmp_dir, exist_ok=True)
        logging.getLogger(__name__).warning(
            "Falling back to temp dir '%s' for folder upload staging", shared_tmp_dir
        )
    
    # Parse embedding_models and create config
    from app.config.embedding_config import EmbeddingConfig
    
    embedding_config = None
    if embedding_models:
        try:
            model_list = json.loads(embedding_models)
            if not isinstance(model_list, list):
                raise ValueError("embedding_models must be a JSON array")
            embedding_config = EmbeddingConfig.from_model_list(model_list)
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid embedding_models format: {e}"
            )
    else:
        embedding_config = EmbeddingConfig.from_model_list(None)

    resolved_chunking_strategy = None
    if chunking_strategy:
        normalized_strategy = chunking_strategy.strip().lower()
        if normalized_strategy in {
            "sandwitch_chunk",
            "sandwich_chunk",
            "chunk_text",
            "chunk_hybrid",
            "chunk_recursive",
        }:
            resolved_chunking_strategy = normalized_strategy
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid chunking_strategy. Allowed values: "
                    "sandwitch_chunk, chunk_text, chunk_hybrid, chunk_recursive"
                ),
            )

    if chunk_size is not None and chunk_size <= 0:
        raise HTTPException(status_code=400, detail="chunk_size must be a positive integer")

    await check_permission(
        session,
        user,
        search_space_id,
        Permission.DOCUMENTS_CREATE.value,
        "You don't have permission to create documents in this search space",
    )

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        rel_paths: list[str] = json.loads(relative_paths)
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid relative_paths JSON: {e}"
        ) from e

    if len(rel_paths) != len(files):
        raise HTTPException(
            status_code=400,
            detail=f"Mismatch: {len(files)} files but {len(rel_paths)} relative_paths",
        )

    for file in files:
        file_size = file.size or 0
        if file_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{file.filename}' ({file_size / (1024 * 1024):.1f} MB) "
                f"exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB per-file limit.",
            )

    from app.services.folder_service import MAX_FOLDER_DEPTH

    max_subfolder_depth = max((p.count("/") for p in rel_paths if "/" in p), default=0)
    if 1 + max_subfolder_depth > MAX_FOLDER_DEPTH:
        raise HTTPException(
            status_code=400,
            detail=f"Folder structure too deep: {1 + max_subfolder_depth} levels "
            f"exceeds the maximum of {MAX_FOLDER_DEPTH}.",
        )

    if root_folder_id:
        root_folder = await session.get(Folder, root_folder_id)
        if not root_folder or root_folder.search_space_id != search_space_id:
            raise HTTPException(
                status_code=404, detail="Root folder not found in this search space"
            )

    if not root_folder_id:
        watched_metadata = {
            "watched": True,
            "folder_path": folder_name,
            "processing_mode": validated_mode.value,
        }
        existing_root = (
            await session.execute(
                select(Folder).where(
                    Folder.name == folder_name,
                    Folder.parent_id.is_(None),
                    Folder.search_space_id == search_space_id,
                )
            )
        ).scalar_one_or_none()

        if existing_root:
            root_folder_id = existing_root.id
            existing_root.folder_metadata = watched_metadata
        else:
            root_folder = Folder(
                name=folder_name,
                search_space_id=search_space_id,
                created_by_id=str(user.id),
                position="a0",
                folder_metadata=watched_metadata,
            )
            session.add(root_folder)
            await session.flush()
            root_folder_id = root_folder.id

        await session.commit()

    async def _read_and_save(file: UploadFile, idx: int) -> dict:
        content = await file.read()
        raw_name = file.filename or rel_paths[idx]
        filename = raw_name.split("/")[-1]

        def _write_temp() -> str:
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=os.path.splitext(filename)[1],
                dir=shared_tmp_dir,
            ) as tmp:
                tmp.write(content)
                return tmp.name

        temp_path = await asyncio.to_thread(_write_temp)
        return {
            "temp_path": temp_path,
            "relative_path": rel_paths[idx],
            "filename": filename,
        }

    file_mappings = await asyncio.gather(
        *(_read_and_save(f, i) for i, f in enumerate(files))
    )

    from app.tasks.celery_tasks.document_tasks import (
        index_uploaded_folder_files_task,
    )

    # Serialize config to dict for Celery
    config_dict = None
    if embedding_config:
        config_dict = {
            "mode": embedding_config.mode,
            "model_keys": embedding_config.get_model_keys()
        }

    index_uploaded_folder_files_task.delay(
        search_space_id=search_space_id,
        user_id=str(user.id),
        folder_name=folder_name,
        root_folder_id=root_folder_id,
        enable_summary=enable_summary,
        use_vision_llm=use_vision_llm,
        file_mappings=list(file_mappings),
        processing_mode=validated_mode.value,
        embedding_config=config_dict,
        chunking_strategy=resolved_chunking_strategy,
        chunk_size=chunk_size,
    )

    return {
        "message": f"Folder upload started for {len(files)} file(s)",
        "status": "processing",
        "root_folder_id": root_folder_id,
        "file_count": len(files),
    }


@router.post("/documents/folder-unlink")
async def folder_unlink(
    request: FolderUnlinkRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Handle file deletion events from the desktop watcher.

    For each relative path, find the matching document and delete it.
    """
    from app.indexing_pipeline.document_hashing import compute_identifier_hash
    from app.tasks.connector_indexers.local_folder_indexer import (
        _cleanup_empty_folder_chain,
    )

    await check_permission(
        session,
        user,
        request.search_space_id,
        Permission.DOCUMENTS_DELETE.value,
        "You don't have permission to delete documents in this search space",
    )

    deleted_count = 0

    for rel_path in request.relative_paths:
        unique_id = f"{request.folder_name}:{rel_path}"
        uid_hash = compute_identifier_hash(
            DocumentType.LOCAL_FOLDER_FILE.value,
            unique_id,
            request.search_space_id,
        )

        existing = (
            await session.execute(
                select(Document).where(Document.unique_identifier_hash == uid_hash)
            )
        ).scalar_one_or_none()

        if existing:
            deleted_folder_id = existing.folder_id
            await session.delete(existing)
            await session.flush()

            if deleted_folder_id and request.root_folder_id:
                await _cleanup_empty_folder_chain(
                    session, deleted_folder_id, request.root_folder_id
                )
            deleted_count += 1

    await session.commit()
    return {"deleted_count": deleted_count}


@router.post("/documents/folder-sync-finalize")
async def folder_sync_finalize(
    request: FolderSyncFinalizeRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Finalize a full folder scan by deleting orphaned documents.

    The client sends the complete list of relative paths currently in the
    folder. Any document in the DB for this folder that is NOT in the list
    gets deleted.
    """
    from app.indexing_pipeline.document_hashing import compute_identifier_hash
    from app.services.folder_service import get_folder_subtree_ids
    from app.tasks.connector_indexers.local_folder_indexer import (
        _cleanup_empty_folders,
    )

    await check_permission(
        session,
        user,
        request.search_space_id,
        Permission.DOCUMENTS_DELETE.value,
        "You don't have permission to delete documents in this search space",
    )

    if not request.root_folder_id:
        return {"deleted_count": 0}

    subtree_ids = await get_folder_subtree_ids(session, request.root_folder_id)

    seen_hashes: set[str] = set()
    for rel_path in request.all_relative_paths:
        unique_id = f"{request.folder_name}:{rel_path}"
        uid_hash = compute_identifier_hash(
            DocumentType.LOCAL_FOLDER_FILE.value,
            unique_id,
            request.search_space_id,
        )
        seen_hashes.add(uid_hash)

    all_folder_docs = (
        (
            await session.execute(
                select(Document).where(
                    Document.document_type == DocumentType.LOCAL_FOLDER_FILE,
                    Document.search_space_id == request.search_space_id,
                    Document.folder_id.in_(subtree_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    deleted_count = 0
    for doc in all_folder_docs:
        if doc.unique_identifier_hash not in seen_hashes:
            await session.delete(doc)
            deleted_count += 1

    await session.flush()

    existing_dirs: set[str] = set()
    for rel_path in request.all_relative_paths:
        parent = str(os.path.dirname(rel_path))
        if parent and parent != ".":
            existing_dirs.add(parent)

    folder_mapping: dict[str, int] = {"": request.root_folder_id}

    await _cleanup_empty_folders(
        session,
        request.root_folder_id,
        request.search_space_id,
        existing_dirs,
        folder_mapping,
        subtree_ids=subtree_ids,
    )

    await session.commit()
    return {"deleted_count": deleted_count}
