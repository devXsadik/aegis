"""Vehicle matcher: every vehicle event is scored against the active vehicle watchlist and
the lookouts on its camera (core/analysis/vehicle_match.py). The best hit raises one
VEHICLE_MATCH (or LOOKOUT_MATCH) alert that an operator must confirm or reject."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.models.detection import Detection
from backend.models.watchlist import WatchlistVehicle
from backend.services import event_router, lookout
from backend.services.matching.common import camera, dispatch_sync, load_json_config
from backend.services.watchlist_gov import active_vehicles
from core.analysis import vehicle_attrs, vehicle_match
from core.ingest.events import NormalizedEvent

logger = logging.getLogger("HumanAnalysis")
CONFIG_KEY = "vehicle_match"
RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def config(db: Session) -> dict:
    return vehicle_match.merge_config(load_json_config(db, CONFIG_KEY))


def _decode_crop(det: Detection):
    if not det.crop:
        return None
    from backend.utils.at_rest import unseal
    import cv2
    data = unseal(det.crop, det.crop_encrypted)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    return img


def _entry(v: WatchlistVehicle) -> dict:
    return {"plate": v.plate_raw, "vehicle_type": v.vehicle_type, "color_primary": v.color_primary,
            "color_secondary": v.color_secondary, "make_model": v.make_model}


def _reid(vec: Optional[np.ndarray], v) -> Optional[float]:
    if vec is None:
        return None
    best = None
    for ph in getattr(v, "photos", []) or []:
        if not ph.embedding:
            continue
        e = np.frombuffer(ph.embedding, dtype=np.float32)
        c = vehicle_attrs.cosine(vec, e)
        if c is not None and (best is None or c > best):
            best = c
    return best


def enrich(ev: NormalizedEvent, det: Detection) -> tuple:
    """Fill attributes the camera did not send from the crop (baseline / trained model), and
    get a re-ID vector. Returns (read dict, night flag, vector)."""
    crop = _decode_crop(det)
    conf = dict(ev.attribute_confidences or {})
    read = {"plate_text": ev.plate_text, "vehicle_type": ev.vehicle_type, "color": ev.color,
            "make_model": ev.make_model, "confidences": conf}
    night = bool(ev.is_night)
    vec = ev.vector()
    if crop is not None:
        night = night or vehicle_attrs.is_night(crop)
        if not (ev.color and ev.vehicle_type):
            got = vehicle_attrs.classify(crop, ev.extra.get("detector_class"), ev.extra.get("detector_conf"))
            for k, ck in (("vehicle_type", "type"), ("color", "color"), ("make_model", "model")):
                if not read.get(k) and got.get(k):
                    read[k] = got[k]
                    if ck in got["confidences"]:
                        conf[ck] = got["confidences"][ck]
            det.vehicle_type = det.vehicle_type or read["vehicle_type"]
            det.color = det.color or read["color"]
            det.make_model = det.make_model or read["make_model"]
        if vec is None:
            vec, model = vehicle_attrs.reid_embedding(crop)
            det.embedding, det.embedding_model = vec.tobytes(), model
    if ev.plate_confidence is not None:
        conf.setdefault("plate", ev.plate_confidence)
    det.color_reliable = not night
    det.attr_conf = json.dumps(conf) if conf else det.attr_conf
    return read, night, vec


def match_vehicle(db: Session, ev: NormalizedEvent, det: Detection) -> List[dict]:
    cfg = config(db)
    read, night, vec = enrich(ev, det)
    bolos = lookout.active_for_camera(db, ev.camera_id, kind="vehicle")
    best = None
    for v in active_vehicles(db):
        r = vehicle_match.score({**read, "reid": _reid(vec, v)}, _entry(v), cfg, night=night,
                                lookout=bool(lookout.covers(bolos, v.ref)))
        if r.level and (best is None or (RANK[r.severity], r.score) > (RANK[best[1].severity], best[1].score)):
            best = (v, r, lookout.covers(bolos, v.ref))
    # General lookouts (from Vehicle Search: "white Axio around Gulshan"), not tied to an entry.
    for b in bolos:
        if b.target_ref:
            continue
        try:
            target = json.loads(b.payload or "{}")
        except ValueError:
            continue
        r = vehicle_match.score({**read, "reid": None}, target, {**cfg, "candidate_requires_reid": False},
                                night=night, lookout=True)
        if r.level and (best is None or (RANK[r.severity], r.score) > (RANK[best[1].severity], best[1].score)):
            best = (None, r, b)
    if not best:
        return []
    v, r, bolo = best
    det.matched, det.match_ref = True, (v.ref if v else bolo.ref)
    cam = camera(db, ev.camera_id)
    crop_url = f"/api/v1/detections/{det.id}/crop" if det.crop else None
    extra = {
        "match": r.as_dict(), "detection_id": det.id, "crop_url": crop_url, "direction": ev.direction,
        "night": night, "read": {k: read.get(k) for k in ("plate_text", "vehicle_type", "color", "make_model")},
        "confidences": read.get("confidences"),
        "watch": ({"ref": v.ref, "plate": v.plate_raw, "plate_canonical": v.plate_canonical, "vehicle_type": v.vehicle_type,
                   "color_primary": v.color_primary, "color_secondary": v.color_secondary, "make_model": v.make_model,
                   "case_no": v.case_no, "risk_level": v.risk_level} if v else None),
        "bolo": bolo.ref if bolo else None,
    }
    label = r.label + ("" if v else " (lookout)")
    plate_shown = v.plate_raw if v and v.plate_raw else (read.get("plate_text") or "no plate")
    msg = f"{label}: {plate_shown} at {cam.name if cam else ev.camera_id} — needs verification"
    res = dispatch_sync(db=db, alert_type="VEHICLE_MATCH" if v else "LOOKOUT_MATCH", severity=r.severity,
                        camera_id=ev.camera_id, camera_location=(cam.location or cam.name) if cam else ev.camera_id,
                        plate_number=(v.plate_canonical or v.ref) if v else bolo.ref, message=msg,
                        confidence=r.score, extra=extra)
    det.alert_id = res.get("alert_id")
    return [{"kind": "vehicle", "level": r.level, "severity": r.severity, "ref": det.match_ref,
             "alert_id": res.get("alert_id"), "status": res.get("status")}]


event_router.register("vehicle", match_vehicle)


def embed_photo(data: bytes) -> Optional[bytes]:
    """Re-ID vector for a watchlist photo (stored next to it)."""
    import cv2
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    vec, _ = vehicle_attrs.reid_embedding(img)
    return vec.tobytes() if vec is not None else None
