"""Multi-camera tracking (spec 9.2–9.5).

  sighting of a watchlisted target ─► cross-camera track (one per target, tied to ONE incident)
        │  hop: camera, time, direction, method, plausibility of the travel time
        ├─► if it came from a lookout: lookout re-acquired, HANDOFF on the incident timeline
        └─► direction known: predict the next cameras (graph neighbours inside the direction cone,
            ranked by bearing match then distance) → automatic lookout with an ETA window per camera,
            cameras boosted, officers of those areas told "target heading towards your area"
  lookout window passes without a sighting ─► second ring of neighbours, wider window
  still nothing after MAX_RING ─► track LOST, operator told

Human in the loop: officers are notified about a target only after an operator confirmed one of
its alerts (track.verified). Tracking itself (lookouts, camera priority) runs from the first hit."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.alert import Alert
from backend.models.bolo import Bolo, BoloCamera
from backend.models.camera import Camera
from backend.models.incident import Incident, IncidentAssignment
from backend.models.tracking import CameraEdge, CrossCameraTrack, TrackHop
from backend.services import geo
from backend.services.incident_service import add_event
from clock import utcnow

logger = logging.getLogger("HumanAnalysis")

CONE_DEG = float(os.getenv("TRACK_CONE_DEG", "60"))          # ± around the direction of travel
MAX_RING = int(os.getenv("TRACK_MAX_RING", "2"))
TRACK_IDLE_MIN = float(os.getenv("TRACK_IDLE_MINUTES", "120"))
URBAN_SPEED_MS = float(os.getenv("TRACK_SPEED_KMH", "25")) / 3.6
MAX_SPEED_MS = float(os.getenv("TRACK_MAX_SPEED_KMH", "140")) / 3.6
NEIGHBOUR_KM = float(os.getenv("TRACK_NEIGHBOUR_KM", "3"))
MIN_WINDOW_S = 120


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


# ——— graph ———

def suggest_edges(db: Session, max_km: float = NEIGHBOUR_KM, k: int = 4, replace_auto: bool = True) -> int:
    """Link each camera to its k nearest cameras within max_km (both ways). Admin-made edges stay."""
    cams = [c for c in db.query(Camera).filter(Camera.lat.isnot(None), Camera.lng.isnot(None))]
    if replace_auto:
        db.query(CameraEdge).filter(CameraEdge.auto_suggested == True).delete()  # noqa: E712
    have = {(e.from_camera, e.to_camera) for e in db.query(CameraEdge)}
    made = 0
    for a in cams:
        near = sorted(((geo.haversine_m(a.lat, a.lng, b.lat, b.lng), b) for b in cams if b.camera_id != a.camera_id),
                      key=lambda x: x[0])
        for d, b in near[:k]:
            if d > max_km * 1000 or (a.camera_id, b.camera_id) in have or (b.camera_id, a.camera_id) in have:
                continue
            db.add(CameraEdge(from_camera=a.camera_id, to_camera=b.camera_id, distance_m=round(d, 1),
                              travel_s=round(d * 1.3 / URBAN_SPEED_MS, 1),     # roads are ~30 % longer than straight
                              bearing_deg=round(geo.bearing_deg(a.lat, a.lng, b.lat, b.lng), 1),
                              bidirectional=True, auto_suggested=True))
            have.add((a.camera_id, b.camera_id))
            made += 1
    db.flush()
    return made


def neighbours(db: Session, camera_id: str) -> List[dict]:
    """[{camera_id, distance_m, travel_s, bearing_deg}] leaving `camera_id` (edges are two-way unless marked)."""
    out = []
    for e in db.query(CameraEdge).filter(or_(CameraEdge.from_camera == camera_id,
                                             (CameraEdge.to_camera == camera_id) & (CameraEdge.bidirectional == True))):  # noqa: E712
        if e.from_camera == camera_id:
            out.append({"camera_id": e.to_camera, "distance_m": e.distance_m, "travel_s": e.travel_s, "bearing_deg": e.bearing_deg})
        else:
            back = (e.bearing_deg + 180) % 360 if e.bearing_deg is not None else None
            out.append({"camera_id": e.from_camera, "distance_m": e.distance_m, "travel_s": e.travel_s, "bearing_deg": back})
    return out


def predict_next(db: Session, from_camera: str, bearing: Optional[float], exclude: Iterable[str] = (),
                 cone: float = CONE_DEG) -> List[dict]:
    """Neighbours inside the direction cone, best bearing match first, then nearest; with ETA window."""
    skip = set(exclude) | {from_camera}
    cands = []
    for n in neighbours(db, from_camera):
        if n["camera_id"] in skip:
            continue
        diff = geo.angle_diff(bearing, n["bearing_deg"]) if bearing is not None and n["bearing_deg"] is not None else None
        if bearing is not None and (diff is None or diff > cone):
            continue
        t = n["travel_s"] or (n["distance_m"] / URBAN_SPEED_MS)
        cands.append({**n, "bearing_diff": round(diff, 1) if diff is not None else None,
                      "eta_from_s": round(max(0.0, t * 0.5), 1), "eta_to_s": round(max(MIN_WINDOW_S, t * 2.0), 1)})
    cands.sort(key=lambda c: ((c["bearing_diff"] or 0) // 15, c["distance_m"]))
    for i, c in enumerate(cands):
        c["rank"] = i
    return cands


# ——— tracks ———

def active_track(db: Session, kind: str, target_ref: str) -> Optional[CrossCameraTrack]:
    cutoff = utcnow() - timedelta(minutes=TRACK_IDLE_MIN)
    return (db.query(CrossCameraTrack)
            .filter(CrossCameraTrack.kind == kind, CrossCameraTrack.target_ref == target_ref,
                    CrossCameraTrack.status == "active", CrossCameraTrack.last_seen >= cutoff)
            .order_by(CrossCameraTrack.id.desc()).first())


def _cam(db: Session, camera_id: str) -> Optional[Camera]:
    return db.query(Camera).filter(Camera.camera_id == camera_id).first()


def _label(target: dict) -> str:
    return target.get("name") or target.get("plate") or target.get("ref") or "Target"


def on_sighting(db: Session, *, kind: str, target_ref: str, target: dict, camera_id: str, ts: datetime,
                direction: Optional[str] = None, bearing: Optional[float] = None, method: str = "",
                confidence: Optional[float] = None, detection_id: Optional[int] = None,
                alert_id: Optional[int] = None, incident_id: Optional[int] = None) -> CrossCameraTrack:
    """Record one sighting of a watchlisted target and do the handoff."""
    ts = _naive(ts)
    if bearing is None and direction:
        bearing = {d: i * 45.0 for i, d in enumerate(geo.COMPASS_8)}.get(direction)
    track = active_track(db, kind, target_ref)
    if track is not None and track.last_camera == camera_id and track.last_seen \
            and (ts - _naive(track.last_seen)).total_seconds() < 60:
        track.last_seen = max(ts, _naive(track.last_seen))        # still in view: no new hop
        if direction:
            track.direction, track.bearing = direction, bearing
        return track
    if track is None:
        track = CrossCameraTrack(kind=kind, target_ref=target_ref, incident_id=incident_id, status="active")
        db.add(track)
        db.flush()
    if incident_id and not track.incident_id:
        track.incident_id = incident_id
    consistent, note = True, None
    if track.last_camera and track.last_camera != camera_id and track.last_seen:
        a, b = _cam(db, track.last_camera), _cam(db, camera_id)
        dt = (ts - _naive(track.last_seen)).total_seconds()
        if a and b and a.lat is not None and b.lat is not None and dt > 0:
            speed = geo.haversine_m(a.lat, a.lng, b.lat, b.lng) / dt
            if speed > MAX_SPEED_MS:
                consistent, note = False, f"implausible travel: {speed * 3.6:.0f} km/h from {track.last_camera}"
    bolo = _reacquired(db, track, kind, target_ref, camera_id, ts)
    db.add(TrackHop(track_id=track.id, camera_id=camera_id, seen_at=ts, direction=direction, bearing=bearing, method=method,
                    confidence=confidence, detection_id=detection_id, alert_id=alert_id,
                    bolo_ref=bolo.ref if bolo else None, consistent=consistent, note=note))
    moved = track.last_camera is not None and track.last_camera != camera_id
    track.last_camera, track.last_seen = camera_id, ts
    if direction:
        track.direction, track.bearing = direction, bearing
    db.flush()
    inc = db.get(Incident, track.incident_id) if track.incident_id else None
    if inc and moved:
        cam = _cam(db, camera_id)
        add_event(db, inc, "HANDOFF", f"{_label(target)} seen at {cam.name if cam else camera_id}"
                  + (f", moving {direction}" if direction else "") + (f" (lookout {bolo.ref})" if bolo else "")
                  + ("" if consistent else f" — {note}"), "SYSTEM", camera_id=camera_id,
                  payload={"track_id": track.id, "direction": direction, "bolo": bolo.ref if bolo else None,
                           "consistent": consistent, "alert_id": alert_id})
        inc.cross_track_id = track.id
    predicted = []
    if direction and bearing is not None:
        predicted = start_lookout(db, track, kind, target_ref, target, camera_id, direction, bearing, ts)
    if track.verified:
        notify_step(db, track, target, camera_id, direction, predicted, alert_id)
    return track


def _reacquired(db, track, kind, target_ref, camera_id, ts) -> Optional[Bolo]:
    bolo = (db.query(Bolo).join(BoloCamera).filter(Bolo.status == "active", Bolo.kind == kind,
                                                   Bolo.target_ref == target_ref, BoloCamera.camera_id == camera_id)
            .order_by(Bolo.id.desc()).first())
    if bolo:
        bolo.status, bolo.found_camera, bolo.found_at = "reacquired", camera_id, ts
        _unboost(db, [c.camera_id for c in bolo.cameras])
    return bolo


def _unboost(db, camera_ids):
    from backend.api.lookout_routes import boost
    db.flush()
    boost(db, camera_ids, False)


def start_lookout(db: Session, track: CrossCameraTrack, kind: str, target_ref: str, target: dict, from_camera: str,
                  direction: str, bearing: float, ts: datetime, ring: int = 1, exclude: Iterable[str] = ()) -> List[dict]:
    """Automatic lookout on the cameras the target is heading to. Older automatic lookouts for this
    track end (a newer position supersedes them)."""
    for old in db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active", Bolo.origin == "auto"):
        old.status = "cancelled"
        _unboost(db, [c.camera_id for c in old.cameras])
    nxt = predict_next(db, from_camera, bearing, exclude=exclude)
    if not nxt:
        return []
    window_end = ts + timedelta(seconds=max(c["eta_to_s"] for c in nxt))
    b = Bolo(ref=f"B-{uuid.uuid4().hex[:8].upper()}", kind=kind, target_ref=target_ref, origin="auto",
             payload=json.dumps({k: v for k, v in target.items() if k in ("plate", "vehicle_type", "color_primary",
                                                                         "make_model", "name")}, ensure_ascii=False),
             origin_camera=from_camera, direction=direction, heading_deg=bearing, incident_id=track.incident_id,
             cross_track_id=track.id, ring=ring, window_start=ts, window_end=window_end, status="active",
             reason=f"Auto handoff from {from_camera}")
    for c in nxt:
        b.cameras.append(BoloCamera(camera_id=c["camera_id"], rank=c["rank"], ring=ring, eta_from_s=c["eta_from_s"],
                                    eta_to_s=c["eta_to_s"], distance_m=c["distance_m"]))
    db.add(b)
    db.flush()
    from backend.api.lookout_routes import boost
    boost(db, [c["camera_id"] for c in nxt], True)
    inc = db.get(Incident, track.incident_id) if track.incident_id else None
    if inc:
        names = ", ".join(c["camera_id"] for c in nxt[:4])
        add_event(db, inc, "BOLO", f"Lookout {b.ref} (ring {ring}) on {len(nxt)} camera(s) towards {direction}: {names}",
                  "SYSTEM", camera_id=from_camera, payload={"bolo": b.ref, "cameras": [c["camera_id"] for c in nxt],
                                                            "ring": ring, "window_end": window_end.isoformat()})
    return nxt


# ——— notifications (9.5) ———

def _area_officers(db: Session, camera_id: str) -> Set[int]:
    from backend.services.jurisdiction import eligible_officers
    res = eligible_officers(db, camera_id=camera_id)
    return {o["id"] for o in res["officers"] if o["duty_status"] != "off_duty"}


def notify_step(db: Session, track: CrossCameraTrack, target: dict, camera_id: str, direction: Optional[str],
                predicted: List[dict], alert_id: Optional[int]) -> None:
    from backend.services.notify import notify
    cam = _cam(db, camera_id)
    where = cam.name if cam else camera_id
    toward = ""
    if predicted:
        first = _cam(db, predicted[0]["camera_id"])
        eta_min = max(1, round(predicted[0]["eta_from_s"] * 2 / 60))
        toward = f" towards {first.name if first else predicted[0]['camera_id']}, ETA ~{eta_min} min"
    title = f"{_label(target)} detected at {where}" + (f", moving {direction}" if direction else "")
    payload = {"camera_id": camera_id, "camera": where, "lat": cam.lat if cam else None, "lng": cam.lng if cam else None,
               "direction": direction, "next": [p["camera_id"] for p in predicted[:3]], "snapshot": target.get("snapshot"),
               "map": f"/#/map?incident={track.incident_id}" if track.incident_id else None, "track_id": track.id}
    assigned = {a.user_id for a in db.query(IncidentAssignment).filter(IncidentAssignment.incident_id == track.incident_id)} \
        if track.incident_id else set()
    here = _area_officers(db, camera_id) | assigned
    notify(db, here, kind="target_detected", title=title, body=f"{title}{toward}.", priority="critical",
           incident_id=track.incident_id, alert_id=alert_id, payload=payload,
           dedup_key=f"seen:{track.id}:{camera_id}", sms=True)
    ahead: Set[int] = set()
    for p in predicted[:4]:
        ahead |= _area_officers(db, p["camera_id"])
    ahead -= here
    if ahead:
        notify(db, ahead, kind="heading_to_area", title=f"{_label(target)} heading towards your area",
               body=f"Last seen at {where}" + (f", moving {direction}" if direction else "") + f"{toward}.",
               priority="high", incident_id=track.incident_id, alert_id=alert_id, payload=payload,
               dedup_key=f"ahead:{track.id}:{camera_id}")


def on_alert_confirmed(db: Session, alert: Alert) -> Optional[CrossCameraTrack]:
    """An operator confirmed an identification alert: the track is verified, officers get told."""
    hop = db.query(TrackHop).filter(TrackHop.alert_id == alert.id).first()
    if not hop:
        return None
    track = hop.track
    newly = not track.verified
    track.verified = True
    inc = db.get(Incident, track.incident_id) if track.incident_id else None
    if inc and inc.status in ("new", "acknowledged", "open"):
        add_event(db, inc, "VERIFIED", f"Operator confirmed the match (alert #{alert.id})", "SYSTEM",
                  payload={"from": inc.status, "to": "verified_match", "alert_id": alert.id})
        inc.status = "verified_match"
    if newly:
        target = _target_info(db, track)
        bolo = (db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active")
                .order_by(Bolo.id.desc()).first())
        predicted = [{"camera_id": c.camera_id, "eta_from_s": c.eta_from_s or 0} for c in sorted(bolo.cameras, key=lambda c: c.rank)] if bolo else []
        notify_step(db, track, target, track.last_camera or hop.camera_id, track.direction, predicted, alert.id)
    return track


def _target_info(db: Session, track: CrossCameraTrack) -> dict:
    if track.kind == "vehicle":
        from backend.models.watchlist import WatchlistVehicle
        v = db.query(WatchlistVehicle).filter(WatchlistVehicle.ref == track.target_ref).first()
        return {"ref": track.target_ref, "plate": v.plate_raw if v else None,
                "vehicle_type": v.vehicle_type if v else None, "color_primary": v.color_primary if v else None,
                "make_model": v.make_model if v else None}
    from backend.models.known_person import KnownPerson
    p = db.query(KnownPerson).filter(KnownPerson.person_id == track.target_ref).first()
    return {"ref": track.target_ref, "name": p.name if p else track.target_ref}


# ——— lookout sweep (expand → lost) ———

def sweep(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or utcnow()
    out = {"expanded": 0, "lost": 0, "expired": 0}
    for b in db.query(Bolo).filter(Bolo.status == "active", Bolo.window_end < now).all():
        if b.origin != "auto" or not b.cross_track_id:
            b.status = "expired"
            _unboost(db, [c.camera_id for c in b.cameras])
            out["expired"] += 1
            continue
        track = db.get(CrossCameraTrack, b.cross_track_id)
        tried = {c.camera_id for c in b.cameras} | {b.origin_camera}
        b.status = "expired"
        _unboost(db, [c.camera_id for c in b.cameras])
        if b.ring < MAX_RING and track and track.status == "active":
            ring_cams: List[dict] = []
            for c in b.cameras:
                for n in predict_next(db, c.camera_id, b.heading_deg, exclude=tried, cone=CONE_DEG * 1.5):
                    if n["camera_id"] not in {x["camera_id"] for x in ring_cams}:
                        n["eta_from_s"] += c.eta_from_s or 0
                        n["eta_to_s"] = (n["eta_to_s"] + (c.eta_to_s or 0)) * 1.5      # window widens
                        ring_cams.append(n)
            if ring_cams:
                nb = Bolo(ref=f"B-{uuid.uuid4().hex[:8].upper()}", kind=b.kind, target_ref=b.target_ref, origin="auto",
                          payload=b.payload, origin_camera=b.origin_camera, direction=b.direction, heading_deg=b.heading_deg,
                          incident_id=b.incident_id, cross_track_id=b.cross_track_id, ring=b.ring + 1, window_start=now,
                          window_end=now + timedelta(seconds=max(c["eta_to_s"] for c in ring_cams)), status="active",
                          reason=f"Expanded from {b.ref}")
                for i, c in enumerate(sorted(ring_cams, key=lambda c: c["distance_m"])):
                    nb.cameras.append(BoloCamera(camera_id=c["camera_id"], rank=i, ring=b.ring + 1, eta_from_s=c["eta_from_s"],
                                                 eta_to_s=c["eta_to_s"], distance_m=c["distance_m"]))
                db.add(nb)
                db.flush()
                from backend.api.lookout_routes import boost
                boost(db, [c["camera_id"] for c in ring_cams], True)
                inc = db.get(Incident, b.incident_id) if b.incident_id else None
                if inc:
                    add_event(db, inc, "BOLO", f"Not re-acquired: lookout widened to ring {nb.ring} ({len(ring_cams)} camera(s))",
                              "SYSTEM", payload={"bolo": nb.ref, "ring": nb.ring})
                out["expanded"] += 1
                continue
        if track and track.status == "active":
            track.status = "lost"
            b.status = "lost"
            inc = db.get(Incident, b.incident_id) if b.incident_id else None
            if inc:
                add_event(db, inc, "BOLO", f"Track lost: not re-acquired after {b.ring} ring(s) of lookouts", "SYSTEM",
                          payload={"bolo": b.ref, "track_id": track.id})
            _notify_lost(db, track, inc)
            out["lost"] += 1
    db.flush()
    return out


def _notify_lost(db: Session, track: CrossCameraTrack, inc: Optional[Incident]) -> None:
    from backend.models.user import User
    from backend.services.notify import notify
    ops = [u.id for u in db.query(User).filter(User.role.in_(["operator", "supervisor"]), User.is_active == True)]  # noqa: E712
    if inc and inc.assigned_to:
        ops.append(inc.assigned_to)
    target = _target_info(db, track)
    notify(db, ops, kind="lost", title=f"Track lost: {_label(target)}",
           body=f"Last seen at {track.last_camera}" + (f" moving {track.direction}" if track.direction else "") + ".",
           priority="high", incident_id=track.incident_id, dedup_key=f"lost:{track.id}")


def trail(db: Session, incident_id: int) -> List[dict]:
    """Movement trail for the incident map: hops in time order with camera positions."""
    tracks = db.query(CrossCameraTrack).filter(CrossCameraTrack.incident_id == incident_id).all()
    cams = {c.camera_id: c for c in db.query(Camera)}
    pts = []
    for t in tracks:
        for h in t.hops:
            c = cams.get(h.camera_id)
            pts.append({"camera_id": h.camera_id, "label": c.name if c else h.camera_id, "lat": c.lat if c else None,
                        "lng": c.lng if c else None, "at": h.seen_at.isoformat() if h.seen_at else None,
                        "direction": h.direction, "consistent": h.consistent, "bolo": h.bolo_ref,
                        "alert_id": h.alert_id,
                        "snapshot": f"/api/v1/detections/{h.detection_id}/crop" if h.detection_id else None})
    pts.sort(key=lambda p: p["at"] or "")
    return pts
