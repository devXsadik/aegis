.PHONY: setup demo test backend pipeline frontend

setup:
	./scripts/setup.sh

demo:
	./scripts/run_defense_demo.sh

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
