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
    assert client.post(f"{API}/incidents/{iid}/assignments", headers=world["sup"],
                       json={"user_ids": [o["b"][0]], "include_neighbours": True}).status_code == 400   # reason needed
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


def test_unmapped_camera_override_lists_all_officers(world):
    """A camera outside every mapped area: nobody covers it; the supervisor override lists every
    officer (flagged out of area, reason required), the operator still gets nothing."""
    o = world["officers"]
    inc = client.post(f"{API}/incidents/", headers=world["op"], json={"title": f"Unmapped {RUN}", "priority": "high",
                                                                      "lat": 10.0, "lng": 10.0}).json()
    res = client.get(f"{API}/incidents/{inc['id']}/eligible-officers", headers=world["op"]).json()
    assert res["unmapped"] is True and res["officers"] == []
    res = client.get(f"{API}/incidents/{inc['id']}/eligible-officers?neighbours=true", headers=world["sup"]).json()
    ids = {x["id"] for x in res["officers"]}
    assert {o["a_free"][0], o["b"][0]} <= ids and all(x["out_of_area"] for x in res["officers"])
    assert client.post(f"{API}/incidents/{inc['id']}/assignments", headers=world["sup"],
                       json={"user_ids": [o["b"][0]], "include_neighbours": True}).status_code == 400
    got = client.post(f"{API}/incidents/{inc['id']}/assignments", headers=world["sup"],
                      json={"user_ids": [o["b"][0]], "include_neighbours": True, "reason": "area not mapped"})
    assert got.status_code == 200, got.text


# ——— dispatch messages, roster, district scope ———

def test_messages_between_dispatch_and_field(world):
    o, iid = world["officers"], world["inc"]["id"]
    client.post(f"{API}/incidents/{iid}/assignments", headers=world["op"], json={"user_ids": [o["a_free"][0]]})
    r = client.post(f"{API}/incidents/{iid}/messages", headers=world["op"], json={"body": "Suspect in a red CNG, heading north"})
    assert r.status_code == 201 and not r.json()["from_field"]
    items = client.get(f"{API}/notifications/me", headers=o["a_free"][1]).json()
    assert any(n["kind"] == "message" and n["ack_deadline"] is None for n in items)      # no escalation
    r = client.post(f"{API}/incidents/{iid}/messages", headers=o["a_free"][1], json={"body": "On Road 11, no sign yet"})
    assert r.status_code == 201 and r.json()["from_field"] and r.json()["author_name"] == "Officer a_free"
    thread = client.get(f"{API}/incidents/{iid}/messages", headers=o["a_free"][1]).json()
    assert [m["body"] for m in thread][-2:] == ["Suspect in a red CNG, heading north", "On Road 11, no sign yet"]
    _, stranger = _user(f"j_stranger_{RUN}", "police")                     # no area, not assigned
    assert client.post(f"{API}/incidents/{iid}/messages", headers=stranger, json={"body": "x"}).status_code == 404
    assert client.post(f"{API}/incidents/{iid}/messages", headers=world["op"], json={"body": "  "}).status_code == 422
    assert client.post(f"{API}/incidents/{iid}/messages", headers=world["op"],
                       json={"body": "see", "evidence_ref": "EV-NOPE"}).status_code == 400
    events = client.get(f"{API}/incidents/{iid}", headers=world["op"]).json()["events"]
    assert sum(e["event_type"] == "MESSAGE" for e in events) == 2


