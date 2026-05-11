#!/bin/bash
# Restart frontend container to load multi-embedding UI

echo "Stopping frontend container..."
sudo docker compose stop frontend

echo "Removing old container..."
sudo docker compose rm -f frontend

echo "Starting frontend with custom image..."
sudo docker compose up -d frontend

echo ""
echo "Waiting for frontend to be ready..."
sleep 5

echo ""
echo "Checking frontend status..."
sudo docker ps | grep frontend

echo ""
echo "✅ Frontend restarted!"
echo ""
echo "Open http://localhost:3000 to see the Embedding Model Selector"
echo "It should appear after 'Processing Mode' and before the 'Upload' button"
