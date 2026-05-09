#!/bin/bash
# Setup Docker without sudo requirement

echo "Adding current user to docker group..."
sudo usermod -aG docker $USER

echo ""
echo "✅ User added to docker group!"
echo ""
echo "⚠️  IMPORTANT: You must LOG OUT and LOG BACK IN for this to take effect"
echo ""
echo "After logging back in, test with:"
echo "  docker ps"
echo "  docker compose ps"
echo ""
echo "These should work WITHOUT sudo!"
