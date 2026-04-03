"""Tests for route groups with prefix, layout, and nesting."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_PAGE = """
import { h } from "preact";
export default function Page({ message }) {
    return h("div", { "data-testid": "page" }, message || "ok");
}
"""

_LAYOUT = """
import { h } from "preact";
export default function Layout({ children }) {
    return h("section", { "data-testid": "group-layout" }, children);
}
"""


async def test_group_prefix():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    grp = app.group("/api/v1")

    @grp.get("/users", component="Page")
    async def users(ctx: Context):
        return {"message": "users"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/users")
        assert r.status_code == 200
        assert "users" in r.text


async def test_group_layout():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    app.load_component("Layout", _LAYOUT)
    grp = app.group("/admin", layout="Layout")

    @grp.get("/", component="Page")
    async def admin_home(ctx: Context):
        return {"message": "admin"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/admin")
        assert 'data-testid="group-layout"' in r.text
        assert "admin" in r.text


async def test_nested_groups():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    api = app.group("/api")
    v1 = api.group("/v1")

    @v1.get("/items", component="Page")
    async def items(ctx: Context):
        return {"message": "items-v1"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/items")
        assert r.status_code == 200
        assert "items-v1" in r.text


async def test_group_post_route():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    grp = app.group("/admin")
    called = {}

    @grp.post("/action", component="Page")
    async def action(ctx: Context):
        called["ok"] = True

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/admin/action")
        assert r.status_code == 200
        assert called.get("ok") is True
