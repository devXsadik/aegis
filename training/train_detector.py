#!/usr/bin/env python3
"""YOLO detector trainer (vehicles, weapons, plates, …).

    python -m training.train_detector --data det_v4_yolo.zip --config training/configs/detector.yaml
    python -m training.train_detector --data datasets/weapons --config training/configs/weapon.yaml \\
        --install models/weapon_yolo.pt

Input: YOLO export (images/, labels/, data.yaml). Starts from the weights in the config.
Output (runs/detector/<time>/): best.pt, model.onnx, labels.json, metrics.json (mAP50, mAP50-95,
per-class AP). TensorRT: `yolo export model=best.pt format=engine half=True` on the GPU box."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from training.common import load_yaml, run_dir, save_metrics, seed_everything, unpack


def _resolve_weights(path: str) -> str:
    p = Path(path)
    if p.is_file():
        return str(p)
    local = Path("models") / p.name
    if local.is_file():
        return str(local)
    return path


def _device(cfg: dict) -> str:
    pref = str(cfg.get("device") or "auto").lower()
    if pref != "auto":
        return pref
    try:
        import torch
        if torch.cuda.is_available():
            return "0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", default=str(Path(__file__).parent / "configs" / "detector.yaml"))
    ap.add_argument("--out", default="runs")
    ap.add_argument("--install", default="", help="Copy best.pt (+ labels.json) to this path when done")
    args = ap.parse_args(argv)
    cfg = load_yaml(args.config)
    seed_everything(cfg.get("seed", 13))
    from ultralytics import YOLO

    out = run_dir(args.out, "detector", cfg)
    root = unpack(args.data, str(out / "data"))
    # Never mutate the source data.yaml — write a run-local copy with an absolute path.
    src_yaml = (root / "data.yaml").read_text()
    data_yaml = out / "data.yaml"
    data_yaml.write_text(src_yaml.replace("path: .", f"path: {root.resolve()}", 1))

    weights = _resolve_weights(cfg.get("weights", "yolov8s.pt"))
    device = _device(cfg)
    imgsz = int(cfg.get("imgsz", 960))
    # `arch` (e.g. yolov8s-p2.yaml: an extra high-resolution head for tiny objects) is built fresh
    # and gets every matching layer from `weights`.
    arch = cfg.get("arch")
    model = YOLO(arch).load(weights) if arch else YOLO(weights)
    extra = {k: cfg[k] for k in ("scale", "copy_paste", "translate", "hsv_h", "hsv_s", "hsv_v",
                                 "perspective", "erasing", "lr0", "freeze") if k in cfg}
    model.train(
        data=str(data_yaml),
        epochs=int(cfg.get("epochs", 100)),
        imgsz=imgsz,
        batch=int(cfg.get("batch", 16)),
        project=str(out),
        name="train",
        seed=int(cfg.get("seed", 13)),
        patience=int(cfg.get("patience", 30)),
        device=device,
        cos_lr=True,
        close_mosaic=10,
        exist_ok=True,
        mosaic=float(cfg.get("mosaic", 1.0)),
        mixup=float(cfg.get("mixup", 0.0)),
        degrees=float(cfg.get("degrees", 0.0)),
        fliplr=float(cfg.get("fliplr", 0.5)),
        **extra,
    )
    best = out / "train" / "weights" / "best.pt"
    trained = YOLO(str(best))
    val = trained.val(data=str(data_yaml), split="test" if (root / "images" / "test").exists() else "val")
    names = trained.names
    metrics = {
        "mAP50": float(val.box.map50),
        "mAP50_95": float(val.box.map),
        "per_class_AP50_95": {
            names[int(c)]: float(ap) for c, ap in zip(val.box.ap_class_index, val.box.maps)
        },
        "device": device,
        "weights": weights,
        "arch": arch,
    }
    onnx_path = trained.export(format="onnx", imgsz=imgsz, opset=17)
    Path(onnx_path).rename(out / "model.onnx")
    labels = {"version": f"det-{out.name}", "names": names, "task": "detect"}
    (out / "labels.json").write_text(json.dumps(labels, indent=2))
    save_metrics(out, metrics)

    if args.install:
        dest = Path(args.install)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, dest)
        shutil.copy2(out / "labels.json", dest.with_suffix(".labels.json"))
        onnx_dest = dest.with_suffix(".onnx")
        if (out / "model.onnx").is_file():
            shutil.copy2(out / "model.onnx", onnx_dest)
        print(f"Installed → {dest}")

    print(f"Done: {out}  mAP50 {metrics['mAP50']:.3f}  mAP50-95 {metrics['mAP50_95']:.3f}")
    return {"dir": str(out), "metrics": metrics}


if __name__ == "__main__":
    main()
