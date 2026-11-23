"""Watchlist governance: required legal fields, second-person approval, expiry stops alerts,
re-approval after legal edits, vehicle rules, audit of views, plate helper."""

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.known_person import KnownPerson
from backend.models.user import User
from backend.services import alert_dispatcher as ad
from backend.services import watchlist_gov as gov
from clock import utcnow

client = TestClient(app)
API = "/api/v1/watchlist"
RUN = uuid.uuid4().hex[:6]


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


def _person(pid, category="criminal"):
    init_db()
    db = SessionLocal()
    db.add(KnownPerson(person_id=pid, name=f"Name {pid}", category=category, criminal_status="wanted"))
    db.commit()
    db.close()


def _legal(days=30, **kw):
    now = utcnow()
    return {"case_no": "FIR-77/2026", "legal_basis": "Arrest warrant, Dhaka CMM court order 12/2026",
            "issuing_authority": "DMP Gulshan", "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=days)).isoformat(), **kw}


def _dispatch(pid):
    loop = asyncio.new_event_loop()
    with patch.object(ad, "_send_webhooks", new=AsyncMock(return_value="")), \
         patch.object(ad, "broadcast_live_event", new=AsyncMock(return_value={})), \
         patch.object(ad.manager, "broadcast", new=AsyncMock()):
        return loop.run_until_complete(ad.dispatch_alert(alert_type="CRIMINAL_DETECTED", severity="critical",
                                                         person_name=pid, camera_id=f"wl_cam_{uuid.uuid4().hex[:4]}"))


@pytest.fixture(scope="module")
def users():
    return {"op": _user(f"wl_op_{RUN}", "operator"), "sup": _user(f"wl_sup_{RUN}", "supervisor"),
            "sup2": _user(f"wl_sup2_{RUN}", "supervisor"), "admin": _user(f"wl_admin_{RUN}", "admin"),
            "police": _user(f"wl_pol_{RUN}", "police")}


def test_person_needs_legal_fields_and_second_person(users, monkeypatch):
    monkeypatch.setenv("ALERT_DEDUPE_SECONDS", "0")
    pid = f"P-WL{RUN}"
    _person(pid)
    assert _dispatch(pid)["status"] == "rejected"                        # not on the watchlist yet
    op, sup = users["op"][1], users["sup"]
    bad = client.put(f"{API}/persons/{pid}/request", headers=op, json=_legal(legal_basis="short"))
    assert bad.status_code == 400
    assert client.put(f"{API}/persons/{pid}/request", headers=op, json=_legal(days=400)).status_code == 400
    assert client.put(f"{API}/persons/{pid}/request", headers=users["police"][1], json=_legal()).status_code == 403
    r = client.put(f"{API}/persons/{pid}/request", headers=sup[1], json=_legal(aliases=["Kala Babu", " "])).json()
    assert r["status"] == "pending" and r["aliases"] == ["Kala Babu"] and r["alerting"] is False
    assert _dispatch(pid)["status"] == "rejected"                        # pending does not alert
    # the requester may not approve; an operator may not approve at all
    assert client.post(f"{API}/persons/{pid}/approve", headers=sup[1], json={}).status_code == 403
    assert client.post(f"{API}/persons/{pid}/approve", headers=op, json={}).status_code == 403
    ok = client.post(f"{API}/persons/{pid}/approve", headers=users["sup2"][1], json={"note": "checked warrant"}).json()
    assert ok["status"] == "active" and ok["alerting"] is True and ok["approved_by"] == f"wl_sup2_{RUN}"
    assert _dispatch(pid)["status"] != "rejected"

    # changing a legal field sends it back to pending: alerts stop until re-approved
    again = client.put(f"{API}/persons/{pid}/request", headers=op, json=_legal(days=60)).json()
    assert again["status"] == "pending" and not again["alerting"]
    # descriptive edits do not
    client.post(f"{API}/persons/{pid}/approve", headers=users["sup2"][1], json={})
    meta = client.patch(f"{API}/persons/{pid}", headers=op, json={"risk_level": "high", "offence": "Robbery"}).json()
    assert meta["status"] == "active" and meta["risk_level"] == "high"
    assert client.patch(f"{API}/persons/{pid}", headers=op, json={"risk_level": "extreme"}).status_code == 400

    # revoke needs a reason
    assert client.post(f"{API}/persons/{pid}/revoke", headers=users["sup"][1], json={}).status_code == 400
    rv = client.post(f"{API}/persons/{pid}/revoke", headers=users["sup"][1], json={"note": "Arrested"}).json()
    assert rv["status"] == "revoked" and _dispatch(pid)["status"] == "rejected"


def test_expiry_stops_alerts_without_a_job(users, monkeypatch):
    monkeypatch.setenv("ALERT_DEDUPE_SECONDS", "0")
    pid = f"P-EX{RUN}"
    _person(pid)
    client.put(f"{API}/persons/{pid}/request", headers=users["op"][1], json=_legal())
    client.post(f"{API}/persons/{pid}/approve", headers=users["sup"][1], json={})
    db = SessionLocal()
    p = db.query(KnownPerson).filter(KnownPerson.person_id == pid).first()
    assert pid in gov.active_person_ids(db)
    p.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert pid not in gov.active_person_ids(db) and not gov.is_active(p)
    db.close()
    assert _dispatch(pid)["status"] == "rejected"
    got = client.get(f"{API}/persons/{pid}", headers=users["op"][1]).json()
    assert got["effective_status"] == "expired"
    listed = client.get(f"{API}/persons?status=expired", headers=users["op"][1]).json()   # sweep relabels
    assert any(x["person_id"] == pid for x in listed)


def test_only_criminals_can_be_listed(users):
    pid = f"P-CIV{RUN}"
    _person(pid, category="civilian")
    assert client.put(f"{API}/persons/{pid}/request", headers=users["op"][1], json=_legal()).status_code == 400


def test_vehicle_rules_and_plate_loader(users):
    op, sup = users["op"][1], users["sup"][1]
    assert client.post(f"{API}/vehicles", headers=op, json=_legal(vehicle_type="car")).status_code == 400   # no plate, no colour
    assert client.post(f"{API}/vehicles", headers=op, json=_legal(vehicle_type="spaceship", color_primary="white")).status_code == 400
    assert client.post(f"{API}/vehicles", headers=op, json=_legal(plate="hello")).status_code == 400
    attr_only = client.post(f"{API}/vehicles", headers=op, json=_legal(vehicle_type="car", color_primary="white",
                                                                       make_model="toyota_axio")).json()
    assert attr_only["status"] == "pending" and attr_only["plate"] is None
    v = client.post(f"{API}/vehicles", headers=op, json=_legal(plate="ঢাকা মেট্রো-গ ১২-৩৪৫৬", vehicle_type="microbus",
                                                               color_primary="white", make_model="toyota_noah")).json()
    assert v["plate_canonical"] == "DHAKA-METRO-GA-12-3456" and v["plate_bangla"] == "ঢাকা মেট্রো-গ ১২-৩৪৫৬"
    from backend.services.watchlist_store import load_watchlisted_plates
    assert "DHAKA-METRO-GA-12-3456" not in load_watchlisted_plates()
    client.post(f"{API}/vehicles/{v['ref']}/approve", headers=sup, json={})
    assert "DHAKA-METRO-GA-12-3456" in load_watchlisted_plates()
    from core.analysis.anpr import LicensePlateDatabase
    lpdb = LicensePlateDatabase(load_watchlisted_plates)
    assert lpdb.is_watchlisted("Dhaka Metro Ga 12-3456") and lpdb.is_watchlisted("ঢাকামেট্রোগ১২৩৪৫৬")
    # changing the plate of an active entry needs re-approval
    ch = client.patch(f"{API}/vehicles/{v['ref']}", headers=op, json={"plate": "Dhaka Metro Ga 12-3457"}).json()
    assert ch["status"] == "pending" and "DHAKA-METRO-GA-12-3457" not in load_watchlisted_plates()
    found = client.get(f"{API}/vehicles?q=dhaka metro ga 12-3457", headers=op).json()
    assert [x["ref"] for x in found] == [v["ref"]]
    # approved entries are revoked, not deleted; pending ones may be removed by an admin
    client.post(f"{API}/vehicles/{v['ref']}/approve", headers=sup, json={})
    assert client.delete(f"{API}/vehicles/{v['ref']}", headers=users["admin"][1]).status_code == 409
    assert client.delete(f"{API}/vehicles/{attr_only['ref']}", headers=users["admin"][1]).status_code == 200
    queue = client.get(f"{API}/approvals", headers=sup).json()
    assert all(x["status"] == "pending" for x in queue["vehicles"])


def test_views_are_audited_and_plate_helper(users):
    op = users["op"][1]
    client.get(f"{API}/vehicles", headers=op)
    logs = client.get("/api/v1/audit/?action=WATCHLIST_LIST", headers=users["admin"][1]).json()
    assert logs and logs[0]["username"] in (f"wl_op_{RUN}", f"wl_admin_{RUN}")
    h = client.post(f"{API}/plates/normalize", headers=op, json={"text": "Dhaka Metro Ga 12-3456"}).json()
    assert h["canonical"] == "DHAKA-METRO-GA-12-3456" and h["complete"] and h["bangla"].startswith("ঢাকা")
    h = client.post(f"{API}/plates/normalize", headers=op, json={"text": "গ ১২-৩৪৫৬"}).json()
    assert not h["complete"] and "city" in h["hint"]
    cat = client.get(f"{API}/catalog?kind=type", headers=op).json()
    assert {"cng", "leguna", "easy_bike"} <= {c["code"] for c in cat}
    assert client.post(f"{API}/catalog", headers=op, json={"kind": "color", "code": "pink", "name_en": "Pink"}).status_code == 403


def test_legacy_plates_endpoint_retired(users):
    assert client.post("/api/v1/vehicles/plates", headers=users["admin"][1],
                       json={"plate_number": "X 12-3456"}).status_code == 410
