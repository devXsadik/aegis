#!/usr/bin/env python3
"""Aegis city simulator: the whole flow without real cameras.

    python scripts/simulate.py seed                      # 8 cameras on a Dhaka corridor, graph, areas,
                                                         # officers, a wanted person, watchlisted vehicles
    python scripts/simulate.py run [--speed 20] [--auto-confirm]
                                                         # a watchlisted Axio drives the corridor; a wanted
                                                         # person walks past two cameras; background traffic
    python scripts/simulate.py rtsp                      # optional: loop clips as RTSP for the real pipeline

What happens during `run` (watch it on Command map, Alerts, Incidents, an officer's Responders page):
  1. Gulshan-1: plate read + attributes → VEHICLE_MATCH "Confirmed vehicle match", incident opened,
     direction N from the in-frame track and camera heading → lookout on the next cameras north
  2. You (or --auto-confirm) confirm the alert → officers of each area are notified, ETA included
  3. Gulshan-2, Banani: re-acquired on the lookout → SAME incident, HANDOFF, trail grows
  4. Kakoli: plate hidden by a bus, attributes + appearance only → "Candidate vehicle" (only because
     a lookout covers that camera)
  5. Airport road: nothing → the lookout widens, then the track is marked lost
  Meanwhile: a wanted person (simulated face embeddings) is seen twice; random traffic fills Vehicle Search.

Events go through the real ingest API (POST /api/v1/ingest/simulator/{camera}) with the internal key,
so matching, tracking, notifications and audit are the production code paths.
Face images are NOT synthesised (no fake people): the simulated face camera sends embeddings of a
registered test identity, model "sim-face-1"."""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# Gulshan Avenue → Kemal Atatürk Ave → Banani → Kakoli → Airport Road (roughly north), heading = way the camera faces.
CAMERAS = [
    ("sim_gulshan1", "Gulshan-1 circle", 23.7807, 90.4167, 0, "Gulshan Avenue"),
    ("sim_gulshan2", "Gulshan-2 circle", 23.7925, 90.4141, 0, "Gulshan Avenue"),
    ("sim_banani", "Banani 11", 23.7937, 90.4045, 315, "Kemal Atatürk Avenue"),
    ("sim_kakoli", "Kakoli crossing", 23.7986, 90.4005, 0, "Airport Road"),
    ("sim_mohakhali", "Mohakhali flyover", 23.7781, 90.4006, 180, "Airport Road"),
    ("sim_tejgaon", "Tejgaon link", 23.7642, 90.3982, 180, "Tejgaon Link Road"),
    ("sim_badda", "Badda link", 23.7811, 90.4265, 90, "Progati Sarani"),
    ("sim_airport", "Khilkhet / Airport road", 23.8290, 90.4200, 0, "Airport Road"),
]
EDGES = [("sim_gulshan1", "sim_gulshan2"), ("sim_gulshan2", "sim_banani"), ("sim_banani", "sim_kakoli"),
         ("sim_kakoli", "sim_airport"), ("sim_gulshan1", "sim_mohakhali"), ("sim_mohakhali", "sim_tejgaon"),
         ("sim_gulshan1", "sim_badda"), ("sim_mohakhali", "sim_kakoli")]
TARGET = {"plate": "ঢাকা মেট্রো-গ ২৭-৪৫১৮", "vehicle_type": "car", "color": "white", "make_model": "toyota_axio"}
DECOYS = [("ঢাকা মেট্রো-খ ১১-২২৩৩", "microbus", "black", "toyota_noah"),
          ("ঢাকা মেট্রো-চ ৫১-৯০০১", "car", "silver", "toyota_premio"),
          ("ঢাকা মেট্রো-ঠ ১৪-০০৪২", "pickup", "white", "mitsubishi_l200"),
          ("ঢাকা-হ ৩২-৭৭০০", "cng", "green", "bajaj_re_cng")]
COLORS_BGR = {"white": (238, 238, 238), "black": (25, 25, 25), "silver": (192, 192, 192), "green": (40, 150, 40),
              "red": (40, 40, 200), "blue": (190, 90, 30)}
FACE_MODEL = "sim-face-1"


def api():
    import httpx
    base = os.getenv("AEGIS_API", "http://127.0.0.1:8000").rstrip("/")
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        sys.exit("INTERNAL_API_KEY is not set (.env)")
    return httpx.Client(base_url=f"{base}/api/v1", headers={"X-Internal-Key": key}, timeout=30)


