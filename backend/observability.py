"""Operational visibility: request metrics, request ids, JSON logs and (optional) error tracking.

* Every response carries X-Request-ID (taken from the proxy's header when present); with
  LOG_FORMAT=json each log line is one JSON object with that id, ready for Loki / ELK / CloudWatch.
* Request counts and latency per route template feed /api/v1/metrics (Prometheus). Counters are
  per worker process; scrape every worker, or sum them in Prometheus.
* SENTRY_DSN turns on error tracking (pip install sentry-sdk). Nothing personal is sent: no
  request bodies, cookies, auth headers, query strings or user details, only stack traces and the
  route template.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_lock = threading.Lock()
_count: dict = defaultdict(int)                 # (method, route, status_class) -> n
_hist: dict = defaultdict(lambda: [0] * (len(BUCKETS) + 1))   # (method, route) -> cumulative-able counts
_sum: dict = defaultdict(float)
_in_flight = 0


class RequestContextMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware): adds X-Request-ID and records latency; streams untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        global _in_flight
        rid = next((v.decode() for k, v in scope.get("headers", ()) if k == b"x-request-id"), "")[:64] or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        start = time.perf_counter()
        status = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        with _lock:
            _in_flight += 1
        try:
            await self.app(scope, receive, _send)
        finally:
            with _lock:
                _in_flight -= 1
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            if not path.endswith(("/live", "/ws/alerts", "/ws/incidents", "/ws/notifications")):   # long streams skew latency
                observe(scope.get("method", "GET"), path, status["code"], time.perf_counter() - start)
            request_id.reset(token)


def observe(method: str, route: str, status: int, seconds: float) -> None:
    with _lock:
        _count[(method, route, f"{status // 100}xx")] += 1
        h = _hist[(method, route)]
        for i, b in enumerate(BUCKETS):
            if seconds <= b:
                h[i] += 1
                break
        else:
            h[-1] += 1
        _sum[(method, route)] += seconds


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prometheus_lines() -> list:
    with _lock:
        count, hist, sums, flying = dict(_count), {k: list(v) for k, v in _hist.items()}, dict(_sum), _in_flight
    lines = ["# HELP aegis_http_requests_total HTTP requests by route template and status class",
             "# TYPE aegis_http_requests_total counter"]
    for (m, r, s), n in sorted(count.items()):
        lines.append(f'aegis_http_requests_total{{method="{m}",route="{_esc(r)}",status="{s}"}} {n}')
    lines += ["# HELP aegis_http_request_duration_seconds Request latency",
              "# TYPE aegis_http_request_duration_seconds histogram"]
    for (m, r), h in sorted(hist.items()):
        acc = 0
        for b, n in zip(BUCKETS, h):
            acc += n
            lines.append(f'aegis_http_request_duration_seconds_bucket{{method="{m}",route="{_esc(r)}",le="{b}"}} {acc}')
        acc += h[-1]
        lines.append(f'aegis_http_request_duration_seconds_bucket{{method="{m}",route="{_esc(r)}",le="+Inf"}} {acc}')
        lines.append(f'aegis_http_request_duration_seconds_count{{method="{m}",route="{_esc(r)}"}} {acc}')
        lines.append(f'aegis_http_request_duration_seconds_sum{{method="{m}",route="{_esc(r)}"}} {sums[(m, r)]:.6f}')
    lines += ["# HELP aegis_http_in_flight Requests being served now", "# TYPE aegis_http_in_flight gauge",
              f"aegis_http_in_flight {flying}"]
    return lines


def reset() -> None:
    with _lock:
        _count.clear()
        _hist.clear()
        _sum.clear()


# ——— logs ———

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
               "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
               "request_id": request_id.get()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging() -> None:
    if os.getenv("LOG_FORMAT", "").lower() != "json":
        return
    fmt = JsonFormatter()
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for h in root.handlers:
        h.setFormatter(fmt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            h.setFormatter(fmt)


# ——— error tracking ———

_SECRET_HEADERS = {"authorization", "cookie", "x-internal-key", "x-camera-token", "set-cookie"}


def scrub_event(event: dict, hint=None) -> dict:
    """Keep the stack trace and route; drop anything that could identify a person or a secret."""
    req = event.get("request") or {}
    for k in ("data", "cookies", "query_string", "env"):
        req.pop(k, None)
    if isinstance(req.get("headers"), dict):
        req["headers"] = {k: v for k, v in req["headers"].items() if k.lower() not in _SECRET_HEADERS}
    if "url" in req:
        req["url"] = req["url"].split("?")[0]
    event.pop("user", None)
    for exc in (event.get("exception") or {}).get("values", []):          # local variables can hold faces, plates
        for frame in (exc.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)
    event.setdefault("tags", {})["request_id"] = request_id.get()
    return event


def init_sentry() -> bool:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False
    sentry_sdk.init(dsn=dsn, environment=os.getenv("ENVIRONMENT", "development"),
                    release=os.getenv("AEGIS_RELEASE") or None, send_default_pii=False, include_local_variables=False,
                    traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0") or 0), before_send=scrub_event)
    return True
