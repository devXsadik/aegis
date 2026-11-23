#!/usr/bin/env python3
"""Register a finished run in the model registry (it starts in 'staging'; promote it from the
dashboard: Models & data → Registry, or POST /api/v1/ml/models/{id}/promote).

    python -m training.register runs/attributes/20261123-101500 --task vehicle_attr --version 1.3 \\
        --api http://localhost:8000 --token "$AEGIS_TOKEN" [--dataset-id 7]"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run")
    ap.add_argument("--task", required=True, choices=("vehicle_detect", "vehicle_attr", "vehicle_reid", "face", "plate_detect", "weapon_detect"))
    ap.add_argument("--weights", choices=("onnx", "pt"), default="onnx",
                    help="pt: upload train/weights/best.pt (plate / weapon detectors load .pt)")
    ap.add_argument("--version", required=True)
    ap.add_argument("--name")
    ap.add_argument("--dataset-id", type=int)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", required=True, help="an ML engineer's bearer token")
    args = ap.parse_args(argv)
    import requests
    run = Path(args.run)
    if args.weights == "pt":
        files = {"file": ("model.pt", (run / "train" / "weights" / "best.pt").read_bytes())}
    else:
        files = {"file": ("model.onnx", (run / "model.onnx").read_bytes())}
    if (run / "labels.json").exists():
        files["labels"] = ("labels.json", (run / "labels.json").read_bytes())
    metrics = json.loads((run / "metrics.json").read_text()) if (run / "metrics.json").exists() else {}
    flat = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
    for head, m in (metrics.get("test") or {}).items():
        flat[f"{head}_accuracy"] = m.get("accuracy")
    r = requests.post(f"{args.api}/api/v1/ml/models", headers={"Authorization": f"Bearer {args.token}"},
                      data={"task": args.task, "version": args.version, "name": args.name or f"{args.task}-{run.name}",
                            "metrics": json.dumps(flat), **({"dataset_id": args.dataset_id} if args.dataset_id else {}),
                            "notes": f"run {run}"}, files=files, timeout=300)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
