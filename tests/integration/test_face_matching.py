"""Face watchlist matching: thresholds, approved entries only, nothing kept for non-matches,
quality gate, side-by-side data on the alert, and the dlib / ArcFace spaces never mixing."""
import base64
import json
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.alert import Alert
from backend.models.detection import Detection
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson
from backend.services.face_index import INDEX
from core.ingest.events import encode_vec
from tests.watch_helpers import approved

client = TestClient(app)
RUN = uuid.uuid4().hex[:6]
KEY = {"X-Internal-Key": "test-internal-key-for-ci"}
MODEL = "test-arc-1"


def unit(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def near(v, noise, seed=0):
    w = v + noise * np.random.default_rng(seed).normal(size=v.shape).astype(np.float32)
    return (w / np.linalg.norm(w)).astype(np.float32)


@pytest.fixture(scope="module")
def world():
    import os
    os.environ["ALERT_DEDUPE_SECONDS"] = "0"
    init_db()
    db = SessionLocal()
    wanted = KnownPerson(person_id=f"P-F{RUN}", name="Wanted Face", category="criminal", criminal_status="wanted", **approved())
    pending = KnownPerson(person_id=f"P-G{RUN}", name="Pending Face", category="criminal", criminal_status="wanted")
    db.add_all([wanted, pending])
    db.flush()
    va, vb = unit(1), unit(2)
    db.add(FaceEncoding(person_id=wanted.id, encoding=va.tobytes(), encoding_version=MODEL))
    db.add(FaceEncoding(person_id=pending.id, encoding=vb.tobytes(), encoding_version=MODEL))
    db.commit()
    db.close()
    client.post("/api/v1/cameras/", headers=_admin(), json={"camera_id": f"fcam_{RUN}", "name": "Face cam"})
    INDEX.refresh(SessionLocal(), MODEL, force=True)
    return {"va": va, "vb": vb, "wanted": f"P-F{RUN}", "pending": f"P-G{RUN}", "cam": f"fcam_{RUN}"}


def _admin():
    from backend.auth.auth import hash_password, issue_token
    from backend.models.user import User
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == f"f_admin_{RUN}").first() or User(
        username=f"f_admin_{RUN}", email=f"fa{RUN}@t.local", hashed_password=hash_password("pass12345678"), role="admin", is_active=True)
    db.add(u)
    db.commit()
    tok = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {tok}"}


def _send(world, vec, **kw):
    r = client.post(f"/api/v1/ingest/generic/{world['cam']}", headers=KEY,
                    json={"type": "face", "embedding": encode_vec(vec), "embedding_model": MODEL, **kw})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def test_close_face_raises_possible_match_with_side_by_side(world):
    out = _send(world, near(world["va"], 0.02), quality=0.9)
    res = out["results"][0]
    assert res["person_id"] == world["wanted"] and res["severity"] == "critical" and res["similarity"] > 0.9
    db = SessionLocal()
    a = db.get(Alert, res["alert_id"])
    d = json.loads(a.details)
    det = db.query(Detection).filter(Detection.event_id == out["event_id"]).first()
    db.close()
    assert a.alert_type == "FACE_MATCH" and a.review_status == "pending" and "needs verification" in a.message
    assert d["face"]["name"] == "Wanted Face" and d["face"]["possible_threshold"] == 0.38
    assert det.matched and det.embedding is not None


def test_weaker_similarity_is_lower_severity(world):
    v = near(world["va"], 0.2, seed=3)
    sim = float(v @ world["va"])
    assert 0.38 <= sim < 0.5, sim
    res = _send(world, v)["results"][0]
    assert res["severity"] == "medium"


def test_stranger_leaves_no_trace(world):
    out = _send(world, unit(99))
    assert out["results"] == []
    db = SessionLocal()
    assert db.query(Detection).filter(Detection.event_id == out["event_id"]).first() is None
    db.close()


def test_unapproved_entry_never_matches(world):
    out = _send(world, near(world["vb"], 0.01))
    assert out["results"] == []


def test_thresholds_are_configurable(world):
    admin = _admin()
    assert client.put("/api/v1/config/threshold.face_possible_similarity", headers=admin, json={"value": "0.8"}).status_code in (200, 204)
    out = _send(world, near(world["va"], 0.2, seed=3))
    assert out["results"] == []
    client.put("/api/v1/config/threshold.face_possible_similarity", headers=admin, json={"value": "0.38"})


def test_quality_gate_drops_blurry_crops(world):
    from core.recognition import embedder

    class Fake(embedder.Embedder):
        name = MODEL

        def available(self):
            return True

        def detect(self, img):
            return None

        def embed(self, img, row=None):
            return world["va"]

    blurry = np.full((120, 120, 3), 128, np.uint8)
    crop = base64.b64encode(cv2.imencode(".jpg", blurry)[1].tobytes()).decode()
    embedder.set_embedder(Fake())
    try:
        r = client.post(f"/api/v1/ingest/generic/{world['cam']}", headers=KEY, json={"type": "face", "crop_image": crop})
        res = r.json()["results"][0]["results"]
        assert res[0]["dropped"] == "quality" and any("blurry" in x for x in res[0]["reasons"])
        sharp = np.random.default_rng(5).integers(0, 255, (120, 120, 3), dtype=np.uint8)
        crop = base64.b64encode(cv2.imencode(".jpg", sharp)[1].tobytes()).decode()
        r = client.post(f"/api/v1/ingest/generic/{world['cam']}", headers=KEY, json={"type": "face", "crop_image": crop})
        res = r.json()["results"][0]["results"]
        assert res and res[0]["person_id"] == world["wanted"]
        db = SessionLocal()
        det = db.query(Detection).filter(Detection.alert_id == res[0]["alert_id"]).first()
        assert det.crop is not None                                        # matched: crop kept for the operator
        db.close()
    finally:
        embedder.set_embedder(None)


def test_dlib_and_arcface_vectors_never_mix(world):
    from backend.services.watchlist_store import load_face_encodings
    encs, names = load_face_encodings()
    assert world["wanted"] not in names                    # only dlib-version rows reach the pipeline loader
