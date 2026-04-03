"""Taiyaki — main application class."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager as _acm
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from taiyaki_web.context import Context
from taiyaki_web.csrf import CSRF_TOKEN_KEY
from taiyaki_web.head import extract_taiyaki_head, strip_taiyaki_head
from taiyaki_web.html import document, document_parts
from taiyaki_web.islands import IslandRegistry
from taiyaki_web.renderers import RENDERERS
from taiyaki_web.runtime import JsRuntime

_VENDOR = Path(__file__).parent / "vendor"
_DEFAULT_TITLE = "Taiyaki"


async def _maybe_await(result: Any) -> Any:
    if hasattr(result, "__await__"):
        return await result
    return result


class Taiyaki:
    """Preact SSR + htmx + Islands web framework."""

    def __init__(
        self,
        *,
        components_dir: str = "components",
        islands_dir: str = "islands",
        layout: str | None = None,
        error_component: str | None = None,
        not_found_component: str | None = None,
        dev_mode: bool = False,
        pool_size: int = 1,
        renderer: str = "preact",
    ) -> None:
        if renderer not in RENDERERS:
            raise ValueError(
                f"Unknown renderer '{renderer}'. Choose from: {', '.join(RENDERERS)}"
            )
        self._renderer = renderer
        self._import_map = RENDERERS[renderer]["import_map"]
        self._pool: Any = None
        if pool_size > 1:
            from taiyaki_web.pool import RuntimePool

            self._pool = RuntimePool(pool_size=pool_size, renderer=renderer)
        self._runtime = JsRuntime(renderer=renderer) if not self._pool else None
        self._routes: list[Route] = []
        self._components_dir = Path(components_dir)
        self._islands_dir = Path(islands_dir)
        self._loaded_components: set[str] = set()
        self._app: Starlette | None = None
        self._global_layout = layout
        self._error_component = error_component
        self._not_found_component = not_found_component
        self._dev_mode = dev_mode
        self._middleware: list[Any] = []
        self._static_mounts: list[tuple[str, str]] = []
        self._cache: Any = None
        self._island_hashes: dict[str, str] = {}
        self._route_meta: list[dict[str, Any]] = []

    # ── Runtime helper ──

    @_acm
    async def _use_runtime(self) -> AsyncIterator[JsRuntime]:
        """Acquire a runtime from the pool (or use the single instance)."""
        if self._pool:
            rt = await self._pool.acquire()
            try:
                yield rt
            finally:
                self._pool.release(rt)
        else:
            yield self._runtime

    # ── Middleware ──

    def use(self, middleware: Any) -> None:
        """Add a global middleware. Resets the cached ASGI app."""
        self._middleware.append(middleware)
        self._app = None

    # ── Routing ──

    def get(
        self,
        path: str,
        *,
        component: str,
        layout: str | None = None,
        stream: bool = False,
        cache: bool = False,
        cache_ttl: float = 0,
        _group: Any = None,
    ) -> Callable:
        """Register a GET route. The decorated function is the loader."""

        def decorator(fn: Callable) -> Callable:
            config = {
                "component": component,
                "loader": fn,
                "layout": layout,
                "stream": stream,
                "cache": cache,
                "cache_ttl": cache_ttl,
                "group": _group,
            }
            self._routes.append(
                Route(path, self._make_page_handler(config), methods=["GET"])
            )
            self._route_meta.append(
                {
                    "path": path,
                    "method": "GET",
                    "component": component,
                    "loader": fn,
                    "docstring": fn.__doc__,
                }
            )
            return fn

        return decorator

    def post(self, path: str, **kw: Any) -> Callable:
        """Register a POST route."""
        return self._register_action(path, "POST", **kw)

    def put(self, path: str, **kw: Any) -> Callable:
        """Register a PUT route."""
        return self._register_action(path, "PUT", **kw)

    def delete(self, path: str, **kw: Any) -> Callable:
        """Register a DELETE route."""
        return self._register_action(path, "DELETE", **kw)

    def patch(self, path: str, **kw: Any) -> Callable:
        """Register a PATCH route."""
        return self._register_action(path, "PATCH", **kw)

    def _register_action(
        self,
        path: str,
        method: str,
        *,
        component: str | None = None,
        layout: str | None = None,
        _group: Any = None,
    ) -> Callable:
        def decorator(fn: Callable) -> Callable:
            config = {
                "component": component,
                "action": fn,
                "layout": layout,
                "group": _group,
            }
            self._routes.append(
                Route(path, self._make_action_handler(config), methods=[method])
            )
            self._route_meta.append(
                {
                    "path": path,
                    "method": method,
                    "component": component,
                    "action": fn,
                    "docstring": fn.__doc__,
                }
            )
            return fn

        return decorator

    # ── Shared render pipeline ──

    def _inject_framework_props(
        self, ctx: Context, request: Request, props: dict[str, Any]
    ) -> None:
        """Inject _errors and _csrfToken into props if applicable."""
        if ctx.has_errors():
            props["_errors"] = ctx.field_errors
        csrf_token = self._get_csrf_token(request)
        if csrf_token:
            props["_csrfToken"] = csrf_token

    async def _render_page(
        self,
        ctx: Context,
        component: str,
        props: dict[str, Any],
        layout: str | None,
        group: Any,
    ) -> Response:
        """Render a component through the layout chain into a full HTML page."""
        self._ensure_component(component)
        try:
            async with self._use_runtime() as rt:
                html = rt.render_to_string(component, props)
                html = await self._apply_layouts(html, layout, group, props, rt=rt)
        except Exception as exc:
            if self._dev_mode:
                return self._render_error_overlay(exc, component)
            raise
        html, dark_head = extract_taiyaki_head(html)
        title = ctx.title or _DEFAULT_TITLE
        response = self._build_page(title, html, ctx=ctx, dark_head_content=dark_head)
        return ctx._apply_to_response(response)

    def _render_error_overlay(
        self, error: Exception, component: str | None = None
    ) -> Response:
        from taiyaki_web.overlay import render_error_overlay

        source, source_file = self._find_component_source(component)
        sm = None
        if component:
            rt = self._runtime
            if rt:
                sm = rt.get_source_map(component)
        html = render_error_overlay(
            error,
            component=component,
            source=source,
            source_file=source_file,
            source_map=sm,
        )
        return HTMLResponse(html, status_code=500)

    def _find_component_file(self, name: str) -> Path | None:
        """Find a component file by name in components/islands dirs."""
        for d in (self._components_dir, self._islands_dir):
            for ext in (".jsx", ".tsx"):
                path = d / f"{name}{ext}"
                if path.exists():
                    return path
        return None

    def _find_component_source(
        self,
        name: str | None,
    ) -> tuple[str | None, str | None]:
        if not name:
            return None, None
        path = self._find_component_file(name)
        if path:
            try:
                return path.read_text(), str(path)
            except OSError:
                pass
        return None, None

    async def _render_page_streaming(
        self,
        ctx: Context,
        component: str,
        props: dict[str, Any],
        layout: str | None,
        group: Any,
    ) -> Response:
        """Render a page as a StreamingResponse, splitting at markers."""
        from starlette.responses import StreamingResponse
        from taiyaki_web.streaming import split_at_markers, streaming_chunks

        self._ensure_component(component)
        async with self._use_runtime() as rt:
            raw_html = rt.render_to_string(component, props)
            raw_html = await self._apply_layouts(raw_html, layout, group, props, rt=rt)

        raw_html, dark_head = extract_taiyaki_head(raw_html)
        body_chunks = split_at_markers(raw_html)
        title = ctx.title or _DEFAULT_TITLE
        head_extra, scripts = self._page_chrome(ctx)
        meta_tags = ctx.meta_tags
        head, chunks, tail = document_parts(
            title,
            body_chunks,
            head_extra=head_extra,
            scripts=scripts,
            meta_tags=meta_tags,
            import_map=self._import_map,
            dark_head_content=dark_head,
        )

        response = StreamingResponse(
            streaming_chunks(head, chunks, tail),
            media_type="text/html",
        )
        return ctx._apply_to_response(response)

    def _page_chrome(self, ctx: Context) -> tuple[str, str]:
        """Build head_extra and scripts shared by _build_page and streaming."""
        scripts = '<script src="/_taiyaki/htmx.min.js"></script>\n'
        scripts += IslandRegistry.hydration_script(
            ctx.page_islands,
            renderer=self._renderer,
            island_hashes=self._island_hashes or None,
        )

        head_extra = ""
        csrf_token = self._get_csrf_token(ctx.request)
        if csrf_token:
            head_extra += f'  <meta name="csrf-token" content="{csrf_token}">\n'
            head_extra += (
                "<script>"
                'document.addEventListener("DOMContentLoaded",()=>{'
                "const t=document.querySelector('meta[name=\"csrf-token\"]');"
                'if(t)document.body.addEventListener("htmx:configRequest",'
                'e=>{e.detail.headers["X-CSRF-Token"]=t.content})'
                "});"
                "</script>\n"
            )

        if self._dev_mode:
            scripts += (
                "<script>"
                'const es=new EventSource("/_taiyaki/reload");'
                'es.onmessage=(e)=>{if(e.data==="reload")location.reload()};'
                "</script>\n"
            )

        return head_extra, scripts

    def _get_cache(self):
        if self._cache is None:
            from taiyaki_web.cache import ResponseCache

            self._cache = ResponseCache()
        return self._cache

    def _make_page_handler(self, config: dict[str, Any]) -> Callable:
        app = self

        async def handler(request: Request) -> Response:
            use_cache = config.get("cache", False)
            cache_ttl = config.get("cache_ttl", 0)

            if use_cache:
                resp_cache = app._get_cache()
                path = request.url.path
                qs = str(request.url.query) if request.url.query else ""
                entry = resp_cache.get(path, qs)
                if entry is not None:
                    if_none_match = request.headers.get("if-none-match", "").strip('"')
                    if if_none_match == entry.etag:
                        return Response(status_code=304)
                    resp = HTMLResponse(entry.body)
                    resp.headers["ETag"] = f'"{entry.etag}"'
                    resp.headers["Cache-Control"] = "private, must-revalidate"
                    return resp

            ctx = Context(request)
            loader = config.get("loader")
            result = await _maybe_await(loader(ctx)) if loader else None
            props: dict[str, Any] = result if isinstance(result, dict) else {}

            app._inject_framework_props(ctx, request, props)
            if ctx.redirect_url:
                return ctx._apply_to_response(Response())

            if config.get("stream"):
                return await app._render_page_streaming(
                    ctx,
                    config["component"],
                    props,
                    config.get("layout"),
                    config.get("group"),
                )
            response = await app._render_page(
                ctx,
                config["component"],
                props,
                config.get("layout"),
                config.get("group"),
            )

            if use_cache and isinstance(response, HTMLResponse):
                body_text = response.body.decode("utf-8")
                entry = resp_cache.put(path, qs, body_text, ttl=cache_ttl)
                response.headers["ETag"] = f'"{entry.etag}"'
                response.headers["Cache-Control"] = "private, must-revalidate"

            return response

        return handler

    def _make_action_handler(self, config: dict[str, Any]) -> Callable:
        app = self

        async def handler(request: Request) -> Response:
            ctx = Context(request)
            action = config.get("action")
            if action:
                await _maybe_await(action(ctx))

            if ctx.redirect_url:
                return ctx._apply_to_response(Response())

            component = config.get("component")
            if component:
                props: dict[str, Any] = {}
                if ctx.has_errors():
                    form = await request.form()
                    props["_formData"] = dict(form)
                app._inject_framework_props(ctx, request, props)
                return await app._render_page(
                    ctx,
                    component,
                    props,
                    config.get("layout"),
                    config.get("group"),
                )

            return ctx._apply_to_response(Response())

        return handler

    async def _apply_layouts(
        self,
        html: str,
        route_layout: str | None,
        group: Any,
        props: dict[str, Any],
        rt: JsRuntime | None = None,
    ) -> str:
        runtime = rt or self._runtime
        layouts: list[str] = []
        if route_layout:
            layouts.append(route_layout)
        if group is not None:
            group_layout = getattr(group, "layout", None)
            if group_layout:
                layouts.append(group_layout)
        if self._global_layout:
            layouts.append(self._global_layout)
        for layout_name in layouts:
            self._ensure_component(layout_name)
            html = runtime.render_with_layout(layout_name, html, props)
        return html

    def _get_csrf_token(self, request: Request) -> str | None:
        state = request.scope.get("state", {})
        session = state.get("session")
        if session:
            return session.get(CSRF_TOKEN_KEY)
        return None

    # ── API Endpoints ──

    def api_get(self, path: str) -> Callable:
        return self._register_api(path, "GET")

    def api_post(self, path: str) -> Callable:
        return self._register_api(path, "POST")

    def api_put(self, path: str) -> Callable:
        return self._register_api(path, "PUT")

    def api_delete(self, path: str) -> Callable:
        return self._register_api(path, "DELETE")

    def api_patch(self, path: str) -> Callable:
        return self._register_api(path, "PATCH")

    def _register_api(self, path: str, method: str) -> Callable:
        def decorator(fn: Callable) -> Callable:
            async def handler(request: Request) -> Response:
                ctx = Context(request)
                result = await _maybe_await(fn(ctx))
                if isinstance(result, Response):
                    return ctx._apply_to_response(result)
                return ctx._apply_to_response(JSONResponse(result))

            self._routes.append(Route(path, handler, methods=[method]))
            self._route_meta.append(
                {
                    "path": path,
                    "method": method,
                    "api": True,
                    "handler": fn,
                    "docstring": fn.__doc__,
                }
            )
            return fn

        return decorator

    # ── Route Groups ──

    def group(
        self,
        prefix: str,
        *,
        layout: str | None = None,
        middleware: list[Any] | None = None,
    ) -> "RouteGroup":
        from taiyaki_web.groups import RouteGroup

        return RouteGroup(self, prefix, layout=layout, middleware=middleware)

    # ── Static File Serving ──

    def static(self, path: str, directory: str) -> None:
        self._static_mounts.append((path, directory))
        self._app = None

    # ── Component Loading ──

    def _ensure_component(self, name: str) -> None:
        if name in self._loaded_components:
            return
        path = self._find_component_file(name)
        if path:
            if self._pool:
                self._pool.load_component_file(path)
            else:
                self._runtime.load_component_file(path)
            self._loaded_components.add(name)

    def load_component(self, name: str, source: str) -> None:
        if self._pool:
            self._pool.load_component(name, source)
        else:
            self._runtime.load_component(name, source)
        self._loaded_components.add(name)

    # ── Rendering ──

    async def render(self, component: str, **props: Any) -> str:
        """SSR a component to static HTML (no hydration)."""
        self._ensure_component(component)
        async with self._use_runtime() as rt:
            return rt.render_to_string(component, props)

    async def island(
        self,
        component: str,
        *,
        load: str = "immediate",
        _ctx: Context | None = None,
        **props: Any,
    ) -> str:
        """SSR an island component with hydration markers."""
        self._ensure_component(component)
        if _ctx:
            _ctx.page_islands.add(component)
        async with self._use_runtime() as rt:
            html = rt.render_to_string(component, props)
        return IslandRegistry.wrap_html(component, html, props, load=load)

    async def partial(self, component: str, **props: Any) -> Response:
        """Return partial HTML for htmx swap."""
        self._ensure_component(component)
        async with self._use_runtime() as rt:
            html = rt.render_to_string(component, props)
        return HTMLResponse(strip_taiyaki_head(html))

    def _build_page(
        self,
        title: str,
        body: str,
        *,
        ctx: Context | None = None,
        dark_head_content: str = "",
    ) -> Response:
        if ctx:
            head_extra, scripts = self._page_chrome(ctx)
            meta_tags = ctx.meta_tags
        else:
            head_extra, scripts, meta_tags = "", "", None
        html = document(
            title,
            body,
            head_extra=head_extra,
            scripts=scripts,
            meta_tags=meta_tags,
            import_map=self._import_map,
            dark_head_content=dark_head_content,
        )
        return HTMLResponse(html)

    # ── ASGI ──

    def _build_app(self) -> Starlette:
        routes = list(self._routes)

        for path, directory in self._static_mounts:
            routes.append(Mount(path, app=StaticFiles(directory=directory)))

        lifespan = None
        if self._dev_mode:
            from contextlib import asynccontextmanager
            from taiyaki_web.dev import DevReloader

            self._dev_reloader = DevReloader(
                watch_dirs=[self._components_dir, self._islands_dir],
                on_change=lambda _: self._invalidate_components(),
            )
            routes.extend(self._dev_reloader.routes())

            @asynccontextmanager
            async def lifespan(app: Any):
                await self._dev_reloader.start()
                yield
                await self._dev_reloader.stop()

        if self._islands_dir.exists():
            routes.append(
                Mount(
                    "/_taiyaki/islands",
                    app=self._island_file_app(),
                    name="taiyaki_islands",
                )
            )
        routes.append(
            Mount(
                "/_taiyaki",
                app=StaticFiles(directory=str(_VENDOR)),
                name="taiyaki_static",
            )
        )

        exception_handlers: dict[int, Any] = {}
        if self._not_found_component:
            exception_handlers[404] = self._handle_404
        if self._error_component:
            exception_handlers[500] = self._handle_500

        app: Any = Starlette(
            routes=routes,
            exception_handlers=exception_handlers or None,
            lifespan=lifespan,
        )

        for mw in reversed(self._middleware):
            app = mw(app)

        return app

    def _invalidate_components(self) -> None:
        self._loaded_components.clear()
        if self._pool:
            self._pool.invalidate_all()
        else:
            self._runtime.invalidate_all()
        if self._cache is not None:
            self._cache.invalidate()

    async def _handle_404(self, request: Request, exc: Exception) -> Response:
        self._ensure_component(self._not_found_component)
        props = {"path": str(request.url.path)}
        async with self._use_runtime() as rt:
            html = rt.render_to_string(self._not_found_component, props)
            html = await self._apply_layouts(html, None, None, props, rt=rt)
        return HTMLResponse(document("Not Found", html), status_code=404)

    async def _handle_500(self, request: Request, exc: Exception) -> Response:
        props: dict[str, Any] = {"message": str(exc)}
        if self._dev_mode:
            import traceback

            props["traceback"] = traceback.format_exc()
        self._ensure_component(self._error_component)
        async with self._use_runtime() as rt:
            html = rt.render_to_string(self._error_component, props)
        return HTMLResponse(document("Error", html), status_code=500)

    def _island_file_app(self) -> Callable:
        import re as _re
        import taiyaki
        from taiyaki_web.islands import content_hash

        cache: dict[str, str] = {}
        islands_root = self._islands_dir.resolve()
        # Regex to match hashed island URLs: name-{8hex}.js
        _hash_re = _re.compile(r"^(.+)-[0-9a-f]{8}$")

        async def app(scope: dict, receive: Callable, send: Callable) -> None:
            if scope["type"] != "http":
                return
            root = scope.get("root_path", "")
            full_path = scope["path"]
            rel = full_path[len(root) :] if full_path.startswith(root) else full_path
            raw_name = rel.strip("/").removesuffix(".js")
            # Strip content hash suffix if present
            m = _hash_re.match(raw_name)
            name = m.group(1) if m else raw_name
            src = None
            for ext in (".jsx", ".tsx"):
                candidate = self._islands_dir / f"{name}{ext}"
                resolved = candidate.resolve()
                if resolved.is_relative_to(islands_root) and resolved.is_file():
                    src = resolved
                    break
            if src is None:
                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            key = str(src)
            if key not in cache or self._dev_mode:
                import_source = "react" if self._renderer == "react" else "preact"
                js = taiyaki.transform_jsx(src.read_text(), import_source)
                cache[key] = js
                self._island_hashes[name] = content_hash(js)
            js_content = cache[key]
            headers: dict[str, str] = {}
            if m:
                # Hashed URLs are immutable
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response = Response(
                js_content,
                media_type="application/javascript",
                headers=headers,
            )
            await response(scope, receive, send)

        return app

    @property
    def asgi(self) -> Starlette:
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def run(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        import uvicorn

        uvicorn.run(self.asgi, host=host, port=port)

    # ── SSG ──

    async def generate_static_site(
        self,
        output_dir: str,
        routes: list[str | dict[str, Any]],
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        from taiyaki_web.ssg import StaticSiteGenerator

        gen = StaticSiteGenerator(self)
        await gen.generate(output_dir, routes, on_progress=on_progress)
