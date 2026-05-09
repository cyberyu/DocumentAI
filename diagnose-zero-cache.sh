#!/bin/bash
# Zero Cache Diagnostic Script - Compare Broken Machine vs Working System
# Run this on your broken machine (the one showing skeleton loaders)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "ZERO CACHE DIAGNOSTIC REPORT"
echo "=========================================="
echo ""

# Detect container names
DB_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'postgres|db' | head -1)
FRONTEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'frontend|web' | head -1)
ZERO_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'zero-cache|zero' | head -1)
BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'backend' | head -1)

echo "Detected containers:"
echo "  DB: $DB_CONTAINER"
echo "  Frontend: $FRONTEND_CONTAINER"
echo "  Zero-cache: $ZERO_CONTAINER"
echo "  Backend: $BACKEND_CONTAINER"
echo ""

# Check if zero-cache exists
if [ -z "$ZERO_CONTAINER" ]; then
    echo -e "${RED}❌ CRITICAL: zero-cache container NOT FOUND${NC}"
    echo "   Zero Cache is required for real-time document updates!"
    echo "   Documents will show as skeleton loaders without it."
    echo ""
    echo "Expected working system has: rocicorp/zero:0.26.2"
    echo ""
    exit 1
else
    echo -e "${GREEN}✅ Zero-cache container found: $ZERO_CONTAINER${NC}"
fi
echo ""

# ============================================================
# CHECK 1: Replication Slot Active (MOST CRITICAL)
# ============================================================
echo "=========================================="
echo "CHECK 1: PostgreSQL Replication Slot"
echo "=========================================="
echo "Working system has:"
echo "  slot_name: zero_0_1777926735448"
echo "  active: t"
echo ""
echo "Your system:"

SLOT_CHECK=$(docker exec $DB_CONTAINER psql -U surfsense -d surfsense -t -c \
  "SELECT slot_name, plugin, active FROM pg_replication_slots;" 2>&1)

echo "$SLOT_CHECK"

if echo "$SLOT_CHECK" | grep -q " t$"; then
    echo -e "${GREEN}✅ PASS: Replication slot is ACTIVE${NC}"
elif echo "$SLOT_CHECK" | grep -q " f$"; then
    echo -e "${RED}❌ FAIL: Replication slot is INACTIVE${NC}"
    echo "   Zero-cache is not connected to PostgreSQL!"
    echo "   Fix: docker restart $ZERO_CONTAINER"
elif [ -z "$SLOT_CHECK" ]; then
    echo -e "${RED}❌ FAIL: No replication slot found${NC}"
    echo "   Zero-cache never created a replication slot!"
    echo "   Fix: Check zero-cache logs for errors"
else
    echo -e "${YELLOW}⚠️  WARNING: Could not determine slot status${NC}"
fi
echo ""

# ============================================================
# CHECK 2: WAL Level (SECOND MOST CRITICAL)
# ============================================================
echo "=========================================="
echo "CHECK 2: PostgreSQL WAL Level"
echo "=========================================="
echo "Working system has: logical"
echo "Your system:"

WAL_LEVEL=$(docker exec $DB_CONTAINER psql -U surfsense -d surfsense -t -c "SHOW wal_level;" 2>&1 | xargs)

echo "  $WAL_LEVEL"

if [ "$WAL_LEVEL" = "logical" ]; then
    echo -e "${GREEN}✅ PASS: WAL level is logical${NC}"
else
    echo -e "${RED}❌ FAIL: WAL level is '$WAL_LEVEL' (must be 'logical')${NC}"
    echo "   Logical replication is IMPOSSIBLE without this!"
    echo "   Fix:"
    echo "     1. Edit postgresql.conf: wal_level = logical"
    echo "     2. Restart PostgreSQL container"
    echo "     3. Restart zero-cache container"
fi
echo ""

# ============================================================
# CHECK 3: Publication Includes Documents Table
# ============================================================
echo "=========================================="
echo "CHECK 3: Zero Publication Tables"
echo "=========================================="
echo "Working system includes: documents table"
echo "Your system:"

PUBLICATION_TABLES=$(docker exec $DB_CONTAINER psql -U surfsense -d surfsense -t -c \
  "SELECT tablename FROM pg_publication_tables WHERE pubname='zero_publication' ORDER BY tablename;" 2>&1)

echo "$PUBLICATION_TABLES"

