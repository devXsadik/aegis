"""Face matcher: live faces against the PERSON watchlist (approved, unexpired entries only).

  quality gate → embedding → vector index → similarity ≥ possible threshold?
     yes: FACE_MATCH alert "Possible match — needs verification" (critical above the alert
          threshold, medium between); the crop and embedding are kept with the alert
     no : nothing is kept — the detection row is deleted, the embedding never stored, the
          crop never written. Faces of people not on the watchlist are not identities here.
An operator must confirm or reject before any field action (review-required alert type)."""

from __future__ import annotations

import logging
from typing import List

import numpy as np
from sqlalchemy.orm import Session

from backend.models.detection import Detection
from backend.models.known_person import KnownPerson
from backend.models.person_image import PersonImage
from backend.services import event_router
from backend.services.event_router import _crop_bytes
from backend.services.face_index import INDEX
from backend.services.matching.common import camera, dispatch_sync
from backend.utils.at_rest import seal
from core.ingest.events import NormalizedEvent
from core.recognition import embedder, quality

logger = logging.getLogger("HumanAnalysis")


def _decode(b64: str):
    import cv2
    data = _crop_bytes(b64)
    if not data:
        return None, None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return img, data


def match_face(db: Session, ev: NormalizedEvent, det: Detection) -> List[dict]:
    from backend.api.config_routes import threshold
    emb = embedder.get()
    img, raw = _decode(ev.crop_image) if ev.crop_image else (None, None)
    vec = ev.vector()
    model = ev.embedding_model or emb.name
    q_score, reasons = ev.quality, []
    if img is not None:
        row = emb.detect(img) if hasattr(emb, "detect") and emb.available() else None
        ok, q_score, reasons = quality.check(img, row)
        if not ok:
            db.delete(det)
            return [{"kind": "face", "dropped": "quality", "reasons": reasons}]
        if vec is None and emb.available():
            vec, model = emb.embed(img, row), emb.name
    if vec is None:
        db.delete(det)
        return [{"kind": "face", "dropped": "no embedding (model not installed and none sent)"}]

    hits = INDEX.search(db, vec, model, k=3)
    possible, alert_at = threshold(db, "face_possible_similarity"), threshold(db, "face_alert_similarity")
    if not hits or hits[0][1] < possible:
        db.delete(det)                         # not on the watchlist: keep nothing about this face
        return []
    pid, sim = hits[0]
    person = db.query(KnownPerson).filter(KnownPerson.person_id == pid).first()
    det.matched, det.match_ref = True, pid
    if raw:
        det.crop, det.crop_encrypted = seal(raw)
    det.embedding, det.embedding_model = embedder.to_bytes(vec), model
    db.flush()
    photos = [i for (i,) in db.query(PersonImage.id).filter(PersonImage.person_id == person.id).order_by(PersonImage.id).limit(4)]
    severity = "critical" if sim >= alert_at else "medium"
    cam = camera(db, ev.camera_id)
    extra = {"face": {"person_id": pid, "name": person.name, "similarity": round(sim, 3), "alert_threshold": alert_at,
                      "possible_threshold": possible, "quality": q_score, "model": model,
                      "crop_url": f"/api/v1/detections/{det.id}/crop" if raw else None,
                      "watch_photos": [f"/api/v1/faces/images/{i}" for i in photos],
                      "others": [{"person_id": p, "similarity": round(s, 3)} for p, s in hits[1:]],
                      "case_no": person.case_no, "risk_level": person.risk_level, "offence": person.offence},
             "detection_id": det.id, "direction": ev.direction}
    res = dispatch_sync(db=db, alert_type="FACE_MATCH", severity=severity, camera_id=ev.camera_id,
                        camera_location=(cam.location or cam.name) if cam else ev.camera_id, person_name=pid,
                        message=f"Possible match — needs verification: {person.name} ({round(sim * 100)}%) at "
                                f"{cam.name if cam else ev.camera_id}",
                        confidence=sim, extra=extra)
    det.alert_id = res.get("alert_id")
    return [{"kind": "face", "person_id": pid, "similarity": round(sim, 3), "severity": severity,
             "alert_id": res.get("alert_id"), "status": res.get("status")}]


event_router.register("face", match_face)