def test_roster_puts_officers_on_shift_first(world):
    from datetime import datetime, timedelta, timezone
    o, iid = world["officers"], world["inc"]["id"]
    now = datetime.now(timezone.utc)
    shift = {"user_id": o["a_far"][0], "starts_at": (now - timedelta(hours=1)).isoformat(),
             "ends_at": (now + timedelta(hours=7)).isoformat(), "assignment": "Patrol car 3"}
    assert client.post(f"{API}/roster", headers=world["op"], json=shift).status_code == 403      # supervisors plan
    r = client.post(f"{API}/roster", headers=world["sup"], json=shift)
    assert r.status_code == 201
    assert client.post(f"{API}/roster", headers=world["sup"], json=shift).status_code == 409      # overlapping
    bad = {**shift, "ends_at": (now - timedelta(hours=2)).isoformat()}
    assert client.post(f"{API}/roster", headers=world["sup"], json=bad).status_code == 422
    listed = client.get(f"{API}/roster", headers=world["op"]).json()["shifts"]
    mine = next(s for s in listed if s["id"] == r.json()["id"])
    assert mine["now"] and mine["area"] == "Thana A" and mine["officer"] == "Officer a_far"
    assert all(s["user_id"] == o["a_far"][0] for s in client.get(f"{API}/roster", headers=o["a_far"][1]).json()["shifts"])
    res = client.get(f"{API}/incidents/{iid}/eligible-officers", headers=world["op"]).json()["officers"]
    avail = [x for x in res if x["duty_status"] == "available" and not x.get("assigned")]
    assert avail[0]["id"] == o["a_far"][0] and avail[0]["on_shift"]          # on shift beats nearer
    assert all("eta_s" in x for x in res if x["distance_m"] is not None)
    assert client.delete(f"{API}/roster/{r.json()['id']}", headers=world["sup"]).json() == {"ok": True}


def test_district_admin_only_sees_and_manages_their_district(world):
    _, other_admin = _user(f"j_oadm_{RUN}", "admin")
    db = SessionLocal()
    elsewhere = client.post(f"{API}/jurisdictions", headers=world["admin"], json={
        "code": f"X-{RUN}", "name_en": "Other district", "level": "district", "geojson": box(91.0, 24.0, 91.1, 24.1)}).json()
    db.close()
    # national admin makes a district admin for the test district
    r = client.post(f"{API}/auth/users", headers=world["admin"], json={
        "username": f"j_dadm_{RUN}", "email": f"j_dadm_{RUN}@t.local", "password": "Str0ng-pass-123!", "role": "admin",
        "scope_jurisdiction_id": world["dist"]["id"]})
    assert r.status_code == 200, r.text
    from backend.auth.auth import issue_token
    db = SessionLocal()
    dadm = {"Authorization": f"Bearer {issue_token(db.get(User, r.json()['id']))}"}
    db.close()
    visible = {u["username"] for u in client.get(f"{API}/auth/users", headers=dadm).json()}
    assert f"j_a_free_{RUN}" in visible and f"j_b_{RUN}" in visible               # officers of its thanas
    assert f"j_oadm_{RUN}" not in visible and f"j_admin_{RUN}" not in visible       # national accounts
    made = client.post(f"{API}/auth/users", headers=dadm, json={
        "username": f"j_dop_{RUN}", "email": f"j_dop_{RUN}@t.local", "password": "Str0ng-pass-123!", "role": "operator"}).json()
    assert made["scope_jurisdiction_id"] == world["dist"]["id"]                     # inherits the district
    assert client.post(f"{API}/auth/users", headers=dadm, json={
        "username": f"j_dx_{RUN}", "email": f"j_dx_{RUN}@t.local", "password": "Str0ng-pass-123!", "role": "operator",
        "scope_jurisdiction_id": elsewhere["id"]}).status_code == 403
    assert client.patch(f"{API}/auth/users/{made['id']}", headers=dadm, json={"scope_jurisdiction_id": None}).status_code == 403
    # a district operator sees only incidents of the district
    db = SessionLocal()
    dop = {"Authorization": f"Bearer {issue_token(db.get(User, made['id']))}"}
    db.close()
    out = client.post(f"{API}/incidents/", headers=world["op"], json={"title": f"Far away {RUN}", "priority": "low"}).json()
    listed = client.get(f"{API}/incidents/?limit=200", headers=dop).json()
    ids = {i["id"] for i in (listed["items"] if isinstance(listed, dict) else listed)}
    assert world["inc"]["id"] in ids and out["id"] not in ids
    assert client.get(f"{API}/incidents/{out['id']}", headers=dop).status_code == 404
