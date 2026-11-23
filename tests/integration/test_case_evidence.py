"""Evidence upload (spec 12) and face folders (spec 13)."""
import io
import hashlib
import uuid

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson
from backend.models.user import User
from backend.services.face_index import INDEX
from core.recognition import embedder
from tests.watch_helpers import approved

client = TestClient(app)
R = uuid.uuid4().hex[:6]
MODEL = "test-evid-1"


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


def jpeg(seed, size=160):
    img = np.random.default_rng(seed).integers(0, 255, (size, size, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def unit(seed):
    v = np.random.default_rng(seed).normal(size=64).astype(np.float32)
    return v / np.linalg.norm(v)


class FakeEmbedder(embedder.Embedder):
    """Every 'image' is one face; its identity is the seed hidden in the first pixel row."""
    name = MODEL

    def available(self):
        return True

    def embed(self, img, row=None):
        key = int(img[0, 0, 0]) % 3            # 3 identities
        return unit(1000 + key)


@pytest.fixture(scope="module")
def ctx():
    import os
    os.environ["FACE_GROUPING_SYNC"] = "true"
    embedder.set_embedder(FakeEmbedder())
    _, op = _user(f"ev_op_{R}", "operator")
    _, admin = _user(f"ev_admin_{R}", "admin")
    _, police = _user(f"ev_pol_{R}", "police")
    inc = client.post("/api/v1/incidents/", headers=op, json={"title": f"Evidence case {R}", "priority": "high"}).json()
    db = SessionLocal()
    crook = KnownPerson(person_id=f"P-EV{R}", name="Evidence Crook", category="criminal", criminal_status="wanted", **approved())
    db.add(crook)
    db.flush()
    db.add(FaceEncoding(person_id=crook.id, encoding=unit(1000 + 2).tobytes(), encoding_version=MODEL))   # identity 2 is a criminal
    db.commit()
    db.close()
    INDEX.refresh(SessionLocal(), MODEL, force=True)
    yield {"op": op, "admin": admin, "police": police, "inc": inc}
    embedder.set_embedder(None)
    os.environ.pop("FACE_GROUPING_SYNC", None)


def face_img(identity, seed):
    img = np.random.default_rng(seed).integers(0, 255, (160, 160, 3), dtype=np.uint8)
    img[0, 0, 0] = identity
    return cv2.imencode(".png", img)[1].tobytes()


def up(ctx, files, **form):
    return client.post("/api/v1/evidence-items", headers=ctx["op"], data={"incident_id": ctx["inc"]["id"], **form},
                       files=[("files", f) for f in files])


def test_upload_validates_dedupes_and_records_custody(ctx):
    pdf = b"%PDF-1.4 test document " + R.encode()
    res = up(ctx, [("a.png", face_img(0, 1), "image/png"), ("doc.pdf", pdf, "application/pdf"),
                   ("fake.pdf", b"not a pdf", "application/pdf"), ("x.exe", b"MZ..", "application/x-msdownload")],
             description="Scene photos", location="Gulshan 2", captured_at="2026-11-20T10:00:00").json()
    ok = [r for r in res["results"] if r["ok"]]
    bad = {r["filename"]: r["code"] for r in res["results"] if not r["ok"]}
    assert len(ok) == 2 and bad == {"fake.pdf": 415, "x.exe": 415}
    img = next(r for r in ok if r["kind"] == "image")
    assert img["sha256"] == hashlib.sha256(face_img(0, 1)).hexdigest()
    assert img["faces_status"] == "pending"                       # "Processing faces…" right after upload
    after = client.get(f"/api/v1/evidence-items?incident_id={ctx['inc']['id']}", headers=ctx["op"]).json()["items"]
    done = next(i for i in after if i["ref"] == img["ref"])
    assert done["faces_status"] == "done" and done["faces_found"] == 1
    again = up(ctx, [("copy.png", face_img(0, 1), "image/png")]).json()["results"][0]
    assert not again["ok"] and again["code"] == 409 and img["ref"] in again["error"]
    detail = client.get(f"/api/v1/evidence-items/{img['ref']}", headers=ctx["op"]).json()
    assert [c["action"] for c in detail["custody"]] == ["UPLOADED", "VIEWED"]
    assert len(detail["faces"]) == 1 and detail["faces"][0]["group_id"]
    f = client.get(f"/api/v1/evidence-items/{img['ref']}/file", headers=ctx["op"])
    assert f.content == face_img(0, 1) and f.headers["x-evidence-sha256"] == img["sha256"]
    v = client.get(f"/api/v1/evidence-items/{img['ref']}/verify", headers=ctx["op"]).json()
    assert v["ok"] and v["chain_ok"] and v["records"] == 3
    inc = client.get(f"/api/v1/incidents/{ctx['inc']['id']}", headers=ctx["op"]).json()
    assert sum(e["event_type"] == "EVIDENCE" for e in inc["events"]) == 2


def test_versions_keep_the_original_and_only_admin_soft_deletes(ctx):
    first = up(ctx, [("b.png", face_img(1, 2), "image/png")]).json()["results"][0]
    v2 = client.post(f"/api/v1/evidence-items/{first['ref']}/versions", headers=ctx["op"], data={"note": "faces blurred"},
                     files={"file": ("b2.png", face_img(1, 3), "image/png")}).json()
    assert v2["version"] == 2 and v2["parent_id"] == first["id"]
    assert client.get(f"/api/v1/evidence-items/{first['ref']}/file", headers=ctx["op"]).content == face_img(1, 2)
    assert client.post(f"/api/v1/evidence-items/{first['ref']}/delete", headers=ctx["op"], json={"reason": "duplicate upload"}).status_code == 403
    d = client.post(f"/api/v1/evidence-items/{first['ref']}/delete", headers=ctx["admin"], json={"reason": "uploaded to wrong case"}).json()
    assert d["deleted"]
    assert client.get(f"/api/v1/evidence-items/{first['ref']}", headers=ctx["op"]).status_code == 404
    assert client.get(f"/api/v1/evidence-items/{first['ref']}", headers=ctx["admin"]).status_code == 200


def test_faces_are_grouped_and_criminal_matches_need_verification(ctx):
    res = up(ctx, [("p1.png", face_img(0, 10), "image/png"), ("p2.png", face_img(0, 11), "image/png"),
                   ("p3.png", face_img(1, 12), "image/png"), ("c1.png", face_img(2, 13), "image/png")]).json()
    assert all(r["ok"] for r in res["results"])
    groups = client.get("/api/v1/person-groups", headers=ctx["op"]).json()
    mine = [g for g in groups if g["faces"] > 0]
    crim = next(g for g in mine if g["criminal"] and g["criminal"]["person_id"] == f"P-EV{R}")
    assert crim["status"] == "criminal_possible" and crim["name"] == "Evidence Crook"
    unknown0 = next(g for g in mine if g["code"].startswith("UNKNOWN") and g["faces"] >= 3)    # identity 0: 3 photos
    detail = client.get(f"/api/v1/person-groups/{crim['id']}", headers=ctx["op"]).json()
    face = detail["items"][0]
    assert face["verify_status"] == "pending"
    r = client.post(f"/api/v1/evidence-faces/{face['id']}/verify", headers=ctx["op"], json={"decision": "confirm"}).json()
    assert r["verify_status"] == "confirmed"
    assert client.get(f"/api/v1/person-groups/{crim['id']}", headers=ctx["op"]).json()["status"] == "criminal"
    assert unknown0["best_face_url"]


def test_merge_split_move_and_rename_are_logged(ctx):
    groups = [g for g in client.get("/api/v1/person-groups", headers=ctx["op"]).json() if g["code"].startswith("UNKNOWN") and not g["criminal"]]
    a, b = groups[0], groups[1]
    merged = client.post("/api/v1/person-groups/merge", headers=ctx["op"], json={"target_id": a["id"], "source_ids": [b["id"]]}).json()
    assert merged["faces"] == a["faces"] + b["faces"]
    assert client.get(f"/api/v1/person-groups/{b['id']}", headers=ctx["op"]).status_code == 404
    faces = client.get(f"/api/v1/person-groups/{a['id']}", headers=ctx["op"]).json()["items"]
    split = client.post("/api/v1/person-groups/move", headers=ctx["op"], json={"face_ids": [faces[0]["id"]]}).json()
    assert split["faces"] == 1 and split["code"].startswith("UNKNOWN")
    back = client.post("/api/v1/person-groups/move", headers=ctx["op"], json={"face_ids": [faces[0]["id"]], "target_id": a["id"]}).json()
    assert back["id"] == a["id"]
    named = client.patch(f"/api/v1/person-groups/{a['id']}", headers=ctx["op"], json={"name": "Driver in blue shirt"}).json()
    assert named["status"] == "named"
    logs = client.get("/api/v1/audit/?action=PERSON_GROUP_MERGE", headers=ctx["admin"]).json()
    assert logs


def test_police_only_see_their_incidents_evidence(ctx):
    items = client.get(f"/api/v1/evidence-items?incident_id={ctx['inc']['id']}", headers=ctx["police"]).json()
    assert items["total"] == 0
    assert client.post("/api/v1/evidence-items", headers=ctx["police"], data={"incident_id": ctx["inc"]["id"]},
                       files=[("files", ("x.png", face_img(0, 99), "image/png"))]).status_code == 404


class FakeS3:
    """The four calls blobstore makes, with S3's write-once semantics under Object Lock."""

    def __init__(self):
        self.objects, self.puts = {}, []

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)

    def put_object(self, Bucket, Key, Body, ContentType, **extra):
        self.puts.append({"key": Key, **extra})
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def head_bucket(self, Bucket):
        return {}


def test_evidence_goes_to_object_storage_sealed_and_locked(ctx, monkeypatch):
    from backend.services import blobstore
    fake = FakeS3()
    blobstore.set_client(fake)
    monkeypatch.setenv("EVIDENCE_STORE", "s3")
    monkeypatch.setenv("S3_BUCKET", "aegis-evidence")
    monkeypatch.setenv("S3_OBJECT_LOCK_DAYS", "3650")
    try:
        pdf = b"%PDF-1.4 stored in s3 " + R.encode()
        r = up(ctx, [("s3.pdf", pdf, "application/pdf")]).json()["results"][0]
        assert r["ok"]
        (key, stored), = [(k, v) for (b, k), v in fake.objects.items() if b == "aegis-evidence"]
        assert key.startswith("evidence/") and key.endswith(".bin")
        assert stored != pdf                                        # the provider only sees ciphertext
        assert fake.puts[0]["ObjectLockMode"] == "COMPLIANCE" and fake.puts[0]["ObjectLockRetainUntilDate"]
        f = client.get(f"/api/v1/evidence-items/{r['ref']}/file", headers=ctx["op"])
        assert f.status_code == 200 and f.content == pdf
        assert blobstore.health() == {"backend": "s3", "ok": True, "object_lock_days": 3650}
    finally:
        blobstore.set_client(None)


class FakePeople:
    """Finds one person: a red top over blue trousers, painted into the test image."""

    def detect(self, frame):
        return [([40, 20, 100, 180], 0.9, 0)]


def _person_img():
    img = np.full((200, 160, 3), 128, np.uint8)
    img[20:110, 40:100] = (40, 40, 220)          # BGR red top
    img[110:180, 40:100] = (200, 60, 20)         # BGR blue trousers
    return cv2.imencode(".png", img)[1].tobytes()


def test_find_people_in_case_evidence_by_clothing(ctx, monkeypatch):
    from backend.services import appearance_index
    monkeypatch.setenv("APPEARANCE_INDEX", "true")
    appearance_index.set_detector(FakePeople())
    try:
        r = up(ctx, [("crowd.png", _person_img(), "image/png")]).json()["results"][0]
        assert r["ok"]
        iid = ctx["inc"]["id"]
        hit = client.get(f"/api/v1/evidence-appearance?incident_id={iid}&upper=red&lower=blue", headers=ctx["op"]).json()
        mine = [x for x in hit["results"] if x["ref"] == r["ref"]]
        assert len(mine) == 1 and mine[0]["upper"] == "red" and mine[0]["lower"] == "blue"
        assert not [x for x in client.get(f"/api/v1/evidence-appearance?incident_id={iid}&upper=green", headers=ctx["op"]).json()["results"]
                    if x["ref"] == r["ref"]]
        crop = client.get(f"/api/v1/evidence-appearance/{mine[0]['id']}/crop", headers=ctx["op"])
        assert crop.status_code == 200 and crop.content[:2] == b"\xff\xd8"
        assert client.get(f"/api/v1/evidence-appearance?incident_id={iid}&upper=purple", headers=ctx["op"]).status_code == 400
        assert client.get(f"/api/v1/evidence-appearance?incident_id={iid}", headers=ctx["police"]).status_code in (403, 404)
    finally:
        appearance_index.set_detector(None)
