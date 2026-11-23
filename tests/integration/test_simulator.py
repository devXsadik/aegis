"""The city simulator drives the full flow through the real ingest API (spec 16):
detect → match → direction → lookout → re-acquire on the same incident → candidate inside the lookout."""
import importlib.util
import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal
from backend.models.bolo import Bolo
from backend.models.tracking import CrossCameraTrack

ROOT = Path(__file__).resolve().parents[2]


def _sim():
    spec = importlib.util.spec_from_file_location("simulate", ROOT / "scripts" / "simulate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_simulated_drive(monkeypatch):
    sim = _sim()
    monkeypatch.setenv("ALERT_DEDUPE_SECONDS", "0")
    client = TestClient(app, base_url="http://testserver/api/v1")
    client.headers["X-Internal-Key"] = os.environ["INTERNAL_API_KEY"]
    monkeypatch.setattr(sim, "api", lambda: client)
    monkeypatch.setattr(sim.time, "sleep", lambda s: None)
    sim.seed()
    sim.seed()                                     # idempotent
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    sim.run(speed=1000, auto_confirm=False, rounds=1)
    out = "\n".join(printed)
    assert "Gulshan-1 circle: confirmed (critical)" in out
    assert "Kakoli (plate hidden): candidate" in out
    assert "face P-SIM00001" in out
    db = SessionLocal()
    t = db.query(CrossCameraTrack).filter(CrossCameraTrack.target_ref == "V-SIMAXIO").order_by(CrossCameraTrack.id.desc()).first()
    cams = [h.camera_id for h in t.hops]
    assert cams[:3] == ["sim_gulshan1", "sim_gulshan2", "sim_banani"] and t.incident_id
    assert all(h.direction for h in t.hops[:3])
    assert db.query(Bolo).filter(Bolo.cross_track_id == t.id).count() >= 2
    db.close()
