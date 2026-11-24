#!/usr/bin/env python3
"""How well does a weapon model work at CCTV distance? Class-agnostic (the alert does not use the
weapon type), at the pipeline's threshold, on held-out data only.

    python -m training.evaluate_weapons models/weapon_yolo.pt [other.pt …] --data datasets/weapons_cctv

Three tests:
  photos      the held-out labelled photos (`real_*` in the test split), as photographed
  shrunk      the same photos shrunk into a 1920x1080 frame (weapon ~50 / 25 / 12 % of the size)
  cctv        synthetic camera frames of the test split (`syn_test_*`, never trained on), run the way
              the pipeline runs: people found by the person model, then WeaponDetector in `full`
              and `both` mode. Also counts false alarms on the frames with people and no weapon.

"found" = a predicted box overlaps a labelled weapon (IoU >= 0.3, or the prediction lies mostly
inside it). It is not mAP: it is the share of weapons that would reach the confirmation step.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)


def hit(gt, pred) -> bool:
    """IoU, or a prediction that covers part of a long weapon (blade without the handle)."""
    if iou(gt, pred) >= 0.3:
        return True
    ix = max(0, min(gt[2], pred[2]) - max(gt[0], pred[0]))
    iy = max(0, min(gt[3], pred[3]) - max(gt[1], pred[1]))
    return ix * iy >= 0.7 * (pred[2] - pred[0]) * (pred[3] - pred[1]) > 0


def labels_of(img_path: Path, shape):
    h, w = shape[:2]
    lp = Path(str(img_path).replace("/images/", "/labels/")).with_suffix(".txt")
    out = []
    for line in lp.read_text().splitlines() if lp.is_file() else []:
        p = line.split()
        if len(p) == 5:
            cx, cy, bw, bh = map(float, p[1:])
            out.append(((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
    return out


class Tally:
    def __init__(self):
        self.gt = self.found = self.preds = self.true_preds = 0
        self.frames = self.alarm_frames = 0           # weapon-free frames, and those with a hit
        self.by_size = {"<24px": [0, 0], "24-48px": [0, 0], ">48px": [0, 0]}

    def add(self, gts, preds):
        used = set()
        for g in gts:
            side = min(g[2] - g[0], g[3] - g[1])
            bucket = "<24px" if side < 24 else "24-48px" if side < 48 else ">48px"
            self.by_size[bucket][0] += 1
            j = next((j for j, p in enumerate(preds) if j not in used and hit(g, p)), None)
            if j is not None:
                used.add(j)
                self.found += 1
                self.by_size[bucket][1] += 1
        self.gt += len(gts)
        self.preds += len(preds)
        self.true_preds += sum(1 for p in preds if any(hit(g, p) for g in gts))
        if not gts:
            self.frames += 1
            self.alarm_frames += bool(preds)

    def row(self) -> dict:
        r = {"weapons": self.gt, "found": round(self.found / self.gt, 3) if self.gt else None,
             "precision": round(self.true_preds / self.preds, 3) if self.preds else None}
        if self.frames:
            r["weapon_free_frames"] = self.frames
            r["false_alarm_frames"] = round(self.alarm_frames / self.frames, 3)
        sizes = {k: f"{v[1]}/{v[0]}" for k, v in self.by_size.items() if v[0]}
        if sizes:
            r["found_by_size"] = sizes
        return r


def shrink(img, gts, frac):
    h, w = img.shape[:2]
    s = frac * 1080 / max(h, w)
    small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    canvas = np.full((1080, 1920, 3), 110, np.uint8)
    canvas[400:400 + small.shape[0], 800:800 + small.shape[1]] = small
    return canvas, [(g[0] * s + 800, g[1] * s + 400, g[2] * s + 800, g[3] * s + 400) for g in gts]


def evaluate(model_path: str, data: Path, conf: float, person_model: str) -> dict:
    from ultralytics import YOLO
    from core.detectors.weapon_detector import WeaponDetector

    test = data / "images" / "test"
    photos = sorted(test.glob("real_*"))
    frames = sorted(p for p in test.glob("syn_test_*") if not p.stem.endswith("_p"))
    out = {"model": model_path}

    full = WeaponDetector(model_path, conf, "cpu", mode="full")
    t = Tally()
    loaded = []
    for p in photos:
        img = cv2.imread(str(p))
        gts = labels_of(p, img.shape)
        loaded.append((img, gts))
        t.add(gts, [d["bbox"] for d in full.detect(img)])
    out["photos"] = t.row()
    for frac in (0.5, 0.25, 0.12):
        t = Tally()
        for img, gts in loaded:
            canvas, sg = shrink(img, gts, frac)
            t.add(sg, [d["bbox"] for d in full.detect(canvas)])
        out[f"shrunk_{int(frac * 100)}pct"] = t.row()

    people_model = YOLO(person_model)
    both = WeaponDetector(model_path, conf, "cpu", mode="both")
    tf, tb = Tally(), Tally()
    for p in frames:
        img = cv2.imread(str(p))
        gts = labels_of(p, img.shape)
        r = people_model.predict(img, conf=0.5, classes=[0], verbose=False, device="cpu")[0]
        people = [([*map(int, b)], float(c), 0) for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())]
        tf.add(gts, [d["bbox"] for d in full.detect(img, people=people)])
        tb.add(gts, [d["bbox"] for d in both.detect(img, people=people)])
    out["cctv_full_frame"] = tf.row()
    out["cctv_with_person_crops"] = tb.row()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("models", nargs="+")
    ap.add_argument("--data", default="datasets/weapons_cctv")
    ap.add_argument("--conf", type=float, default=0.4, help="weapon_conf_threshold of config.yaml")
    ap.add_argument("--person-model", default="models/yolov8s.pt")
    ap.add_argument("--json", default="", help="also write the results here")
    args = ap.parse_args(argv)
    results = [evaluate(m, Path(args.data), args.conf, args.person_model) for m in args.models]
    for r in results:
        print(f"\n== {r['model']}")
        for k, v in r.items():
            if k != "model":
                print(f"  {k:26s} {json.dumps(v)}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
