#!/usr/bin/env python3
"""Matching worker: consumes normalized events from the bus and runs the matchers.

Run as many as you like (same group = shared work):
    INGEST_ASYNC=true BUS_URL=redis://localhost:6379/0 python scripts/worker.py --consumer m1
The API then only validates and queues (POST /api/v1/ingest/...), and these do the matching.
Without a Redis bus, the API matches inline and this script is not needed."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.services import event_router  # noqa: E402
from core.bus import get_bus, RedisStreamBus  # noqa: E402
from core.ingest.events import NormalizedEvent  # noqa: E402

log = logging.getLogger("aegis.worker")
_stop = False


def _sigterm(*_):
    global _stop
    _stop = True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--group", default="matcher")
    ap.add_argument("--consumer", default=f"{socket.gethostname()}-{os.getpid()}")
    ap.add_argument("--batch", type=int, default=50)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    import backend.services.matching  # noqa: F401  registers the matchers
    bus = get_bus()
    if not isinstance(bus, RedisStreamBus):
        log.error("No Redis bus (set BUS_URL=redis://…). In-process mode needs no worker.")
        sys.exit(2)
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    log.info("worker %s in group %s", args.consumer, args.group)
    while not _stop:
        batch = bus.read("detections", args.group, args.consumer, count=args.batch, block_ms=2000)
        if not batch:
            continue
        db = SessionLocal()
        try:
            done = []
            for mid, data in batch:
                try:
                    event_router.handle(db, NormalizedEvent.from_dict(data))
                    done.append(mid)
                except Exception as e:          # a bad event is acked and logged, not retried forever
                    log.exception("event %s failed: %s", data.get("event_id"), e)
                    done.append(mid)
            db.commit()
            bus.ack("detections", args.group, *done)
        finally:
            db.close()


if __name__ == "__main__":
    main()
