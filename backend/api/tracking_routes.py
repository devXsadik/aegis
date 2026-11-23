"""Camera network graph, cross-camera tracks and personal notifications."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, get_current_user, operator_or_admin
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.tracking import CameraEdge, CrossCameraTrack, Notification
from backend.models.user import User
from backend.services import geo, tracking
from backend.services.audit import log_audit
from backend.services.notify import out as notification_out
from clock import utcnow

router = APIRouter(tags=["tracking"])


class EdgeIn(BaseModel):
    from_camera: str
    to_camera: str
    distance_m: Optional[float] = Field(default=None, gt=0)
    travel_s: Optional[float] = Field(default=None, gt=0)
    road_name: Optional[str] = Field(default=None, max_length=120)
    bidirectional: bool = True


def _edge_out(e: CameraEdge) -> dict:
    return {"id": e.id, "from_camera": e.from_camera, "to_camera": e.to_camera, "distance_m": e.distance_m,
            "travel_s": e.travel_s, "bearing_deg": e.bearing_deg, "road_name": e.road_name,
            "bidirectional": e.bidirectional, "auto_suggested": e.auto_suggested}


@router.get("/camera-graph")
def graph(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    cams = [{"camera_id": c.camera_id, "name": c.name, "lat": c.lat, "lng": c.lng, "heading": c.heading}
            for c in db.query(Camera).filter(Camera.lat.isnot(None))]
    return {"cameras": cams, "edges": [_edge_out(e) for e in db.query(CameraEdge)]}


@router.post("/camera-graph/suggest")
def suggest(request: Request, max_km: float = 3.0, k: int = 4, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    n = tracking.suggest_edges(db, max_km=max_km, k=k)
    log_audit(db, admin, "GRAPH_SUGGEST", "camera_graph", "", f"{n} edges (≤{max_km} km, k={k})", request)
    db.commit()
    return {"created": n}


@router.put("/camera-graph/edges")
def upsert_edge(body: EdgeIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    a = db.query(Camera).filter(Camera.camera_id == body.from_camera).first()
    b = db.query(Camera).filter(Camera.camera_id == body.to_camera).first()
    if not a or not b or a.camera_id == b.camera_id:
        raise HTTPException(400, "Two different, existing cameras are needed")
    dist = body.distance_m
    if dist is None:
        if a.lat is None or b.lat is None:
            raise HTTPException(400, "distance_m is required when a camera has no position")
        dist = geo.haversine_m(a.lat, a.lng, b.lat, b.lng) * 1.3
    e = db.query(CameraEdge).filter(CameraEdge.from_camera == a.camera_id, CameraEdge.to_camera == b.camera_id).first() \
        or CameraEdge(from_camera=a.camera_id, to_camera=b.camera_id)
    e.distance_m = round(dist, 1)
    e.travel_s = body.travel_s or round(dist / tracking.URBAN_SPEED_MS, 1)
    e.bearing_deg = round(geo.bearing_deg(a.lat, a.lng, b.lat, b.lng), 1) if a.lat is not None and b.lat is not None else None
    e.road_name, e.bidirectional, e.auto_suggested = body.road_name, body.bidirectional, False
    db.add(e)
    log_audit(db, admin, "GRAPH_EDGE", "camera_graph", f"{a.camera_id}->{b.camera_id}", f"{e.distance_m} m", request)
    db.commit()
    return _edge_out(e)


@router.delete("/camera-graph/edges/{edge_id}")
def delete_edge(edge_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    e = db.get(CameraEdge, edge_id)
    if not e:
        raise HTTPException(404, "Edge not found")
    log_audit(db, admin, "GRAPH_EDGE_DELETE", "camera_graph", f"{e.from_camera}->{e.to_camera}", "", request)
    db.delete(e)
    db.commit()
    return {"deleted": edge_id}


@router.get("/camera-graph/predict")
def predict(camera_id: str, direction: Optional[str] = None, bearing: Optional[float] = None,
            db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if bearing is None and direction:
        bearing = {d: i * 45.0 for i, d in enumerate(geo.COMPASS_8)}.get(direction.upper())
    return {"from": camera_id, "bearing": bearing, "next": tracking.predict_next(db, camera_id, bearing)}


@router.get("/tracks")
def tracks(status: Optional[str] = "active", db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    q = db.query(CrossCameraTrack)
    if status:
        q = q.filter(CrossCameraTrack.status == status)
    out = []
    for t in q.order_by(CrossCameraTrack.id.desc()).limit(100):
        out.append({"id": t.id, "kind": t.kind, "target_ref": t.target_ref, "incident_id": t.incident_id, "status": t.status,
                    "verified": t.verified, "last_camera": t.last_camera, "last_seen": t.last_seen, "direction": t.direction,
                    "trail": tracking.trail(db, t.incident_id) if t.incident_id else []})
    return out


# ——— notifications (personal) ———

class AckBody(BaseModel):
    state: str = Field(pattern="^(acknowledged|en_route|located|unable)$")
    note: Optional[str] = Field(default=None, max_length=300)


@router.get("/notifications/me")
def my_notifications(unacked: bool = False, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unacked:
        q = q.filter(Notification.acked_at.is_(None))
    return [notification_out(n) for n in q.order_by(Notification.id.desc()).limit(min(limit, 200))]


@router.post("/notifications/{nid}/ack")
def ack_notification(nid: int, body: AckBody, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    now = utcnow()
    n.ack_state, n.acked_at = body.state, n.acked_at or now
    n.read_at = n.read_at or now
    # The officer's answer also moves the incident (same rules as the incident page).
    if n.incident_id:
        from backend.models.incident import IncidentAssignment
        row = db.query(IncidentAssignment).filter(IncidentAssignment.incident_id == n.incident_id,
                                                  IncidentAssignment.user_id == user.id).first()
        if row is None and body.state in ("en_route", "located"):
            # An area officer who responds to a heads-up joins the incident.
            row = IncidentAssignment(incident_id=n.incident_id, user_id=user.id, state="assigned")
            db.add(row)
            db.flush()
    else:
        row = None
    log_audit(db, user, "NOTIFICATION_ACK", "notification", str(nid), body.state, request)
    db.commit()
    if n.incident_id and row is not None and body.state != "acknowledged":
        _officer_state(db, n.incident_id, user, body.state, body.note)
    return notification_out(n)


def _officer_state(db: Session, incident_id: int, user: User, state: str, note: Optional[str]) -> None:
    """Reuse the incident rule set: En route / Located / Unable from the officer's phone."""
    from backend.models.incident import Incident, IncidentAssignment
    from backend.services.incident_service import add_event
    from backend.services import incident_status as fsm
    inc = db.get(Incident, incident_id)
    row = db.query(IncidentAssignment).filter(IncidentAssignment.incident_id == incident_id,
                                              IncidentAssignment.user_id == user.id).first()
    if not inc or not row:
        return
    row.state = state
    add_event(db, inc, "OFFICER_STATE", f"{user.username}: {state.replace('_', ' ')}" + (f" — {note}" if note else ""),
              user.username, actor_id=user.id, payload={"state": state, "note": note, "via": "notification"})
    cur = fsm.normalize(inc.status)
    if state == "located" and "target_located" in fsm.TRANSITIONS.get(cur, []):
        add_event(db, inc, "STATUS", f"{cur} → target_located", user.username, payload={"from": cur, "to": "target_located", "auto": True})
        inc.status = "target_located"
    elif state == "en_route" and cur in ("new", "acknowledged", "verified_match"):
        add_event(db, inc, "STATUS", f"{cur} → officer_dispatched", user.username, payload={"from": cur, "to": "officer_dispatched", "auto": True})
        inc.status = "officer_dispatched"
    db.commit()


