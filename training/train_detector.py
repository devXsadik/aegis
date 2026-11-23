#!/usr/bin/env python3
"""Vehicle detector + type classes for Bangladeshi roads (YOLOv8 / YOLO11, Ultralytics).

    python -m training.train_detector --data det_v4_yolo.zip --config training/configs/detector.yaml

Input: the "yolo" export of a detection dataset (images/, labels/, data.yaml), classes such as
car, bus, truck, cng, leguna, easy_bike, motorcycle, rickshaw … Starts from COCO weights.
Output (runs/detector/<time>/): best.pt, model.onnx, labels.json, metrics.json (mAP50, mAP50-95,
per-class AP). TensorRT: `yolo export model=best.pt format=engine half=True` on the GPU box."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.common import load_yaml, run_dir, save_metrics, seed_everything, unpack


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", default=str(Path(__file__).parent / "configs" / "detector.yaml"))
    ap.add_argument("--out", default="runs")
    args = ap.parse_args(argv)
    cfg = load_yaml(args.config)
    seed_everything(cfg.get("seed", 13))
    from ultralytics import YOLO

    out = run_dir(args.out, "detector", cfg)
    root = unpack(args.data, str(out / "data"))
    data_yaml = root / "data.yaml"
    text = data_yaml.read_text().replace("path: .", f"path: {root.resolve()}")
    data_yaml.write_text(text)
    model = YOLO(cfg.get("weights", "yolov8s.pt"))
    model.train(data=str(data_yaml), epochs=int(cfg.get("epochs", 100)), imgsz=int(cfg.get("imgsz", 960)),
                batch=int(cfg.get("batch", 16)), project=str(out), name="train", seed=int(cfg.get("seed", 13)),
                patience=int(cfg.get("patience", 30)), cos_lr=True, close_mosaic=10, exist_ok=True)
    best = out / "train" / "weights" / "best.pt"
    trained = YOLO(str(best))
    val = trained.val(data=str(data_yaml), split="test" if (root / "images" / "test").exists() else "val")
    names = trained.names
    metrics = {"mAP50": float(val.box.map50), "mAP50_95": float(val.box.map),
               "per_class_AP50_95": {names[int(c)]: float(ap) for c, ap in zip(val.box.ap_class_index, val.box.maps)}}
    onnx_path = trained.export(format="onnx", imgsz=int(cfg.get("imgsz", 960)), opset=17)
    Path(onnx_path).rename(out / "model.onnx")
    (out / "labels.json").write_text(json.dumps({"version": f"det-{out.name}", "names": names}, indent=2))
    save_metrics(out, metrics)
    print(f"Done: {out}  mAP50 {metrics['mAP50']:.3f}  mAP50-95 {metrics['mAP50_95']:.3f}")
    return {"dir": str(out), "metrics": metrics}


if __name__ == "__main__":
    main()
