"""Small process-local request limiter for the temporary demo deployment."""
from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock
from time import monotonic
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


Rule = tuple[str, int, Callable[[str, str], bool]]


class DemoRateLimitMiddleware(BaseHTTPMiddleware):
    """Limit expensive route groups by the direct peer address.

    This is intentionally process-local. It is suitable for one temporary demo
    process only; a multi-worker or multi-instance deployment needs host-level
    or shared rate limiting as well.
    """

    def __init__(self, app, *, window_seconds: int, simulation: int, analysis: int, ml: int) -> None:
        super().__init__(app)
        self.window_seconds = window_seconds
        self.rules: tuple[Rule, ...] = (
            ("simulation", simulation, self._is_simulation),
            ("analysis", analysis, self._is_analysis),
            ("ml", ml, self._is_ml),
        )
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = RLock()

    @staticmethod
    def _is_simulation(method: str, path: str) -> bool:
        return method == "POST" and path.startswith("/api/v1/simulation/")

    @staticmethod
    def _is_analysis(method: str, path: str) -> bool:
        return method == "GET" and "/telemetry/analysis" in path

    @staticmethod
    def _is_ml(method: str, path: str) -> bool:
        return method == "GET" and path.startswith("/api/v1/ml/")

    async def dispatch(self, request: Request, call_next) -> Response:
        # CORS preflight must remain available even when the API is busy.
        if request.method == "OPTIONS":
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        matched = next(((name, limit) for name, limit, predicate in self.rules
                        if predicate(request.method, request.url.path)), None)
        if matched is None:
            return await call_next(request)
        name, limit = matched
        now = monotonic()
        key = (client, name)
        with self._lock:
            bucket = self._requests[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now + 0.999))
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded for {name} requests"},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
        return await call_next(request)
