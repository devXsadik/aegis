#!/usr/bin/env python3
"""Vehicle re-identification: an appearance vector that stays close for the same physical vehicle
across cameras. Pre-train on a public set (VeRi-776), then fine-tune on our camera footage.

    python -m training.train_reid --data VeRi/ --format veri          # public pre-training
    python -m training.train_reid --data reid_v2_reid.zip --init runs/reid/<time>/model.pt   # fine-tune

--format veri   : VeRi-776 folder (image_train/, image_query/, image_test/; names <vid>_c<cam>_...)
--format export : the dashboard's "reid" export (images/<split>/<identity>/*.jpg)
Output: model.onnx (256×256 → L2-normalised vector, what core/analysis/vehicle_attrs.py loads as
vehicle_reid.onnx), model.pt, metrics.json with Rank-1 and mAP on the held-out identities."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from training.common import device, load_yaml, reid_rank1_map, run_dir, save_metrics, seed_everything, unpack


def scan(root: Path, fmt: str):
    """{'train': [(path, id, cam)], 'query': [...], 'gallery': [...]}"""
    out = {"train": [], "query": [], "gallery": []}
    if fmt == "veri":
        rx = re.compile(r"(\d+)_c(\d+)_")
        for split, folder in (("train", "image_train"), ("query", "image_query"), ("gallery", "image_test")):
            for p in sorted((root / folder).glob("*.jpg")):
                m = rx.match(p.name)
                if m:
                    out[split].append((p, m.group(1), m.group(2)))
        return out
    for split in ("train", "val", "test"):
        for ident_dir in sorted((root / "images" / split).glob("*")):
            files = sorted(ident_dir.glob("*.jpg"))
            if split == "train":
                out["train"] += [(f, ident_dir.name, "0") for f in files]
            elif files:                                     # first image of each identity queries the rest
                out["query"].append((files[0], ident_dir.name, "q"))
                out["gallery"] += [(f, ident_dir.name, "g") for f in files[1:]]
    return out


def build(backbone: str, n_ids: int, dim: int, pretrained: bool):
    import torch.nn as nn
    import torchvision.models as tvm
    if backbone == "tiny":
        body = nn.Sequential(nn.Conv2d(3, 16, 3, 2, 1), nn.ReLU(), nn.Conv2d(16, 32, 3, 2, 1), nn.ReLU(),
                             nn.AdaptiveAvgPool2d(1), nn.Flatten())
        feat = 32
    else:
        m = tvm.resnet50(weights="DEFAULT" if pretrained else None)
        feat = m.fc.in_features
        m.fc = nn.Identity()
        body = m

    class ReID(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = body
            self.neck = nn.Sequential(nn.Linear(feat, dim), nn.BatchNorm1d(dim))     # BNNeck
            self.cls = nn.Linear(dim, n_ids, bias=False)

        def embed(self, x):
            v = self.neck(self.body(x))
            return v / (v.norm(dim=1, keepdim=True) + 1e-9)

        def forward(self, x):
            return self.embed(x)
    return ReID()


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--format", choices=("veri", "export"), default="export")
    ap.add_argument("--config", default=str(Path(__file__).parent / "configs" / "reid.yaml"))
    ap.add_argument("--init", help="model.pt to fine-tune from")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--backbone")
    args = ap.parse_args(argv)
    cfg = load_yaml(args.config)
    for k in ("epochs", "backbone"):
        if getattr(args, k):
            cfg[k] = getattr(args, k)
    seed_everything(cfg.get("seed", 13))
    import cv2
    import torch
    import torch.nn as nn

    out = run_dir(args.out, "reid", cfg)
    root = unpack(args.data, str(out / "data"))
    data = scan(root, args.format)
    ids = sorted({i for _, i, _ in data["train"]})
    idx = {i: k for k, i in enumerate(ids)}
    size = int(cfg.get("size", 256))
    mean, std = np.array([0.485, 0.456, 0.406], np.float32), np.array([0.229, 0.224, 0.225], np.float32)

    def load(p):
        img = cv2.cvtColor(cv2.resize(cv2.imread(str(p)), (size, size)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        return ((img - mean) / std).transpose(2, 0, 1)

    dev = device()
    net = build(cfg.get("backbone", "resnet50"), len(ids), int(cfg.get("dim", 512)), cfg.get("pretrained", True)).to(dev)
    if args.init:
        state = torch.load(args.init, map_location="cpu")
        net.load_state_dict({k: v for k, v in state.items() if not k.startswith("cls.")}, strict=False)
    opt = torch.optim.Adam(net.parameters(), lr=float(cfg.get("lr", 3.5e-4)))
    ce = nn.CrossEntropyLoss(label_smoothing=0.1)
    triplet = nn.TripletMarginLoss(margin=float(cfg.get("margin", 0.3)))
    by_id = {}
    for p, i, _ in data["train"]:
        by_id.setdefault(i, []).append(p)
    rng = np.random.default_rng(cfg.get("seed", 13))
    P, K = int(cfg.get("p", 16)), int(cfg.get("k", 4))                 # P identities × K images per batch
    for epoch in range(int(cfg.get("epochs", 60))):
        net.train()
        usable = [i for i in ids if len(by_id[i]) >= 2]
        rng.shuffle(usable)
        for s in range(0, len(usable), P):
            group = usable[s:s + P]
            if len(group) < 2:
                continue
            paths, labels = [], []
            for i in group:
                pick = rng.choice(len(by_id[i]), size=K, replace=len(by_id[i]) < K)
                paths += [by_id[i][j] for j in pick]
                labels += [idx[i]] * K
            x = torch.tensor(np.stack([load(p) for p in paths])).to(dev)
            y = torch.tensor(labels).to(dev)
            emb = net.neck(net.body(x))
            norm = emb / (emb.norm(dim=1, keepdim=True) + 1e-9)
            # batch-hard triplets
            d = torch.cdist(norm, norm)
            same = y[:, None] == y[None, :]
            hardest_pos = norm[(d * same).argmax(1)]
            hardest_neg = norm[(d + same * 1e3).argmin(1)]
            loss = ce(net.cls(emb), y) + triplet(norm, hardest_pos, hardest_neg)
            opt.zero_grad()
            loss.backward()
            opt.step()

    net.eval()

    def feats(items):
        vs = []
        with torch.no_grad():
            for s in range(0, len(items), 64):
                vs.append(net.embed(torch.tensor(np.stack([load(p) for p, _, _ in items[s:s + 64]])).to(dev)).cpu().numpy())
        return np.concatenate(vs) if vs else np.zeros((0, 1))

    metrics = {"identities_train": len(ids)}
    if data["query"] and data["gallery"]:
        cams = args.format == "veri"
        metrics.update(reid_rank1_map(feats(data["query"]), [i for _, i, _ in data["query"]],
                                      feats(data["gallery"]), [i for _, i, _ in data["gallery"]],
                                      [c for _, _, c in data["query"]] if cams else None,
                                      [c for _, _, c in data["gallery"]] if cams else None))
    net.cpu()
    torch.save(net.state_dict(), out / "model.pt")

    class Export(nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return self.m.embed(x)
    torch.onnx.export(Export(net), torch.zeros(1, 3, size, size), str(out / "model.onnx"), input_names=["input"],
                      output_names=["embedding"], opset_version=17, dynamo=False)
    save_metrics(out, metrics)
    print(f"Done: {out}  rank-1 {metrics.get('rank1', 0):.3f}  mAP {metrics.get('mAP', 0):.3f}")
    return {"dir": str(out), "metrics": metrics}


if __name__ == "__main__":
    main()
