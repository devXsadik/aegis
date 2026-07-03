#!/usr/bin/env bash
# Start full defense demo: backend + pipeline + frontend (automated alerts)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "============================================"
echo "  Ai-SSS Defense Demo — Auto Alert Mode"
echo "============================================"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from example — edit INTERNAL_API_KEY if needed"
fi

export $(grep -v '^#' .env | xargs) 2>/dev/null || true

echo "[1/5] Seeding demo admin (admin/admin123)..."
python3 scripts/seed_demo.py 2>/dev/null || true

echo "[2/5] Syncing camera GPS to database..."
python3 scripts/seed_cameras.py 2>/dev/null || true

echo "[3/5] Starting FastAPI backend on :8000..."
uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

VIDEO="${1:-data/demo/clips/sample.mp4}"
if [ -f "$VIDEO" ]; then
  echo "[4/5] Starting pipeline on video: $VIDEO"
  python3 main.py --video "$VIDEO" &
else
  echo "[4/5] Starting pipeline (webcam or config camera)..."
  echo "      Tip: add data/demo/clips/sample.mp4 for reliable defense demo"
  python3 main.py &
fi
PIPELINE_PID=$!

echo "[5/5] Starting dashboard on :5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd "$ROOT"

echo ""
echo "============================================"
echo "  DEMO READY — Automated alerts ON"
echo "============================================"
echo "  Dashboard:  http://localhost:5173"
echo "  API docs:     http://localhost:8000/docs"
echo "  Login:        admin / admin123"
echo ""
echo "  Criminal on ANY camera → auto alert everywhere"
echo "  Press Ctrl+C to stop all services"
echo "============================================"

cleanup() {
  echo "Stopping services..."
  kill $BACKEND_PID $PIPELINE_PID $FRONTEND_PID 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

wait
