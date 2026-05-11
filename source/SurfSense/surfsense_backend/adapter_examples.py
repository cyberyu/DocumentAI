"""
Example Concrete Adapter Implementations

This file demonstrates how to implement adapters for different software stacks:
- Python SDKs (MinerU, FastEmbed, FlashRank)
- REST APIs (OpenAI, Voyage, Cohere)
- Docker services (OpenSearch, PostgreSQL)

These are reference implementations showing adapter pattern in action.
"""

import logging
import time
import importlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests

from adapter_base_classes import (
    ETLAdapter,
    ChunkingAdapter,
    EmbeddingAdapter,
    StorageAdapter,
    RetrievalAdapter,
    RerankingAdapter,
    ETLAdapterError,
    EmbeddingAdapterError,
    StorageAdapterError,
)
from adapter_dataflow_models import (
    RawDocument,
    Chunk,
    EmbeddedChunk,
    Query,
    SearchResult,
    RerankedResult,
    create_chunk_from_text,
)

logger = logging.getLogger(__name__)


# ============================================================================
# ETL ADAPTERS - Different software stacks for document extraction
# ============================================================================

class MinerUAdapter(ETLAdapter):
    """
    MinerU ETL Adapter - Python SDK (local)
    
    Software Stack: Python library with GPU acceleration
    Best for: PDFs with complex tables, formulas (financial, scientific)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Lazy import - only load when using MinerU
        import_errors: list[str] = []
        self.extractor = None
        for module_name in ("mineru", "magic_pdf"):
            try:
                module = importlib.import_module(module_name)
                magic_pdf_cls = getattr(module, "MagicPDF", None)
                if magic_pdf_cls is not None:
                    self.extractor = magic_pdf_cls
                    break
                import_errors.append(
                    f"module '{module_name}' imported but MagicPDF symbol not found"
                )
            except Exception as exc:
                import_errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

        if self.extractor is None:
            details = "; ".join(import_errors)
            raise ETLAdapterError(
                "MinerU not installed. Install from https://github.com/opendatalab/mineru "
                "(recommended: uv pip install -U \"mineru[all]\"). "
                f"Import details: {details}"
            )
    
    def extract_from_file(self, file_path: Path, **kwargs) -> RawDocument:
        """Extract content using MinerU Python SDK"""
        try:
            # Call MinerU extraction
            extractor = self.extractor(str(file_path))
            result = extractor.extract()
            
            # Convert MinerU output to RawDocument
            return RawDocument(
                source_path=str(file_path),
                content=result.content_markdown,  # Markdown output
                metadata={
                    "pages": result.page_count,
                    "title": result.title,
                    "format": "pdf",
                },
                tables=[
                    {"data": table.to_dict(), "page": table.page_num}
                    for table in result.tables
                ],
                formulas=[formula.latex for formula in result.formulas],
                etl_provider="mineru",
                extraction_metadata={
                    "ocr_applied": result.ocr_used,
                    "table_extraction_quality": result.table_confidence,
                }
            )
        except Exception as e:
            raise ETLAdapterError(f"MinerU extraction failed: {e}")
    
    def extract_from_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        **kwargs
    ) -> RawDocument:
        """Extract from bytes (for uploaded files)"""
        # Write to temp file, then extract
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            return self.extract_from_file(Path(tmp.name))
    
    def supported_formats(self) -> List[str]:
        return [".pdf"]
    
    def estimate_cost(self, file_path: Path) -> float:
        return 0.0  # Local processing, no API cost


class DoclingAdapter(ETLAdapter):
    """
    Docling ETL Adapter - Python SDK (local, async)
    
    Software Stack: IBM Research library, fast multi-format extraction
    Best for: Office documents (DOCX, PPTX, XLSX), quick processing
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            from docling import DocumentConverter
            self.converter = DocumentConverter()
        except ImportError:
            raise ETLAdapterError("Docling not installed. Run: pip install docling")
    
    def extract_from_file(self, file_path: Path, **kwargs) -> RawDocument:
        """Extract using Docling SDK"""
        try:
            result = self.converter.convert(str(file_path))
            
            return RawDocument(
                source_path=str(file_path),
                content=result.markdown,
                metadata={
                    "format": file_path.suffix[1:],  # Remove leading dot
                    "title": result.metadata.get("title"),
                    "author": result.metadata.get("author"),
                },
                tables=[t.to_dict() for t in result.tables],
                images=[{"url": img.url, "caption": img.caption} for img in result.images],
                etl_provider="docling",
            )
        except Exception as e:
            raise ETLAdapterError(f"Docling extraction failed: {e}")
    
    def extract_from_bytes(self, file_bytes: bytes, filename: str, **kwargs) -> RawDocument:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as tmp:
            tmp.write(file_bytes)
            tmp.flush()
            return self.extract_from_file(Path(tmp.name))
    
    def supported_formats(self) -> List[str]:
        return [".pdf", ".docx", ".pptx", ".xlsx", ".html"]
    
    def estimate_cost(self, file_path: Path) -> float:
        return 0.0


