#!/bin/bash
# Fix the login page refresh loop by disabling Zero Cache

echo "=== Fixing login page refresh loop ==="
echo "Stopping Zero Cache (causing schema incompatibility)..."

sudo docker compose -f docker-compose-adaptable-rag.yml stop zero-cache
sudo docker compose -f docker-compose-adaptable-rag.yml rm -f zero-cache

echo "Restarting frontend..."
sudo docker compose -f docker-compose-adaptable-rag.yml restart frontend

echo ""
echo "Waiting 10 seconds for frontend to start..."
sleep 10

echo ""
echo "=== Status Check ==="
sudo docker compose -f docker-compose-adaptable-rag.yml ps frontend backend

echo ""
echo "✅ Done! Zero Cache has been disabled."
echo "📍 Try accessing http://localhost:3929/login now"
echo ""
echo "ℹ️  The page should stop refreshing. Zero Cache was causing the loop"
echo "   due to missing 'user' table in the replication schema."
echo ""
