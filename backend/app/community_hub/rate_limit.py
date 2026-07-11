from __future__ import annotations

import hashlib
import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse


RATE_WINDOW_SECONDS = 60.0


@dataclass(slots=True)
class _Bucket:
    window_started: float
    count: int
    last_seen: float


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Thread-safe fixed-window limiter with a hard memory bound.

    Keys are opaque digests/scopes assembled by the middleware.  Expired
    buckets are removed on access.  If the hard bound remains full after that
    cleanup, a new key is denied instead of evicting an active bucket, which
    prevents key churn from resetting an existing caller's quota.
    """

    def __init__(
        self,
        *,
        max_buckets: int = 10_000,
        window_seconds: float = RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_buckets <= 0:
            raise ValueError("max_buckets must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_buckets = max_buckets
        self._window_seconds = window_seconds
        self._clock = clock
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def bucket_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def _remove_expired(self, now: float) -> None:
        # OrderedDict is maintained by last access; once the oldest entry is
        # still fresh, every later entry is fresh as well.
        while self._buckets:
            _key, bucket = next(iter(self._buckets.items()))
            if now - bucket.last_seen < self._window_seconds:
                break
            self._buckets.popitem(last=False)

    def check(self, key: str, limit: int) -> RateLimitDecision:
        if limit <= 0:
            raise ValueError("limit must be positive")
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_buckets:
                    return RateLimitDecision(False, max(1, math.ceil(self._window_seconds)))
                self._buckets[key] = _Bucket(
                    window_started=now,
                    count=1,
                    last_seen=now,
                )
                return RateLimitDecision(True, 0)

            if now - bucket.window_started >= self._window_seconds:
                bucket.window_started = now
                bucket.count = 1
                bucket.last_seen = now
                self._buckets.move_to_end(key)
                return RateLimitDecision(True, 0)

            bucket.last_seen = now
            self._buckets.move_to_end(key)
            if bucket.count >= limit:
                retry = max(
                    1,
                    math.ceil(bucket.window_started + self._window_seconds - now),
                )
                return RateLimitDecision(False, retry)
            bucket.count += 1
            return RateLimitDecision(True, 0)


def _peer_ip(scope: dict[str, Any]) -> str:
    client = scope.get("client")
    raw = str(client[0]) if client and len(client) >= 1 else "unknown"
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        # Test ASGI clients use a symbolic peer. Keep it bounded; forwarded
        # headers are intentionally never consulted because they are spoofable
        # unless a separately administered trusted proxy is present.
        return raw[:128] or "unknown"


def _bearer_digest(scope: dict[str, Any]) -> str:
    authorization = b""
    for name, value in scope.get("headers", ()):  # raw ASGI bytes, never logged
        if name.lower() == b"authorization":
            authorization = value
            break
    scheme, separator, credential = authorization.partition(b" ")
    if not separator or scheme.lower() != b"bearer" or not credential.strip():
        credential = b"missing-or-invalid-bearer"
    return hashlib.sha256(credential.strip()).hexdigest()


class HubRateLimitMiddleware:
    """Apply hub limits using the direct socket peer, never X-Forwarded-For."""

    def __init__(
        self,
        app: Any,
        *,
        limiter: InMemoryRateLimiter,
        enroll_per_minute: int,
        sync_per_minute: int,
        other_per_minute: int,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.enroll_per_minute = enroll_per_minute
        self.sync_per_minute = sync_per_minute
        self.other_per_minute = other_per_minute

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        peer = _peer_ip(scope)
        if path == "/v1/enroll":
            key = f"enroll:{peer}"
            limit = self.enroll_per_minute
        elif path == "/v1/sync/tournaments":
            key = f"sync:{peer}:{_bearer_digest(scope)}"
            limit = self.sync_per_minute
        elif path == "/v1" or path.startswith("/v1/"):
            key = f"other:{peer}"
            limit = self.other_per_minute
        else:
            await self.app(scope, receive, send)
            return

        decision = self.limiter.check(key, limit)
        if decision.allowed:
            await self.app(scope, receive, send)
            return
        await JSONResponse(
            status_code=429,
            content={"detail": "Trop de requetes; reessayez plus tard."},
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )(scope, receive, send)
