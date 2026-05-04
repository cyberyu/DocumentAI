#!/bin/bash
# Script to find and extract LLM requirement validation code

echo "=== Finding LLM Requirement Code ==="

# Copy relevant backend files to examine
mkdir -p /tmp/backend_code

echo "1. Copying backend models and routes..."
docker cp surfsense-adaptable-rag-backend-1:/app/app/models /tmp/backend_code/ 2>/dev/null || echo "  ⚠️  Could not copy models"
docker cp surfsense-adaptable-rag-backend-1:/app/app/routes /tmp/backend_code/ 2>/dev/null || echo "  ⚠️  Could not copy routes"

echo "2. Searching for LLM validation..."
grep -r "agent_llm" /tmp/backend_code/ 2>/dev/null | head -20

echo "3. Searching for document upload validation..."
grep -r -i "upload.*document\|document.*upload" /tmp/backend_code/ 2>/dev/null | head -10

echo "4. Searching for 'setup' or 'configure' requirements..."
grep -r -i "setup.*llm\|configure.*llm\|require.*llm" /tmp/backend_code/ 2>/dev/null | head -10

echo ""
echo "Files copied to: /tmp/backend_code/"
echo "Manual inspection: ls -la /tmp/backend_code/"
