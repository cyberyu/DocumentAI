#!/bin/bash
# Quick fix: Set agent_llm_id for all search spaces via database

echo "=== Removing LLM Requirement for Document Upload ==="
echo ""
echo "Setting agent_llm_id=-1 for all search spaces..."
echo ""

docker exec surfsense-adaptable-rag-db-1 psql -U surfsense -d surfsense <<EOF
-- Update existing search spaces to have default LLM ID
UPDATE searchspaces 
SET agent_llm_id = -1 
WHERE agent_llm_id IS NULL;

-- Show updated search spaces
SELECT id, name, agent_llm_id, embedder_llm_id 
FROM searchspaces;
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ All search spaces now have agent_llm_id set"
    echo "✅ You can now upload documents!"
    echo ""
    echo "Next steps:"
    echo "  1. Refresh the browser at http://localhost:3929"
    echo "  2. Upload MSFT_FY26Q1_10Q.docx"
    echo ""
else
    echo ""
    echo "❌ Failed to update database"
    echo "   Try running with: sudo ./remove_llm_requirement.sh"
fi