if echo "$PUBLICATION_TABLES" | grep -q "documents"; then
    echo -e "${GREEN}✅ PASS: 'documents' table is in publication${NC}"
else
    echo -e "${RED}❌ FAIL: 'documents' table NOT in publication${NC}"
    echo "   Zero-cache cannot see document updates!"
    echo "   Fix:"
    echo "     docker exec $DB_CONTAINER psql -U surfsense -d surfsense -c \\"
    echo "       \"ALTER PUBLICATION zero_publication ADD TABLE documents;\""
    echo "     docker restart $ZERO_CONTAINER"
fi
echo ""

# ============================================================
# CHECK 4: WAL Sender (Zero-Cache Streaming?)
# ============================================================
echo "=========================================="
echo "CHECK 4: WAL Sender Status"
echo "=========================================="
echo "Working system has: state=streaming, application_name=zero-replicator"
echo "Your system:"

WAL_SENDER=$(docker exec $DB_CONTAINER psql -U surfsense -d surfsense -t -c \
  "SELECT application_name, state, client_addr FROM pg_stat_replication;" 2>&1)

if [ -z "$WAL_SENDER" ]; then
    echo -e "${RED}❌ FAIL: No active WAL sender (zero-cache not streaming)${NC}"
    echo "   Fix: docker restart $ZERO_CONTAINER"
else
    echo "$WAL_SENDER"
    if echo "$WAL_SENDER" | grep -q "streaming"; then
        echo -e "${GREEN}✅ PASS: Zero-cache is streaming${NC}"
    else
        echo -e "${RED}❌ FAIL: Replication not streaming${NC}"
    fi
fi
echo ""

# ============================================================
# CHECK 5: Zero-Cache Environment Variables
# ============================================================
echo "=========================================="
echo "CHECK 5: Zero-Cache Configuration"
echo "=========================================="
echo "Critical variables from working system:"
echo "  ZERO_APP_PUBLICATIONS=zero_publication"
echo "  ZERO_UPSTREAM_DB=postgresql://surfsense:surfsense@db:5432/surfsense?sslmode=disable"
echo ""
echo "Your system:"

ZERO_PUBLICATIONS=$(docker inspect $ZERO_CONTAINER --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ZERO_APP_PUBLICATIONS || echo "NOT SET")
ZERO_UPSTREAM=$(docker inspect $ZERO_CONTAINER --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ZERO_UPSTREAM_DB || echo "NOT SET")

echo "  $ZERO_PUBLICATIONS"
echo "  $ZERO_UPSTREAM"

if echo "$ZERO_PUBLICATIONS" | grep -q "zero_publication"; then
    echo -e "${GREEN}✅ PASS: ZERO_APP_PUBLICATIONS is correct${NC}"
else
    echo -e "${RED}❌ FAIL: ZERO_APP_PUBLICATIONS misconfigured${NC}"
fi
echo ""

# ============================================================
# CHECK 6: Frontend Environment Variables
# ============================================================
echo "=========================================="
echo "CHECK 6: Frontend Configuration"
echo "=========================================="
echo "Working system has: NEXT_PUBLIC_ZERO_CACHE_URL=http://localhost:5929"
echo "Your system:"

ZERO_URL=$(docker inspect $FRONTEND_CONTAINER --format '{{range .Config.Env}}{{println .}}{{end}}' | grep NEXT_PUBLIC_ZERO_CACHE_URL || echo "NOT SET")

echo "  $ZERO_URL"

if echo "$ZERO_URL" | grep -q "NEXT_PUBLIC_ZERO_CACHE_URL="; then
    echo -e "${GREEN}✅ PASS: NEXT_PUBLIC_ZERO_CACHE_URL is set${NC}"
    
    # Extract port from URL
    PORT=$(echo "$ZERO_URL" | sed -n 's/.*:\([0-9]*\).*/\1/p')
    
    # Test if port is reachable
    echo ""
    echo "Testing connectivity to zero-cache on port $PORT..."
    if curl -s -m 2 http://localhost:$PORT/api/v0/metrics > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Zero-cache is reachable on port $PORT${NC}"
    else
        echo -e "${RED}❌ Cannot reach zero-cache on port $PORT${NC}"
        echo "   Browser cannot connect to zero-cache!"
        echo "   Check port mapping in docker-compose.yml"
    fi
