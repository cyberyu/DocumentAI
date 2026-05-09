#!/bin/bash
# Tag old/misleading frontend images as outdated

echo "🔍 Checking Docker images..."
echo ""

cd /mnt/ssd1/projects/DocumentAI

echo "All frontend-related images:"
docker images | grep -E "frontend|surfsense-web|REPOSITORY"
echo ""

echo "📝 Tagging old images as outdated..."
echo ""

# Tag documentai-frontend:latest as outdated if it exists
if docker images | grep -q "documentai-frontend.*latest"; then
    echo "→ Tagging documentai-frontend:latest as outdated_documentai-frontend:latest"
    docker tag documentai-frontend:latest outdated_documentai-frontend:latest
    docker rmi documentai-frontend:latest
fi

# Tag GitHub registry image as outdated if it exists
if docker images | grep -q "ghcr.io/modsetter/surfsense-web"; then
    echo "→ Tagging ghcr.io/modsetter/surfsense-web:latest as outdated_surfsense-web:github"
    docker tag ghcr.io/modsetter/surfsense-web:latest outdated_surfsense-web:github
    docker rmi ghcr.io/modsetter/surfsense-web:latest
fi

echo ""
echo "📊 Updated images:"
docker images | grep -E "frontend|surfsense-web|outdated|REPOSITORY"
echo ""

echo "✅ Correct image to use: custom-surfsense-web:multi-embed"
echo "❌ Outdated images: outdated_*"
echo ""

read -p "Do you want to restart frontend with correct image now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🔄 Restarting frontend..."
    docker compose -f docker-compose-adaptable-rag.yml stop frontend
    docker compose -f docker-compose-adaptable-rag.yml rm -f frontend
    docker compose -f docker-compose-adaptable-rag.yml up -d frontend
    
    echo ""
    echo "⏳ Waiting for frontend..."
    sleep 5
    
    echo ""
    echo "✅ Frontend restarted!"
    echo ""
    echo "Verify:"
    docker ps --format "table {{.Names}}\t{{.Image}}" | grep frontend
fi

echo ""
echo "🌐 Open http://localhost:3929"
