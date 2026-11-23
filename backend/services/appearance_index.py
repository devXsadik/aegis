"""Index the people in a case's evidence by clothing colour (after upload, in the background).

Uses the person detector the pipeline uses (YOLO, COCO person) on photos and on video sampled
every APPEARANCE_EVERY_S seconds. Off with APPEARANCE_INDEX=false. Only evidence attached to an
incident is indexed; the rows go when the evidence or the incident goes (cascade)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.case_evidence import EvidenceItem, EvidencePerson

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="appearance")
_lock = threading.Lock()
_detector = None
MIN_HEIGHT_PX = 60


def enabled() -> bool:
    return os.getenv("APPEARANCE_INDEX", "true").lower() not in ("0", "false", "no")


def set_detector(d) -> None:
    """Tests install a fake: an object with detect(frame) -> [([x1,y1,x2,y2], conf, 0)]."""
    global _detector
    _detector = d


def _people_detector():
    global _detector
    if _detector is None:
        from core.detectors.detector import HumanDetector
        from paths import ROOT
        path = os.getenv("APPEARANCE_MODEL") or str(ROOT / "models" / "yolov8s.pt")
        _detector = HumanDetector(path, conf_threshold=0.45, device="cpu")
    return _detector


def index_item(db: Session, item: EvidenceItem, data: Optional[bytes] = None) -> int:
    import cv2
    from backend.services import case_evidence
    from backend.services.face_grouping import _frames
    from backend.utils.at_rest import seal
    from core.analysis.appearance import clothing_colours
    if item.kind not in ("image", "snapshot", "video"):
        return 0
    data = data if data is not None else case_evidence.read(item)
    db.query(EvidencePerson).filter(EvidencePerson.item_id == item.id).delete()
    det = _people_detector()
    n = 0
    for t, frame in _frames(item, data):
        h, w = frame.shape[:2]
        for box, _conf, _cls in det.detect(frame):
            x1, y1, x2, y2 = [int(v) for v in box]
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if y2 - y1 < MIN_HEIGHT_PX or x2 <= x1:
                continue
            crop = frame[y1:y2, x1:x2]
            upper, lower = clothing_colours(crop)
            thumb = cv2.resize(crop, (max(1, int(96 * (x2 - x1) / (y2 - y1))), 96))
            ok, jpg = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
            blob, enc = seal(jpg.tobytes()) if ok else (None, False)
            db.add(EvidencePerson(item_id=item.id, incident_id=item.incident_id, t_seconds=t, bbox=f"{x1},{y1},{x2},{y2}",
                                  upper_color=upper, lower_color=lower, crop=blob, crop_encrypted=enc))
            n += 1
    return n


def schedule(item_id: int) -> None:
    if not enabled():
        return

    def run():
        from backend.db.database import SessionLocal
        with _lock:
            db = SessionLocal()
            try:
                item = db.get(EvidenceItem, item_id)
                if item and not item.deleted_at:
                    index_item(db, item)
                db.commit()
            except Exception as e:  # noqa: BLE001 - search is a convenience; the evidence is fine
                logger.warning("appearance indexing failed for evidence %s: %s", item_id, e)
                db.rollback()
            finally:
                db.close()
    if os.getenv("FACE_GROUPING_SYNC", "").lower() in ("1", "true", "yes"):
        run()
    else:
        _executor.submit(run)


def search(db: Session, incident_id: int, upper: Optional[str], lower: Optional[str], limit: int = 200) -> list:
    q = db.query(EvidencePerson, EvidenceItem.ref, EvidenceItem.kind).join(EvidenceItem, EvidenceItem.id == EvidencePerson.item_id) \
        .filter(EvidencePerson.incident_id == incident_id, EvidenceItem.deleted_at.is_(None))
    if upper:
        q = q.filter(EvidencePerson.upper_color == upper)
    if lower:
        q = q.filter(EvidencePerson.lower_color == lower)
    return [{"id": p.id, "ref": ref, "kind": kind, "t_seconds": p.t_seconds, "upper": p.upper_color, "lower": p.lower_color,
             "bbox": [int(v) for v in p.bbox.split(",")]}
            for p, ref, kind in q.order_by(EvidencePerson.item_id, EvidencePerson.t_seconds).limit(limit)]


def colours_in_case(db: Session, incident_id: int) -> dict:
    from collections import Counter
    rows = db.query(EvidencePerson.upper_color, EvidencePerson.lower_color).filter(EvidencePerson.incident_id == incident_id).all()
    return {"people": len(rows), "upper": Counter(u for u, _ in rows if u), "lower": Counter(lw for _, lw in rows if lw)}
