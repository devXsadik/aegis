.PHONY: setup demo test backend pipeline frontend ingest run all stop docker-build docker-up docker-down docker-logs docker-admin

setup:
	./scripts/setup.sh

demo: run

run all:
	./run.sh $(ARGS)

stop:
	@for port in 8000 5173; do \
	  lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true; \
	done
	@echo "Stopped processes on :8000 and :5173"

test:
	pytest tests/unit/ -v

backend:
	uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pipeline:
	python main.py --video data/demo/clips/sample.mp4

frontend:
	cd frontend && npm run dev

ingest:
	python scripts/ingest_watchlist.py

# ---- Docker (full stack: Postgres, Redis, API, AI pipeline, dashboard) ----
docker-build:
	docker compose build

docker-up:
	docker compose up -d --build
	@echo "Dashboard: http://localhost:$${HTTP_PORT:-8080}"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100

# Lost the admin password? Reset it inside the running container:
docker-admin:
	docker compose exec backend python scripts/seed_demo.py --reset-password
