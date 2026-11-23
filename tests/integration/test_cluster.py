"""Several API workers sharing state through Redis (backend/services/cluster.py).

Starts a throwaway redis-server on a free port; skipped when redis-server is not installed."""
import asyncio
import json
import shutil
import socket
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server not installed")


@pytest.fixture()
def redis_url(monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import redis
    url = f"redis://127.0.0.1:{port}/0"
    for _ in range(50):
        try:
            redis.from_url(url).ping()
            break
        except Exception:
            time.sleep(0.05)
    from backend.services import cluster, ha
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setattr(ha, "_client", None)
    monkeypatch.setattr(ha, "_checked", False)
    monkeypatch.setattr(cluster, "_bin", None)
    yield url
    cluster.stop_subscriber()
    if cluster._sub_thread:
        cluster._sub_thread.join(timeout=3)
    ha._client, ha._checked, cluster._bin = None, False, None
    proc.terminate()
    proc.wait(timeout=5)


def test_beats_frames_and_rate_limits_are_shared(redis_url):
    from backend.api.system_routes import pipeline_cameras
    from backend.services import cluster
    assert cluster.enabled()
    cluster.put_beat("cam-x", {"fps": 7.5, "last_seen": "2026-11-23T10:00:00"}, "2026-11-23T10:00:00")
    assert pipeline_cameras()["cam-x"]["fps"] == 7.5
    assert cluster.pipeline_meta()["online"] is True
    cluster.drop_beat("cam-x")
    assert "cam-x" not in pipeline_cameras()
    cluster.put_frame("cam-y", b"\xff\xd8jpeg")
    assert cluster.get_frame("cam-y") == b"\xff\xd8jpeg" and "cam-y" in cluster.frame_cameras()
    assert [cluster.rate_check("1.2.3.4:login", 3, 60) for _ in range(4)] == [True, True, True, False]


def test_websocket_messages_reach_other_workers(redis_url):
    import redis
    from backend.services import cluster
    from backend.utils.websocket import manager
    got = []

    class FakeWS:
        async def send_text(self, text):
            got.append(json.loads(text))

    async def run():
        manager.active_connections.setdefault("user:99", set()).add(ws := FakeWS())
        cluster.start_subscriber(asyncio.get_running_loop())
        await asyncio.sleep(0.3)                     # subscribed
        other = {"c": "user:99", "m": {"kind": "test", "n": 1}, "n": "another-worker"}
        redis.from_url(redis_url).publish(cluster.WS_CHANNEL, json.dumps(other))
        own = {"c": "user:99", "m": {"kind": "echo"}, "n": cluster.NODE}   # own messages: already delivered
        redis.from_url(redis_url).publish(cluster.WS_CHANNEL, json.dumps(own))
        for _ in range(40):
            if got:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        manager.active_connections["user:99"].discard(ws)
    asyncio.run(run())
    assert got == [{"kind": "test", "n": 1}]


def test_only_one_worker_runs_a_background_job(redis_url):
    from backend.services import cluster
    runs = []

    async def job(tag):
        runs.append(tag)
        await asyncio.sleep(3600)

    async def run():
        a = asyncio.create_task(cluster.run_as_leader("t-job", lambda: job("a"), ttl=3, node="worker-a"))
        await asyncio.sleep(0.2)
        b = asyncio.create_task(cluster.run_as_leader("t-job", lambda: job("b"), ttl=3, node="worker-b"))
        await asyncio.sleep(0.5)
        assert runs == ["a"]
        a.cancel()                                          # worker a stops: lock released
        await asyncio.gather(a, return_exceptions=True)
        await asyncio.sleep(1.5)
        b.cancel()
        await asyncio.gather(b, return_exceptions=True)
    asyncio.run(run())
    assert runs == ["a", "b"]
