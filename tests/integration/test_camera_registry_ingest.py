"""Camera registry (credentials, tokens, CSV import, health) and event ingestion."""
import base64
import uuid

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.camera import Camera
from backend.models.detection import Detection
from backend.models.user import User
from backend.services import event_router

client = TestClient(app)
RUN = uuid.uuid4().hex[:6]
CAM = f"reg_{RUN}"


def _user(name, role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    tok = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {tok}"}


ADMIN = None


def admin():
    global ADMIN
    ADMIN = ADMIN or _user(f"reg_admin_{RUN}", "admin")
    return ADMIN


def _make_camera(cid=CAM, **kw):
    r = client.post("/api/v1/cameras/", headers=admin(), json={"camera_id": cid, "name": "Reg cam", "lat": 23.79, "lng": 90.41,
                                                              "heading": 90, "fov": 70, "protocol": "rtsp",
                                                              "capabilities": ["anpr", "vehicle_attr"], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_registry_fields_and_write_only_credentials(monkeypatch):
    cam = _make_camera(rtsp_url="rtsp://10.0.0.5:554/Streaming/Channels/101")
    assert cam["capabilities"] == ["anpr", "vehicle_attr"] and cam["protocol"] == "rtsp" and not cam["has_credentials"]
    assert client.put(f"/api/v1/cameras/{CAM}/credentials", headers=_user(f"reg_op_{RUN}", "operator"),
                      json={"username": "u", "password": "p"}).status_code == 403
    r = client.put(f"/api/v1/cameras/{CAM}/credentials", headers=admin(), json={"username": "admin", "password": "p@ss:w/rd"})
    assert r.json()["has_credentials"]
    listed = client.get(f"/api/v1/cameras/{CAM}/detail", headers=admin()).json()
    assert listed["has_credentials"] and "credentials" not in listed and "p@ss" not in str(listed)
    db = SessionLocal()
    raw = db.query(Camera).filter(Camera.camera_id == CAM).first().credentials
    db.close()
    assert b"p@ss" not in raw                                              # sealed at rest
    key = "test-internal-key-for-ci"
    src = client.get(f"/api/v1/cameras/{CAM}/stream-source", headers={"X-Internal-Key": key}).json()
    assert src["source"] == "rtsp://admin:p%40ss%3Aw%2Frd@10.0.0.5:554/Streaming/Channels/101"
    assert client.get(f"/api/v1/cameras/{CAM}/stream-source").status_code in (401, 403)
    assert client.post("/api/v1/cameras/", headers=admin(), json={"camera_id": f"bad_{RUN}", "name": "x", "heading": 400}).status_code == 422


def test_ingest_with_camera_token_stores_and_matches():
    cid = f"hook_{RUN}"
    _make_camera(cid, protocol="webhook", vendor="hikvision")
    body = {"eventType": "ANPR", "ANPR": {"licensePlate": "Dhaka Metro Ga 12-3456", "confidenceLevel": 88},
            "Vehicle": {"vehicleColor": "white", "vehicleType": "SUV"},
            "picture": base64.b64encode(b"\xff\xd8fakejpeg").decode()}
    assert client.post(f"/api/v1/ingest/hikvision/{cid}", json=body).status_code == 401
    assert client.post(f"/api/v1/ingest/hikvision/{cid}", json=body, headers={"X-Camera-Token": "nope"}).status_code == 401
    tok = client.post(f"/api/v1/cameras/{cid}/ingest-token", headers=admin()).json()
    assert tok["url"] == f"/api/v1/ingest/hikvision/{cid}"
    seen = []

    def spy(db, ev, det):
        seen.append((ev.plate_text, det.plate_canonical))
        return []
    event_router.register("vehicle", spy)
    try:
        r = client.post(f"/api/v1/ingest/hikvision/{cid}", json=body, headers={"X-Camera-Token": tok["token"]})
    finally:
        event_router.unregister("vehicle", spy)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1 and seen[-1] == ("Dhaka Metro Ga 12-3456", "DHAKA-METRO-GA-12-3456")
    db = SessionLocal()
    det = db.query(Detection).filter(Detection.camera_id == cid).first()
    cam = db.query(Camera).filter(Camera.camera_id == cid).first()
    assert det.color == "white" and det.vehicle_type == "suv" and det.expires_at > det.ts and det.crop
    assert cam.last_heartbeat is not None
    db.close()
    assert client.post(f"/api/v1/ingest/hikvision/{cid}", json={"eventType": "Motion"},
                       headers={"X-Camera-Token": tok["token"]}).status_code == 422
    # faces: no crop kept unless a matcher keeps it
    r = client.post(f"/api/v1/ingest/generic/{cid}", json={"type": "face", "crop_image": base64.b64encode(b"x").decode()},
                    headers={"X-Camera-Token": tok["token"]})
    db = SessionLocal()
    face = db.query(Detection).filter(Detection.event_id == r.json()["results"][0]["event_id"]).first()
    assert face.kind == "face" and face.crop is None and face.embedding is None
    db.close()


def test_retention_purge_keeps_matched_and_attached():
    from datetime import timedelta
    from clock import utcnow
    db = SessionLocal()
    old = utcnow() - timedelta(days=400)
    for i, (m, inc) in enumerate(((False, None), (True, None), (False, 7))):
        db.add(Detection(event_id=f"ret{RUN}{i}", camera_id="r", ts=old, kind="vehicle", matched=m, incident_id=inc,
                         expires_at=old + timedelta(days=1)))
    db.commit()
    assert event_router.purge_expired(db) >= 1
    db.commit()
    left = {d.event_id for d in db.query(Detection).filter(Detection.event_id.like(f"ret{RUN}%"))}
    assert left == {f"ret{RUN}1", f"ret{RUN}2"}
    db.close()


def test_csv_import_dry_run_then_commit():
    csv_ok = ("camera_id,name,lat,lng,heading,fov,protocol,capabilities,ir_mode,sample_fps,username,password\n"
              f"csv_a_{RUN},A cam,23.78,90.41,10,80,rtsp,face|anpr,true,5,admin,pw\n"
              f"csv_b_{RUN},B cam,23.79,90.42,200,60,webhook,anpr,false,,,\n")
    files = {"file": ("c.csv", csv_ok, "text/csv")}
    dry = client.post("/api/v1/cameras/import", headers=admin(), files=files).json()
    assert dry["dry_run"] and dry["valid"] == 2
    assert client.get(f"/api/v1/cameras/csv_a_{RUN}/detail", headers=admin()).status_code == 404
    bad = csv_ok + f"csv_c_{RUN},C,99,90,0,60,rtsp,laser,,,,\n"
    res = client.post("/api/v1/cameras/import?dry_run=false", headers=admin(), files={"file": ("c.csv", bad, "text/csv")})
    assert res.status_code == 422 and any(not r["ok"] for r in res.json()["detail"]["rows"])
    done = client.post("/api/v1/cameras/import?dry_run=false", headers=admin(), files={"file": ("c.csv", csv_ok, "text/csv")}).json()
    assert done["valid"] == 2
    a = client.get(f"/api/v1/cameras/csv_a_{RUN}/detail", headers=admin()).json()
    assert a["has_credentials"] and a["capabilities"] == ["face", "anpr"] and a["ir_mode"] is True and a["sample_fps"] == 5


def test_health_statuses():
    from backend.api.system_routes import _pipeline_status
    from clock import utcnow
    _make_camera(f"h_live_{RUN}")
    _make_camera(f"h_slow_{RUN}")
    _make_camera(f"h_dead_{RUN}")
    _pipeline_status["cameras"][f"h_live_{RUN}"] = {"last_seen": utcnow().isoformat(), "fps": 12}
    _pipeline_status["cameras"][f"h_slow_{RUN}"] = {"last_seen": utcnow().isoformat(), "fps": 1.0}
    h = client.get("/api/v1/cameras/health", headers=admin()).json()
    by = {c["camera_id"]: c for c in h["cameras"]}
    assert by[f"h_live_{RUN}"]["status"] == "online"
    assert by[f"h_slow_{RUN}"]["status"] == "degraded" and "fps" in by[f"h_slow_{RUN}"]["reason"]
    assert by[f"h_dead_{RUN}"]["status"] == "offline"
    assert set(h["summary"]) == {"online", "degraded", "offline", "disabled"}