class UnstructuredAdapter(ETLAdapter):
    """
    Unstructured.io ETL Adapter - REST API (cloud)
    
    Software Stack: REST API with authentication
    Best for: Broad format support (HTML, EML, XML, etc.), cloud processing
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.endpoint = config.get("endpoint", "https://api.unstructured.io/general/v0/general")
    
    def extract_from_file(self, file_path: Path, **kwargs) -> RawDocument:
        """Extract using Unstructured REST API"""
        with open(file_path, "rb") as f:
            return self.extract_from_bytes(f.read(), file_path.name)
    
    def extract_from_bytes(self, file_bytes: bytes, filename: str, **kwargs) -> RawDocument:
        """Extract from bytes via REST API"""
        try:
            # Prepare multipart form data
            files = {"files": (filename, file_bytes)}
            headers = {"unstructured-api-key": self.api_key} if self.api_key else {}
            data = {"strategy": "auto"}  # auto, fast, hi_res
            
            # Call REST API
            response = requests.post(
                self.endpoint,
                files=files,
                headers=headers,
                data=data,
                timeout=60
            )
            response.raise_for_status()
            
            # Parse JSON response
            elements = response.json()
            
            # Combine text elements
            content = "\n\n".join([
                elem.get("text", "") for elem in elements
                if elem.get("type") in ["Title", "NarrativeText", "ListItem"]
            ])
            
            return RawDocument(
                source_path=filename,
                content=content,
                metadata={
                    "format": Path(filename).suffix[1:],
                    "element_count": len(elements),
                },
                tables=[
                    elem for elem in elements if elem.get("type") == "Table"
                ],
                etl_provider="unstructured",
                extraction_metadata={
                    "api_version": response.headers.get("x-api-version"),
                }
            )
        except requests.exceptions.RequestException as e:
            raise ETLAdapterError(f"Unstructured API failed: {e}")
    
    def supported_formats(self) -> List[str]:
        return [".html", ".eml", ".xml", ".pdf", ".docx", ".txt", ".md"]
    
    def estimate_cost(self, file_path: Path) -> float:
        # Unstructured pricing: $10 per 1000 pages
        # Estimate 1 page for non-PDFs
        return 0.01


# ============================================================================
# CHUNKING ADAPTERS - Pure Python (no external services)
# ============================================================================

class HybridSandwichChunker(ChunkingAdapter):
    """
    Hybrid Sandwich Chunking - Adds context before/after each chunk
    
    Software Stack: Pure Python (regex + string ops)
    """
    
    def chunk_document(self, document: RawDocument) -> List[Chunk]:
        """Split document with context sandwich"""
        text = document.content
        chunk_size = self.chunk_size
        overlap = self.overlap
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            
            # Extract prefix context (e.g., previous heading)
            prefix_start = max(0, start - 100)
            prefix = text[prefix_start:start].strip()
            
            # Extract suffix context (e.g., next paragraph start)
            suffix_end = min(len(text), end + 100)
            suffix = text[end:suffix_end].strip()
            
            chunks.append(Chunk(
                doc_id=document.doc_id,
                text=chunk_text,
                token_count=len(chunk_text.split()),
                char_start=start,
                char_end=end,
                chunk_index=chunk_index,
                prefix_context=prefix,
                suffix_context=suffix,
                metadata=document.metadata.copy(),
                chunking_strategy="hybrid_sandwich",
                chunking_params={"chunk_size": chunk_size, "overlap": overlap},
            ))
            
            start += chunk_size - overlap
            chunk_index += 1
        
        return chunks


# ============================================================================
# EMBEDDING ADAPTERS - Mix of REST APIs and Python SDKs
# ============================================================================

class OpenAIEmbeddingAdapter(EmbeddingAdapter):
    """
    OpenAI Embedding Adapter - REST API
    
    Software Stack: HTTPS REST API with Bearer token
    Models: text-embedding-3-small (1536), text-embedding-3-large (3072)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        if not self.api_key:
            raise EmbeddingAdapterError("OpenAI API key required")
        
        self.endpoint = "https://api.openai.com/v1/embeddings"
        self.model_name = config.get("model", "text-embedding-3-large")
        self.dimensions = 3072 if "3-large" in self.model_name else 1536
    
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """Embed chunks using OpenAI API with batching"""
        embedded_chunks = []
        batch_size = self.batch_size
        
        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [chunk.get_full_context() for chunk in batch]
            
            # Call API with retry logic
            start_time = time.time()
            embeddings = self._call_api(texts)
            latency_ms = (time.time() - start_time) * 1000
            
            # Compute cost (OpenAI pricing: $0.13 per 1M tokens for 3-large)
            total_tokens = sum(len(text.split()) for text in texts)
            cost_usd = (total_tokens / 1_000_000) * 0.13
            
            # Create EmbeddedChunk objects
            for chunk, embedding_vector in zip(batch, embeddings):
                embedded_chunks.append(EmbeddedChunk(
                    chunk=chunk,
                    embeddings={self.model_name: embedding_vector},
                    embedding_provider="openai",
                    embedding_models=[self.model_name],
                    embedding_dimensions={self.model_name: self.dimensions},
                    embedding_cost_usd=cost_usd / len(batch),
                    embedding_latency_ms=latency_ms / len(batch),
                ))
        
        return embedded_chunks
    
    def embed_query(self, query_text: str) -> List[float]:
        """Embed single query"""
        embeddings = self._call_api([query_text])
        return embeddings[0]
    
    def _call_api(self, texts: List[str]) -> List[List[float]]:
        """Call OpenAI API with retry logic"""
        payload = {
            "model": self.model_name,
            "input": texts,
            "dimensions": self.dimensions
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(5):
            try:
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()
                return [item["embedding"] for item in data["data"]]
            
            except requests.exceptions.RequestException as e:
                if attempt < 4 and ("rate_limit" in str(e).lower() or response.status_code == 429):
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Rate limit hit, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise EmbeddingAdapterError(f"OpenAI API failed: {e}")
    
    def get_dimensions(self) -> int:
        return self.dimensions
    
    def estimate_cost(self, num_tokens: int) -> float:
        return (num_tokens / 1_000_000) * 0.13  # $0.13 per 1M tokens


class FastEmbedAdapter(EmbeddingAdapter):
    """
    FastEmbed Adapter - Python SDK (local, GPU)
    
    Software Stack: Python library with ONNX runtime
    Models: 12+ models from 384 to 1024 dimensions
    Cost: FREE (local inference)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            from fastembed import TextEmbedding
            self.model = TextEmbedding(
                model_name=config.get("model", "BAAI/bge-base-en-v1.5")
            )
        except ImportError:
            raise EmbeddingAdapterError("FastEmbed not installed. Run: pip install fastembed")
        
        self.dimensions = 768  # Depends on model
    
    def embed_chunks(self, chunks: List[Chunk]) -> List[EmbeddedChunk]:
        """Embed locally with FastEmbed"""
        texts = [chunk.get_full_context() for chunk in chunks]
        
        start_time = time.time()
        embeddings = list(self.model.embed(texts))
        latency_ms = (time.time() - start_time) * 1000
        
        return [
            EmbeddedChunk(
                chunk=chunk,
                embeddings={self.model.model_name: embedding.tolist()},
                embedding_provider="fastembed",
                embedding_models=[self.model.model_name],
                embedding_dimensions={self.model.model_name: self.dimensions},
                embedding_cost_usd=0.0,  # FREE!
                embedding_latency_ms=latency_ms / len(chunks),
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
    
    def embed_query(self, query_text: str) -> List[float]:
        embeddings = list(self.model.embed([query_text]))
        return embeddings[0].tolist()
    
    def get_dimensions(self) -> int:
        return self.dimensions
    
    def estimate_cost(self, num_tokens: int) -> float:
        return 0.0  # Always free


# ============================================================================
# STORAGE ADAPTERS - Docker services with client libraries
# ============================================================================

class OpenSearchAdapter(StorageAdapter):
    """
    OpenSearch Storage Adapter - Docker service
    
    Software Stack: HTTP client (opensearch-py) to Docker container
    Features: k-NN vector search + BM25 full-text search
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            from opensearchpy import OpenSearch
            self.client = OpenSearch(
                hosts=config.get("hosts", ["http://localhost:9200"]),
                timeout=30,
                max_retries=3,
            )
        except ImportError:
            raise StorageAdapterError("opensearch-py not installed. Run: pip install opensearch-py")
    
    def create_index(self, embedding_dimensions: int, **kwargs):
        """Create index with k-NN + BM25"""
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "number_of_shards": 2,
                }
            },
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "keyword"},
                    "text": {"type": "text"},  # BM25 search
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": embedding_dimensions,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                            "parameters": {"ef_construction": 256, "m": 16}
                        }
                    },
                    "metadata": {"type": "object"},
                }
            }
        }
        
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        self.client.indices.create(index=self.index_name, body=index_body)
    
    def index_chunks(self, chunks: List[EmbeddedChunk], batch_size: int = 100):
        """Bulk index chunks"""
        from opensearchpy import helpers
        
        actions = []
        for embedded in chunks:
            chunk = embedded.chunk
            embedding_vector = embedded.get_embedding()
            
            actions.append({
                "_index": self.index_name,
                "_id": chunk.chunk_id,
                "_source": {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "embedding": embedding_vector,
                    "metadata": chunk.metadata,
                }
            })
            
            if len(actions) >= batch_size:
                helpers.bulk(self.client, actions)
                actions = []
        
        if actions:
            helpers.bulk(self.client, actions)
    
    def delete_by_doc_id(self, doc_id: str):
        """Delete all chunks from a document"""
        self.client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"doc_id": doc_id}}}
        )
    
    def clear_index(self):
        """Delete all data"""
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)


# Register all adapters with factory
def register_example_adapters():
    """Register all example adapters with AdapterFactory"""
    from adapter_base_classes import AdapterFactory
    
    # ETL adapters
    AdapterFactory.register_etl("mineru", MinerUAdapter)
    AdapterFactory.register_etl("docling", DoclingAdapter)
    AdapterFactory.register_etl("unstructured", UnstructuredAdapter)
    
    # Chunking adapters
    AdapterFactory.register_chunking("hybrid_sandwich", HybridSandwichChunker)
    
    # Embedding adapters
    AdapterFactory.register_embedding("openai", OpenAIEmbeddingAdapter)
    AdapterFactory.register_embedding("fastembed", FastEmbedAdapter)
    
    # Storage adapters
    AdapterFactory.register_storage("opensearch", OpenSearchAdapter)
    
    logger.info("Registered example adapters with AdapterFactory")
