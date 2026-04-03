"""Tests for route registration and dispatch."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


def _simple_component(name: str = "Page", tag: str = "div") -> str:
    return f"""
import {{ h }} from "preact";
export default function {name}({{ message }}) {{
    return h("{tag}", {{ "data-testid": "{name.lower()}" }}, message || "hello");
}}
"""


async def test_get_route():
    app = Taiyaki()
    app.load_component("Page", _simple_component())

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "home"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "home" in r.text
        assert 'data-testid="page"' in r.text


async def test_post_route():
    app = Taiyaki()
    app.load_component("Page", _simple_component())
    called = {}

    @app.post("/submit", component="Page")
    async def submit(ctx: Context):
        called["ok"] = True

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/submit")
        assert r.status_code == 200
        assert called.get("ok") is True


async def test_path_params():
    app = Taiyaki()
    app.load_component("User", """
import { h } from "preact";
export default function User({ name }) {
    return h("span", { id: "user" }, name);
}
""")

    @app.get("/users/{name}", component="User")
    async def user(ctx: Context):
        return {"name": ctx.param("name")}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/users/alice")
        assert r.status_code == 200
        assert "alice" in r.text


async def test_query_params():
    app = Taiyaki()
    app.load_component("Search", """
import { h } from "preact";
export default function Search({ q }) {
    return h("div", { id: "search" }, q || "empty");
}
""")

    @app.get("/search", component="Search")
    async def search(ctx: Context):
        return {"q": ctx.query("q", "none")}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/search?q=hello")
        assert "hello" in r.text


async def test_404_for_unknown_route():
    app = Taiyaki()

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/nonexistent")
        assert r.status_code == 404
