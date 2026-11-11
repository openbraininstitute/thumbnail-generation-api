"""One log line per HTTP request, and its ``request_id`` (``X-Request-ID``) on every line.

Pure ASGI, not ``BaseHTTPMiddleware``: that one runs the app in another task, so the bound id would
not reach the handlers.
"""

import re
import time
from uuid import uuid7

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import timing as timings
from app.logs import bind, get_logger

log = get_logger("api.request")

HEADER = b"x-request-id"
SERVER_TIMING = b"server-timing"
SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
QUIET_SUFFIX = "/health"  # the load balancer probes it every few seconds: debug, not info


def request_id_of(scope: Scope) -> str:
    """The caller's id when it is a plain token (no log injection), else a new UUIDv7.

    Examples:
        >>> request_id_of({"headers": [(b"x-request-id", b"req-1:a.b")]})
        'req-1:a.b'
        >>> len(request_id_of({"headers": [(b"x-request-id", b"a b")]}))
        36
    """
    sent = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
    return sent if SAFE_ID.fullmatch(sent) else str(uuid7())


class RequestLog:
    """ASGI middleware: bind ``request_id``, log ``request`` with status and duration."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve HTTP; pass other scopes through untouched."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_of(scope)
        started = time.perf_counter()
        status = 500  # what a crash before the first byte means

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                # Every route answers whole, so the body is built by now: "app" is the app's time.
                elapsed = (time.perf_counter() - started) * 1000
                timing = timings.header(phases, elapsed).encode()
                message["headers"] = [
                    *message.get("headers", []),
                    (HEADER, request_id.encode()),
                    (SERVER_TIMING, timing),
                ]
            await send(message)

        with bind(request_id=request_id), timings.collect() as phases:
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                path: str = scope["path"]  # never the query string
                if status >= 500:  # noqa: PLR2004 - HTTP server error
                    emit = log.error
                elif path.endswith(QUIET_SUFFIX):
                    emit = log.debug
                else:
                    emit = log.info
                emit(
                    "request",
                    method=scope["method"],
                    path=path,
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    **{f"{name}_ms": round(ms, 2) for name, ms in phases},
                )
