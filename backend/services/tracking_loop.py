"""Every TRACK_SWEEP_SECONDS: widen or close lookouts whose window passed (services/tracking.sweep),
and escalate notifications nobody acknowledged in time (services/escalation)."""

import asyncio
import logging
import os

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("HumanAnalysis")


def _once() -> dict:
    from backend.db.database import SessionLocal
    from backend.services import tracking
    db = SessionLocal()
    try:
        out = tracking.sweep(db)
        try:
            from backend.services.escalation import escalate_notifications
            out["escalated"] = escalate_notifications(db)
        except ImportError:
            pass
        db.commit()
        return out
    finally:
        db.close()


async def tracking_loop() -> None:
    every = float(os.getenv("TRACK_SWEEP_SECONDS", "15"))
    if every <= 0:
        return
    while True:
        await asyncio.sleep(every)
        try:
            out = await run_in_threadpool(_once)
            if any(out.values()):
                logger.info("Tracking sweep: %s", out)
        except Exception as e:  # noqa: BLE001
            logger.warning("Tracking sweep failed: %s", e)
