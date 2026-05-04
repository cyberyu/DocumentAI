#!/bin/bash
# Setup monitoring for document upload debug session
# Usage: ./setup-upload-monitoring.sh

set -e

echo "==================================="
echo "Upload Monitoring Setup"
echo "==================================="
echo ""

# Create timestamp for this session
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SESSION_DIR="upload-debug-$TIMESTAMP"

mkdir -p "$SESSION_DIR"
cd "$SESSION_DIR"

echo "✓ Created session directory: $SESSION_DIR"
echo ""

# Check containers are running
echo "Checking containers..."
if ! docker ps | grep -q backend; then
    echo "❌ Backend container not running!"
    exit 1
fi
echo "✓ Backend running"

if ! docker ps | grep -q postgres; then
    echo "❌ PostgreSQL container not running!"
    exit 1
fi
echo "✓ PostgreSQL running"

if ! docker ps | grep -q documentai-frontend; then
    echo "❌ Frontend container not running!"
    exit 1
fi
echo "✓ Frontend running"
echo ""

# Get database connection details
echo "Detecting database credentials..."
DB_USER="user"
DB_NAME="dbname"

# Try to detect from docker-compose or environment
if [ -f "../docker-compose.yml" ] || [ -f "../docker-compose-adaptable-rag.yml" ]; then
    echo "✓ Found docker-compose file"
fi

echo ""
echo "==================================="
echo "Monitoring Commands Ready"
echo "==================================="
echo ""
echo "Open these in separate terminal windows/tabs:"
echo ""
echo "TERMINAL 1 - Backend Logs:"
echo "cd $(pwd) && docker logs backend -f | tee backend.log"
echo ""
echo "TERMINAL 2 - Frontend Logs:"
echo "cd $(pwd) && docker logs documentai-frontend-1 -f | tee frontend.log"
echo ""
echo "TERMINAL 3 - PostgreSQL Logs:"
echo "cd $(pwd) && docker logs postgres -f | tee postgres.log"
echo ""
echo "TERMINAL 4 - Database Status Watch:"
echo "watch -n 2 'docker exec postgres psql -U $DB_USER -d $DB_NAME -c \"SELECT id, file_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT 5;\" 2>/dev/null'"
echo ""
echo "==================================="
echo "Browser Setup"
echo "==================================="
echo ""
echo "1. Open: http://localhost:3929"
echo "2. Press F12 (DevTools)"
echo "3. Go to Network tab"
echo "4. Check ✓ Preserve log"
echo "5. Check ✓ Disable cache"
echo "6. Go to Console tab"
echo "7. Clear console"
echo ""
echo "==================================="
echo "Ready to Upload!"
echo "==================================="
echo ""
echo "When upload is complete, run:"
echo "  cd $(pwd)"
echo "  ../collect-upload-data.sh"
echo ""
echo "Session directory: $(pwd)"
echo ""

# Create helper script for post-upload data collection
cat > collect-data.sh << 'COLLECT'
#!/bin/bash
# Collect upload debug data after test

echo "==================================="
echo "Collecting Upload Debug Data"
echo "==================================="
echo ""

# Stop all log tails first
echo "Stop all 'docker logs -f' commands (Ctrl+C in each terminal)"
read -p "Press Enter when ready..."

# Get JWT token
echo ""
echo "Get JWT token from browser:"
echo "  DevTools → Application → Cookies → jwt"
echo ""
read -p "Paste JWT token: " JWT_TOKEN

if [ -z "$JWT_TOKEN" ]; then
    echo "⚠️  No token provided, skipping API tests"
else
    echo "✓ Token received"
    
    # Get documents via API
    echo ""
    echo "Fetching documents from API..."
    curl -s "http://localhost:8929/api/v1/documents" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json" | jq . > api-documents.json
    
    if [ -s api-documents.json ]; then
        echo "✓ Saved api-documents.json"
        DOC_COUNT=$(jq 'length' api-documents.json 2>/dev/null || echo "0")
        echo "  Documents in response: $DOC_COUNT"
    fi
    
    # Get search spaces
    echo ""
    echo "Fetching search spaces..."
    curl -s "http://localhost:8929/api/v1/search-spaces" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json" | jq . > api-search-spaces.json
    
    if [ -s api-search-spaces.json ]; then
        echo "✓ Saved api-search-spaces.json"
    fi
fi

# Database snapshots
echo ""
echo "Collecting database snapshots..."

