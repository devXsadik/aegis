#!/bin/bash
# ──────────────────────────────────────────────
#  AI Surveillance System — One-command Launcher
# ──────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BACKEND_PORT="${BACKEND_PORT:-8000}"
PID_FILE="/tmp/surveillance_pids"

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    if [ -f "$PID_FILE" ]; then
        while read -r pid; do
            kill "$pid" 2>/dev/null && echo -e "  ${RED}✗${NC} Stopped PID $pid"
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "  --camera URL     RTSP URL or camera index (passed to main.py)"
    echo "  --video  FILE    Video file path (passed to main.py)"
    echo "  --port   PORT    Backend port (default: 8000)"
    echo "  --no-backend     Skip starting the API backend"
    echo "  --no-pipeline    Skip starting the surveillance pipeline"
    echo "  --help           Show this help"
    echo ""
    echo "Examples:"
    echo "  $0                                    # USB camera + backend"
    echo "  $0 --camera \"rtsp://admin:pass@10.0.0.1:554/stream\""
    echo "  $0 --no-backend                       # Detection only, no UI"
    echo "  $0 --no-pipeline --port 8080          # Backend only on port 8080"
    echo ""
}

# Defaults
RUN_BACKEND=true
RUN_PIPELINE=true
CAMERA_ARG=""
VIDEO_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --camera)   CAMERA_ARG="--camera $2"; shift 2 ;;
        --video)    VIDEO_ARG="--video $2"; shift 2 ;;
        --port)     BACKEND_PORT="$2"; shift 2 ;;
        --no-backend)   RUN_BACKEND=false; shift ;;
        --no-pipeline)  RUN_PIPELINE=false; shift ;;
        --help)     print_usage; exit 0 ;;
        *)          echo "Unknown option: $1"; print_usage; exit 1 ;;
    esac
done

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════╗"
echo "  ║   AI Surveillance System — Launcher  ║"
echo "  ╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Check environment ──
if ! python3 -c "import cv2" 2>/dev/null; then
    echo -e "${RED}ERROR: opencv-python not installed. Run: pip install -r requirements.txt${NC}"
    exit 1
fi

# ── Start Backend (FastAPI) ──
if [ "$RUN_BACKEND" = true ]; then
    echo -e "${GREEN}[1/2]${NC} Starting backend on port ${BACKEND_PORT}..."
    uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
    BACKEND_PID=$!
    echo "$BACKEND_PID" > "$PID_FILE"
    echo -e "      PID ${BACKEND_PID}  |  API: ${CYAN}http://localhost:${BACKEND_PORT}${NC}"
    echo -e "      Dashboard: ${CYAN}http://localhost:${BACKEND_PORT}/dashboard${NC}"
    echo -e "      Docs:      ${CYAN}http://localhost:${BACKEND_PORT}/docs${NC}"
    sleep 2
fi

# ── Start Pipeline (main.py) ──
if [ "$RUN_PIPELINE" = true ]; then
    echo -e "${GREEN}[2/2]${NC} Starting surveillance pipeline..."
    PYTHONPATH="$SCRIPT_DIR" python3 main.py $CAMERA_ARG $VIDEO_ARG &
    PIPELINE_PID=$!
    echo "$PIPELINE_PID" >> "$PID_FILE"
    echo -e "      PID ${PIPELINE_PID}  |  Press ${RED}Ctrl+C${NC} to stop all"
fi

echo ""
echo -e "${YELLOW}Both processes running. Press Ctrl+C to stop everything.${NC}"
echo ""

# Wait for any child to exit
wait