def face_vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def render_vehicle(color: str, plate: str, vtype: str) -> bytes:
    """A simple synthetic vehicle image (body, windows, plate) — enough for colour and re-ID baselines."""
    img = np.full((180, 300, 3), (70, 70, 70), np.uint8)
    body = COLORS_BGR.get(color, (128, 128, 128))
    h0 = 50 if vtype in ("microbus", "bus", "truck") else 70
    cv2.rectangle(img, (20, h0), (280, 150), body, -1)
    cv2.rectangle(img, (60, h0 - 30), (240, h0), (40, 40, 40), -1)
    cv2.circle(img, (70, 152), 16, (15, 15, 15), -1)
    cv2.circle(img, (230, 152), 16, (15, 15, 15), -1)
    cv2.rectangle(img, (105, 120), (195, 142), (255, 255, 255), -1)
    cv2.putText(img, "".join(ch for ch in plate if ch.isdigit())[-6:], (110, 138), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
    noise = np.random.default_rng(len(plate)).integers(-6, 6, img.shape, dtype=np.int16)
    return cv2.imencode(".jpg", np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8))[1].tobytes()


# ——— seed ———

def seed() -> None:
    from backend.auth.auth import hash_password
    from backend.db.database import SessionLocal, init_db
    from backend.models.camera import Camera
    from backend.models.face_encoding import FaceEncoding
    from backend.models.jurisdiction import OfficerProfile
    from backend.models.known_person import KnownPerson
    from backend.models.tracking import CameraEdge
    from backend.models.user import User
    from backend.models.watchlist import WatchlistVehicle, WatchlistVehiclePhoto
    from backend.services import geo
    from backend.services.jurisdiction import locate
    from backend.services.matching.vehicle import embed_photo
    from backend.utils.at_rest import seal
    from clock import utcnow
    from core.analysis.bd_plate import canonical
    import hashlib
    import subprocess

    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_jurisdictions.py"), "--officers"], check=True,
                   env={**os.environ, "SEED_OFFICER_PASSWORD": os.getenv("SEED_OFFICER_PASSWORD", "sim-officer-2026")})
    init_db()
    db = SessionLocal()
    try:
        for cid, name, lat, lng, heading, road in CAMERAS:
            cam = db.query(Camera).filter(Camera.camera_id == cid).first() or Camera(camera_id=cid)
            cam.name, cam.location, cam.lat, cam.lng, cam.heading, cam.fov = name, name, lat, lng, heading, 70
            cam.road_name, cam.protocol, cam.vendor, cam.active = road, "webhook", "simulator", True
            cam.capabilities = json.dumps(["face", "anpr", "vehicle_attr"])
            j = locate(db, lat, lng)
            cam.jurisdiction_id = j.id if j else None
            db.add(cam)
        db.flush()
        pos = {c[0]: (c[2], c[3]) for c in CAMERAS}
        for a, b in EDGES:
            if not db.query(CameraEdge).filter_by(from_camera=a, to_camera=b).first():
                d = geo.haversine_m(*pos[a], *pos[b]) * 1.3
                db.add(CameraEdge(from_camera=a, to_camera=b, distance_m=round(d, 1), travel_s=round(d / 7.0, 1),
                                  bearing_deg=round(geo.bearing_deg(*pos[a], *pos[b]), 1), bidirectional=True))
        # Two people for the second-person rule, so the seeded watchlist is properly approved.
        pw = os.getenv("SIM_PASSWORD", "sim-pass-2026")
        users = {}
        for uname, role in (("sim_operator", "operator"), ("sim_supervisor", "supervisor")):
            u = db.query(User).filter(User.username == uname).first()
            if not u:
                u = User(username=uname, email=f"{uname}@example.invalid", hashed_password=hash_password(pw), role=role, is_active=True)
                db.add(u)
                db.flush()
            users[role] = u
        # all officers on duty for the demo
        for p in db.query(OfficerProfile):
            p.duty_status = "on_duty"
        now = utcnow()
        legal = dict(case_no="SIM-FIR 1/2026", issuing_authority="Simulation", legal_basis="Simulated warrant for the demo run",
                     starts_at=now - timedelta(minutes=5), expires_at=now + timedelta(days=30), wl_status="active",
                     requested_by=users["operator"].id, approved_by=users["supervisor"].id, approved_at=now)
        if not db.query(WatchlistVehicle).filter(WatchlistVehicle.ref == "V-SIMAXIO").first():
            v = WatchlistVehicle(ref="V-SIMAXIO", plate_raw=TARGET["plate"], plate_canonical=canonical(TARGET["plate"]),
                                 vehicle_type="car", color_primary="white", make_model="toyota_axio", risk_level="high",
                                 marks="Roof rack, dent on rear left door", offence="Armed robbery getaway car", **legal)
            db.add(v)
            db.flush()
            photo = render_vehicle("white", TARGET["plate"], "car")
            blob, enc = seal(photo)
            db.add(WatchlistVehiclePhoto(vehicle_id=v.id, image=blob, encrypted=enc, sha256=hashlib.sha256(photo).hexdigest(),
                                         embedding=embed_photo(photo)))
        if not db.query(KnownPerson).filter(KnownPerson.person_id == "P-SIM00001").first():
            p = KnownPerson(person_id="P-SIM00001", name="Simulated Wanted Person", category="criminal",
                            criminal_status="wanted", risk_level="high", offence="Robbery (simulation)", **legal)
            db.add(p)
            db.flush()
            for k in range(3):
                db.add(FaceEncoding(person_id=p.id, encoding=(face_vec(7) + 0.03 * face_vec(100 + k)).astype(np.float32).tobytes(),
                                    encoding_version=FACE_MODEL))
        db.commit()
        print(f"Seeded {len(CAMERAS)} cameras, {len(EDGES)} links, watchlist V-SIMAXIO and P-SIM00001.")
        print(f"Users: sim_operator / sim_supervisor (password {pw}); officers from seed_jurisdictions.")
    finally:
        db.close()


