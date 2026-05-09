#!/bin/bash
# Multi-Embedding Feature Test Script

set -e

echo "======================================"
echo "Multi-Embedding Integration Test"
echo "======================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
BACKEND_URL="${BACKEND_URL:-http://localhost:8929}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3929}"
TEST_FILE="${TEST_FILE:-MSFT_FY26Q1_10Q.docx}"

echo "Configuration:"
echo "  Backend: $BACKEND_URL"
echo "  Frontend: $FRONTEND_URL"
echo "  Test File: $TEST_FILE"
echo ""

# Step 1: Check services
echo -e "${YELLOW}[1/6] Checking services...${NC}"
if curl -s -f "$BACKEND_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend is healthy${NC}"
else
    echo -e "${RED}✗ Backend is not responding${NC}"
    exit 1
fi

if curl -s -f "$FRONTEND_URL" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Frontend is accessible${NC}"
else
    echo -e "${RED}✗ Frontend is not responding${NC}"
    exit 1
fi
echo ""

# Step 2: Login and get token
echo -e "${YELLOW}[2/6] Authenticating...${NC}"
LOGIN_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}')

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$TOKEN" ]; then
    echo -e "${RED}✗ Failed to get authentication token${NC}"
    echo "Response: $LOGIN_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Authenticated successfully${NC}"
echo ""

# Step 3: Check if new endpoint exists (embedding models list)
echo -e "${YELLOW}[3/6] Checking embedding models endpoint...${NC}"
MODELS_RESPONSE=$(curl -s "$BACKEND_URL/api/v1/embeddings/models" \
  -H "Authorization: Bearer $TOKEN")

if echo "$MODELS_RESPONSE" | jq -e 'type == "array"' > /dev/null 2>&1; then
    MODEL_COUNT=$(echo "$MODELS_RESPONSE" | jq 'length')
    echo -e "${GREEN}✓ Embedding models endpoint working ($MODEL_COUNT models available)${NC}"
    echo "$MODELS_RESPONSE" | jq -r '.[] | "  - \(.id) (\(.dimensions)d, $\(.cost_per_million)/1M)"' | head -5
else
    echo -e "${YELLOW}⚠ Embedding models endpoint not found (backend integration needed)${NC}"
fi
echo ""

# Step 4: Test frontend UI
echo -e "${YELLOW}[4/6] Testing frontend upload page...${NC}"
FRONTEND_HTML=$(curl -s "$FRONTEND_URL")

if echo "$FRONTEND_HTML" | grep -q "EmbeddingModelSelector\|embedding.*model\|multi.*embed"; then
    echo -e "${GREEN}✓ Frontend includes embedding selector code${NC}"
else
    echo -e "${YELLOW}⚠ Embedding selector not found in frontend HTML${NC}"
fi
echo ""

# Step 5: Test upload with multiple embeddings
echo -e "${YELLOW}[5/6] Testing multi-embedding upload...${NC}"

if [ ! -f "$TEST_FILE" ]; then
    echo -e "${YELLOW}⚠ Test file not found: $TEST_FILE${NC}"
    echo "  Creating dummy test file..."
    echo "This is a test document for multi-embedding upload." > test_upload.txt
    TEST_FILE="test_upload.txt"
fi

# Upload with multiple embedding models
UPLOAD_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/v1/documents/fileupload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@$TEST_FILE" \
  -F "search_space_id=1" \
  -F "should_summarize=false" \
  -F "use_vision_llm=false" \
  -F "processing_mode=basic" \
  -F 'embedding_models=["fastembed/bge-base-en-v1.5","openai/text-embedding-3-large"]')

DOC_ID=$(echo "$UPLOAD_RESPONSE" | jq -r '.document_ids[0] // empty')

if [ -n "$DOC_ID" ]; then
    echo -e "${GREEN}✓ Document uploaded successfully (ID: $DOC_ID)${NC}"
    echo "  Response: $UPLOAD_RESPONSE" | jq '.'
else
    echo -e "${RED}✗ Upload failed${NC}"
    echo "  Response: $UPLOAD_RESPONSE"
fi
echo ""

# Step 6: Verify processing
echo -e "${YELLOW}[6/6] Checking document processing...${NC}"
if [ -n "$DOC_ID" ]; then
    sleep 5  # Wait for processing
    
    DOC_STATUS=$(curl -s "$BACKEND_URL/api/v1/documents/$DOC_ID" \
      -H "Authorization: Bearer $TOKEN")
    
    STATUS=$(echo "$DOC_STATUS" | jq -r '.status.state // "unknown"')
    echo "  Document status: $STATUS"
    
    if [ "$STATUS" = "ready" ]; then
        echo -e "${GREEN}✓ Document processed successfully${NC}"
    elif [ "$STATUS" = "processing" ] || [ "$STATUS" = "pending" ]; then
        echo -e "${YELLOW}⚠ Document still processing (check later)${NC}"
    else
        echo -e "${RED}✗ Document processing failed${NC}"
    fi
fi
echo ""

# Summary
echo "======================================"
echo "Test Summary"
echo "======================================"
echo ""
echo "Frontend UI Integration:"
echo "  1. Navigate to: $FRONTEND_URL"
echo "  2. Go to document upload page"
echo "  3. Look for 'Embedding Models' accordion"
echo "  4. Select multiple models (e.g., FastEmbed + OpenAI)"
echo "  5. Upload a document"
echo ""
echo "Expected Result:"
echo "  - UI shows embedding model selector"
echo "  - Can select 1+ models"
echo "  - Upload includes embedding_models parameter"
echo "  - Backend processes with all selected models"
echo "  - Each chunk gets multiple embeddings"
echo ""
echo "OpenSearch Verification:"
echo "  curl http://localhost:9200/surfsense_chunks_1/_mapping | jq"
echo "  # Should show multiple knn_vector fields:"
echo "  #   - embedding_fastembed_bge_base_en_v1_5"
echo "  #   - embedding_openai_text_embedding_3_large"
echo ""
echo "======================================"
echo -e "${GREEN}Integration test complete!${NC}"
echo "======================================"
