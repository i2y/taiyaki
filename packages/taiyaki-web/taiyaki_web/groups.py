"""Route groups with shared prefix, layout, and middleware."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from taiyaki_web.app import Taiyaki


class RouteGroup:
    """A group of routes sharing a URL prefix, layout, and middleware."""

    def __init__(
        self,
        app: Taiyaki,
        prefix: str,
        *,
        layout: str | None = None,
        middleware: list[Any] | None = None,
    ) -> None:
        self._app = app
        self.prefix = prefix.rstrip("/")
        self.layout = layout
        self.middleware = middleware or []

    def _full_path(self, path: str) -> str:
        if path == "/":
            return self.prefix or "/"
        return self.prefix + "/" + path.lstrip("/")

    def get(
        self,
        path: str,
        *,
        component: str,
        layout: str | None = None,
        stream: bool = False,
        cache: bool = False,
        cache_ttl: float = 0,
    ) -> Callable:
        return self._app.get(
            self._full_path(path),
            component=component,
            layout=layout,
            stream=stream,
            cache=cache,
            cache_ttl=cache_ttl,
            _group=self,
        )

    def post(self, path: str, **kw: Any) -> Callable:
        return self._app.post(self._full_path(path), _group=self, **kw)

    def put(self, path: str, **kw: Any) -> Callable:
        return self._app.put(self._full_path(path), _group=self, **kw)

    def delete(self, path: str, **kw: Any) -> Callable:
        return self._app.delete(self._full_path(path), _group=self, **kw)

    def patch(self, path: str, **kw: Any) -> Callable:
        return self._app.patch(self._full_path(path), _group=self, **kw)

    def api_get(self, path: str) -> Callable:
        return self._app.api_get(self._full_path(path))

    def api_post(self, path: str) -> Callable:
        return self._app.api_post(self._full_path(path))

    def api_put(self, path: str) -> Callable:
        return self._app.api_put(self._full_path(path))

    def api_delete(self, path: str) -> Callable:
        return self._app.api_delete(self._full_path(path))

    def api_patch(self, path: str) -> Callable:
        return self._app.api_patch(self._full_path(path))

    def group(
        self,
        prefix: str,
        *,
        layout: str | None = None,
        middleware: list[Any] | None = None,
    ) -> RouteGroup:
        return RouteGroup(
            self._app,
            self._full_path(prefix),
            layout=layout or self.layout,
            middleware=self.middleware + (middleware or []),
        )

    def __enter__(self) -> RouteGroup:
        return self

    def __exit__(self, *args: Any) -> None:
        pass