# ——— run ———

def path_points(exit_side: str, n: int = 12):
    end = {"top": (0.5, 0.02), "bottom": (0.5, 0.98), "left": (0.02, 0.5), "right": (0.98, 0.5)}[exit_side]
    start = (1 - end[0], 1 - end[1]) if exit_side in ("left", "right") else (end[0], 1 - end[1])
    return [(start[0] + (end[0] - start[0]) * i / (n - 1), start[1] + (end[1] - start[1]) * i / (n - 1)) for i in range(n)]


def exit_for(heading: float, bearing: float) -> str:
    """Which border a target leaves through, given its true bearing and the camera's heading."""
    rel = (bearing - heading) % 360
    return "top" if rel < 45 or rel >= 315 else "right" if rel < 135 else "bottom" if rel < 225 else "left"


def vehicle_event(cam, heading: float, bearing: float, *, plate=True, spec=TARGET, conf=0.93) -> dict:
    from core.tracking.direction import from_points
    d = from_points(path_points(exit_for(heading, bearing)), heading)
    ev = {"type": "vehicle", "vehicle_type": spec["vehicle_type"], "color": spec["color"],
          "make_model": spec["make_model"].replace("_", " ").title() if spec.get("make_model") else None,
          "attribute_confidences": {"type": 0.9, "color": 0.88, "model": 0.8, **({"plate": conf} if plate else {})},
          "direction": d.direction, "crop_image": base64.b64encode(render_vehicle(spec["color"], spec.get("plate", ""), spec["vehicle_type"])).decode(),
          "source": "simulator", "track_id": f"{cam}-{random.randint(1000, 9999)}"}
    if plate:
        ev["plate_text"] = spec["plate"]
    return ev


def post(client, cam: str, ev: dict) -> list:
    r = client.post(f"/ingest/simulator/{cam}", json=ev)
    if r.status_code != 200:
        print(f"  ! {cam}: HTTP {r.status_code} {r.text[:200]}")
        return []
    return [x for res in r.json()["results"] for x in res.get("results", [])]


def say(t0, msg):
    print(f"[{time.time() - t0:6.1f}s] {msg}")


