import time
import threading
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Tuple


class InMemoryRateLimiter:
    def __init__(self):
        self._buckets: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            cutoff = now - window_seconds
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= max_requests:
                return False
            bucket.append(now)
            return True


_limiter = InMemoryRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Protect auth + internal event paths under /api/v1."""

    _PROTECTED = (
        "/api/v1/auth/login",
        "/api/v1/auth/users",
        "/api/v1/events/internal",
        "/api/v1/alerts/dispatch",
    )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self._PROTECTED):
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{path}"
            limit = 10 if "login" in path else 60
            if not _limiter.check(key, max_requests=limit, window_seconds=60):
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
        return await call_next(request)

