"""Evidence face grouping (spec 13): one folder per person across all case evidence.

For every face in an evidence image (or sampled video frame):
  1. quality gate (size, blur, head turn)
  2. compare with the CRIMINAL watchlist (approved entries) — above the possible threshold the face
     is attached to that person's folder as "Possible match — needs verification" (an officer
     confirms or rejects; nothing is decided automatically)
  3. otherwise compare with existing folders: joins the most similar one above GROUP_SIMILARITY
  4. otherwise a new folder UNKNOWN-000123
Identical files never get here twice (SHA-256 dedupe at upload)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from clock import utcnow
from typing import List, Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.models.case_evidence import EvidenceFace, EvidenceItem, PersonGroup
from backend.models.known_person import KnownPerson
from backend.services.face_index import INDEX
from backend.utils.at_rest import seal
from core.recognition import embedder, quality

logger = logging.getLogger("HumanAnalysis")
GROUP_SIMILARITY = float(os.getenv("GROUP_SIMILARITY", "0.5"))
VIDEO_EVERY_S = float(os.getenv("GROUP_VIDEO_EVERY_S", "2"))
VIDEO_MAX_FRAMES = int(os.getenv("GROUP_VIDEO_MAX_FRAMES", "150"))
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face-group")
_lock = threading.Lock()


def _next_code(db: Session) -> str:
    last = db.query(PersonGroup.id).order_by(PersonGroup.id.desc()).first()
    return f"UNKNOWN-{(last[0] if last else 0) + 1:06d}"


def _frames(item: EvidenceItem, data: bytes):
    """(seconds_or_None, BGR frame) for an image, or sampled frames of a video."""
    import cv2
    if item.kind in ("image", "snapshot"):
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            yield None, img
        return
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(data)
        tmp.flush()
        cap = cv2.VideoCapture(tmp.name)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        step = max(1, int(fps * VIDEO_EVERY_S))
        i = n = 0
        while n < VIDEO_MAX_FRAMES:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    yield i / fps, frame
                    n += 1
            i += 1
        cap.release()


def _detect_all(emb, frame) -> list:
    """All face rows in a frame (YuNet) — or the whole frame as one face when no detector is there."""
    if hasattr(emb, "_models") and emb.available():
        _, det = emb._models()
        if det is not None:
            h, w = frame.shape[:2]
            det.setInputSize((w, h))
            _, faces = det.detect(frame)
            return [] if faces is None else list(faces)
    return [None]


def _crop(frame, row):
    if row is None:
        return frame
    x, y, w, h = (int(max(0, v)) for v in row[:4])
    pad = int(0.2 * max(w, h))
    return frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]


def _group_for(db: Session, vec: np.ndarray, model: str) -> tuple:
    rows = (db.query(EvidenceFace.embedding, EvidenceFace.group_id).join(PersonGroup)
            .filter(EvidenceFace.embedding_model == model, PersonGroup.merged_into.is_(None)).all())
    best_gid, best = None, -1.0
    for e, gid in rows:
        s = float(np.dot(np.frombuffer(e, dtype=np.float32), vec))
        if s > best:
            best_gid, best = gid, s
    return (best_gid, best) if best >= GROUP_SIMILARITY else (None, best)


def _criminal_group(db: Session, person: KnownPerson, when) -> PersonGroup:
    g = db.query(PersonGroup).filter(PersonGroup.known_person_id == person.id, PersonGroup.merged_into.is_(None)).first()
    if not g:
        g = PersonGroup(code=_next_code(db), name=person.name, status="criminal_possible", known_person_id=person.id,
                        first_seen=when, last_seen=when)
        db.add(g)
        db.flush()
    return g


def process_item(db: Session, item: EvidenceItem, data: Optional[bytes] = None) -> int:
    """Find, match and group the faces in one evidence item. Returns faces stored."""
    from backend.api.config_routes import threshold
    from backend.services.case_evidence import read
    emb = embedder.get()
    if not emb.available():
        item.faces_status = "skipped"
        return 0
    item.faces_status = "processing"
    db.flush()
    data = data if data is not None else read(item)
    when = item.captured_at or item.uploaded_at or utcnow()
    possible = threshold(db, "face_possible_similarity")
    stored = 0
    import cv2
    for ts, frame in _frames(item, data):
        for row in _detect_all(emb, frame):
            face = _crop(frame, row)
            ok, q, _ = quality.check(face, row)
            if not ok:
                continue
            vec = emb.embed(frame, row) if row is not None else emb.embed(face)
            if vec is None:
                continue
            ef = EvidenceFace(item_id=item.id, frame_ts=ts, bbox=",".join(str(int(v)) for v in row[:4]) if row is not None else None,
                              embedding=embedder.to_bytes(vec), embedding_model=emb.name, quality=q)
            ef.crop, ef.crop_encrypted = seal(cv2.imencode(".jpg", face)[1].tobytes())
            hits = INDEX.search(db, vec, emb.name, k=1)
            if hits and hits[0][1] >= possible:
                person = db.query(KnownPerson).filter(KnownPerson.person_id == hits[0][0]).first()
                g = _criminal_group(db, person, when)
                ef.watch_person_id, ef.watch_similarity, ef.verify_status = person.id, hits[0][1], "pending"
                ef.group_id, ef.group_similarity = g.id, hits[0][1]
            else:
                gid, sim = _group_for(db, vec, emb.name)
                if gid is None:
                    g = PersonGroup(code=_next_code(db), status="unknown", first_seen=when, last_seen=when)
                    db.add(g)
                    db.flush()
                    gid, sim = g.id, 1.0
                ef.group_id, ef.group_similarity = gid, sim
            db.add(ef)
            db.flush()
            g = db.get(PersonGroup, ef.group_id)
            g.first_seen = min(filter(None, [g.first_seen, when]), default=when)
            g.last_seen = max(filter(None, [g.last_seen, when]), default=when)
            if g.best_face_id is None:
                g.best_face_id = ef.id
            else:
                best = db.get(EvidenceFace, g.best_face_id)
                if best is None or (q or 0) > (best.quality or 0):
                    g.best_face_id = ef.id
            stored += 1
    item.faces_found = stored
    item.faces_status = "done" if stored else "none"
    return stored


def schedule(item_id: int) -> None:
    """Background processing after upload (synchronous when FACE_GROUPING_SYNC=true, e.g. tests)."""
    def run():
        from backend.db.database import SessionLocal
        with _lock:
            db = SessionLocal()
            try:
                item = db.get(EvidenceItem, item_id)
                if item and item.faces_status == "pending":
                    process_item(db, item)
                db.commit()
            except Exception as e:  # noqa: BLE001
                logger.exception("face grouping failed for evidence %s: %s", item_id, e)
                db.rollback()
                item = db.get(EvidenceItem, item_id)
                if item:
                    item.faces_status = "failed"
                    db.commit()
            finally:
                db.close()
    if os.getenv("FACE_GROUPING_SYNC", "").lower() in ("1", "true", "yes"):
        run()
    else:
        _executor.submit(run)


def merge(db: Session, target: PersonGroup, sources: List[PersonGroup]) -> int:
    n = 0
    for s in sources:
        if s.id == target.id:
            continue
        for f in list(s.faces):
            f.group_id = target.id
            n += 1
        s.merged_into = target.id
        target.first_seen = min(filter(None, [target.first_seen, s.first_seen]), default=None)
        target.last_seen = max(filter(None, [target.last_seen, s.last_seen]), default=None)
        if not target.known_person_id and s.known_person_id:
            target.known_person_id, target.status = s.known_person_id, s.status
    return n
