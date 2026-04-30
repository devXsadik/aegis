#!/bin/bash
# deploy.sh - Production Deployment Script

set -e

echo "================================================"
echo "  AI Surveillance System - Production Deploy"
echo "================================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed"
    echo "Install from: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "ERROR: docker-compose is not installed"
    exit 1
fi

# Check for .env file
if [ ! -f .env ]; then
    echo "ERROR: .env file not found"
    echo "Copy .env.example and configure it:"
    echo "  cp .env.example .env"
    echo "  # Edit .env with your secure keys"
    exit 1
fi

# Load environment variables
source .env

# Validate required variables
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_32_CHARS_MIN" ]; then
    echo "ERROR: SECRET_KEY is not configured in .env"
    exit 1
fi

if [ -z "$ENCRYPTION_KEY" ] || [ "$ENCRYPTION_KEY" = "CHANGE_THIS_ENCRYPTION_KEY_32_CHARS" ]; then
    echo "ERROR: ENCRYPTION_KEY is not configured in .env"
    exit 1
fi

echo "1. Building Docker images..."
docker-compose build

echo ""
echo "2. Starting PostgreSQL database..."
docker-compose up -d db
echo "   Waiting for database to be ready..."
sleep 10

echo ""
echo "3. Running database migrations..."
docker-compose run --rm backend python backend/init_db.py

echo ""
echo "4. Starting all services..."
docker-compose up -d

echo ""
echo "5. Checking service health..."
sleep 5
if curl -f <http://localhost:8000/health> &> /dev/null; then
    echo "   ✓ Backend is healthy"
else
    echo "   ✗ Backend health check failed"
    docker-compose logs backend
fi

echo ""
echo "================================================"
echo "  Deployment Complete!"
echo "================================================"
echo ""
echo "Services running:"
echo "  - Backend API: <http://localhost:8000>"
echo "  - API Docs: <http://localhost:8000/docs>"
echo "  - PostgreSQL: localhost:5432"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
echo ""
