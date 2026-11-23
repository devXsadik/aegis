"""Shared bits for the trainers: reproducible runs, metrics, dataset readers."""

from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(False)
    except ImportError:
        pass


def run_dir(base: str, name: str, config: dict) -> Path:
    """runs/<name>/<timestamp>/ with the config and the code version, for reproducibility."""
    d = Path(base) / name / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = "unknown"
    (d / "config.json").write_text(json.dumps({**config, "git_commit": commit}, indent=2))
    return d


def load_yaml(path: str) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f) or {}


def unpack(src: str, dest: str) -> Path:
    """A dataset export (.zip from the dashboard) or an already unpacked folder."""
    p = Path(src)
    if p.is_dir():
        return p
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p) as z:
        z.extractall(out)
    return out


def read_attribute_labels(root: Path) -> List[dict]:
    with open(root / "labels.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ——— metrics ———

def confusion(y_true: Sequence[int], y_pred: Sequence[int], n: int) -> np.ndarray:
    m = np.zeros((n, n), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        if 0 <= t < n and 0 <= p < n:
            m[t, p] += 1
    return m


def per_class_accuracy(cm: np.ndarray, classes: Sequence[str]) -> Dict[str, float]:
    out = {}
    for i, c in enumerate(classes):
        tot = cm[i].sum()
        out[c] = float(cm[i, i] / tot) if tot else None
    return out


def accuracy(cm: np.ndarray) -> float:
    tot = cm.sum()
    return float(np.trace(cm) / tot) if tot else 0.0


def reid_rank1_map(q_feat: np.ndarray, q_ids: Sequence, g_feat: np.ndarray, g_ids: Sequence,
                   q_cams: Sequence = None, g_cams: Sequence = None) -> Dict[str, float]:
    """Rank-1 and mAP (cosine). Same-camera gallery matches are ignored (standard VeRi / Market rule)."""
    q = q_feat / (np.linalg.norm(q_feat, axis=1, keepdims=True) + 1e-9)
    g = g_feat / (np.linalg.norm(g_feat, axis=1, keepdims=True) + 1e-9)
    sims = q @ g.T
    g_ids = np.asarray(g_ids)
    ranks1, aps = [], []
    for i in range(len(q)):
        keep = np.ones(len(g_ids), bool)
        if q_cams is not None and g_cams is not None:
            keep = ~((g_ids == q_ids[i]) & (np.asarray(g_cams) == q_cams[i]))
        order = np.argsort(-sims[i][keep])
        hits = (g_ids[keep][order] == q_ids[i]).astype(np.float64)
        if hits.sum() == 0:
            continue
        ranks1.append(hits[0])
        cum = np.cumsum(hits)
        precision = cum / (np.arange(len(hits)) + 1)
        aps.append(float((precision * hits).sum() / hits.sum()))
    return {"rank1": float(np.mean(ranks1)) if ranks1 else 0.0, "mAP": float(np.mean(aps)) if aps else 0.0,
            "queries": len(aps)}


def save_metrics(d: Path, metrics: dict) -> None:
    (d / "metrics.json").write_text(json.dumps(metrics, indent=2, default=float))


def device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() and os.getenv("TRAIN_MPS", "0") == "1":
            return "mps"
    except ImportError:
        pass
    return "cpu"
