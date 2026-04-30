#!/bin/bash
# Phase 1 Security Foundation Setup Script

set -e

echo "================================================"
echo "  AI Surveillance System - Phase 1 Setup"
echo "================================================"
echo ""

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "ERROR: PostgreSQL is not installed or not in PATH"
    echo "Install with: brew install postgresql (macOS) or apt-get install postgresql (Ubuntu)"
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    exit 1
fi

echo "1. Creating PostgreSQL database..."
echo "   (You may be prompted for PostgreSQL password)"
createdb surveillance_db 2>/dev/null || echo "   Database may already exist"

echo ""
echo "2. Creating .env file from example..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "   .env created. Please edit it with your secure keys!"
    echo "   Generate encryption key with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
else
    echo "   .env already exists, skipping"
fi

echo ""
echo "3. Installing Python dependencies..."
pip3 install -r requirements.txt

echo ""
echo "4. Initializing database schema..."
cd backend && python3 init_db.py && cd ..

echo ""
echo "5. Running data migration (pickle -> PostgreSQL)..."
cd backend && python3 migrate.py && cd ..

echo ""
echo "6. Creating admin user..."
echo "   You can create an admin user via API after starting the server:"
echo "   POST /auth/users with admin credentials"

echo ""
echo "================================================"
echo "  Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env with secure SECRET_KEY and ENCRYPTION_KEY"
echo "  2. Start the API server: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"
echo "  3. Start surveillance: python3 main_phase1.py"
echo "  4. API docs available at: http://localhost:8000/docs"
echo ""
