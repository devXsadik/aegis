#!/usr/bin/env python3
"""Multi-head vehicle attribute classifier: colour + type + make/model on one backbone.

    python -m training.train_attributes --data attrs_v3_attributes.zip --config training/configs/attributes.yaml

Input: the "attributes" export of a dataset (labels.csv + images/ + classes.json).
Output (runs/attributes/<time>/): model.onnx, labels.json (the format core/analysis/vehicle_attrs.py
reads), metrics.json (per-class accuracy, confusion matrices, day / night accuracy separately).
Register it with training/register.py, then promote it in the dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from training.common import (accuracy, confusion, device, load_yaml, per_class_accuracy, read_attribute_labels,
                             run_dir, save_metrics, seed_everything, unpack)

HEADS = ("color", "type", "model")
CSV_FIELD = {"color": "color", "type": "vehicle_type", "model": "make_model"}


def build(backbone: str, n_classes: dict, pretrained: bool):
    import torch.nn as nn
    import torchvision.models as tvm
    if backbone == "tiny":                                  # tests / smoke runs
        body = nn.Sequential(nn.Conv2d(3, 16, 3, 2, 1), nn.ReLU(), nn.Conv2d(16, 32, 3, 2, 1), nn.ReLU(),
                             nn.AdaptiveAvgPool2d(1), nn.Flatten())
        dim = 32
    elif backbone == "convnext_tiny":
        m = tvm.convnext_tiny(weights="DEFAULT" if pretrained else None)
        dim = m.classifier[2].in_features
        m.classifier[2] = nn.Identity()
        body = m
    else:
        m = tvm.efficientnet_b0(weights="DEFAULT" if pretrained else None)
        dim = m.classifier[1].in_features
        m.classifier = nn.Identity()
        body = m

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = body
            self.drop = nn.Dropout(0.2)
            self.heads = nn.ModuleDict({f"h_{h}": nn.Linear(dim, n) for h, n in n_classes.items()})   # "type" is reserved

        def forward(self, x):
            f = self.drop(self.body(x))
            return tuple(self.heads[f"h_{h}"](f) for h in n_classes)
    return Net()


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--config", default=str(Path(__file__).parent / "configs" / "attributes.yaml"))
    ap.add_argument("--out", default="runs")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--backbone")
    ap.add_argument("--size", type=int)
    args = ap.parse_args(argv)
    cfg = load_yaml(args.config)
    for k in ("epochs", "backbone", "size"):
        if getattr(args, k):
            cfg[k] = getattr(args, k)
    seed_everything(cfg.get("seed", 13))
    import cv2
    import torch
    import torch.nn as nn

    out = run_dir(args.out, "attributes", cfg)
    root = unpack(args.data, str(out / "data"))
    rows = read_attribute_labels(root)
    heads = [h for h in HEADS if any(r.get(CSV_FIELD[h]) for r in rows)]
    classes = {h: sorted({r[CSV_FIELD[h]] for r in rows if r.get(CSV_FIELD[h])}) for h in heads}
    size = int(cfg.get("size", 224))
    mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)

    def load(r):
        img = cv2.imread(str(root / r["file"]))
        img = cv2.cvtColor(cv2.resize(img, (size, size)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        return ((img - mean) / std).transpose(2, 0, 1)

    def target(r, h):
        v = r.get(CSV_FIELD[h])
        return classes[h].index(v) if v in classes[h] else -100            # -100: ignored (unlabelled head)

    split = {s: [r for r in rows if r["split"] == s] for s in ("train", "val", "test")}
    dev = device()
    net = build(cfg.get("backbone", "efficientnet_b0"), {h: len(classes[h]) for h in heads}, cfg.get("pretrained", True)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=float(cfg.get("lr", 3e-4)), weight_decay=float(cfg.get("weight_decay", 1e-4)))
    losses = {h: nn.CrossEntropyLoss(ignore_index=-100, label_smoothing=float(cfg.get("label_smoothing", 0.05))) for h in heads}
    bs = int(cfg.get("batch", 32))
    rng = np.random.default_rng(cfg.get("seed", 13))
    for epoch in range(int(cfg.get("epochs", 20))):
        net.train()
        order = rng.permutation(len(split["train"]))
        for i in range(0, len(order), bs):
            batch = [split["train"][j] for j in order[i:i + bs]]
            x = torch.tensor(np.stack([load(r) for r in batch])).to(dev)
            if cfg.get("hflip", True) and rng.random() < 0.5:
                x = torch.flip(x, dims=[3])
            outs = net(x)
            loss = sum(losses[h](o, torch.tensor([target(r, h) for r in batch]).to(dev)) for h, o in zip(heads, outs))
            opt.zero_grad()
            loss.backward()
            opt.step()

    def evaluate(subset):
        net.eval()
        res = {}
        with torch.no_grad():
            preds = {h: [] for h in heads}
            for i in range(0, len(subset), bs):
                outs = net(torch.tensor(np.stack([load(r) for r in subset[i:i + bs]])).to(dev))
                for h, o in zip(heads, outs):
                    preds[h] += o.argmax(1).cpu().tolist()
        for h in heads:
            pairs = [(target(r, h), p) for r, p in zip(subset, preds[h]) if target(r, h) >= 0]
            cm = confusion([t for t, _ in pairs], [p for _, p in pairs], len(classes[h]))
            res[h] = {"accuracy": accuracy(cm), "per_class": per_class_accuracy(cm, classes[h]), "confusion": cm.tolist(), "n": len(pairs)}
        return res

    test = split["test"] or split["val"]
    metrics = {"test": evaluate(test) if test else {},
               "test_day": evaluate([r for r in test if r.get("day_night") == "day"]) if test else {},
               "test_night": evaluate([r for r in test if r.get("day_night") == "night"]) if test else {},
               "classes": classes, "train_items": len(split["train"])}
    net.eval().cpu()
    torch.onnx.export(net, torch.zeros(1, 3, size, size), str(out / "model.onnx"), input_names=["input"],
                      output_names=list(heads), opset_version=17, dynamo=False)
    labels = {"version": f"attr-{out.name}", "input_size": size,
              "heads": [{"name": h, "output": h, "classes": classes[h]} for h in heads]}
    (out / "labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False))
    save_metrics(out, metrics)
    print(f"Done: {out}  test accuracy: " + ", ".join(f"{h} {metrics['test'].get(h, {}).get('accuracy', 0):.3f}" for h in heads))
    return {"dir": str(out), "metrics": metrics}


if __name__ == "__main__":
    main()
