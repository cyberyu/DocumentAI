"""
Multi-Embedding Upload API

FastAPI endpoints for document upload with embedding model selection.

Endpoints:
- GET /api/v1/embeddings/models - List available embedding models
- POST /api/v1/documents/fileupload-multi-embed - Upload with model selection
"""
from typing import List, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from pydantic import BaseModel

from opensearch_multi_embedding_storage import get_available_embedding_models
from multi_embedding_processor import MultiEmbeddingProcessor, MultiEmbeddingOpenSearchStorage

router = APIRouter(prefix="/api/v1", tags=["multi-embedding"])


class EmbeddingModelInfo(BaseModel):
    """Embedding model information for frontend."""
    key: str
    provider: str
    dimensions: int
    cost_per_1m_tokens: float
    max_seq_length: int
    description: str
    is_free: bool


class MultiEmbeddingUploadResponse(BaseModel):
    """Response from multi-embedding upload."""
    document_id: int
    status: str
    chunks_processed: int
    embedding_models_used: List[str]
    total_cost_usd: float
    message: str


@router.get("/embeddings/models", response_model=List[EmbeddingModelInfo])
async def get_embedding_models():
    """
    Get list of available embedding models.
    
    Returns model metadata for frontend display:
    - Provider (fastembed, openai, voyage, etc.)
    - Dimensions
    - Cost per 1M tokens
    - Max sequence length
    - Description
    - Whether it's free
    
    Example response:
    ```json
    [
        {
            "key": "fastembed/bge-base-en-v1.5",
            "provider": "fastembed",
            "dimensions": 768,
            "cost_per_1m_tokens": 0.0,
            "max_seq_length": 512,
            "description": "Balanced quality/speed",
            "is_free": true
        },
        {
            "key": "openai/text-embedding-3-large",
            "provider": "openai",
            "dimensions": 3072,
            "cost_per_1m_tokens": 0.13,
            "max_seq_length": 8192,
            "description": "Highest quality (3K dims!)",
            "is_free": false
        }
    ]
    ```
    """
    models = get_available_embedding_models()
    return models


@router.post("/documents/fileupload-multi-embed", response_model=MultiEmbeddingUploadResponse)
async def upload_file_with_multi_embedding(
    file: UploadFile = File(...),
    search_space_id: int = Form(...),
    embedding_models: str = Form(...),  # JSON string: ["openai/text-embedding-3-large", "voyage/voyage-finance-2"]
    should_summarize: bool = Form(False),
    use_vision_llm: bool = Form(False),
    processing_mode: str = Form("basic"),
):
    """
    Upload document and generate multiple embeddings.
    
    Args:
        file: Document file (PDF, DOCX, etc.)
        search_space_id: Search space ID
        embedding_models: JSON array of model keys
            Example: '["fastembed/bge-base-en-v1.5", "openai/text-embedding-3-large"]'
        should_summarize: Whether to generate summary
        use_vision_llm: Whether to use vision LLM
        processing_mode: Processing mode (basic, advanced)
    
    Returns:
        Processing summary with metrics
    
    Flow:
        1. ETL: Extract text from file (existing pipeline)
        2. Chunk: Create chunks (existing chunker)
        3. Embed: Generate embeddings for selected models (parallel)
        4. Store: Index in OpenSearch with all embeddings
    """
    import json
    
    try:
        # Parse embedding models selection
        try:
            selected_models = json.loads(embedding_models)
            if not selected_models or not isinstance(selected_models, list):
                raise ValueError("embedding_models must be non-empty array")
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid embedding_models format: {e}"
            )
        
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file uploaded")
        
        # Read file content
        file_content = await file.read()
        
        # TODO: Integrate with existing SurfSense upload pipeline
        # For now, return placeholder response
        
        # Step 1: ETL (use existing docling/MinerU service)
        # raw_document = await etl_service.extract(file_content, file.filename)
        
        # Step 2: Chunk (use existing document_chunker)
        # chunks = await chunker_service.chunk(raw_document)
        
        # Step 3: Create document record in PostgreSQL
        # document = await db.documents.create(
        #     title=file.filename,
        #     search_space_id=search_space_id,
        #     status={"state": "processing"}
        # )
        
        # Step 4: Multi-embedding + OpenSearch storage
        # storage = MultiEmbeddingOpenSearchStorage(hosts=["http://opensearch:9200"])
        # processor = MultiEmbeddingProcessor(storage)
        # summary = await processor.process_and_store_document(
        #     chunks=chunks,
        #     model_keys=selected_models,
        #     document_id=document.id,
        #     search_space_id=search_space_id,
        # )
        
        # Step 5: Update document status
        # await db.documents.update(document.id, status={"state": "ready"})
        
        # Placeholder response
        return MultiEmbeddingUploadResponse(
            document_id=999,  # TODO: Real document ID
            status="success",
            chunks_processed=50,  # TODO: Real count
            embedding_models_used=selected_models,
            total_cost_usd=0.0025,  # TODO: Real cost
            message=f"Document uploaded with {len(selected_models)} embedding models"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)}"
        )


# Integration helper for existing SurfSense backend
def integrate_multi_embedding_to_surfsense():
    """
    Integration guide for adding multi-embedding to existing SurfSense backend.
    
    Files to modify:
    1. app/main.py - Add router:
       ```python
       from multi_embedding_api import router as multi_embed_router
       app.include_router(multi_embed_router)
       ```
    
    2. app/indexing_pipeline/document_processor.py - Replace single embedding:
       ```python
       # OLD: Single embedding
       embedding_vector = await embedding_service.embed(chunk.text)
       
       # NEW: Multi-embedding
       if selected_embedding_models:
           processor = MultiEmbeddingProcessor(opensearch_storage)
           await processor.process_and_store_document(
               chunks=chunks,
               model_keys=selected_embedding_models,
               document_id=document.id,
               search_space_id=search_space_id,
           )
       else:
           # Fallback to single embedding
           embedding_vector = await embedding_service.embed(chunk.text)
       ```
    
    3. app/retriever/chunks_hybrid_search.py - Support multi-model search:
       ```python
       # Add model selection parameter
       async def search(query: str, model_key: str = None, ...):
           if model_key:
               # Use specific embedding model
               results = await storage.vector_search_multi_model(
                   query_embedding, search_space_id, model_key
               )
           else:
               # Use default model
               results = await storage.vector_search(...)
       ```
    
    Environment variables needed:
    - OPENAI_API_KEY (if using OpenAI models)
    - VOYAGE_API_KEY (if using Voyage models)
    - COHERE_API_KEY (if using Cohere models)
    - GOOGLE_API_KEY (if using Google models)
    - JINA_API_KEY (if using Jina models)
    """
    pass
