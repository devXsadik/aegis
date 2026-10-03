#!/usr/bin/env bash
# ============================================================
# Aegis — one-command full system run
# Usage:
#   ./run.sh
#   ./run.sh data/demo/clips/sample.mp4
#   ./run.sh --no-pipeline          # backend + dashboard only
#   make run
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

NO_PIPELINE=0
VIDEO=""
for arg in "$@"; do
  case "$arg" in
    --no-pipeline) NO_PIPELINE=1 ;;
    --help|-h)
      echo "Usage: ./run.sh [video.mp4] [--no-pipeline]"
      echo "  Starts backend :8000, frontend :5173, and CV pipeline."
      exit 0
      ;;
    *) VIDEO="$arg" ;;
  esac
done

if [ -z "$VIDEO" ]; then
  VIDEO="data/demo/clips/sample.mp4"
fi

BACKEND_PID=""
PIPELINE_PID=""
FRONTEND_PID=""
PIDS=()

cleanup() {
  echo ""
  echo "Stopping Aegis…"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Kill anything still bound to our ports (orphans from prior runs)
  for port in 8000 5173; do
    if command -v lsof >/dev/null 2>&1; then
      lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
    fi
  done
  echo "Stopped."
  exit 0
}
trap cleanup INT TERM EXIT

echo "============================================"
echo "  Aegis Command Center — Full System"
echo "============================================"

# --- Python ---
PYTHON="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
  # shellcheck disable=SC1091
  source .venv/bin/activate 2>/dev/null || true
fi

# --- .env ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "[env] Ensuring secrets + local database…"
$PYTHON scripts/ensure_local_env.py

# Load env without breaking on spaces/special chars
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a

export BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
export PIPELINE_STREAM_ENABLED="${PIPELINE_STREAM_ENABLED:-true}"
export DVR_ENABLED="${DVR_ENABLED:-true}"
export AUTO_ALERTS_ENABLED="${AUTO_ALERTS_ENABLED:-true}"
export USE_SQLITE="${USE_SQLITE:-true}"
export ALLOW_SQLITE_FALLBACK="${ALLOW_SQLITE_FALLBACK:-true}"

# --- Frontend deps ---
if [ ! -d frontend/node_modules ]; then
  echo "[deps] Installing frontend packages…"
  (cd frontend && npm install)
fi

# --- Seed (best-effort) ---
echo "[seed] Demo user + cameras…"
$PYTHON scripts/seed_demo.py 2>/dev/null || echo "  (seed_demo skipped)"
$PYTHON scripts/seed_cameras.py 2>/dev/null || echo "  (seed_cameras skipped)"

# Free ports if stale processes linger
for port in 8000 5173; do
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
  fi
done

# --- Backend ---
echo "[1/3] Backend  → http://localhost:8000"
$PYTHON -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

# Wait until /health responds (max ~30s)
echo -n "      waiting for API"
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  echo -n "."
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo " ✗ (continuing anyway)"
  fi
done

# --- Pipeline ---
if [ "$NO_PIPELINE" -eq 0 ]; then
  if [ -f "$VIDEO" ]; then
    echo "[2/3] Pipeline → $VIDEO"
    $PYTHON main.py --video "$VIDEO" &
  else
    echo "[2/3] Pipeline → webcam / config (no file at $VIDEO)"
    $PYTHON main.py &
  fi
  PIPELINE_PID=$!
  PIDS+=("$PIPELINE_PID")
else
  echo "[2/3] Pipeline skipped (--no-pipeline)"
fi

# --- Frontend ---
echo "[3/3] Dashboard → http://localhost:5173"
(cd frontend && npm run dev -- --host 0.0.0.0 --port 5173) &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

sleep 2

echo ""
echo "============================================"
echo "  SYSTEM RUNNING"
echo "============================================"
echo "  Dashboard   http://localhost:5173"
echo "  API / docs  http://localhost:8000/docs"
echo "  Health      http://localhost:8000/health"
echo "  Login       admin / (password printed by scripts/seed_demo.py)"
echo ""
echo "  Ctrl+C stops backend + pipeline + frontend"
echo "============================================"
echo ""

# Block until any child exits (or Ctrl+C)
wait