docker exec postgres psql -U user -d dbname << 'SQL' > database-documents.txt 2>&1
SELECT id, file_name, status, user_id, search_space_id, created_at, updated_at
FROM documents
ORDER BY created_at DESC
LIMIT 10;
SQL
echo "✓ Saved database-documents.txt"

docker exec postgres psql -U user -d dbname << 'SQL' > database-chunks.txt 2>&1
SELECT 
    d.id as doc_id,
    d.file_name,
    COUNT(dc.id) as chunk_count
FROM documents d
LEFT JOIN document_chunks dc ON d.id = dc.document_id
GROUP BY d.id, d.file_name
ORDER BY d.created_at DESC
LIMIT 10;
SQL
echo "✓ Saved database-chunks.txt"

docker exec postgres psql -U user -d dbname << 'SQL' > database-associations.txt 2>&1
SELECT 
    ss.id as space_id,
    ss.name as space_name,
    d.id as doc_id,
    d.file_name,
    d.status
FROM search_spaces ss
LEFT JOIN search_space_documents ssd ON ss.id = ssd.search_space_id  
LEFT JOIN documents d ON ssd.document_id = d.id
ORDER BY ss.id, d.created_at DESC
LIMIT 20;
SQL
echo "✓ Saved database-associations.txt"

# Check for errors in logs
echo ""
echo "Extracting errors from logs..."

if [ -f backend.log ]; then
    grep -i "error\|exception\|failed\|traceback" backend.log > backend-errors.txt 2>/dev/null || touch backend-errors.txt
    ERROR_COUNT=$(wc -l < backend-errors.txt)
    echo "✓ Saved backend-errors.txt ($ERROR_COUNT errors found)"
fi

if [ -f postgres.log ]; then
    grep -i "error\|failed" postgres.log > postgres-errors.txt 2>/dev/null || touch postgres-errors.txt
    ERROR_COUNT=$(wc -l < postgres-errors.txt)
    echo "✓ Saved postgres-errors.txt ($ERROR_COUNT errors found)"
fi

# Create summary
echo ""
echo "Creating summary..."

cat > SUMMARY.txt << EOF
UPLOAD DEBUG SESSION SUMMARY
============================
Date: $(date)
Session Directory: $(pwd)

FILES COLLECTED:
- backend.log (backend container logs)
- frontend.log (frontend container logs)  
- postgres.log (PostgreSQL logs)
- api-documents.json (GET /api/v1/documents response)
- api-search-spaces.json (GET /api/v1/search-spaces response)
- database-documents.txt (documents table snapshot)
- database-chunks.txt (chunks count per document)
- database-associations.txt (search space associations)
- backend-errors.txt (extracted errors)
- postgres-errors.txt (extracted errors)

QUICK STATS:
EOF

if [ -f api-documents.json ]; then
    DOC_COUNT=$(jq 'length' api-documents.json 2>/dev/null || echo "error")
    echo "- Documents in API response: $DOC_COUNT" >> SUMMARY.txt
fi

if [ -f database-documents.txt ]; then
    DB_DOC_COUNT=$(grep -c "^\s*[0-9]" database-documents.txt 2>/dev/null || echo "0")
    echo "- Documents in database: $DB_DOC_COUNT" >> SUMMARY.txt
fi

if [ -f backend-errors.txt ]; then
    ERROR_COUNT=$(wc -l < backend-errors.txt)
    echo "- Backend errors found: $ERROR_COUNT" >> SUMMARY.txt
fi

echo "" >> SUMMARY.txt
echo "NEXT STEPS:" >> SUMMARY.txt
echo "1. Review SUMMARY.txt" >> SUMMARY.txt
echo "2. Check if documents appear in both DB and API response" >> SUMMARY.txt
echo "3. If mismatch, investigate backend-errors.txt" >> SUMMARY.txt
echo "4. Check browser DevTools for frontend issues" >> SUMMARY.txt
echo "5. Package everything: tar -czf upload-debug.tar.gz ." >> SUMMARY.txt

echo "✓ Saved SUMMARY.txt"

# Display summary
echo ""
echo "==================================="
cat SUMMARY.txt
echo "==================================="
echo ""
echo "All data collected in: $(pwd)"
echo ""
echo "To package for transfer:"
echo "  tar -czf upload-debug.tar.gz ."
echo ""
COLLECT

chmod +x collect-data.sh

echo "Helper script created: collect-data.sh"
echo ""
