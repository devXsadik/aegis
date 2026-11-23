"""Which jurisdiction covers a point / camera, and which officers may be sent there.

An officer covers a camera when one of their jurisdictions is the camera's thana or an
ancestor of it (a district officer covers every thana inside), or contains the camera's
position. Officers mapped straight to the camera (camera_officers) are eligible too."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.camera import Camera
from backend.models.camera_officer import CameraOfficer
from backend.models.incident import Incident, IncidentAssignment
from backend.models.jurisdiction import Jurisdiction, OfficerJurisdiction, OfficerProfile
from backend.models.user import User
from backend.services import geo
from backend.services.incident_status import OPEN_STATUSES

OFFICER_ROLES = ("police", "supervisor")
DUTY_ORDER = {"available": 0, "on_duty": 1, "busy": 2, "off_duty": 3}
LEVEL_ORDER = {"beat": 0, "thana": 1, "district": 2, "division": 3}


def _all(db: Session) -> Dict[int, Jurisdiction]:
    return {j.id: j for j in db.query(Jurisdiction).all()}


def ancestors(jid: Optional[int], by_id: Dict[int, Jurisdiction]) -> List[int]:
    out, seen = [], set()
    while jid and jid in by_id and jid not in seen:
        seen.add(jid)
        out.append(jid)
        jid = by_id[jid].parent_id
    return out


def locate(db: Session, lat: Optional[float], lng: Optional[float],
           by_id: Optional[Dict[int, Jurisdiction]] = None) -> Optional[Jurisdiction]:
    """Most specific jurisdiction whose polygon holds the point."""
    if lat is None or lng is None:
        return None
    by_id = by_id or _all(db)
    hits = [j for j in by_id.values() if j.geojson and geo.contains(j.geojson, lat, lng)]
    return min(hits, key=lambda j: LEVEL_ORDER.get(j.level, 9)) if hits else None


def camera_point(db: Session, camera_id: Optional[str], lat=None, lng=None):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first() if camera_id else None
    if cam and cam.lat is not None:
        lat, lng = cam.lat, cam.lng
    return cam, lat, lng


def covering_ids(db: Session, camera: Optional[Camera], lat, lng, by_id=None) -> Set[int]:
    """Jurisdiction ids whose officers may act at this place (the place's chain up to division)."""
    by_id = by_id or _all(db)
    ids: Set[int] = set()
    if camera and camera.jurisdiction_id:
        ids.update(ancestors(camera.jurisdiction_id, by_id))
    found = locate(db, lat, lng, by_id)
    if found:
        ids.update(ancestors(found.id, by_id))
    return ids


def neighbour_ids(base: Iterable[int], by_id: Dict[int, Jurisdiction]) -> Set[int]:
    """Sibling areas of the most specific covering areas (same parent, same level)."""
    base = set(base)
    leaves = [by_id[i] for i in base if i in by_id and not any(by_id[o].parent_id == i for o in base if o in by_id)]
    out: Set[int] = set()
    for leaf in leaves:
        for j in by_id.values():
            if j.parent_id and j.parent_id == leaf.parent_id and j.level == leaf.level and j.id != leaf.id:
                out.add(j.id)
    return out - base


def incident_jurisdiction(db: Session, inc: Incident) -> Optional[int]:
    cam, lat, lng = camera_point(db, inc.camera_id, inc.lat, inc.lng)
    if cam and cam.jurisdiction_id:
        return cam.jurisdiction_id
    found = locate(db, lat, lng)
    return found.id if found else None


def active_counts(db: Session, user_ids: Iterable[int]) -> Dict[int, int]:
    ids = list(user_ids)
    if not ids:
        return {}
    rows = (db.query(IncidentAssignment.user_id, func.count(IncidentAssignment.id))
            .join(Incident, Incident.id == IncidentAssignment.incident_id)
            .filter(IncidentAssignment.user_id.in_(ids), Incident.status.in_(sorted(OPEN_STATUSES)))
            .group_by(IncidentAssignment.user_id).all())
    return {uid: n for uid, n in rows}


def officer_card(u: User, prof: Optional[OfficerProfile], areas: List[Jurisdiction], *, distance_m=None,
                 active=0, out_of_area=False) -> dict:
    return {
        "id": u.id, "username": u.username, "name": (prof.full_name if prof and prof.full_name else u.username),
        "role": u.role, "rank": prof.rank if prof else None, "badge_no": prof.badge_no if prof else None,
        "station": prof.station.name_en if prof and prof.station else None,
        "phone": u.phone, "duty_status": prof.duty_status if prof else "off_duty",
        "has_photo": bool(prof and prof.photo), "active_incidents": active,
        "distance_m": round(distance_m) if distance_m is not None else None,
        "jurisdictions": [{"id": a.id, "name": a.name_en, "level": a.level} for a in areas],
        "out_of_area": out_of_area,
    }


def eligible_officers(db: Session, *, camera_id: Optional[str], lat=None, lng=None,
                      include_neighbours: bool = False) -> dict:
    """Officers who may be sent to this camera / point, sorted by duty status, then distance,
    then current load. With include_neighbours, officers of adjacent areas are added and flagged."""
    by_id = _all(db)
    cam, lat, lng = camera_point(db, camera_id, lat, lng)
    cover = covering_ids(db, cam, lat, lng, by_id)
    near = neighbour_ids(cover, by_id) if include_neighbours else set()

    links = db.query(OfficerJurisdiction).filter(OfficerJurisdiction.jurisdiction_id.in_(cover | near)).all() \
        if (cover or near) else []
    in_area = {lk.user_id for lk in links if lk.jurisdiction_id in cover}
    neighbour_only = {lk.user_id for lk in links if lk.jurisdiction_id in near} - in_area
    direct = {co.user_id for co in db.query(CameraOfficer).filter(CameraOfficer.camera_id == camera_id).all()} \
        if camera_id else set()
    in_area |= direct
    unmapped = not cover
    if unmapped and include_neighbours:
        # The place lies in no mapped jurisdiction: the override (supervisor / admin, reason
        # required, audit-logged) may pick any active officer, each flagged as out of area.
        everyone = {u.id for u in db.query(User.id).filter(User.is_active == True,  # noqa: E712
                                                           User.role.in_(OFFICER_ROLES))}
        neighbour_only = everyone - in_area
    ids = in_area | neighbour_only
    users = db.query(User).filter(User.id.in_(ids), User.is_active == True,  # noqa: E712
                                  User.role.in_(OFFICER_ROLES)).all() if ids else []
    profs = {p.user_id: p for p in db.query(OfficerProfile).filter(OfficerProfile.user_id.in_(ids)).all()} if ids else {}
    areas_by_user: Dict[int, List[Jurisdiction]] = {}
    for lk in db.query(OfficerJurisdiction).filter(OfficerJurisdiction.user_id.in_(ids)).all() if ids else []:
        if lk.jurisdiction_id in by_id:
            areas_by_user.setdefault(lk.user_id, []).append(by_id[lk.jurisdiction_id])
    counts = active_counts(db, ids)

    cards = []
    for u in users:
        prof = profs.get(u.id)
        dist = None
        if lat is not None:
            if prof and prof.last_lat is not None:
                dist = geo.haversine_m(lat, lng, prof.last_lat, prof.last_lng)
            else:
                st = prof.station if prof and prof.station else None
                c = geo.centroid(st.geojson) if st else None
                if c:
                    dist = geo.haversine_m(lat, lng, c[0], c[1])
        cards.append(officer_card(u, prof, areas_by_user.get(u.id, []), distance_m=dist,
                                  active=counts.get(u.id, 0), out_of_area=u.id in neighbour_only))
    cards.sort(key=lambda c: (c["out_of_area"], DUTY_ORDER.get(c["duty_status"], 9),
                              c["distance_m"] if c["distance_m"] is not None else 1e12, c["active_incidents"], c["name"]))
    area = None
    leaf = min((by_id[i] for i in cover), key=lambda j: LEVEL_ORDER.get(j.level, 9), default=None)
    if leaf:
        area = {"id": leaf.id, "name": leaf.name_en, "name_bn": leaf.name_bn, "level": leaf.level}
    return {"camera_id": camera_id, "lat": lat, "lng": lng, "area": area, "officers": cards,
            "neighbours_included": include_neighbours, "unmapped": unmapped}


def is_eligible(db: Session, user_id: int, *, camera_id, lat=None, lng=None, include_neighbours=False) -> bool:
    res = eligible_officers(db, camera_id=camera_id, lat=lat, lng=lng, include_neighbours=include_neighbours)
    return any(o["id"] == user_id for o in res["officers"])


def officer_area_ids(db: Session, user_id: int) -> Set[int]:
    """Every jurisdiction id an officer covers, including descendants of their areas."""
    by_id = _all(db)
    own = {lk.jurisdiction_id for lk in db.query(OfficerJurisdiction).filter(OfficerJurisdiction.user_id == user_id)}
    return {j for j in by_id if own & set(ancestors(j, by_id))}


def officer_camera_ids(db: Session, user_id: int) -> Set[str]:
    """Cameras an officer may see: mapped to them directly, or inside one of their areas."""
    areas = officer_area_ids(db, user_id)
    by_id = _all(db)
    cams = {co.camera_id for co in db.query(CameraOfficer).filter(CameraOfficer.user_id == user_id)}
    for cam in db.query(Camera).all():
        jid = cam.jurisdiction_id
        if not jid:
            found = locate(db, cam.lat, cam.lng, by_id)
            jid = found.id if found else None
        if jid in areas:
            cams.add(cam.camera_id)
    return cams
