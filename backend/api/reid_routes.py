"""Cross-camera re-identification — same person / plate across cameras."""

from collections import defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.db.database import get_db
from backend.models.user import User
from backend.models.evidence import Evidence
from backend.models.alert import Alert
from backend.models.vehicle import VehicleDetection
from backend.auth.auth import operator_or_admin
from clock import utcnow

router = APIRouter(prefix="/reid", tags=["reid"])


@router.get("/persons")
def person_tracks(
    hours: int = 24,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """
    Group detections of the same person_name across cameras.
    Uses identity labels from the face recognizer (watchlist matches).
    """
    cutoff = utcnow() - timedelta(hours=hours)
    q = db.query(Evidence).filter(
        Evidence.timestamp >= cutoff,
        Evidence.person_name.isnot(None),
        Evidence.person_name != "Unknown",
    )
    if name:
        q = q.filter(Evidence.person_name.ilike(f"%{name}%"))
    rows = q.order_by(desc(Evidence.timestamp)).limit(500).all()

    by_person = defaultdict(list)
    for r in rows:
        by_person[r.person_name].append({
            "evidence_id": r.id,
            "camera": r.camera_location,
            "camera_id": r.camera_id,
            "track_id": r.track_id,
            "category": r.category,
            "is_criminal": r.is_criminal,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "has_image": bool(r.frame_data),
        })

    tracks = []
    for person, sightings in by_person.items():
        cameras = sorted({s["camera"] or s["camera_id"] or "?" for s in sightings})
        tracks.append({
            "person_name": person,
            "sightings": len(sightings),
            "cameras": cameras,
            "cross_camera": len(cameras) > 1,
            "first_seen": sightings[-1]["timestamp"] if sightings else None,
            "last_seen": sightings[0]["timestamp"] if sightings else None,
            "path": sightings[:20],
        })
    tracks.sort(key=lambda t: (not t["cross_camera"], -t["sightings"]))
    return {"period_hours": hours, "persons": tracks}


VISIT_GAP_SECONDS = 120     # sightings on one camera closer than this are one visit
SOURCE_LABEL = {"face": "Face match", "appearance": "Look-alike (clothing, build)", "capture": "Capture"}


def _visits(sightings: list) -> list:
    """Chronological sightings -> visits: one per stretch of time on one camera."""
    out = []
    for s in sightings:
        last = out[-1] if out else None
        if last and last["camera_id"] == s["camera_id"] and (s["at"] - last["_to"]).total_seconds() <= VISIT_GAP_SECONDS:
            last["_to"] = s["at"]
            last["count"] += 1
            last["sources"].add(s["source"])
            last["image"] = last["image"] or s["image"]
            continue
        out.append({"camera_id": s["camera_id"], "camera": s["camera"], "_from": s["at"], "_to": s["at"],
                    "count": 1, "sources": {s["source"]}, "image": s["image"]})
    for v in out:
        v["from"], v["to"] = v.pop("_from").isoformat(), v.pop("_to").isoformat()
        v["sources"] = sorted(SOURCE_LABEL[x] for x in v["sources"])
    return out


@router.get("/persons/{person_name}")
def person_journey(
    person_name: str,
    hours: int = 72,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """Where was this person? Face matches, look-alike tracking and capture stills, merged into
    visits per camera in time order, with each camera's position for the map."""
    from backend.models.camera import Camera
    from backend.models.capture import AlertCapture

    cutoff = utcnow() - timedelta(hours=min(max(hours, 1), 24 * 30))
    sightings = []
    for e in db.query(Evidence).filter(Evidence.person_name == person_name, Evidence.timestamp >= cutoff):
        sightings.append({"at": e.timestamp, "camera_id": e.camera_id or e.camera_location, "camera": e.camera_location,
                          "source": "face", "image": {"kind": "evidence", "id": e.id} if e.frame_data else None})
    for a in db.query(Alert).filter(Alert.person_name == person_name, Alert.timestamp >= cutoff,
                                    Alert.alert_type.in_(["CRIMINAL_DETECTED", "PERSON_TRACKED"])):
        sightings.append({"at": a.timestamp, "camera_id": a.camera_id or a.camera_location, "camera": a.camera_location,
                          "source": "face" if a.alert_type == "CRIMINAL_DETECTED" else "appearance", "image": None})
    for c in db.query(AlertCapture).filter(AlertCapture.person_name == person_name, AlertCapture.timestamp >= cutoff):
        sightings.append({"at": c.timestamp, "camera_id": c.camera_id or c.camera_location,
                          "camera": c.camera_name or c.camera_location, "source": "capture",
                          "image": {"kind": "capture", "id": c.id}})
    for s in sightings:
        s["at"] = s["at"].replace(tzinfo=None)
    sightings.sort(key=lambda s: s["at"])

    visits = _visits(sightings)
    ids = {v["camera_id"] for v in visits}
    cams = {c.camera_id: c for c in db.query(Camera).filter(Camera.camera_id.in_(ids))} if ids else {}
    for v in visits:
        c = cams.get(v["camera_id"])
        v["camera"] = (c.name if c and c.name else None) or v["camera"] or v["camera_id"]
        v["lat"], v["lng"] = (c.lat, c.lng) if c else (None, None)
    return {
        "person_name": person_name,
        "period_hours": hours,
        "sightings": len(sightings),
        "cameras": sorted({v["camera"] for v in visits}),
        "visits": visits,
    }


@router.get("/vehicles")
def vehicle_tracks(
    hours: int = 24,
    plate: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = utcnow() - timedelta(hours=hours)
    q = db.query(VehicleDetection).filter(VehicleDetection.timestamp >= cutoff)
    if plate:
        q = q.filter(VehicleDetection.license_plate.ilike(f"%{plate}%"))
    rows = q.order_by(desc(VehicleDetection.timestamp)).limit(500).all()

    by_plate = defaultdict(list)
    for r in rows:
        key = (r.license_plate or "UNKNOWN").upper()
        by_plate[key].append({
            "id": r.id,
            "camera": r.camera_location,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "is_suspicious": r.is_suspicious,
            "vehicle_type": r.vehicle_type,
        })

    tracks = []
    for p, sightings in by_plate.items():
        cams = sorted({str(s["camera"] or "?") for s in sightings})
        tracks.append({
            "plate_number": p,
            "sightings": len(sightings),
            "cameras": cams,
            "cross_camera": len(cams) > 1,
            "path": sightings[:20],
        })
    tracks.sort(key=lambda t: (not t["cross_camera"], -t["sightings"]))
    return {"period_hours": hours, "vehicles": tracks}

