import json
import logging
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
_current_request_id: ContextVar[str | None] = ContextVar("sps_request_id", default=None)
_access_log = logging.getLogger("sps.access")
_access_log.setLevel(logging.INFO)


def current_request_id() -> str | None:
    """Return the opaque request ID associated with the current request task."""
    return _current_request_id.get()


class RequestCorrelationMiddleware:
    """Add a response ID and emit access logs without query strings or payloads."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def __getattr__(self, name: str):
        """Keep the wrapped FastAPI application's inspection interface available."""
        return getattr(self.app, name)

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

        request_context_token = _current_request_id.set(request_id)
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode("ascii"))]}
            await send(message)

        error_type = None
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            status_code = 500
            error_type = type(exc).__name__
            raise
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
            level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
            _access_log.log(level, json.dumps(event, separators=(",", ":"), sort_keys=True))
            _current_request_id.reset(request_context_token)
