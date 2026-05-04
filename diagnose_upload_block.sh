#!/bin/bash
echo "=== Diagnosing Upload Block ==="
echo ""

echo "1. Checking database search spaces..."
docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "SELECT id, name, agent_llm_id, embedder_llm_id FROM searchspaces;"

echo ""
echo "2. Checking if agent_llm_id is NULL..."
docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense -c "SELECT COUNT(*) as null_llm_count FROM searchspaces WHERE agent_llm_id IS NULL;"

echo ""
echo "3. Copying frontend code to analyze..."
mkdir -p /tmp/frontend_code
docker cp surfsense-adaptable-rag-frontend-1:/app/.next/server /tmp/frontend_code/ 2>/dev/null || echo "Could not copy .next/server"
docker cp surfsense-adaptable-rag-frontend-1:/app/app /tmp/frontend_code/ 2>/dev/null || echo "Could not copy app folder"
docker cp surfsense-adaptable-rag-frontend-1:/app/components /tmp/frontend_code/ 2>/dev/null || echo "Could not copy components"

echo ""
echo "4. Searching for LLM validation in frontend..."
if [ -d /tmp/frontend_code ]; then
    grep -r "agent_llm\|llm.*require\|validation\|upload.*block" /tmp/frontend_code/ 2>/dev/null | grep -v "node_modules" | head -20
fi

echo ""
echo "5. Checking backend logs for upload rejections..."
docker logs surfsense-adaptable-rag-backend-1 2>&1 | tail -100 | grep -i "upload\|validation\|llm" | tail -10

echo ""
echo "Done. Frontend code copied to: /tmp/frontend_code/"
