"""Launch-level API protections: request size limit, chat rate limiting, client identity.

Kept deliberately small (no Redis, no gateway): one process serves Rupsaa, so in-process
limits are enough for launch. Everything is configured in rupsaa/config.py and is OFF in
development unless set explicitly, so local work and tests behave as before.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rupsaa.rag.terminology_import import MAX_FILE_BYTES

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Multipart import uploads carry their own 2 MB file cap (terminology_import / dance_import).
UPLOAD_PATHS = ("/owner/terminology/import", "/owner/dance/import")


def client_key(request: Request) -> str:
    """Who is calling. Behind web/dev_server.py every request arrives from 127.0.0.1, so the
    proxy's X-Forwarded-For is used — but only when the direct peer is that local proxy."""
    peer = request.client.host if request.client else "unknown"
    if peer in LOOPBACK:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return peer


class RateLimiter:
    """Sliding one-minute window per client plus one for the whole server (0 = unlimited).
    The global window is the backstop against clients rotating spoofed forwarding headers."""

    def __init__(self, per_client: int, global_limit: int, clock=time.monotonic):
        self.per_client, self.global_limit = per_client, global_limit
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._global: deque = deque()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.per_client > 0 or self.global_limit > 0

    def check(self, key: str) -> float | None:
        """None if allowed (and counted); otherwise seconds until a slot frees up."""
        now = self._clock()
        with self._lock:
            for q in (self._hits[key], self._global):
                while q and now - q[0] >= 60:
                    q.popleft()
            if self.global_limit and len(self._global) >= self.global_limit:
                return 60 - (now - self._global[0])
            q = self._hits[key]
            if self.per_client and len(q) >= self.per_client:
                return 60 - (now - q[0])
            q.append(now)
            self._global.append(now)
            if len(self._hits) > 50_000:  # forget idle clients
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return None


def rate_limited_response(retry_after: float) -> JSONResponse:
    secs = max(1, int(retry_after) + 1)
    return JSONResponse(status_code=429, headers={"Retry-After": str(secs)},
                        content={"detail": f"Too many messages — please wait {secs} seconds and try again."})


class BodySizeLimitMiddleware:
    """Reject request bodies over `max_bytes` (uploads: the import cap + multipart overhead) with 413,
    whether or not the client sent an honest Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = MAX_FILE_BYTES + 64 * 1024 if scope["path"].startswith(UPLOAD_PATHS) else self.max_bytes
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(send, limit)
            return
        seen = 0
        rejected = False

        async def limited_receive() -> Message:
            nonlocal seen, rejected
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    rejected = True
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            if rejected:
                await _too_large(send, limit)


class _TooLarge(Exception):
    pass


async def _too_large(send: Send, limit: int) -> None:
    body = f'{{"detail": "Request too large (limit {limit} bytes)."}}'.encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
