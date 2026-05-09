#!/bin/bash
# Quick test script for multi-embedding upload
# Usage: ./test_upload.sh your_password

if [ -z "$1" ]; then
    echo "Usage: ./test_upload.sh <password>"
    exit 1
fi

# Clean up old test documents
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "DELETE FROM documents WHERE id >= 9"

# Run test with password from argument
TEST_PASSWORD="$1" python3 test_multi_embedding_api.py

# Wait for processing
sleep 20

# Check debug logs
echo ""
echo "=== Backend logs (embedding_models received) ==="
sudo docker logs surfsense-adaptable-rag-backend-1 2>&1 | grep -E "\[DEBUG\] embedding_models" | tail -5

echo ""
echo "=== Celery logs (embedding_config at indexing) ==="
sudo docker logs surfsense-adaptable-rag-celery_worker-1 2>&1 | grep -E "\[indexing\] Received" | tail -5
