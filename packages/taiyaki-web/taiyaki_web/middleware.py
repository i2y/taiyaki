"""Built-in middleware: Logger, Recover, RecoverWithOverlay."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from starlette.responses import HTMLResponse, Response

logger = logging.getLogger("dark")


class Logger:
    """ASGI middleware that logs request method, path, status, and duration."""

    def __init__(self, app: Any, *, log: logging.Logger | None = None) -> None:
        self.app = app
        self.log = log or logger

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        duration_ms = (time.monotonic() - start) * 1000
        method = scope.get("method", "?")
        path = scope.get("path", "?")
        self.log.info("%s %s %d %.1fms", method, path, status_code, duration_ms)
        from taiyaki_web.console import log_request

        log_request(method, path, status_code, duration_ms)


class Recover:
    """ASGI middleware that catches unhandled exceptions.

    By default returns a plain 500 response. Subclass and override
    ``_error_response`` to customise (see ``RecoverWithOverlay``).
    """

    def __init__(self, app: Any, *, log: logging.Logger | None = None) -> None:
        self.app = app
        self.log = log or logger

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            self.log.exception("Unhandled exception: %s", exc)
            response = self._error_response(exc)
            await response(scope, receive, send)

    def _error_response(self, exc: Exception) -> Response:
        return Response("Internal Server Error", status_code=500)


class RecoverWithOverlay(Recover):
    """Like Recover, but renders the dev error overlay instead of plain text."""

    def _error_response(self, exc: Exception) -> Response:
        from taiyaki_web.overlay import render_error_overlay

        return HTMLResponse(render_error_overlay(exc), status_code=500)
