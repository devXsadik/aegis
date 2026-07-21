#!/bin/bash
# Aegis Setup Script

set -e

echo "================================================"
echo "  AI Surveillance System — Setup"
echo "================================================"
echo ""

if ! command -v psql &> /dev/null; then
    echo "ERROR: PostgreSQL is not installed or not in PATH"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    exit 1
fi

echo "1. Creating PostgreSQL database..."
createdb surveillance_db 2>/dev/null || echo "   Database may already exist"

echo ""
echo "2. Creating .env file from example..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "   .env created — edit SECRET_KEY and INTERNAL_API_KEY"
else
    echo "   .env already exists, skipping"
fi

echo ""
echo "3. Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "4. Initializing database schema..."
python3 -m backend.init_db

echo ""
echo "5. Ingesting known persons (face encodings)..."
python3 -m backend.migrate 2>/dev/null || python3 scripts/ingest_watchlist.py 2>/dev/null || echo "   Run: python3 scripts/ingest_watchlist.py"

echo ""
echo "6. Creating demo admin (admin / admin123)..."
python3 scripts/seed_demo.py 2>/dev/null || true

echo ""
echo "7. Syncing camera GPS to database..."
python3 scripts/seed_cameras.py 2>/dev/null || true

echo ""
echo "8. Converting HEIC face images to JPG (if any)..."
python3 scripts/convert_heic.py 2>/dev/null || true

echo ""
echo "================================================"
echo "  Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  ./scripts/run_defense_demo.sh"
echo "  OR manually:"
echo "    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"
echo "    python3 main.py --video data/demo/clips/sample.mp4"
echo "    cd frontend && npm run dev"
echo ""

