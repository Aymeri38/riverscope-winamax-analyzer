from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from starlette.responses import JSONResponse


SECURITY_HEADERS = (
    (b"content-security-policy", b"frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class LocalHttpSecurityMiddleware:
    """Protect the loopback UI against framing and cross-site state changes.

    Command-line clients do not send ``Origin`` and remain supported. Browser
    requests carrying an Origin must come from the analyzer's own loopback
    origin. ``Sec-Fetch-Site: cross-site`` is rejected as a second signal when
    a browser omits Origin.
    """

    def __init__(self, app: Any, *, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(origin.rstrip("/") for origin in allowed_origins)

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        method = str(scope.get("method", "GET")).upper()
        if method in UNSAFE_METHODS:
            raw_origin = headers.get(b"origin")
            origin = raw_origin.decode("latin-1").rstrip("/") if raw_origin else None
            fetch_site = headers.get(b"sec-fetch-site", b"").decode("latin-1").casefold()
            if (origin is not None and origin not in self.allowed_origins) or (
                origin is None and fetch_site == "cross-site"
            ):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Origine navigateur non autorisee."},
                )
                await response(scope, receive, self._secure_send(send))
                return

        await self.app(scope, receive, self._secure_send(send))

    @staticmethod
    def _secure_send(send: Callable) -> Callable:
        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                existing = list(message.get("headers", []))
                security_names = {name for name, _value in SECURITY_HEADERS}
                existing = [
                    (name, value)
                    for name, value in existing
                    if name.lower() not in security_names
                ]
                existing.extend(SECURITY_HEADERS)
                message["headers"] = existing
            await send(message)

        return secure_send
