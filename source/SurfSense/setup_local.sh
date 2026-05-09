#!/bin/bash
# =============================================================================
# SurfSense Local Development Setup
# Run this once on a brand new machine after cloning the repo.
#
# Prerequisites:
#   - Anaconda / Miniconda installed
#   - Docker + Docker Compose installed
#   - Node.js 20+ installed (for frontend)
# =============================================================================

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/surfsense_backend"
FRONTEND_DIR="$REPO_ROOT/surfsense_web"
COMPOSE_FILE="$REPO_ROOT/../../docker-compose-adaptable-rag.yml"
COMPOSE_DIR="$REPO_ROOT/../.."

echo "============================================="
echo "  SurfSense Local Setup"
echo "  Repo root: $REPO_ROOT"
echo "============================================="

# -----------------------------------------------------------------------------
# STEP 1: Start infrastructure Docker services
# -----------------------------------------------------------------------------
echo ""
echo "[1/5] Starting infrastructure Docker services (db, redis, opensearch)..."
cd "$COMPOSE_DIR"
docker compose -f docker-compose-adaptable-rag.yml up -d db redis opensearch

echo "      Waiting for PostgreSQL to be ready..."
until docker exec surfsense-adaptable-rag-db-1 pg_isready -U surfsense -d surfsense &>/dev/null; do
  sleep 2
done
echo "      PostgreSQL is ready."

# -----------------------------------------------------------------------------
# STEP 2: Create conda environment and install Python dependencies
# -----------------------------------------------------------------------------
echo ""
echo "[2/5] Setting up Python environment..."
if conda env list | grep -q "^documentai "; then
  echo "      Conda env 'documentai' already exists, skipping create."
else
  conda create -n documentai python=3.12 -y
  echo "      Conda env 'documentai' created."
fi

eval "$(conda shell.bash hook)"
conda activate documentai

echo "      Installing Python packages..."
pip install -r "$BACKEND_DIR/requirements.txt" -q
pip install magika -q   # required by chonkie CodeChunker

echo "      Python packages installed."

# -----------------------------------------------------------------------------
# STEP 3: Configure backend .env
# -----------------------------------------------------------------------------
echo ""
echo "[3/5] Configuring backend .env..."
if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env" 2>/dev/null || cat > "$BACKEND_DIR/.env" <<'EOF'
# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://surfsense:surfsense@localhost:5432/surfsense

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── OpenSearch ────────────────────────────────────────────────────────────────
OPENSEARCH_HOSTS=http://localhost:9200

# ── Auth ──────────────────────────────────────────────────────────────────────
SECRET_KEY=change-me-to-a-random-secret

# ── Uvicorn ───────────────────────────────────────────────────────────────────
UVICORN_PORT=8930

# ── ETL / RAG ─────────────────────────────────────────────────────────────────
ETL_SERVICE=DOCLING
RAG_ACTIVE_PROFILE=production
SERVICE_ROLE=api
EOF
  echo "      .env created. Edit $BACKEND_DIR/.env to add your API keys."
else
  echo "      .env already exists, skipping."
fi

# -----------------------------------------------------------------------------
# STEP 4: Install frontend dependencies
# -----------------------------------------------------------------------------
echo ""
echo "[4/5] Installing frontend Node.js dependencies..."
cd "$FRONTEND_DIR"
npm install --legacy-peer-deps
echo "      Frontend dependencies installed."

# -----------------------------------------------------------------------------
# STEP 5: Done — print start instructions
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo "  Setup complete!"
echo "============================================="
echo ""
echo "To START the app, open two terminals:"
echo ""
echo "  Terminal 1 — Backend:"
echo "    conda activate documentai"
echo "    cd $BACKEND_DIR"
echo "    bash run_local.sh"
echo "    → API:  http://localhost:8930"
echo "    → Docs: http://localhost:8930/docs"
echo ""
echo "  Terminal 2 — Frontend:"
echo "    cd $FRONTEND_DIR"
echo "    npm run dev"
echo "    → App:  http://localhost:3000"
echo ""
echo "Infrastructure (Docker) is already running:"
echo "    PostgreSQL  → localhost:5432"
echo "    Redis       → localhost:6379"
echo "    OpenSearch  → localhost:9200"
echo ""
echo "To stop infrastructure:"
echo "    cd $COMPOSE_DIR"
echo "    docker compose -f docker-compose-adaptable-rag.yml stop db redis opensearch"
echo ""
