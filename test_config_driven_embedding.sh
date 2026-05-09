#!/bin/bash
# Test Config-Driven Multi-Embedding Implementation

set -e

echo "======================================="
echo "Config-Driven Multi-Embedding Test"
echo "======================================="
echo ""

# Configuration
BACKEND="http://localhost:8929"
TEST_FILE="MSFT_FY26Q1_10Q.docx"

echo "Configuration:"
echo "  Backend: $BACKEND"
echo "  Test File: $TEST_FILE"
echo ""

# Check test file exists
if [ ! -f "$TEST_FILE" ]; then
    echo "❌ Test file not found: $TEST_FILE"
    exit 1
fi

echo "[1/5] Checking backend health..."
if curl -sf $BACKEND/health > /dev/null 2>&1; then
    echo "✓ Backend is healthy"
else
    echo "✗ Backend not responding at $BACKEND"
    exit 1
fi
echo ""

echo "[2/5] Getting authentication token..."
echo "Note: You need to provide a valid JWT token for testing"
echo "Get token from browser: Application → Cookies → jwt"
echo ""
read -p "Enter JWT token: " TOKEN

if [ -z "$TOKEN" ]; then
    echo "✗ No token provided, skipping API tests"
    echo "ℹ You can still verify the config changes manually"
    exit 0
fi
echo ""

echo "[3/5] Testing default (no embedding_models parameter)..."
RESPONSE=$(curl -s -X POST "$BACKEND/api/v1/documents/fileupload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$TEST_FILE" \
  -F "search_space_id=1")

if echo "$RESPONSE" | jq -e '.document_ids' > /dev/null 2>&1; then
    DOC_ID=$(echo "$RESPONSE" | jq -r '.document_ids[0]')
    echo "✓ Default upload successful (doc_id: $DOC_ID)"
    echo "  Config mode: single (default)"
else
    echo "✗ Default upload failed"
    echo "$RESPONSE" | jq '.'
fi
echo ""

echo "[4/5] Testing single model selection..."
RESPONSE=$(curl -s -X POST "$BACKEND/api/v1/documents/fileupload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$TEST_FILE" \
  -F "search_space_id=1" \
  -F 'embedding_models=["openai/text-embedding-3-large"]')

if echo "$RESPONSE" | jq -e '.document_ids' > /dev/null 2>&1; then
    DOC_ID=$(echo "$RESPONSE" | jq -r '.document_ids[0]')
    echo "✓ Single model upload successful (doc_id: $DOC_ID)"
    echo "  Config mode: single"
    echo "  Model: openai/text-embedding-3-large"
else
    echo "✗ Single model upload failed"
    echo "$RESPONSE" | jq '.'
fi
echo ""

echo "[5/5] Testing multi-model selection..."
RESPONSE=$(curl -s -X POST "$BACKEND/api/v1/documents/fileupload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$TEST_FILE" \
  -F "search_space_id=1" \
  -F 'embedding_models=["fastembed/bge-small-en-v1.5", "openai/text-embedding-3-large"]')

if echo "$RESPONSE" | jq -e '.document_ids' > /dev/null 2>&1; then
    DOC_ID=$(echo "$RESPONSE" | jq -r '.document_ids[0]')
    echo "✓ Multi-model upload successful (doc_id: $DOC_ID)"
    echo "  Config mode: multi"
    echo "  Models:"
    echo "    - fastembed/bge-small-en-v1.5"
    echo "    - openai/text-embedding-3-large"
else
    echo "✗ Multi-model upload failed"
    echo "$RESPONSE" | jq '.'
fi
echo ""

echo "======================================="
echo "Test Complete"
echo "======================================="
echo ""
echo "Next steps:"
echo "1. Check backend logs:"
echo "   sudo docker compose logs surfsense-backend | grep -i 'multi-embed\\|config\\|error'"
echo ""
echo "2. Verify OpenSearch storage:"
echo "   curl -s http://localhost:9200/surfsense_chunks/_mapping | jq '.surfsense_chunks.mappings.properties' | grep embedding_"
echo ""
echo "3. Test via UI:"
echo "   Navigate to http://localhost:3929"
echo "   Upload document with multiple embedding models selected"
