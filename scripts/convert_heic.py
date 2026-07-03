#!/usr/bin/env python3
"""Convert HEIC/HEIF images in data/watchlist/ to JPG for face_recognition."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paths import WATCHLIST_DIR

KNOWN_DIR = WATCHLIST_DIR


def convert_with_sips(heic_path: Path) -> bool:
    jpg_path = heic_path.with_suffix(".jpg")
    if jpg_path.exists():
        return False
    try:
        subprocess.run(
            ["sips", "-s", "format", "jpeg", str(heic_path), "--out", str(jpg_path)],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def convert_with_pillow(heic_path: Path) -> bool:
    jpg_path = heic_path.with_suffix(".jpg")
    if jpg_path.exists():
        return False
    try:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        img = Image.open(heic_path)
        img.convert("RGB").save(jpg_path, "JPEG", quality=90)
        return True
    except ImportError:
        return False
    except Exception:
        return False


def main():
    if not KNOWN_DIR.exists():
        print(f"data/watchlist/ not found at {KNOWN_DIR}")
        return

    converted = 0
    for ext in ("*.HEIC", "*.heic", "*.HEIF", "*.heif"):
        for path in KNOWN_DIR.rglob(ext):
            ok = convert_with_sips(path) or convert_with_pillow(path)
            if ok:
                converted += 1
                print(f"Converted: {path.name} → {path.stem}.jpg")

    if converted:
        print(f"Done — converted {converted} image(s). Run: python3 scripts/ingest_watchlist.py")
    else:
        print("No HEIC files to convert (or sips/Pillow unavailable)")


if __name__ == "__main__":
    main()