else
    echo -e "${RED}❌ FAIL: NEXT_PUBLIC_ZERO_CACHE_URL not set${NC}"
    echo "   Frontend doesn't know where to find zero-cache!"
fi
echo ""

# ============================================================
# CHECK 7: Docker Port Mappings
# ============================================================
echo "=========================================="
echo "CHECK 7: Docker Port Mappings"
echo "=========================================="
echo "Working system mappings:"
echo "  frontend:   0.0.0.0:3929->3000/tcp"
echo "  backend:    0.0.0.0:8929->8000/tcp"
echo "  zero-cache: 0.0.0.0:5929->4848/tcp"
echo ""
echo "Your system:"

docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep -E "frontend|backend|zero"

echo ""

# ============================================================
# CHECK 8: Zero-Cache Logs (Recent Errors)
# ============================================================
echo "=========================================="
echo "CHECK 8: Zero-Cache Logs (Last 30 Lines)"
echo "=========================================="
echo "Looking for errors..."

ZERO_ERRORS=$(docker logs $ZERO_CONTAINER --tail 30 2>&1 | grep -E '"level":"(ERROR|WARN)"|error|ERR|failed|cannot' || echo "No errors found")

if [ "$ZERO_ERRORS" = "No errors found" ]; then
    echo -e "${GREEN}✅ PASS: No recent errors in zero-cache logs${NC}"
else
    echo -e "${YELLOW}⚠️  WARNING: Found potential issues:${NC}"
    echo "$ZERO_ERRORS"
fi
echo ""

# ============================================================
# CHECK 9: Document Status in Database
# ============================================================
echo "=========================================="
echo "CHECK 9: Documents in Database"
echo "=========================================="

DOCS=$(docker exec $DB_CONTAINER psql -U surfsense -d surfsense -t -c \
  "SELECT id, title, status->>'state' as state FROM documents ORDER BY created_at DESC LIMIT 3;" 2>&1)

if [ -z "$DOCS" ]; then
    echo -e "${YELLOW}⚠️  No documents found in database${NC}"
else
    echo "$DOCS"
    if echo "$DOCS" | grep -q "ready"; then
        echo -e "${GREEN}✅ Documents exist with status='ready'${NC}"
    else
        echo -e "${YELLOW}⚠️  Documents may not be in 'ready' state${NC}"
    fi
fi
echo ""

# ============================================================
# CHECK 10: Docker Images
# ============================================================
echo "=========================================="
echo "CHECK 10: Docker Images"
echo "=========================================="
echo "Working system uses:"
echo "  frontend: shiyu688/surfsense-web:hybrid-patch-99pct"
echo "  backend: shiyu688/surfsense-backend:hybrid-patch-99pct"
echo "  zero-cache: rocicorp/zero:0.26.2"
echo ""
echo "Your system:"

docker ps --format 'table {{.Names}}\t{{.Image}}' | grep -E "frontend|backend|zero"

echo ""

# ============================================================
# SUMMARY
# ============================================================
echo "=========================================="
echo "SUMMARY & RECOMMENDED ACTIONS"
echo "=========================================="
echo ""
echo "Based on the checks above, here are the most likely fixes:"
echo ""
echo "1. If replication slot is INACTIVE:"
echo "   → docker restart $ZERO_CONTAINER"
echo ""
echo "2. If WAL level is not 'logical':"
echo "   → Edit postgresql.conf and add: wal_level = logical"
echo "   → docker restart $DB_CONTAINER"
echo "   → docker restart $ZERO_CONTAINER"
echo ""
echo "3. If 'documents' table not in publication:"
echo "   → docker exec $DB_CONTAINER psql -U surfsense -d surfsense -c \\"
echo "     \"ALTER PUBLICATION zero_publication ADD TABLE documents;\""
echo "   → docker restart $ZERO_CONTAINER"
echo ""
echo "4. If NEXT_PUBLIC_ZERO_CACHE_URL is wrong or not set:"
echo "   → Update docker-compose.yml frontend environment"
echo "   → docker compose up -d --force-recreate frontend"
echo ""
echo "5. If zero-cache container not found:"
echo "   → Add zero-cache service to docker-compose.yml"
echo "   → Image: rocicorp/zero:0.26.2"
echo ""
echo "=========================================="
echo "DIAGNOSTIC COMPLETE"
echo "=========================================="
