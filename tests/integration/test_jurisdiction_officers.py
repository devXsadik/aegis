"""Jurisdiction-based officer eligibility, assignment enforcement, neighbour override,
police scoping, and the hash-chained append-only audit log."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_jurisdiction_officers.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.camera import Camera  # noqa: E402
from backend.models.user import User  # noqa: E402

client = TestClient(app)
API = "/api/v1"
RUN = uuid.uuid4().hex[:6]


def box(lng0, lat0, lng1, lat1):
    return {"type": "Polygon", "coordinates": [[[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]]}


def _user(name, role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"),
                 role=role, is_active=True)
        db.add(u)
        db.commit()
    uid, tok = u.id, issue_token(u)
    db.close()
    return uid, {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def world():
    """District with two thanas side by side; one camera in thana A; officers in A, B, district."""
    _, admin = _user(f"j_admin_{RUN}", "admin")
    _, op = _user(f"j_op_{RUN}", "operator")
    _, sup = _user(f"j_sup_{RUN}", "supervisor")
    dist = client.post(f"{API}/jurisdictions", headers=admin, json={
        "code": f"D-{RUN}", "name_en": "Test district", "level": "district", "geojson": box(90.0, 23.0, 90.2, 23.1)}).json()
    ta = client.post(f"{API}/jurisdictions", headers=admin, json={
        "code": f"TA-{RUN}", "name_en": "Thana A", "name_bn": "থানা ক", "level": "thana", "parent_id": dist["id"],
        "geojson": box(90.0, 23.0, 90.1, 23.1)}).json()
    tb = client.post(f"{API}/jurisdictions", headers=admin, json={
        "code": f"TB-{RUN}", "name_en": "Thana B", "level": "thana", "parent_id": dist["id"],
        "geojson": box(90.1, 23.0, 90.2, 23.1)}).json()
    db = SessionLocal()
    cam_id = f"jcam_{RUN}"
    db.add(Camera(camera_id=cam_id, name="J cam", lat=23.05, lng=90.05))
    db.commit()
    db.close()
    officers = {}
    for key, area, duty, pos in (("a_busy", ta, "busy", None), ("a_free", ta, "available", (23.06, 90.06)),
                                 ("a_far", ta, "available", (23.09, 90.09)), ("b", tb, "available", None),
                                 ("dist", dist, "on_duty", None)):
        uid, hdr = _user(f"j_{key}_{RUN}", "police")
        r = client.put(f"{API}/officers/{uid}", headers=admin, json={
            "full_name": f"Officer {key}", "rank": "SI", "badge_no": f"B-{key}-{RUN}", "station_id": area["id"],
            "duty_status": duty, "jurisdiction_ids": [area["id"]]})
        assert r.status_code == 200, r.text
        if pos:
            client.put(f"{API}/officers/me/duty", headers=hdr, json={"duty_status": duty, "lat": pos[0], "lng": pos[1]})
        officers[key] = (uid, hdr)
    inc = client.post(f"{API}/incidents/", headers=op, json={"title": f"J inc {RUN}", "priority": "high",
                                                             "camera_id": cam_id}).json()
    return {"admin": admin, "op": op, "sup": sup, "ta": ta, "tb": tb, "dist": dist, "officers": officers,
            "inc": inc, "cam": cam_id}


def test_incident_gets_jurisdiction_and_locate(world):
    assert world["inc"]["jurisdiction_id"] == world["ta"]["id"]
    loc = client.get(f"{API}/jurisdictions/locate?lat=23.05&lng=90.15", headers=world["op"]).json()
    assert loc["jurisdiction"]["id"] == world["tb"]["id"]
    assert [c["level"] for c in loc["chain"]] == ["thana", "district"]


def test_eligible_officers_only_covering_sorted(world):
    o = world["officers"]
    res = client.get(f"{API}/incidents/{world['inc']['id']}/eligible-officers", headers=world["op"]).json()
    ids = [x["id"] for x in res["officers"]]
    assert o["b"][0] not in ids                                   # other thana: not eligible
    assert set(ids) == {o["a_busy"][0], o["a_free"][0], o["a_far"][0], o["dist"][0]}
    # available first (nearest first), then on duty, then busy
    assert ids[:2] == [o["a_free"][0], o["a_far"][0]] and ids[2] == o["dist"][0] and ids[3] == o["a_busy"][0]
    assert res["area"]["name"] == "Thana A" and res["officers"][0]["distance_m"] < res["officers"][1]["distance_m"]
    assert "phone" in res["officers"][0] and res["officers"][0]["rank"] == "SI"


def test_assignment_enforced_on_server(world):
    o, iid = world["officers"], world["inc"]["id"]
    r = client.post(f"{API}/incidents/{iid}/assignments", headers=world["op"], json={"user_ids": [o["b"][0]]})
    assert r.status_code == 403                                   # outside jurisdiction
    r = client.post(f"{API}/incidents/{iid}/assignments", headers=world["op"],
                    json={"user_ids": [o["b"][0]], "include_neighbours": True})
    assert r.status_code == 403                                   # operator cannot override
    got = client.post(f"{API}/incidents/{iid}/assignments", headers=world["op"],
                      json={"user_ids": [o["a_free"][0], o["dist"][0]]}).json()
    assert {a["user_id"] for a in got["assignments"]} == {o["a_free"][0], o["dist"][0]}
    assert got["status"] == "officer_dispatched"
    # a field officer cannot assign
    assert client.post(f"{API}/incidents/{iid}/assignments", headers=o["a_free"][1],
                       json={"user_ids": [o["a_far"][0]]}).status_code == 403


def test_neighbour_override_by_supervisor_is_audited(world):
    o, iid = world["officers"], world["inc"]["id"]
    assert client.get(f"{API}/incidents/{iid}/eligible-officers?neighbours=true", headers=world["op"]).status_code == 403
    res = client.get(f"{API}/incidents/{iid}/eligible-officers?neighbours=true", headers=world["sup"]).json()
    b = next(x for x in res["officers"] if x["id"] == o["b"][0])
    assert b["out_of_area"] is True and res["officers"][-1]["out_of_area"] is True
    got = client.post(f"{API}/incidents/{iid}/assignments", headers=world["sup"],
                      json={"user_ids": [o["b"][0]], "include_neighbours": True, "reason": "A officers busy"}).json()
    row = next(a for a in got["assignments"] if a["user_id"] == o["b"][0])
    assert row["out_of_area"] is True
    assert any(e["event_type"] == "OVERRIDE" for e in client.get(f"{API}/incidents/{iid}", headers=world["op"]).json()["events"])
    logs = client.get(f"{API}/audit/?action=OVERRIDE_JURISDICTION", headers=world["admin"]).json()
    assert any(lg["resource_id"] == str(iid) for lg in logs)


def test_officer_reports_state_and_police_scoping(world):
    o, iid = world["officers"], world["inc"]["id"]
    r = client.put(f"{API}/incidents/{iid}/assignments/me", headers=o["a_free"][1], json={"state": "located"}).json()
    assert r["status"] == "target_located"
    assert client.put(f"{API}/incidents/{iid}/assignments/me", headers=o["a_far"][1],
                      json={"state": "en_route"}).status_code == 403            # not assigned
    # a_far covers thana A → sees it; an officer with no area and no assignment does not
    assert client.get(f"{API}/incidents/{iid}", headers=o["a_far"][1]).status_code == 200
    _, stranger = _user(f"j_stranger_{RUN}", "police")
    assert client.get(f"{API}/incidents/{iid}", headers=stranger).status_code == 404
    assert all(i["id"] != iid for i in client.get(f"{API}/incidents/", headers=stranger).json())


def test_admin_only_area_and_officer_edits(world):
    assert client.post(f"{API}/jurisdictions", headers=world["op"], json={
        "code": "X", "name_en": "X", "level": "thana"}).status_code == 403
    assert client.post(f"{API}/jurisdictions", headers=world["admin"], json={
        "code": f"BAD-{RUN}", "name_en": "Bad", "level": "thana", "geojson": {"type": "Point", "coordinates": [1, 2]}
    }).status_code == 400
    assert client.put(f"{API}/jurisdictions/{world['dist']['id']}", headers=world["admin"],
                      json={"parent_id": world["ta"]["id"]}).status_code == 400   # cycle
    assert client.delete(f"{API}/jurisdictions/{world['dist']['id']}", headers=world["admin"]).status_code == 409
    uid = world["officers"]["b"][0]
    assert client.put(f"{API}/officers/{uid}", headers=world["sup"], json={"rank": "OC"}).status_code == 403
    clash = client.put(f"{API}/officers/{uid}", headers=world["admin"], json={"badge_no": f"B-a_free-{RUN}"})
    assert clash.status_code == 409
    assert client.put(f"{API}/officers/me/duty", headers=world["op"], json={"duty_status": "available"}).status_code == 403


def test_audit_chain_is_sealed_and_append_only(world):
    from backend.models.audit_log import AuditLog
    v = client.get(f"{API}/audit/verify", headers=world["admin"]).json()
    assert v["ok"] is True and v["checked"] > 0
    _, auditor = _user(f"j_auditor_{RUN}", "auditor")
    assert client.get(f"{API}/audit/verify", headers=auditor).status_code == 200
    assert client.get(f"{API}/incidents/", headers=auditor).status_code == 403
    db = SessionLocal()
    row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row.record_hash and len(row.record_hash) == 64
    row.details = "tampered"
    with pytest.raises(PermissionError):
        db.commit()
    db.rollback()
    db.delete(db.query(AuditLog).order_by(AuditLog.id.desc()).first())
    with pytest.raises(PermissionError):
        db.commit()
    db.rollback()
    db.close()
