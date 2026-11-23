#!/usr/bin/env python3
"""Compute watchlist-matching embeddings (ArcFace-family, e.g. SFace) for every stored person
photo that does not have one for the current model yet. Run after installing / changing the model.

    python scripts/reembed_faces.py [--dry-run]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.face_encoding import FaceEncoding  # noqa: E402
from backend.models.known_person import KnownPerson  # noqa: E402
from backend.models.person_image import PersonImage  # noqa: E402
from backend.utils.at_rest import unseal  # noqa: E402
from core.recognition import embedder  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    emb = embedder.get()
    if not emb.available():
        print("Embedding model not installed: run scripts/ensure_local_env.py first.")
        return 2
    init_db()
    db = SessionLocal()
    done = skipped = failed = 0
    try:
        have = {i for (i,) in db.query(FaceEncoding.image_id).filter(FaceEncoding.encoding_version == emb.name)}
        for img in db.query(PersonImage).all():
            if img.id in have:
                skipped += 1
                continue
            data = unseal(img.image_data, getattr(img, "encrypted", False))
            bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
            vec = emb.embed(bgr) if bgr is not None else None
            if vec is None:
                failed += 1
                continue
            if not args.dry_run:
                person = db.get(KnownPerson, img.person_id)
                db.add(FaceEncoding(person_id=person.id, image_id=img.id, encoding=embedder.to_bytes(vec),
                                    encoding_version=emb.name))
            done += 1
        if not args.dry_run:
            db.commit()
    finally:
        db.close()
    print(f"{emb.name}: embedded {done}, already had {skipped}, no face found {failed}{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