# ——— Command-centre map (spec 11) ———

@router.get("/map/command")
def command_map(jurisdiction_id: Optional[int] = None, hours: float = 2.0, db: Session = Depends(get_db),
                user: User = Depends(operator_or_admin)):
    """Everything the live map draws in one call: cameras coloured by status (and lookout),
    active target trails with direction and predicted next cameras, officer positions, recent
    alerts. Optional filter by area (division / district / thana)."""
    from datetime import timedelta as _td

    from backend.api.camera_registry_routes import camera_health
    from backend.api.system_routes import _pipeline_status
    from backend.models.alert import Alert
    from backend.models.bolo import Bolo, BoloCamera
    from backend.models.jurisdiction import OfficerProfile
    from backend.services.jurisdiction import _all, ancestors, locate

    cams = db.query(Camera).all()
    keep = None
    if jurisdiction_id:
        by_id = _all(db)
        inside = {j for j in by_id if jurisdiction_id in ancestors(j, by_id)}
        keep = set()
        for c in cams:
            jid = c.jurisdiction_id
            if jid is None and c.lat is not None:
                f = locate(db, c.lat, c.lng, by_id)
                jid = f.id if f else None
            if jid in inside:
                keep.add(c.camera_id)
    beats = _pipeline_status.get("cameras", {})
    lookout = {cid for (cid,) in db.query(BoloCamera.camera_id).join(Bolo).filter(Bolo.status == "active")}
    cam_rows = []
    pos = {}
    for c in cams:
        pos[c.camera_id] = (c.lat, c.lng, c.name)
        if c.lat is None or (keep is not None and c.camera_id not in keep):
            continue
        h = camera_health(c, beats.get(c.camera_id))
        cam_rows.append({**h, "fov": c.fov, "road_name": c.road_name, "on_lookout": c.camera_id in lookout})
    track_rows = []
    for t in db.query(CrossCameraTrack).filter(CrossCameraTrack.status == "active").order_by(CrossCameraTrack.id.desc()).limit(50):
        pts = tracking.trail(db, t.incident_id) if t.incident_id else []
        if keep is not None and not any(p["camera_id"] in keep for p in pts):
            continue
        b = (db.query(Bolo).filter(Bolo.cross_track_id == t.id, Bolo.status == "active").order_by(Bolo.id.desc()).first())
        predicted = []
        if b:
            for bc in sorted(b.cameras, key=lambda x: x.rank):
                lat, lng, name = pos.get(bc.camera_id, (None, None, bc.camera_id))
                predicted.append({"camera_id": bc.camera_id, "name": name, "lat": lat, "lng": lng, "ring": bc.ring,
                                  "eta_from_s": bc.eta_from_s, "eta_to_s": bc.eta_to_s})
        info = tracking._target_info(db, t)
        track_rows.append({"id": t.id, "kind": t.kind, "target_ref": t.target_ref, "label": info.get("name") or info.get("plate") or t.target_ref,
                           "incident_id": t.incident_id, "verified": t.verified, "direction": t.direction,
                           "last_camera": t.last_camera, "last_seen": t.last_seen, "trail": pts, "predicted": predicted,
                           "lookout": b.ref if b else None, "window_end": b.window_end if b else None})
    officers = []
    if user.role in ("admin", "supervisor", "operator"):
        since = utcnow() - _td(hours=12)
        for p in db.query(OfficerProfile).filter(OfficerProfile.last_lat.isnot(None), OfficerProfile.last_seen_at >= since):
            u = db.get(User, p.user_id)
            officers.append({"id": p.user_id, "name": p.full_name or (u.username if u else p.user_id), "rank": p.rank,
                             "duty_status": p.duty_status, "lat": p.last_lat, "lng": p.last_lng, "seen": p.last_seen_at})
    alerts = []
    recent = (db.query(Alert).filter(Alert.timestamp >= utcnow() - _td(hours=hours), Alert.dismissed == False)  # noqa: E712
              .order_by(Alert.id.desc()).limit(200))
    for a in recent:
        lat, lng, name = pos.get(a.camera_id, (None, None, None))
        if lat is None or (keep is not None and a.camera_id not in keep):
            continue
        alerts.append({"id": a.id, "type": a.alert_type, "severity": a.severity, "camera_id": a.camera_id, "lat": lat, "lng": lng,
                       "at": a.timestamp, "review_status": a.review_status, "message": a.message})
    return {"cameras": cam_rows, "tracks": track_rows, "officers": officers, "alerts": alerts,
            "summary": {"cameras": len(cam_rows), "on_lookout": sum(c["on_lookout"] for c in cam_rows),
                        "offline": sum(c["status"] == "offline" for c in cam_rows), "tracks": len(track_rows)}}
