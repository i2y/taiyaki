"""HMAC-SHA256 signed cookie session middleware."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class _TrackedDict(dict):
    """Dict that tracks whether it has been modified."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._modified = False

    def __setitem__(self, key: str, value: Any) -> None:
        self._modified = True
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self._modified = True
        super().__delitem__(key)

    def pop(self, *args: Any) -> Any:
        self._modified = True
        return super().pop(*args)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self._modified = True
        return super().setdefault(key, default)


class SessionMiddleware:
    """HMAC-SHA256 signed cookie session middleware (pure ASGI).

    Uses only Python stdlib (hmac, hashlib, json, base64).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret: str,
        cookie_name: str = "taiyaki_session",
        max_age: int = 86400,
        secure: bool = False,
        httponly: bool = True,
        samesite: str = "lax",
    ) -> None:
        self.app = app
        self._secret = secret.encode("utf-8")
        self._cookie_name = cookie_name
        self._max_age = max_age
        self._secure = secure
        self._httponly = httponly
        self._samesite = samesite

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        raw_cookie = request.cookies.get(self._cookie_name)
        session_data = self._load(raw_cookie)
        session = _TrackedDict(session_data)
        scope.setdefault("state", {})
        scope["state"]["session"] = session

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start" and session._modified:
                cookie_value = self._dump(dict(session))
                headers = list(message.get("headers", []))
                # Build Set-Cookie header
                cookie_parts = [f"{self._cookie_name}={cookie_value}"]
                cookie_parts.append(f"Max-Age={self._max_age}")
                cookie_parts.append("Path=/")
                if self._httponly:
                    cookie_parts.append("HttpOnly")
                if self._secure:
                    cookie_parts.append("Secure")
                cookie_parts.append(f"SameSite={self._samesite}")
                headers.append((b"set-cookie", "; ".join(cookie_parts).encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _sign(self, data: bytes) -> str:
        """Base64-encode data and append HMAC-SHA256 signature."""
        encoded = base64.urlsafe_b64encode(data).decode("ascii")
        sig = hmac.new(self._secret, data, hashlib.sha256).hexdigest()
        return f"{encoded}.{sig}"

    def _load(self, cookie_value: str | None) -> dict[str, Any]:
        """Decode and verify a signed session cookie."""
        if not cookie_value:
            return {}
        try:
            encoded, sig = cookie_value.rsplit(".", 1)
            data = base64.urlsafe_b64decode(encoded)
            expected_sig = hmac.new(self._secret, data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_sig, sig):
                return {}
            payload = json.loads(data)
            if payload.get("_exp", 0) < time.time():
                return {}
            return payload.get("_data", {})
        except Exception:
            return {}

    def _dump(self, data: dict[str, Any]) -> str:
        """Serialize session data to a signed cookie value."""
        payload = json.dumps(
            {"_data": data, "_exp": time.time() + self._max_age},
            separators=(",", ":"),
        )
        return self._sign(payload.encode("utf-8"))


def Sessions(
    secret: str,
    *,
    cookie_name: str = "taiyaki_session",
    max_age: int = 86400,
    secure: bool = False,
    httponly: bool = True,
    samesite: str = "lax",
) -> Any:
    """Convenience factory for SessionMiddleware.

    Usage: app.use(dark.Sessions("my-secret-key"))
    """

    def factory(app: ASGIApp) -> SessionMiddleware:
        return SessionMiddleware(
            app,
            secret=secret,
            cookie_name=cookie_name,
            max_age=max_age,
            secure=secure,
            httponly=httponly,
            samesite=samesite,
        )

    return factory
