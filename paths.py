"""
Project path constants — single source of truth for directories.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
WATCHLIST_DIR = DATA_DIR / "watchlist"
DEMO_CLIPS_DIR = DATA_DIR / "demo" / "clips"
RECORDINGS_DIR = DATA_DIR / "recordings"
RESULTS_DIR = DATA_DIR / "results"
EVIDENCE_DIR = ROOT / "evidence"
# Officer-uploaded case files (sealed at rest). AEGIS_UPLOADS_DIR moves them (tests use a temp dir).
DATASETS_DIR = Path(os.environ["AEGIS_DATASETS_DIR"]) if os.getenv("AEGIS_DATASETS_DIR") else ROOT / "data" / "datasets"
MODEL_STORE_DIR = Path(os.environ["AEGIS_MODEL_STORE"]) if os.getenv("AEGIS_MODEL_STORE") else ROOT / "models" / "registry"
UPLOADS_DIR = Path(os.environ["AEGIS_UPLOADS_DIR"]) if os.getenv("AEGIS_UPLOADS_DIR") else EVIDENCE_DIR / "items"
MODELS_DIR = ROOT / "models"
LOGS_DIR = ROOT / "logs"

CONFIG_YAML = CONFIG_DIR / "config.yaml"
# AEGIS_CAMERAS_YAML points tests and the e2e server at a throwaway copy (never the real file).
CAMERAS_YAML = Path(os.environ["AEGIS_CAMERAS_YAML"]) if os.getenv("AEGIS_CAMERAS_YAML") else CONFIG_DIR / "cameras.yaml"
MODELS_YAML = CONFIG_DIR / "models.yaml"
WATCHLIST_MANIFEST = WATCHLIST_DIR / "manifest.json"