def run(speed: float, auto_confirm: bool, rounds: int) -> None:
    import httpx
    from backend.services import geo
    client = api()
    pos = {c[0]: c for c in CAMERAS}
    t0 = time.time()
    sup = None
    if auto_confirm:
        base = os.getenv("AEGIS_API", "http://127.0.0.1:8000").rstrip("/")
        sup = httpx.Client(base_url=f"{base}/api/v1", timeout=30)
        r = sup.post("/auth/login", json={"username": "sim_supervisor", "password": os.getenv("SIM_PASSWORD", "sim-pass-2026")})
        if r.status_code != 200:
            say(t0, f"auto-confirm disabled: supervisor sign-in failed ({r.status_code})")
            sup = None

    def wait(a, b):
        d = geo.haversine_m(pos[a][2], pos[a][3], pos[b][2], pos[b][3]) * 1.3
        time.sleep(max(1.0, d / 7.0 / speed))          # ~25 km/h city speed, sped up

    def bearing(a, b):
        return geo.bearing_deg(pos[a][2], pos[a][3], pos[b][2], pos[b][3])

    def background(n=4):
        for _ in range(n):
            plate, vt, color, model = random.choice(DECOYS)
            cam = random.choice(CAMERAS)[0]
            post(client, cam, vehicle_event(cam, pos[cam][4], random.uniform(0, 360),
                                            spec={"plate": plate, "vehicle_type": vt, "color": color, "make_model": model}))

    for rnd in range(rounds):
        say(t0, f"— round {rnd + 1}: target V-SIMAXIO ({TARGET['plate']}) leaves Gulshan-1 heading north —")
        route = ["sim_gulshan1", "sim_gulshan2", "sim_banani"]
        for i, cam in enumerate(route):
            nxt = route[i + 1] if i + 1 < len(route) else "sim_kakoli"
            res = post(client, cam, vehicle_event(cam, pos[cam][4], bearing(cam, nxt)))
            for r in res:
                say(t0, f"{pos[cam][1]}: {r.get('level')} ({r.get('severity')}) alert #{r.get('alert_id')} {r.get('status')}")
                if sup and r.get("alert_id") and i == 0:
                    sup.put(f"/alerts/{r['alert_id']}/acknowledge", json={"acknowledged": True, "note": "Simulator auto-confirm"})
                    say(t0, "  operator confirmed → officers notified")
            background()
            wait(cam, nxt)
        res = post(client, "sim_kakoli", vehicle_event("sim_kakoli", 0, bearing("sim_kakoli", "sim_airport"), plate=False))
        say(t0, "Kakoli (plate hidden): " + (", ".join(f"{r.get('level')} #{r.get('alert_id')}" for r in res) or "no alert (no lookout here)"))
        say(t0, "Airport road: target not seen — the lookout widens, then the track is marked lost (sweep every 15 s)")

        say(t0, "— wanted person P-SIM00001 walks past Mohakhali, then Tejgaon —")
        for cam in ("sim_mohakhali", "sim_tejgaon"):
            v = face_vec(7) + 0.05 * face_vec(int(time.time()) % 1000)
            ev = {"type": "face", "embedding": base64.b64encode((v / np.linalg.norm(v)).astype(np.float32).tobytes()).decode(),
                  "embedding_model": FACE_MODEL, "quality": 0.8, "direction": "S", "source": "simulator"}
            for r in post(client, cam, ev):
                say(t0, f"{pos[cam][1]}: face {r.get('person_id')} {r.get('similarity')} → alert #{r.get('alert_id')}")
            time.sleep(max(1.0, 60 / speed))
        background(8)
    say(t0, "Done. Open Command map, Alerts and Incidents; officers see notifications on Responders.")


def rtsp() -> None:
    """Loop every clip in data/demo/clips as rtsp://localhost:8554/<camera> (needs MediaMTX running and
    ffmpeg). Then point the cameras' stream URLs at them and run `python main.py --multi`."""
    import shutil
    import subprocess
    clips = sorted((ROOT / "data" / "demo" / "clips").glob("*.mp4"))
    if not clips:
        sys.exit("No clips in data/demo/clips (add MP4 files of street scenes first).")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    print("Start MediaMTX first:  docker run --rm -p 8554:8554 bluenviron/mediamtx")
    procs = []
    for (cid, *_), clip in zip(CAMERAS, clips * len(CAMERAS)):
        url = f"rtsp://127.0.0.1:8554/{cid}"
        procs.append(subprocess.Popen(["ffmpeg", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", str(clip),
                                       "-c", "copy", "-f", "rtsp", url]))
        print(f"{cid} ← {clip.name} at {url}")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    r = sub.add_parser("run")
    r.add_argument("--speed", type=float, default=20, help="time compression (20 = 20x faster than real travel)")
    r.add_argument("--auto-confirm", action="store_true", help="confirm the first alert as sim_supervisor")
    r.add_argument("--rounds", type=int, default=1)
    sub.add_parser("rtsp")
    a = ap.parse_args()
    if a.cmd == "seed":
        seed()
    elif a.cmd == "run":
        run(a.speed, a.auto_confirm, a.rounds)
    else:
        rtsp()
