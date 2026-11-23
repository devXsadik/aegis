#!/usr/bin/env python3
"""Ingest load generator: N simulated cameras posting normalized events at a target rate.

    python scripts/loadtest/ingest_bench.py --cameras 200 --rate 400 --seconds 60 [--plate-hit 0.001]

Uses the cameras made by `python scripts/simulate.py seed` plus throwaway ids `lt_cam_<n>` (created
on the fly through the API is NOT done: register them first with --register, admin token needed,
or run against a test deployment that has them). Reports throughput, p50 / p95 / p99 latency and
errors per second. See docs/LOAD_TEST.md for the full plan."""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

PLATES = ["ঢাকা মেট্রো-খ ১১-২২৩৩", "ঢাকা মেট্রো-চ ৫১-৯০০১", "ঢাকা-হ ৩২-৭৭০০", "চট্ট মেট্রো-গ ১২-৩৪৫৬"]
TYPES = ["car", "microbus", "cng", "bus", "motorcycle", "pickup"]
COLORS = ["white", "black", "silver", "grey", "red", "blue", "green"]


def event(i: int, hit_rate: float) -> dict:
    hit = random.random() < hit_rate
    return {"type": "vehicle", "plate_text": "ঢাকা মেট্রো-গ ২৭-৪৫১৮" if hit else random.choice(PLATES)[:-4] + f"{random.randint(1000, 9999)}",
            "vehicle_type": random.choice(TYPES), "color": random.choice(COLORS),
            "attribute_confidences": {"plate": round(random.uniform(0.6, 0.99), 2), "type": 0.8, "color": 0.8},
            "direction": random.choice(["N", "S", "E", "W"]), "source": "loadtest", "track_id": str(i),
            "embedding": base64.b64encode(os.urandom(4 * 160)).decode(), "embedding_model": "hist-v1"}


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=os.getenv("AEGIS_API", "http://127.0.0.1:8000"))
    ap.add_argument("--cameras", type=int, default=50)
    ap.add_argument("--rate", type=float, default=100, help="events per second, all cameras together")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--plate-hit", type=float, default=0.0, help="share of events that hit the watchlist")
    ap.add_argument("--camera-prefix", default="sim_")
    a = ap.parse_args()
    import httpx
    key = os.environ.get("INTERNAL_API_KEY")
    if not key:
        sys.exit("INTERNAL_API_KEY not set")
    sim_cams = ["sim_gulshan1", "sim_gulshan2", "sim_banani", "sim_kakoli", "sim_mohakhali", "sim_tejgaon", "sim_badda", "sim_airport"]
    cams = (sim_cams * (a.cameras // len(sim_cams) + 1))[:a.cameras]
    lat, errors, codes = [], 0, {}
    sem = asyncio.Semaphore(a.concurrency)
    async with httpx.AsyncClient(base_url=f"{a.api.rstrip('/')}/api/v1", headers={"X-Internal-Key": key}, timeout=30) as c:
        async def one(i):
            nonlocal errors
            async with sem:
                t = time.perf_counter()
                try:
                    r = await c.post(f"/ingest/generic/{cams[i % len(cams)]}", json=event(i, a.plate_hit))
                    codes[r.status_code] = codes.get(r.status_code, 0) + 1
                    if r.status_code != 200:
                        errors += 1
                except Exception:
                    errors += 1
                lat.append((time.perf_counter() - t) * 1000)
        start, tasks, i = time.perf_counter(), [], 0
        while time.perf_counter() - start < a.seconds:
            due = int((time.perf_counter() - start) * a.rate)
            while i < due:
                tasks.append(asyncio.create_task(one(i)))
                i += 1
            await asyncio.sleep(0.005)
        await asyncio.gather(*tasks)
        took = time.perf_counter() - start
    lat.sort()
    q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))] if lat else 0  # noqa: E731
    print(f"sent {i} events in {took:.1f}s → {i / took:.1f}/s  (target {a.rate}/s, {a.cameras} cameras)")
    print(f"latency ms  p50 {q(0.5):.0f}  p95 {q(0.95):.0f}  p99 {q(0.99):.0f}  mean {statistics.mean(lat) if lat else 0:.0f}")
    print(f"errors {errors}  codes {codes}")


if __name__ == "__main__":
    asyncio.run(main())
