"""State shared by several API workers or machines, through Redis (REDIS_URL).

Without Redis everything stays in this process, so exactly one API worker must run (the old
behaviour). With Redis:

* WebSocket messages (alerts, status, incidents, per-user notifications) are delivered to this
  worker's clients at once and published for the other workers, which deliver them to theirs.
* Camera heartbeats and live analytics are a Redis hash, so every worker sees every camera.
* Live frames: the latest JPEG per camera is a Redis key; workers with viewers of that camera
  fetch it when told a new one arrived.
* Rate limits count per minute in Redis, so a client cannot multiply its budget by worker count.
* Background jobs (escalation, maintenance, health watch, tracking) run on one worker only:
  whoever holds a renewing Redis lock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
import uuid
from typing import Awaitable, Callable, Optional

from backend.services.ha import get_redis

logger = logging.getLogger(__name__)

NODE = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
WS_CHANNEL = "aegis:ws"
FRAME_CHANNEL = "aegis:frame"
BEATS_KEY = "aegis:beats"
ANALYTICS_KEY = "aegis:analytics"
STATUS_KEY = "aegis:pipeline"
FRAME_TTL_MS = 15_000


def redis():
    return get_redis()


def enabled() -> bool:
    return redis() is not None


_bin = None


def redis_bin():
    """A second client without response decoding, for JPEG bytes."""
    global _bin
    if _bin is None and enabled():
        import redis as redis_lib
        _bin = redis_lib.from_url(os.environ["REDIS_URL"], socket_connect_timeout=1.5)
    return _bin


# ——— WebSocket fan-out ———

def publish_ws(message: dict, channel: str) -> None:
    r = redis()
    if r is None:
        return
    try:
        r.publish(WS_CHANNEL, json.dumps({"c": channel, "m": message, "n": NODE}, default=str))
    except Exception as e:  # noqa: BLE001 - delivery to this worker's clients already happened
        logger.warning("Redis publish failed: %s", e)


# ——— heartbeats, analytics ———

def put_beat(camera_id: str, meta: dict, now_iso: str) -> None:
    r = redis()
    if r is None:
        return
    try:
        p = r.pipeline()
        p.hset(BEATS_KEY, camera_id, json.dumps(meta, default=str))
        p.hset(STATUS_KEY, mapping={"online": "1", "last_heartbeat": now_iso})
        p.execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis heartbeat write failed: %s", e)


def drop_beat(camera_id: str) -> None:
    r = redis()
    if r is not None:
        try:
            r.hdel(BEATS_KEY, camera_id)
            r.hdel(ANALYTICS_KEY, camera_id)
        except Exception:  # noqa: BLE001
            pass


def _hash(key: str) -> Optional[dict]:
    r = redis()
    if r is None:
        return None
    try:
        return {k: json.loads(v) for k, v in r.hgetall(key).items()}
    except Exception:  # noqa: BLE001
        return None


def beats() -> Optional[dict]:
    """camera -> heartbeat meta from every worker, or None without Redis."""
    return _hash(BEATS_KEY)


def pipeline_meta() -> Optional[dict]:
    r = redis()
    if r is None:
        return None
    try:
        m = r.hgetall(STATUS_KEY)
    except Exception:  # noqa: BLE001
        return None
    return {"online": m.get("online") == "1", "last_heartbeat": m.get("last_heartbeat")}


def put_analytics(camera_id: str, data: dict) -> None:
    r = redis()
    if r is not None:
        try:
            r.hset(ANALYTICS_KEY, camera_id, json.dumps(data, default=str))
        except Exception:  # noqa: BLE001
            pass


def analytics() -> Optional[dict]:
    return _hash(ANALYTICS_KEY)


# ——— live frames ———

def put_frame(camera_id: str, jpeg: bytes) -> None:
    rb = redis_bin()
    if rb is None:
        return
    try:
        rb.set(f"aegis:frame:{camera_id}", jpeg, px=FRAME_TTL_MS)
        redis().publish(FRAME_CHANNEL, f"{camera_id}|{NODE}")
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis frame write failed: %s", e)


def get_frame(camera_id: str) -> Optional[bytes]:
    rb = redis_bin()
    if rb is None:
        return None
    try:
        return rb.get(f"aegis:frame:{camera_id}")
    except Exception:  # noqa: BLE001
        return None


def frame_cameras() -> list:
    rb = redis_bin()
    if rb is None:
        return []
    try:
        return [k.decode().split(":", 2)[2] for k in rb.scan_iter("aegis:frame:*", count=500)]
    except Exception:  # noqa: BLE001
        return []


# ——— rate limits ———

def rate_check(key: str, max_requests: int, window_seconds: int) -> Optional[bool]:
    """True/False from Redis (fixed one-window counter), None when Redis is not in use."""
    r = redis()
    if r is None:
        return None
    try:
        k = f"aegis:rl:{key}:{int(time.time() // window_seconds)}"
        p = r.pipeline()
        p.incr(k)
        p.expire(k, window_seconds + 1)
        n, _ = p.execute()
        return int(n) <= max_requests
    except Exception:  # noqa: BLE001
        return None


# ——— one worker runs the background jobs ———

async def run_as_leader(name: str, job: Callable[[], Awaitable[None]], ttl: int = 30,
                        node: Optional[str] = None) -> None:
    """Run `job` only while this worker holds the lock `name`; another worker takes over within
    `ttl` seconds if this one dies. Without Redis, just run it."""
    r = redis()
    if r is None:
        await job()
        return
    key = f"aegis:leader:{name}"
    me = node or NODE
    task: Optional[asyncio.Task] = None
    try:
        while True:
            try:
                mine = bool(r.set(key, me, nx=True, ex=ttl)) or r.get(key) == me
                if mine:
                    r.expire(key, ttl)
            except Exception:  # noqa: BLE001 - Redis blip: keep the current state
                mine = task is not None
            if mine and task is None:
                logger.info("Background job %s runs on this worker (%s)", name, me)
                task = asyncio.create_task(job())
            elif not mine and task is not None:
                logger.warning("Background job %s moved to another worker", name)
                task.cancel()
                task = None
            if task is not None and task.done():
                if not task.cancelled() and task.exception():
                    logger.error("Background job %s stopped: %s", name, task.exception())
                task = None              # restart it next round
            await asyncio.sleep(ttl / 3)
    finally:
        if task is not None:
            task.cancel()
        try:
            if r.get(key) == me:
                r.delete(key)
        except Exception:  # noqa: BLE001
            pass


# ——— subscriber: messages from the other workers ———

_sub_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def start_subscriber(loop: asyncio.AbstractEventLoop) -> None:
    global _sub_thread
    if not enabled() or (_sub_thread and _sub_thread.is_alive()):
        return
    _stop.clear()
    _sub_thread = threading.Thread(target=_listen, args=(loop,), name="cluster-sub", daemon=True)
    _sub_thread.start()


def stop_subscriber() -> None:
    _stop.set()


def _listen(loop: asyncio.AbstractEventLoop) -> None:
    import redis as redis_lib
    from backend.utils.websocket import manager
    while not _stop.is_set():
        try:
            client = redis_lib.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_connect_timeout=2)
            ps = client.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(WS_CHANNEL, FRAME_CHANNEL)
            while not _stop.is_set():
                msg = ps.get_message(timeout=1.0)
                if not msg:
                    continue
                if msg["channel"] == WS_CHANNEL:
                    data = json.loads(msg["data"])
                    if data.get("n") != NODE:
                        asyncio.run_coroutine_threadsafe(manager.broadcast_local(data["m"], data["c"]), loop)
                elif msg["channel"] == FRAME_CHANNEL:
                    cam, _, node = msg["data"].partition("|")
                    if node != NODE:
                        _remote_frame(cam, loop)
            ps.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("Cluster subscriber reconnecting: %s", e)
            _stop.wait(2.0)


def _remote_frame(camera_id: str, loop) -> None:
    from backend.api import stream_routes
    if not stream_routes.has_viewers(camera_id):
        stream_routes.mark_remote(camera_id)
        return
    data = get_frame(camera_id)
    if data:
        loop.call_soon_threadsafe(stream_routes.store_frame, camera_id, data)


def startup_lock(name: str = "startup", timeout: int = 300):
    """Serialises one-time start-up work (schema upgrade, seeding) across workers starting
    together. Without Redis: a no-op context."""
    import contextlib
    r = redis()
    if r is None:
        return contextlib.nullcontext()
    return r.lock(f"aegis:lock:{name}", timeout=timeout, blocking_timeout=timeout)
