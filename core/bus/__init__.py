"""Event bus between the stages (ingest → detect → match → track → alert).

    bus = get_bus()                       # Redis Streams if BUS_URL / REDIS_URL is set, else in-process
    bus.publish("detections", {...})
    for msg_id, data in bus.read("detections", group="matcher", consumer="m1"): ...; bus.ack(...)

Redis Streams with consumer groups: any stage scales by starting more consumers in the same
group; messages a dead consumer held are re-claimed after `claim_idle_ms`. Payloads are small
JSON (metadata + references to frames in object storage), never raw frames."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Tuple

STREAMS = ("frames", "detections", "matches", "tracks", "bolo", "alerts")
PREFIX = os.getenv("BUS_PREFIX", "aegis")


class Bus:
    def publish(self, stream: str, data: dict, maxlen: int = 100_000) -> str:
        raise NotImplementedError

    def read(self, stream: str, group: str, consumer: str, count: int = 50,
             block_ms: int = 1000) -> List[Tuple[str, dict]]:
        raise NotImplementedError

    def ack(self, stream: str, group: str, *ids: str) -> None:
        raise NotImplementedError

    def length(self, stream: str) -> int:
        raise NotImplementedError


class MemoryBus(Bus):
    """In-process bus for one machine and for tests: each group sees every message once."""

    def __init__(self):
        self._lock = threading.Condition()
        self._log: Dict[str, List[Tuple[str, dict]]] = defaultdict(list)
        self._pos: Dict[Tuple[str, str], int] = defaultdict(int)
        self._pending: Dict[Tuple[str, str], Dict[str, dict]] = defaultdict(dict)
        self._seq = 0

    def publish(self, stream, data, maxlen=100_000):
        with self._lock:
            self._seq += 1
            mid = f"{int(time.time() * 1000)}-{self._seq}"
            log = self._log[stream]
            log.append((mid, json.loads(json.dumps(data, default=str))))
            if len(log) > maxlen:
                drop = len(log) - maxlen
                del log[:drop]
                for key in list(self._pos):
                    if key[0] == stream:
                        self._pos[key] = max(0, self._pos[key] - drop)
            self._lock.notify_all()
            return mid

    def read(self, stream, group, consumer, count=50, block_ms=1000):
        key = (stream, group)
        deadline = time.time() + block_ms / 1000
        with self._lock:
            while self._pos[key] >= len(self._log[stream]):
                left = deadline - time.time()
                if left <= 0:
                    return []
                self._lock.wait(left)
            start = self._pos[key]
            batch = self._log[stream][start:start + count]
            self._pos[key] = start + len(batch)
            for mid, d in batch:
                self._pending[key][mid] = d
            return list(batch)

    def ack(self, stream, group, *ids):
        with self._lock:
            for i in ids:
                self._pending[(stream, group)].pop(i, None)

    def length(self, stream):
        return len(self._log[stream])

    def pending(self, stream, group) -> int:
        return len(self._pending[(stream, group)])


class RedisStreamBus(Bus):
    def __init__(self, url: str, claim_idle_ms: int = 60_000):
        import redis
        self.r = redis.Redis.from_url(url, decode_responses=True)
        self.claim_idle_ms = claim_idle_ms
        self._groups = set()

    def _key(self, stream):
        return f"{PREFIX}:{stream}"

    def _ensure(self, stream, group):
        if (stream, group) in self._groups:
            return
        try:
            self.r.xgroup_create(self._key(stream), group, id="0", mkstream=True)
        except Exception as e:  # BUSYGROUP: already there
            if "BUSYGROUP" not in str(e):
                raise
        self._groups.add((stream, group))

    def publish(self, stream, data, maxlen=100_000):
        return self.r.xadd(self._key(stream), {"d": json.dumps(data, default=str)}, maxlen=maxlen, approximate=True)

    def read(self, stream, group, consumer, count=50, block_ms=1000):
        self._ensure(stream, group)
        out = []
        # Take over messages a crashed consumer never acknowledged.
        try:
            claimed = self.r.xautoclaim(self._key(stream), group, consumer, self.claim_idle_ms, "0-0", count=count)
            for mid, fields in (claimed[1] if claimed else []):
                if fields:
                    out.append((mid, json.loads(fields["d"])))
        except Exception:
            pass
        if len(out) < count:
            res = self.r.xreadgroup(group, consumer, {self._key(stream): ">"}, count=count - len(out), block=block_ms)
            for _, msgs in res or []:
                out += [(mid, json.loads(f["d"])) for mid, f in msgs]
        return out

    def ack(self, stream, group, *ids):
        if ids:
            self.r.xack(self._key(stream), group, *ids)

    def length(self, stream):
        return self.r.xlen(self._key(stream))


_bus: Optional[Bus] = None
_bus_lock = threading.Lock()


def get_bus() -> Bus:
    global _bus
    with _bus_lock:
        if _bus is None:
            url = os.getenv("BUS_URL") or os.getenv("REDIS_URL") or ""
            if url.startswith("redis"):
                try:
                    b = RedisStreamBus(url)
                    b.r.ping()
                    _bus = b
                except Exception:
                    _bus = MemoryBus()
            else:
                _bus = MemoryBus()
        return _bus


def set_bus(bus: Optional[Bus]) -> None:
    """Tests and single-process runs can install their own bus."""
    global _bus
    _bus = bus


def drain(bus: Bus, stream: str, group: str, consumer: str, handler, max_batches: int = 100) -> int:
    """Run `handler(data)` for everything waiting (no blocking); ack each one that succeeded."""
    n = 0
    for _ in range(max_batches):
        batch = bus.read(stream, group, consumer, block_ms=0)
        if not batch:
            break
        for mid, data in batch:
            handler(data)
            bus.ack(stream, group, mid)
            n += 1
    return n


def iter_forever(bus: Bus, stream: str, group: str, consumer: str) -> Iterator[Tuple[str, dict]]:
    while True:
        for item in bus.read(stream, group, consumer, block_ms=2000):
            yield item


__all__ = ["Bus", "MemoryBus", "RedisStreamBus", "get_bus", "set_bus", "drain", "iter_forever", "STREAMS"]
