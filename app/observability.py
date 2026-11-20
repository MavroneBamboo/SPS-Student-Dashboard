import json
import logging
import re
import sys
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ACCESS_LOG = logging.getLogger("sps.access")
_REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
_current_request_id: ContextVar[str | None] = ContextVar("sps_request_id", default=None)
_ACCESS_LOG.setLevel(logging.INFO)
if not _ACCESS_LOG.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _ACCESS_LOG.addHandler(_handler)
_ACCESS_LOG.propagate = True


def current_request_id() -> str | None:
    """Return the request correlation ID for the current sync or async task."""
    return _current_request_id.get()


class RequestCorrelationMiddleware:
    """Emit redacted structured request events and attach an opaque response ID."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                try:
                    candidate = value.decode("ascii")
                except UnicodeDecodeError:
                    break
                if _REQUEST_ID.fullmatch(candidate):
                    request_id = candidate
                break
        started_at = time.perf_counter()
        request_id_token = _current_request_id.set(request_id)
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                message = {
                    **message,
                    "headers": [(name, value) for name, value in message.get("headers", []) if name.lower() != b"x-request-id"]
                    + [(b"x-request-id", request_id.encode("ascii"))],
                }
            await send(message)

        error_type = None
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            status_code = 500
            error_type = type(exc).__name__
            if not response_started:
                body = b"Internal Server Error"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"x-request-id", request_id.encode("ascii")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
        finally:
            route = scope.get("route")
            event = {
                "event": "http.request.completed",
                "request_id": request_id,
                "method": scope.get("method", "UNKNOWN"),
                "route": getattr(route, "path", "unmatched"),
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
            }
            if error_type is not None:
                event["error_type"] = error_type
            level = logging.ERROR if status_code >= 500 or error_type else logging.WARNING if status_code >= 400 else logging.INFO
            _ACCESS_LOG.log(level, json.dumps(event, separators=(",", ":"), sort_keys=True))
            _current_request_id.reset(request_id_token)
