#!/usr/bin/env python3
"""
Multi-Embedding Feature Demo

Tests the complete multi-embedding pipeline:
1. Create index with multiple embedding models
2. Generate embeddings in parallel
3. Store in OpenSearch
4. Search using different models
5. Compare results
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from adapter_dataflow_models import Chunk
from opensearch_multi_embedding_storage import (
    MultiEmbeddingOpenSearchStorage,
    get_available_embedding_models,
)
from multi_embedding_processor import MultiEmbeddingProcessor


async def demo_multi_embedding():
    """Demonstrate multi-embedding feature."""
    
    print("=" * 60)
    print("MULTI-EMBEDDING FEATURE DEMO")
    print("=" * 60)
    
    # Step 1: Show available models
    print("\n📊 AVAILABLE EMBEDDING MODELS\n")
    models = get_available_embedding_models()
    
    print(f"{'Model':<40} {'Dims':<8} {'Cost/1M':<12} {'Provider'}")
    print("-" * 80)
    for model in models:
        cost_str = "FREE" if model["is_free"] else f"${model['cost_per_1m_tokens']:.4f}"
        print(f"{model['key']:<40} {model['dimensions']:<8} {cost_str:<12} {model['provider']}")
    
    # Step 2: User selection (simulated)
    print("\n🎯 USER SELECTS MODELS\n")
    selected_models = [
        "fastembed/bge-base-en-v1.5",      # FREE local model
        "openai/text-embedding-3-large",   # Best quality (if API key available)
    ]
    print("Selected models:")
    for m in selected_models:
        print(f"  ✓ {m}")
    
    # Step 3: Initialize storage
    print("\n🔧 INITIALIZING OPENSEARCH STORAGE\n")
    storage = MultiEmbeddingOpenSearchStorage(
        hosts=["http://localhost:9200"],
        index_prefix="demo"
    )
    
    search_space_id = 999  # Demo search space
    
    # Step 4: Create index
    print(f"\n📝 CREATING INDEX: demo_chunks_{search_space_id}\n")
    try:
        await storage.create_index_multi_embedding(
            search_space_id=search_space_id,
            embedding_models=selected_models,
        )
        print("✅ Index created successfully")
    except Exception as e:
        print(f"⚠️  Index may already exist: {e}")
    
    # Step 5: Create demo chunks
    print("\n📄 CREATING DEMO DOCUMENT CHUNKS\n")
    chunks = [
        Chunk(
            chunk_id="demo_001",
            document_id=999,
            text="Microsoft reported Q1 FY26 revenue of $65.6 billion, representing 16% year-over-year growth driven by strong cloud adoption.",
            token_count=25,
            chunk_index=0,
            metadata={"section": "Financial Results"}
        ),
        Chunk(
            chunk_id="demo_002",
            document_id=999,
            text="Intelligent Cloud revenue reached $28.5 billion with Azure growing 29%, reflecting continued enterprise digital transformation.",
            token_count=20,
            chunk_index=1,
            metadata={"section": "Cloud Performance"}
        ),
        Chunk(
            chunk_id="demo_003",
            document_id=999,
            text="Office Commercial products and cloud services revenue increased 15%, with Microsoft 365 Commercial cloud revenue growing 16%.",
            token_count=22,
            chunk_index=2,
            metadata={"section": "Productivity"}
        ),
    ]
    
    print(f"Created {len(chunks)} demo chunks:")
    for chunk in chunks:
        print(f"  • {chunk.chunk_id}: {chunk.text[:60]}...")
    
    # Step 6: Generate embeddings in parallel
    print("\n⚡ GENERATING EMBEDDINGS (PARALLEL)\n")
    processor = MultiEmbeddingProcessor(storage)
    
    try:
        summary = await processor.process_and_store_document(
            chunks=chunks,
            model_keys=selected_models,
            document_id=999,
            search_space_id=search_space_id,
        )
        
        print("✅ Processing complete:")
        print(f"  • Chunks processed: {summary['chunks_processed']}")
        print(f"  • Models used: {len(summary['embedding_models_used'])}")
        print(f"  • Chunks indexed: {summary['chunks_indexed']}")
        print(f"  • Total cost: ${summary.get('total_cost_usd', 0):.4f}")
        
    except Exception as e:
        print(f"❌ Processing failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 7: Search with different models
    print("\n🔍 SEARCHING WITH DIFFERENT MODELS\n")
    
    query_text = "What was Azure revenue?"
    
    for model_key in selected_models:
        print(f"\n--- Searching with {model_key} ---")
        
        try:
            # Generate query embedding
            adapter = processor._get_adapter(model_key)
            if not adapter:
                print(f"⚠️  Adapter not available for {model_key}")
                continue
            
            query_embedding = adapter.embed_query(query_text)
            
            # Search
            results = await storage.vector_search_multi_model(
                query_embedding=query_embedding,
                search_space_id=search_space_id,
                model_key=model_key,
                top_k=3,
            )
            
            print(f"  Found {len(results)} results:")
            for i, result in enumerate(results, 1):
                print(f"    {i}. Score: {result['vector_score']:.4f}")
                print(f"       {result['content'][:70]}...")
                print()
        
        except Exception as e:
            print(f"  ❌ Search failed: {e}")
    
    # Step 8: Hybrid search with all models
    print("\n🔥 HYBRID SEARCH (BM25 + ALL VECTOR MODELS + RRF)\n")
    
    try:
        # Generate query embeddings for all models
        query_embeddings = {}
        for model_key in selected_models:
            adapter = processor._get_adapter(model_key)
            if adapter:
                query_embeddings[model_key] = adapter.embed_query(query_text)
        
        # Hybrid search
        results = await storage.hybrid_search_multi_model(
            query_text=query_text,
            query_embeddings=query_embeddings,
            search_space_id=search_space_id,
            top_k=3,
            rrf_k=60,
        )
        
        print(f"Found {len(results)} fused results:")
        for i, result in enumerate(results, 1):
            print(f"\n  {i}. RRF Score: {result['rrf_score']:.4f}")
            print(f"     BM25: {result.get('bm25_score', 0):.4f}")
            print(f"     Models contributed: {len(result.get('models_contributed', []))}")
            print(f"     {result['content'][:70]}...")
    
    except Exception as e:
        print(f"❌ Hybrid search failed: {e}")
    
    # Step 9: Cleanup (optional)
    print("\n\n🗑️  CLEANUP\n")
    try:
        index_name = f"demo_chunks_{search_space_id}"
        await storage.client.indices.delete(index=index_name)
        print(f"✅ Deleted index: {index_name}")
    except Exception as e:
        print(f"⚠️  Cleanup failed (index may not exist): {e}")
    
    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)
    print("\nKey Takeaways:")
    print("  ✓ Multiple embeddings generated in parallel")
    print("  ✓ All embeddings stored in single OpenSearch index")
    print("  ✓ Can search using any model independently")
    print("  ✓ Can combine all models with hybrid RRF fusion")
    print("  ✓ Enables A/B testing and model comparison")
    print()


async def demo_model_listing():
    """Demo: List available models with metadata."""
    
    print("\n" + "=" * 60)
    print("EMBEDDING MODELS CATALOG")
    print("=" * 60 + "\n")
    
    models = get_available_embedding_models()
    
    # Group by provider
    by_provider = {}
    for model in models:
        provider = model["provider"]
        if provider not in by_provider:
            by_provider[provider] = []
        by_provider[provider].append(model)
    
    for provider, provider_models in sorted(by_provider.items()):
        print(f"\n{'='*60}")
        print(f"  {provider.upper()}")
        print(f"{'='*60}\n")
        
        for model in provider_models:
            print(f"  {model['key']}")
            print(f"    Dimensions: {model['dimensions']}")
            print(f"    Max Tokens: {model['max_seq_length']}")
            if model['is_free']:
                print(f"    Cost: FREE (local)")
            else:
                print(f"    Cost: ${model['cost_per_1m_tokens']}/1M tokens")
            print(f"    Description: {model['description']}")
            print()


def demo_api_request():
    """Demo: Show how frontend would call the API."""
    
    print("\n" + "=" * 60)
    print("API REQUEST EXAMPLE")
    print("=" * 60 + "\n")
    
    print("Frontend JavaScript:")
    print("""
