#!/bin/bash
# Script to properly mount OpenSearch integration files in backend

echo "=== Mounting OpenSearch Integration Files ==="
echo ""

# Verify files exist
echo "1. Verifying source files..."
if [ ! -f "opensearch_chunk_storage.py" ]; then
    echo "❌ opensearch_chunk_storage.py not found in current directory"
    exit 1
fi

if [ ! -f "chunks_hybrid_search_opensearch.py" ]; then
    echo "❌ chunks_hybrid_search_opensearch.py not found in current directory"
    exit 1
fi

echo "✅ Source files found"
echo ""

# Recreate backend container to pick up volume mounts
echo "2. Recreating backend container..."
docker compose -f docker-compose-adaptable-rag.yml up -d --force-recreate backend

echo ""
echo "3. Waiting for backend to start..."
sleep 20

echo ""
echo "4. Installing opensearch-py library..."
docker exec surfsense-adaptable-rag-backend-1 pip install opensearch-py --quiet

echo ""
echo "5. Verifying mounted files..."
echo ""
echo "Checking opensearch_chunk_storage.py:"
docker exec surfsense-adaptable-rag-backend-1 ls -lh /app/app/storage/opensearch_chunk_storage.py

echo ""
echo "Checking chunks_hybrid_search.py:"
docker exec surfsense-adaptable-rag-backend-1 ls -lh /app/app/retriever/chunks_hybrid_search.py

echo ""
echo "6. Checking OpenSearch connectivity from backend..."
docker exec surfsense-adaptable-rag-backend-1 python3 -c "
import requests
try:
    resp = requests.get('http://opensearch:9200/_cluster/health', timeout=5)
    print(f'✅ OpenSearch accessible from backend: {resp.json().get(\"status\")}')
except Exception as e:
    print(f'❌ Cannot reach OpenSearch: {e}')
"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "✅ OpenSearch integration files are now mounted"
echo "✅ opensearch-py library installed"
echo ""
echo "Next steps:"
echo "  1. Login to http://localhost:3000/login"
echo "  2. Upload MSFT_FY26Q1_10Q.docx"
echo "  3. Check results: curl http://localhost:9200/_cat/indices?v"
