"""Request/response context for loaders and actions."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from taiyaki_web.htmx import is_htmx_request


class Context:
    """Wraps a Starlette Request and accumulates response-side state."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self._store: dict[str, Any] = {}
        self._cookies: list[tuple[str, str, dict[str, Any]]] = []
        self._redirect_url: str | None = None
        self._redirect_status: int = 302
        self._title: str | None = None
        self._meta: list[tuple[str, str]] = []
        self._field_errors: dict[str, list[str]] = {}
        self._page_islands: set[str] = set()

    # ── Request shortcuts ──

    def param(self, name: str) -> str:
        return self.request.path_params[name]

    def query(self, name: str, default: str | None = None) -> str | None:
        return self.request.query_params.get(name, default)

    async def form_data(self) -> dict[str, Any]:
        form = await self.request.form()
        return dict(form)

    async def json(self) -> Any:
        return await self.request.json()

    def get_cookie(self, key: str) -> str | None:
        return self.request.cookies.get(key)

    @property
    def is_htmx(self) -> bool:
        return is_htmx_request(self.request)

    # ── Response state ──

    def redirect(self, url: str, status: int = 302) -> None:
        self._redirect_url = url
        self._redirect_status = status

    def set_cookie(self, key: str, value: str, **kwargs: Any) -> None:
        self._cookies.append((key, value, kwargs))

    def set_title(self, title: str) -> None:
        self._title = title

    def add_meta(self, name: str, content: str) -> None:
        self._meta.append((name, content))

    # ── Field validation errors ──

    def add_field_error(self, field: str, message: str) -> None:
        self._field_errors.setdefault(field, []).append(message)

    def has_errors(self) -> bool:
        return bool(self._field_errors)

    @property
    def field_errors(self) -> dict[str, list[str]]:
        return self._field_errors

    # ── Page state (read by app.py) ──

    @property
    def title(self) -> str | None:
        return self._title

    @property
    def meta_tags(self) -> list[tuple[str, str]]:
        return self._meta

    @property
    def redirect_url(self) -> str | None:
        return self._redirect_url

    @property
    def page_islands(self) -> set[str]:
        return self._page_islands

    # ── Session ──

    def session(self) -> dict[str, Any]:
        state = self.request.scope.get("state", {})
        return state.get("session", {})

    def flash(self, message: str, category: str = "info") -> None:
        session = self.session()
        flashes: list[dict[str, str]] = session.setdefault("_flash", [])
        flashes.append({"message": message, "category": category})

    def get_flashed_messages(self) -> list[dict[str, str]]:
        session = self.session()
        return session.pop("_flash", [])

    # ── KV store ──

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    # ── Internal ──

    def _apply_to_response(self, response: Response) -> Response:
        if self._redirect_url:
            if self.is_htmx:
                response = Response(status_code=200)
                response.headers["HX-Redirect"] = self._redirect_url
            else:
                response = RedirectResponse(
                    self._redirect_url, status_code=self._redirect_status
                )
        for key, value, kwargs in self._cookies:
            response.set_cookie(key, value, **kwargs)
        return response
