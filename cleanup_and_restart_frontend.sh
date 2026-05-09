#!/bin/bash
# Clean up misleading/unused Docker images and restart frontend properly

echo "🧹 Cleaning up Docker images..."
echo ""

cd /mnt/ssd1/projects/DocumentAI

echo "Current frontend-related images:"
docker images | grep -E "frontend|surfsense-web|REPOSITORY"
echo ""

echo "Removing old/unused images..."
# Remove the old documentai-frontend image if it exists
docker rmi documentai-frontend:latest 2>/dev/null || echo "  (documentai-frontend:latest not found)"

# Remove the github registry image since we're using custom build
docker rmi ghcr.io/modsetter/surfsense-web:latest 2>/dev/null || echo "  (ghcr.io/modsetter/surfsense-web:latest not found)"

echo ""
echo "Remaining images:"
docker images | grep -E "frontend|surfsense-web|REPOSITORY"
echo ""

echo "🔄 Now restarting frontend with correct image..."
docker compose -f docker-compose-adaptable-rag.yml stop frontend
docker compose -f docker-compose-adaptable-rag.yml rm -f frontend
docker compose -f docker-compose-adaptable-rag.yml up -d frontend

echo ""
echo "⏳ Waiting for frontend..."
sleep 5

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Verify correct image is running:"
docker ps --format "table {{.Names}}\t{{.Image}}" | grep frontend
echo ""
echo "Expected: custom-surfsense-web:multi-embed"
echo ""
echo "🌐 Open http://localhost:3929"