const formData = new FormData();
formData.append('file', selectedFile);
formData.append('search_space_id', '1');
formData.append('embedding_models', JSON.stringify([
  'fastembed/bge-base-en-v1.5',
  'openai/text-embedding-3-large',
  'voyage/voyage-finance-2'
]));

const response = await fetch('/api/v1/documents/fileupload-multi-embed', {
  method: 'POST',
  body: formData,
  headers: {
    'Authorization': `Bearer ${jwt_token}`
  }
});

const result = await response.json();
console.log(result);
// {
//   document_id: 42,
//   status: "success",
//   chunks_processed: 50,
//   embedding_models_used: ["fastembed/...", "openai/...", "voyage/..."],
//   total_cost_usd: 0.0082,
//   message: "Document uploaded with 3 embedding models"
// }
""")
    
    print("\nCURL equivalent:")
    print("""
curl -X POST http://localhost:8929/api/v1/documents/fileupload-multi-embed \\
  -H "Authorization: Bearer $JWT_TOKEN" \\
  -F "file=@document.pdf" \\
  -F "search_space_id=1" \\
  -F 'embedding_models=["fastembed/bge-base-en-v1.5","openai/text-embedding-3-large"]'
""")


async def main():
    """Run all demos."""
    
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Embedding Feature Demo")
    parser.add_argument(
        "--mode",
        choices=["full", "models", "api"],
        default="full",
        help="Demo mode: full pipeline, model listing, or API example"
    )
    args = parser.parse_args()
    
    if args.mode == "models":
        await demo_model_listing()
    elif args.mode == "api":
        demo_api_request()
    else:
        await demo_model_listing()
        demo_api_request()
        await demo_multi_embedding()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
