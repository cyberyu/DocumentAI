#!/bin/bash
# Restart frontend with multi-embedding UI using the adaptable-rag compose file

echo "🔄 Restarting frontend with multi-embedding UI..."
echo ""

cd /mnt/ssd1/projects/DocumentAI

# Use the adaptable-rag compose file
docker compose -f docker-compose-adaptable-rag.yml stop frontend
docker compose -f docker-compose-adaptable-rag.yml rm -f frontend
docker compose -f docker-compose-adaptable-rag.yml up -d frontend

echo ""
echo "⏳ Waiting for frontend to start..."
sleep 5

echo ""
echo "✅ Frontend restarted with custom-surfsense-web:multi-embed"
echo ""
echo "🌐 Open http://localhost:3000"
echo "📍 Go to Upload tab"
echo "✨ Look for 'Embedding Models' section after 'Processing Mode'"
