"""Seed Dhaka jurisdictions (simplified thana boxes) and demo police officers.

    python scripts/seed_jurisdictions.py               # areas only
    python scripts/seed_jurisdictions.py --officers    # areas + 2 officers per thana

Boundaries are SIMPLIFIED rectangles around each DMP thana, good enough for demos and tests.
Replace them with official BBS / LGED boundaries before any real deployment (PUT /jurisdictions/{id}).
Idempotent: areas are matched by code, officers by username. Officer passwords are random and
printed once; set SEED_OFFICER_PASSWORD to choose one."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.jurisdiction import Jurisdiction, OfficerJurisdiction, OfficerProfile  # noqa: E402
from backend.models.user import User  # noqa: E402


def box(lat0, lng0, lat1, lng1):
    return {"type": "Polygon", "coordinates": [[[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]]}


# code, English, Bangla, (lat0, lng0, lat1, lng1)
THANAS = [
    ("DMP-UTTARA", "Uttara", "উত্তরা", (23.855, 90.380, 23.890, 90.410)),
    ("DMP-MIRPUR", "Mirpur", "মিরপুর", (23.795, 90.345, 23.830, 90.375)),
    ("DMP-CANTONMENT", "Cantonment", "ক্যান্টনমেন্ট", (23.810, 90.385, 23.850, 90.410)),
    ("DMP-BANANI", "Banani", "বনানী", (23.785, 90.395, 23.800, 90.410)),
    ("DMP-GULSHAN", "Gulshan", "গুলশান", (23.775, 90.410, 23.800, 90.430)),
    ("DMP-BADDA", "Badda", "বাড্ডা", (23.770, 90.430, 23.800, 90.450)),
    ("DMP-TEJGAON", "Tejgaon", "তেজগাঁও", (23.755, 90.385, 23.785, 90.405)),
    ("DMP-MOHAMMADPUR", "Mohammadpur", "মোহাম্মদপুর", (23.750, 90.345, 23.775, 90.370)),
    ("DMP-DHANMONDI", "Dhanmondi", "ধানমন্ডি", (23.735, 90.365, 23.755, 90.385)),
    ("DMP-SHAHBAG", "Shahbagh", "শাহবাগ", (23.730, 90.388, 23.745, 90.400)),
    ("DMP-RAMNA", "Ramna", "রমনা", (23.740, 90.400, 23.755, 90.415)),
    ("DMP-MOTIJHEEL", "Motijheel", "মতিঝিল", (23.720, 90.410, 23.735, 90.425)),
    ("DMP-LALBAGH", "Lalbagh", "লালবাগ", (23.710, 90.380, 23.725, 90.395)),
    ("DMP-KOTWALI", "Kotwali", "কোতোয়ালী", (23.700, 90.400, 23.712, 90.415)),
]

RANKS = ["Inspector", "SI", "ASI", "Constable"]
DUTY = ["available", "on_duty", "busy", "off_duty"]
FIRST = ["Rahim", "Karim", "Nasrin", "Farhana", "Sabbir", "Tanvir", "Ayesha", "Mahmud", "Shirin", "Imran",
         "Rafiq", "Sumaiya", "Jahid", "Nusrat", "Habib", "Mitu", "Arif", "Ruma", "Kamal", "Lipi",
         "Sohel", "Rina", "Faisal", "Tania", "Jamal", "Shapla", "Rashed", "Moni"]
LAST = ["Hossain", "Ahmed", "Islam", "Rahman", "Chowdhury", "Uddin", "Akter", "Khan", "Sarkar", "Mia"]


def upsert_area(db, code, en, bn, level, parent_id, geojson):
    j = db.query(Jurisdiction).filter(Jurisdiction.code == code).first()
    if not j:
        j = Jurisdiction(code=code)
        db.add(j)
    j.name_en, j.name_bn, j.level, j.parent_id = en, bn, level, parent_id
    j.geojson = json.dumps(geojson) if geojson else None
    db.flush()
    return j


def seed(with_officers: bool) -> None:
    init_db()
    db = SessionLocal()
    try:
        div = upsert_area(db, "DIV-DHAKA", "Dhaka Division", "ঢাকা বিভাগ", "division", None,
                          box(23.60, 90.20, 24.00, 90.60))
        dmp = upsert_area(db, "DIST-DMP", "Dhaka Metropolitan (DMP)", "ঢাকা মহানগর", "district", div.id,
                          box(23.69, 90.33, 23.90, 90.46))
        thanas = [upsert_area(db, c, en, bn, "thana", dmp.id, box(*b)) for c, en, bn, b in THANAS]
        db.commit()
        print(f"Areas: 1 division, 1 district, {len(thanas)} thanas")

        if not with_officers:
            return
        from backend.auth.auth import hash_password
        password = os.getenv("SEED_OFFICER_PASSWORD") or secrets.token_urlsafe(12)
        made = 0
        for i, t in enumerate(thanas):
            for k in range(2):
                n = i * 2 + k
                username = f"officer_{t.code.split('-')[1].lower()}_{k + 1}"
                u = db.query(User).filter(User.username == username).first()
                if not u:
                    u = User(username=username, email=f"{username}@police.example.invalid",
                             hashed_password=hash_password(password), role="police", is_active=True,
                             phone=f"+88017{10000000 + n * 7919:08d}"[:14])
                    db.add(u)
                    db.flush()
                    made += 1
                prof = db.get(OfficerProfile, u.id) or OfficerProfile(user_id=u.id)
                prof.full_name = f"{FIRST[n % len(FIRST)]} {LAST[n % len(LAST)]}"
                prof.rank = RANKS[(n + k) % len(RANKS)]
                prof.badge_no = f"DMP-{1000 + n}"
                prof.station_id = t.id
                prof.duty_status = DUTY[n % len(DUTY)]
                db.merge(prof)
                if not db.query(OfficerJurisdiction).filter_by(user_id=u.id, jurisdiction_id=t.id).first():
                    db.add(OfficerJurisdiction(user_id=u.id, jurisdiction_id=t.id))
        db.commit()
        print(f"Officers: {len(thanas) * 2} ({made} new)")
        if made:
            print(f"New officer password: {password}  (change it, or set SEED_OFFICER_PASSWORD)")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--officers", action="store_true", help="also create 2 demo officers per thana")
    seed(ap.parse_args().officers)
