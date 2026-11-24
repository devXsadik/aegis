#!/usr/bin/env python3
"""CCTV-like weapon training data: paste weapon cut-outs into camera frames, small and in hands.

The labelled weapon photos are close-ups (weapon ~100 px). On CCTV the same weapon is 15-40 px,
blurred and JPEG-compressed, and held by a person. This builds a YOLO dataset that looks like that:

  * weapon cut-outs (`classification_crops/<split>/<class>/`), background removed with GrabCut;
  * pasted at a person's wrist (YOLOv8-pose) in your own camera frames / any images with people,
    sized to the person (a pistol ~10 % of body height, a sword ~50 %), rotated, light-matched,
    blurred to the frame's sharpness, JPEG-compressed; some frames grey (night IR);
  * every composite also as a person crop enlarged to 640 px, the way the pipeline's
    `weapon.mode: person_crop` sees it;
  * frames with people and no weapon (empty labels) as hard negatives;
  * the real labelled images (`--real`), with their classes remapped.

Splits stay apart: train/val/test crops come from the crops' own splits, and each background
source is cut in time (first 70 % → train, next 15 % → val, last 15 % → test) so no frame or
weapon is shared between training and the test set.

    python -m training.synth_weapons \\
        --crops ~/Downloads/BD_Deshi_Weapon_Dataset_v1/classification_crops \\
        --real datasets/weapons \\
        --backgrounds data/recordings datasets/_bg/coco128/images/train2017 \\
        --classes 3 --out datasets/weapons_cctv --train 1500 --val 250 --test 250

Then train with training/configs/weapon_cctv.yaml. Your own camera footage as backgrounds
(`--backgrounds path/to/clips`) matters more than anything else here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

SRC_NAMES = ["ramda", "chapati", "churi", "boti", "sickle", "sword", "axe", "rod", "pistol", "rifle"]
SCHEMES = {
    10: (SRC_NAMES, {n: i for i, n in enumerate(SRC_NAMES)}),
    3: (["blade", "firearm", "blunt"],
        {"ramda": 0, "chapati": 0, "churi": 0, "boti": 0, "sickle": 0, "sword": 0, "axe": 0,
         "pistol": 1, "rifle": 1, "rod": 2}),
    1: (["weapon"], {n: 0 for n in SRC_NAMES}),
}
# Weapon length as a fraction of the holder's height.
SIZE = {"ramda": (0.28, 0.48), "chapati": (0.14, 0.24), "churi": (0.10, 0.20), "boti": (0.20, 0.34),
        "sickle": (0.16, 0.28), "sword": (0.40, 0.62), "axe": (0.24, 0.42), "rod": (0.35, 0.62),
        "pistol": (0.08, 0.14), "rifle": (0.45, 0.72)}
# COCO classes that look like (or are) weapons: background images containing them are skipped,
# an unlabelled knife would teach the model to ignore knives.
COCO_SKIP = {34, 38, 42, 43, 76}        # baseball bat, tennis racket, fork, knife, scissors
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")
CUTS = {"train": (0.0, 0.70), "val": (0.70, 0.85), "test": (0.85, 1.0)}


# ---------------------------------------------------------------- cut-outs

def cutout(img: np.ndarray) -> np.ndarray:
    """BGRA: the weapon with its photo background removed (GrabCut seeded with an inset box), or
    None when that fails on a crop that is not long and thin."""
    h, w = img.shape[:2]
    s = min(1.0, 220 / max(h, w))
    small = cv2.resize(img, (max(8, int(w * s)), max(8, int(h * s)))) if s < 1 else img
    sh, sw = small.shape[:2]
    mask = np.zeros((sh, sw), np.uint8)
    inset = (max(1, int(sw * 0.04)), max(1, int(sh * 0.04)))
    rect = (inset[0], inset[1], max(2, sw - 2 * inset[0]), max(2, sh - 2 * inset[1]))
    try:
        cv2.grabCut(small, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_RECT)
        fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    except cv2.error:
        fg = np.full((sh, sw), 255, np.uint8)
    frac = fg.mean() / 255
    if not 0.08 <= frac <= 0.97:                # GrabCut failed
        if max(h, w) / max(1, min(h, w)) < 2.2:
            return None                         # a squarish box is mostly photo background: skip it
        fg = np.full((sh, sw), 255, np.uint8)   # long and thin: the box is mostly weapon
        fg[:2], fg[-2:], fg[:, :2], fg[:, -2:] = 0, 0, 0, 0
    fg = cv2.resize(fg, (w, h), interpolation=cv2.INTER_LINEAR)
    fg = cv2.GaussianBlur(fg, (3, 3), 0)
    return np.dstack([img, fg])


def load_cutouts(crops_dir: Path, split: str, cache: Path) -> list:
    """[(source class, BGRA)] for one split; masks cached next to the output."""
    out = []
    for cdir in sorted((crops_dir / split).glob("*")):
        if cdir.name not in SIZE:
            continue
        for p in sorted(cdir.glob("*")):
            if p.suffix.lower() not in IMAGE_EXT:
                continue
            key = cache / f"{split}_{cdir.name}_{p.stem}.png"
            if key.is_file():
                rgba = cv2.imread(str(key), cv2.IMREAD_UNCHANGED)
            else:
                img = cv2.imread(str(p))
                if img is None or min(img.shape[:2]) < 12:
                    continue
                rgba = cutout(img)
                if rgba is None:
                    rgba = np.zeros((1, 1, 4), np.uint8)       # cached as "rejected"
                cv2.imwrite(str(key), rgba)
            if rgba.shape[0] > 1:
                out.append((cdir.name, rgba))
    return out


# ---------------------------------------------------------------- backgrounds

def background_frames(sources, split: str, per_video: int = 60) -> list:
    """[(name, BGR image)] for this split. Videos: evenly spaced frames inside the split's time
    slice. Image folders: files ordered by name hash, sliced the same way."""
    lo, hi = CUTS[split]
    out = []
    for src in sources:
        src = Path(src).expanduser()
        files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file())
        videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
        images = [p for p in files if p.suffix.lower() in IMAGE_EXT and "recordings" not in p.parts]
        for v in videos:
            cap = cv2.VideoCapture(str(v))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            a, b = int(n * lo), int(n * hi)
            step = max(1, (b - a) // max(1, int(per_video * (hi - lo) / 0.7)))
            for i in range(a, b, step):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ok, f = cap.read()
                if ok:
                    out.append((f"{v.stem}_{i}", f))
            cap.release()
        images.sort(key=lambda p: hashlib.md5(p.name.encode()).hexdigest())
        a, b = int(len(images) * lo), int(len(images) * hi)
        for p in images[a:b]:
            if _coco_has_weapon_like(p):
                continue
            img = cv2.imread(str(p))
            if img is not None:
                out.append((p.stem, img))
    return out


def _coco_has_weapon_like(img_path: Path) -> bool:
    lbl = Path(str(img_path).replace("/images/", "/labels/")).with_suffix(".txt")
    if not lbl.is_file():
        return False
    return any(int(line.split()[0]) in COCO_SKIP for line in lbl.read_text().splitlines() if line.strip())


def find_people(pose, img) -> list:
    """[(box, {left_wrist, right_wrist, hip}: (x, y) or None)] for clearly seen people."""
    r = pose.predict(img, conf=0.4, verbose=False, device="cpu")[0]
    out = []
    if r.boxes is None or len(r.boxes) == 0:
        return out
    boxes = r.boxes.xyxy.cpu().numpy()
    kp = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None
    for i, b in enumerate(boxes):
        if b[3] - b[1] < 40:
            continue
        pts = {}
        if kp is not None:
            for name, k in (("left_wrist", 9), ("right_wrist", 10), ("hip", 11)):
                x, y, c = kp[i][k]
                pts[name] = (float(x), float(y)) if c > 0.5 else None
        out.append((tuple(map(float, b)), pts))
    return out


# ---------------------------------------------------------------- compositing

def _rotate(rgba: np.ndarray, angle: float) -> np.ndarray:
    h, w = rgba.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(rgba, m, (nw, nh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))


def paste(frame: np.ndarray, rgba: np.ndarray, src_class: str, person, rng: random.Random):
    """Paste one weapon at the person's hand; → (x1, y1, x2, y2) of the visible weapon or None."""
    box, pts = person
    ph = box[3] - box[1]
    lo, hi = SIZE[src_class]
    length = ph * rng.uniform(lo, hi)
    angle = rng.choice([rng.uniform(-50, 50), rng.uniform(40, 140)])       # carried or raised
    w = _rotate(rgba, angle)
    ys, xs = np.where(w[:, :, 3] > 40)
    if len(xs) < 4:
        return None
    w = w[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = length / max(w.shape[:2])
    nw, nh = max(2, int(w.shape[1] * s)), max(2, int(w.shape[0] * s))
    if min(nw, nh) < 3:
        return None
    w = cv2.resize(w, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)

    hands = [p for p in (pts.get("left_wrist"), pts.get("right_wrist")) if p]
    if hands:
        hx, hy = rng.choice(hands)
    else:                                   # no visible wrist: at the side, hand height
        hx = rng.choice([box[0] + 0.1 * (box[2] - box[0]), box[2] - 0.1 * (box[2] - box[0])])
        hy = box[1] + rng.uniform(0.45, 0.6) * ph
    # The hand holds one end: shift the weapon so the hand sits within its first third.
    dx, dy = rng.uniform(-0.35, 0.35) * nw, rng.uniform(-0.35, 0.35) * nh
    x1, y1 = int(hx - nw / 2 + dx), int(hy - nh / 2 + dy)
    fh, fw = frame.shape[:2]
    cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(fw, x1 + nw), min(fh, y1 + nh)
    if cx2 - cx1 < 3 or cy2 - cy1 < 3 or (cx2 - cx1) * (cy2 - cy1) < 0.6 * nw * nh:
        return None
    patch = w[cy1 - y1:cy2 - y1, cx1 - x1:cx2 - x1]
    rgb, a = patch[:, :, :3].astype(np.float32), patch[:, :, 3:].astype(np.float32) / 255
    region = frame[cy1:cy2, cx1:cx2].astype(np.float32)
    # Light match: pull the weapon's brightness halfway to its surroundings.
    gain = (region.mean() + 1) / (rgb.mean() + 1)
    rgb = np.clip(rgb * (1 + 0.5 * (gain - 1)), 0, 255)
    if s < 0.6:
        rgb = cv2.GaussianBlur(rgb, (3, 3), rng.uniform(0.3, 1.0))
    frame[cy1:cy2, cx1:cx2] = (rgb * a + region * (1 - a)).astype(np.uint8)
    ys, xs = np.where(patch[:, :, 3] > 100)
    if len(xs) < 3:
        return None
    return (cx1 + xs.min(), cy1 + ys.min(), cx1 + xs.max() + 1, cy1 + ys.max() + 1)


def degrade(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """CCTV look: softness, noise, compression; sometimes night IR (grey)."""
    if rng.random() < 0.4:
        h, w = img.shape[:2]
        f = rng.uniform(0.5, 0.8)
        img = cv2.resize(cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA), (w, h))
    if rng.random() < 0.15:
        img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    if rng.random() < 0.5:
        img = np.clip(img.astype(np.int16) + np.random.default_rng(rng.randrange(1 << 30))
                      .normal(0, rng.uniform(2, 7), img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    q = rng.randint(35, 85)
    return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)


def person_view(img, labels, person_box, size: int = 640):
    """The pipeline's person crop (core.detectors.weapon_detector.crop_region), enlarged."""
    from core.detectors.weapon_detector import crop_region
    r = crop_region(person_box, img.shape)
    rw, rh = r[2] - r[0], r[3] - r[1]
    if rw < 8 or rh < 8:
        return None, []
    s = size / max(rw, rh)
    crop = cv2.resize(img[r[1]:r[3], r[0]:r[2]], (int(rw * s), int(rh * s)), interpolation=cv2.INTER_LINEAR)
    out = []
    for c, (x1, y1, x2, y2) in labels:
        ix1, iy1, ix2, iy2 = max(x1, r[0]), max(y1, r[1]), min(x2, r[2]), min(y2, r[3])
        if ix2 - ix1 < 2 or iy2 - iy1 < 2 or (ix2 - ix1) * (iy2 - iy1) < 0.6 * (x2 - x1) * (y2 - y1):
            continue
        out.append((c, ((ix1 - r[0]) * s, (iy1 - r[1]) * s, (ix2 - r[0]) * s, (iy2 - r[1]) * s)))
    return crop, out


# ---------------------------------------------------------------- writing

def write(out: Path, split: str, name: str, img, labels) -> None:
    h, w = img.shape[:2]
    cv2.imwrite(str(out / "images" / split / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    lines = []
    for c, (x1, y1, x2, y2) in labels:
        lines.append(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
    (out / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))


def copy_real(real: Path, out: Path, mapping: dict) -> dict:
    """The labelled photos, classes remapped (source data.yaml uses SRC_NAMES order)."""
    counts = {}
    for split in SPLITS:
        src = real / "images" / split
        if not src.is_dir():
            continue
        for p in sorted(src.glob("*")):
            lbl = real / "labels" / split / f"{p.stem}.txt"
            if not lbl.is_file():
                continue
            rows = []
            for line in lbl.read_text().splitlines():
                parts = line.split()
                if len(parts) == 5:
                    rows.append(" ".join([str(mapping[SRC_NAMES[int(parts[0])]]), *parts[1:]]))
            shutil.copy2(p, out / "images" / split / f"real_{p.stem}{p.suffix}")
            (out / "labels" / split / f"real_{p.stem}.txt").write_text("\n".join(rows) + "\n")
            counts[split] = counts.get(split, 0) + 1
    return counts


def build(args) -> dict:
    rng = random.Random(args.seed)
    np.random.seed(args.seed)
    names, mapping = SCHEMES[args.classes]
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    for split in SPLITS:
        (out / "images" / split).mkdir(parents=True)
        (out / "labels" / split).mkdir(parents=True)
    cache = out.parent / f".{out.name}_cutouts"
    cache.mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO
    pose = YOLO(args.pose)
    stats = {"names": names, "real": copy_real(Path(args.real), out, mapping) if args.real else {}}
    targets = {"train": args.train, "val": args.val, "test": args.test}
    for split in SPLITS:
        cuts = load_cutouts(Path(args.crops).expanduser(), split, cache)
        bgs = [(n, f, find_people(pose, f)) for n, f in background_frames(args.backgrounds, split)]
        with_people = [b for b in bgs if b[2]]
        made = {"composites": 0, "person_views": 0, "negatives": 0, "weapons": 0,
                "cutouts": len(cuts), "backgrounds": len(bgs), "with_people": len(with_people)}
        if not cuts or not with_people:
            stats[split] = made
            continue
        for i in range(targets[split]):
            bname, bg, people = rng.choice(with_people)
            img = bg.copy()
            negative = rng.random() < args.negatives
            labels = []
            if not negative:
                for person in rng.sample(people, k=min(len(people), rng.choice([1, 1, 1, 2]))):
                    src_class, rgba = rng.choice(cuts)
                    box = paste(img, rgba, src_class, person, rng)
                    if box:
                        labels.append((mapping[src_class], box))
                if not labels:
                    continue
            img = degrade(img, rng)
            tag = f"syn_{split}_{i:05d}"
            write(out, split, tag, img, labels)
            made["negatives" if negative else "composites"] += 1
            made["weapons"] += len(labels)
            if rng.random() < args.person_views:
                person = rng.choice(people)
                crop, plabels = person_view(img, labels, person[0])
                if crop is not None and (plabels or negative):
                    write(out, split, f"{tag}_p", crop, plabels)
                    made["person_views"] += 1
        stats[split] = made
    (out / "data.yaml").write_text(
        "# CCTV-like weapons: real photos + synthetic composites (training/synth_weapons.py)\n"
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\n"
        f"nc: {len(names)}\nnames:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(names)))
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crops", required=True, help="classification_crops/ with train|val|test/<class>/")
    ap.add_argument("--backgrounds", nargs="+", required=True, help="videos, image folders (with people)")
    ap.add_argument("--real", default="", help="labelled YOLO set (10 source classes) to include, remapped")
    ap.add_argument("--classes", type=int, choices=sorted(SCHEMES), default=3)
    ap.add_argument("--out", default="datasets/weapons_cctv")
    ap.add_argument("--train", type=int, default=1500)
    ap.add_argument("--val", type=int, default=250)
    ap.add_argument("--test", type=int, default=250)
    ap.add_argument("--negatives", type=float, default=0.2, help="share of frames with people and no weapon")
    ap.add_argument("--person-views", type=float, default=0.6, help="share also saved as an enlarged person crop")
    ap.add_argument("--pose", default="models/yolov8n-pose.pt")
    ap.add_argument("--seed", type=int, default=13)
    stats = build(ap.parse_args(argv))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
