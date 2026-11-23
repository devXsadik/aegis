"""Multi-camera tracking (spec 9): direction → next-camera prediction → lookout → re-acquisition on
the SAME incident → officer notifications (only after an operator confirmed) → ring expansion → lost."""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.bolo import Bolo
from backend.models.incident import Incident
from backend.models.tracking import CrossCameraTrack, Notification
from backend.models.user import User
from backend.services import tracking
from clock import utcnow

client = TestClient(app)
R = uuid.uuid4().hex[:5]
KEY = {"X-Internal-Key": "test-internal-key-for-ci"}
LNG = 90.70 + (int(R, 16) % 1000) / 100000     # own corner of the map per run


def _user(name, role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    uid, tok = u.id, issue_token(u)
    db.close()
    return uid, {"Authorization": f"Bearer {tok}"}


def box(lat0, lat1):
    return {"type": "Polygon", "coordinates": [[[LNG - 0.05, lat0], [LNG + 0.05, lat0], [LNG + 0.05, lat1], [LNG - 0.05, lat1], [LNG - 0.05, lat0]]]}


@pytest.fixture(scope="module")
def net():
    import os
    os.environ["ALERT_DEDUPE_SECONDS"] = "0"
    _, admin = _user(f"t_admin_{R}", "admin")
    _, op = _user(f"t_op_{R}", "operator")
    _, sup = _user(f"t_sup_{R}", "supervisor")
    south = client.post("/api/v1/jurisdictions", headers=admin, json={"code": f"TS-{R}", "name_en": "South thana", "level": "thana", "geojson": box(23.700, 23.785)}).json()
    north = client.post("/api/v1/jurisdictions", headers=admin, json={"code": f"TN-{R}", "name_en": "North thana", "level": "thana", "geojson": box(23.785, 23.900)}).json()
    offs = {}
    for key, area in (("s", south), ("n", north)):
        uid, hdr = _user(f"t_off_{key}_{R}", "police")
        client.put(f"/api/v1/officers/{uid}", headers=admin, json={"jurisdiction_ids": [area["id"]], "duty_status": "on_duty"})
        offs[key] = (uid, hdr)
    cams = {"A": 23.780, "B": 23.790, "C": 23.800, "S": 23.770}
    for k, lat in cams.items():
        client.post("/api/v1/cameras/", headers=admin, json={"camera_id": f"t{k}_{R}", "name": f"Cam {k}", "lat": lat, "lng": LNG, "heading": 0})
    db = SessionLocal()
    from backend.models.tracking import CameraEdge
    from backend.services import geo
    for a, b in (("A", "B"), ("B", "C"), ("A", "S")):
        d = geo.haversine_m(cams[a], LNG, cams[b], LNG)
        db.add(CameraEdge(from_camera=f"t{a}_{R}", to_camera=f"t{b}_{R}", distance_m=d, travel_s=d / 7,
                          bearing_deg=geo.bearing_deg(cams[a], LNG, cams[b], LNG)))
    db.commit()
    db.close()
    now = utcnow()
    plate = f"Dhaka Metro Ha {10 + int(R, 16) % 89}-{1000 + int(R, 16) % 8999}"
    v = client.post("/api/v1/watchlist/vehicles", headers=op, json={
        "plate": plate, "vehicle_type": "car", "color_primary": "white", "case_no": "FIR-T", "issuing_authority": "DMP",
        "legal_basis": "Court order for tracking test", "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=2)).isoformat()}).json()
    client.post(f"/api/v1/watchlist/vehicles/{v['ref']}/approve", headers=sup, json={})
    return {"admin": admin, "op": op, "offs": offs, "plate": plate, "ref": v["ref"], "cam": lambda k: f"t{k}_{R}"}


def see(net, cam, direction=None, ts=None):
    ev = {"type": "vehicle", "plate_text": net["plate"], "vehicle_type": "car", "color": "white",
          "attribute_confidences": {"plate": 0.95, "type": 0.9, "color": 0.9}, "direction": direction}
    if ts:
        ev["timestamp"] = ts.isoformat()
    r = client.post(f"/api/v1/ingest/generic/{net['cam'](cam)}", headers=KEY, json=ev)
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["results"][0]


def test_prediction_respects_direction(net):
    nxt = client.get(f"/api/v1/camera-graph/predict?camera_id={net['cam']('A')}&direction=N", headers=net["op"]).json()["next"]
    assert [n["camera_id"] for n in nxt] == [net["cam"]("B")]
    south = tracking.predict_next(SessionLocal(), net["cam"]("A"), 180.0)
    assert [n["camera_id"] for n in south] == [net["cam"]("S")]
    assert south[0]["eta_to_s"] >= south[0]["eta_from_s"]


def test_handoff_chain_same_incident_and_notifications(net):
    t0 = utcnow()
    first = see(net, "A", "N", t0)
    assert first["severity"] == "critical"
    db = SessionLocal()
    track = db.query(CrossCameraTrack).filter(CrossCameraTrack.target_ref == net["ref"], CrossCameraTrack.status == "active").one()
    inc_id = track.incident_id
    bolo = db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active").one()
    assert [c.camera_id for c in bolo.cameras] == [net["cam"]("B")] and bolo.direction == "N"
    assert db.query(Notification).filter(Notification.incident_id == inc_id).count() == 0   # not verified yet
    db.close()

    # operator confirms → track verified → area officers (here + ahead) notified
    client.put(f"/api/v1/alerts/{first['alert_id']}/acknowledge", headers=net["op"], json={"acknowledged": True, "note": "plate checked"})
    db = SessionLocal()
    assert db.get(CrossCameraTrack, track.id).verified
    assert db.get(Incident, inc_id).status == "verified_match"
    kinds = {(n.user_id, n.kind) for n in db.query(Notification).filter(Notification.incident_id == inc_id)}
    db.close()
    assert (net["offs"]["s"][0], "target_detected") in kinds
    assert (net["offs"]["n"][0], "heading_to_area") in kinds

    # re-acquired at B (from the lookout) → same incident, HANDOFF, new lookout towards C
    second = see(net, "B", "N", t0 + timedelta(minutes=3))
    db = SessionLocal()
    assert db.query(Incident).filter(Incident.alert_id == second["alert_id"]).count() == 0     # no new incident
    inc = client.get(f"/api/v1/incidents/{inc_id}", headers=net["op"]).json()
    kinds = [e["event_type"] for e in inc["events"]]
    assert "HANDOFF" in kinds and kinds.count("BOLO") >= 2
    assert [p["camera_id"] for p in inc["trail"]] == [net["cam"]("A"), net["cam"]("B")]
    assert inc["trail"][1]["bolo"] is not None
    assert db.query(Bolo).filter(Bolo.ref == inc["trail"][1]["bolo"]).one().status == "reacquired"
    nxt = db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active").one()
    assert [c.camera_id for c in nxt.cameras] == [net["cam"]("C")]
    n_b = db.query(Notification).filter(Notification.user_id == net["offs"]["n"][0], Notification.kind == "target_detected").first()
    assert n_b and "moving N" in n_b.title
    db.close()

    # the north officer answers from the phone: En route → joins the incident, status follows
    r = client.post(f"/api/v1/notifications/{n_b.id}/ack", headers=net["offs"]["n"][1], json={"state": "en_route"}).json()
    assert r["ack_state"] == "en_route"
    inc = client.get(f"/api/v1/incidents/{inc_id}", headers=net["op"]).json()
    assert any(a["user_id"] == net["offs"]["n"][0] and a["state"] == "en_route" for a in inc["assignments"])
    assert client.post(f"/api/v1/notifications/{n_b.id}/ack", headers=net["offs"]["s"][1], json={"state": "en_route"}).status_code == 404
    mine = client.get("/api/v1/notifications/me", headers=net["offs"]["n"][1]).json()
    assert mine and all("payload" in m for m in mine)


def test_lookout_expands_then_track_is_lost(net):
    db = SessionLocal()
    track = db.query(CrossCameraTrack).filter(CrossCameraTrack.target_ref == net["ref"], CrossCameraTrack.status == "active").one()
    b = db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active").one()
    out = tracking.sweep(db, now=b.window_end.replace(tzinfo=None) + timedelta(seconds=1))
    db.commit()
    assert out["lost"] == 1 or out["expanded"] == 1
    if out["expanded"]:
        b2 = db.query(Bolo).filter(Bolo.cross_track_id == track.id, Bolo.status == "active").one()
        tracking.sweep(db, now=b2.window_end.replace(tzinfo=None) + timedelta(seconds=1))
        db.commit()
    db.refresh(track)
    assert track.status == "lost"
    inc = client.get(f"/api/v1/incidents/{track.incident_id}", headers=net["op"]).json()
    assert any("Track lost" in e["message"] for e in inc["events"])
    db.close()


def test_implausible_travel_is_flagged(net):
    t0 = utcnow()
    see(net, "S", None, t0)
    see(net, "C", None, t0 + timedelta(seconds=5))        # ~3 km in 5 s
    db = SessionLocal()
    track = db.query(CrossCameraTrack).filter(CrossCameraTrack.target_ref == net["ref"], CrossCameraTrack.status == "active").one()
    assert track.hops[-1].consistent is False and "implausible" in track.hops[-1].note
    db.close()


def test_graph_api_admin(net):
    g = client.get("/api/v1/camera-graph", headers=net["op"]).json()
    assert any(e["from_camera"] == net["cam"]("A") for e in g["edges"])
    assert client.post("/api/v1/camera-graph/suggest", headers=net["op"]).status_code == 403
    e = client.put("/api/v1/camera-graph/edges", headers=net["admin"], json={"from_camera": net["cam"]("C"), "to_camera": net["cam"]("S")}).json()
    assert e["distance_m"] > 2000 and 170 < e["bearing_deg"] < 190
    assert client.delete(f"/api/v1/camera-graph/edges/{e['id']}", headers=net["admin"]).status_code == 200


def test_unacknowledged_notification_escalates_once(net):
    from backend.services.escalation import escalate_notifications
    from backend.services.notify import notify
    _, sup_hdr = _user(f"t_sup_{R}", "supervisor")
    db = SessionLocal()
    sup_id = db.query(User).filter(User.username == f"t_sup_{R}").one().id
    rows = notify(db, [net["offs"]["s"][0]], kind="target_detected", title="Test target", priority="critical",
                  payload={"camera_id": net["cam"]("A")}, dedup_key=f"esc-test-{R}")
    db.commit()
    assert rows[0].ack_deadline is not None
    assert escalate_notifications(db, now=utcnow()) == 0                       # not due yet
    n = escalate_notifications(db, now=utcnow() + timedelta(minutes=5))
    db.commit()
    assert n >= 1
    esc = db.query(Notification).filter(Notification.kind == "escalation", Notification.dedup_key == f"esc:{rows[0].id}").all()
    assert sup_id in {e.user_id for e in esc}
    assert escalate_notifications(db, now=utcnow() + timedelta(minutes=10)) == 0  # once only
    db.close()


def test_command_map_layers(net):
    see(net, "A", "N", utcnow())
    m = client.get("/api/v1/map/command", headers=net["op"]).json()
    mine = [c for c in m["cameras"] if c["camera_id"].endswith(R)]
    assert any(c["on_lookout"] for c in mine) and all("status" in c for c in mine)
    t = next(t for t in m["tracks"] if t["target_ref"] == net["ref"])
    assert t["predicted"] and t["predicted"][0]["camera_id"] == net["cam"]("B") and t["trail"]
    viewer_like = client.get("/api/v1/map/command?jurisdiction_id=999999", headers=net["op"]).json()
    assert viewer_like["cameras"] == [] and viewer_like["tracks"] == []
