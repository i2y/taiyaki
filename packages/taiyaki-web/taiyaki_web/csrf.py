"""CSRF protection middleware."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

CSRF_TOKEN_KEY = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "_csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CSRFMiddleware:
    """CSRF protection middleware (pure ASGI).

    Requires SessionMiddleware to be active (stores token in session).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session: dict[str, Any] = scope.get("state", {}).get("session", {})

        if CSRF_TOKEN_KEY not in session:
            session[CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)

        method = scope.get("method", "GET")
        if method in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        # Unsafe method — resolve token from header or form body
        request = Request(scope)
        token = request.headers.get(CSRF_HEADER, "")
        actual_receive = receive

        if not token:
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                # Read body and replay for downstream
                body = b""
                while True:
                    message = await receive()
                    body += message.get("body", b"")
                    if not message.get("more_body", False):
                        break
                parsed = parse_qs(body.decode("utf-8", errors="replace"))
                token_list = parsed.get(CSRF_FORM_FIELD, [])
                token = token_list[0] if token_list else ""

                body_sent = False

                async def replay_receive() -> dict:
                    nonlocal body_sent
                    if not body_sent:
                        body_sent = True
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }
                    return {"type": "http.disconnect"}

                actual_receive = replay_receive

        expected = session.get(CSRF_TOKEN_KEY, "")
        if not token or not secrets.compare_digest(str(token), str(expected)):
            response = Response("CSRF token mismatch", status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, actual_receive, send)


def CSRF() -> Any:
    """Convenience factory: app.use(dark.CSRF())"""

    def factory(app: Any) -> CSRFMiddleware:
        return CSRFMiddleware(app)

    return factory
