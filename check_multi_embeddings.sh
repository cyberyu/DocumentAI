#!/bin/bash

echo "========================================"
echo "Multi-Embedding Verification Script"
echo "========================================"
echo ""

# Check documents in database
echo "[1/6] Checking documents in PostgreSQL..."
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "SELECT id, name, created_at FROM documents ORDER BY created_at DESC LIMIT 5;"
echo ""

# List all tables
echo "[2/6] Listing all tables..."
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "\dt"
echo ""

# Check chunks table for embedding fields
echo "[3/6] Checking chunks table structure..."
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "\d chunks" 2>/dev/null || echo "Chunks table not found"
echo ""

# Check recent chunks with their embeddings
echo "[4/6] Checking recent chunks..."
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "SELECT id, document_id, created_at, LENGTH(content) as content_length FROM chunks ORDER BY created_at DESC LIMIT 10;" 2>/dev/null || echo "No chunks found"
echo ""

# Count total chunks
echo "[5/6] Counting total chunks..."
sudo docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "SELECT COUNT(*) as total_chunks FROM chunks;" 2>/dev/null || echo "Cannot count chunks"
echo ""

# Check OpenSearch indices
echo "[6/6] Checking OpenSearch indices..."
curl -s "localhost:9200/_cat/indices?v" | grep -v "^$"
echo ""

# Search for any chunk-related indices in OpenSearch
echo "[7/6] Searching for chunk indices in OpenSearch..."
curl -s "localhost:9200/_cat/indices?v" | grep -i "chunk" || echo "No chunk indices found in OpenSearch"
echo ""

# Check backend logs for embedding processing
echo "[8/6] Checking backend logs for embedding activity (last 100 lines)..."
sudo docker logs surfsense-adaptable-rag-backend-1 --tail 100 2>&1 | grep -i "embedding\|multi\|chunk\|upload\|document" | tail -30 || echo "No relevant logs found"
echo ""

echo "========================================"
echo "Verification Complete!"
echo "========================================"
