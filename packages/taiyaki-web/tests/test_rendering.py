"""Tests for SSR rendering, props, and layout composition."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


async def test_component_receives_props():
    app = Taiyaki()
    app.load_component("Greeting", """
import { h } from "preact";
export default function Greeting({ name, age }) {
    return h("p", { "data-testid": "greet" }, name + " is " + age);
}
""")

    @app.get("/", component="Greeting")
    async def index(ctx: Context):
        return {"name": "Alice", "age": "30"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert "Alice is 30" in r.text


async def test_global_layout():
    app = Taiyaki(layout="MainLayout")
    app.load_component("MainLayout", """
import { h } from "preact";
export default function MainLayout({ children }) {
    return h("main", { "data-testid": "main-layout" }, children);
}
""")
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("p", { "data-testid": "page" }, "content");
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'data-testid="main-layout"' in r.text
        assert 'data-testid="page"' in r.text
        assert r.text.index('data-testid="main-layout"') < r.text.index('data-testid="page"')


async def test_route_layout():
    app = Taiyaki()
    app.load_component("RouteLayout", """
import { h } from "preact";
export default function RouteLayout({ children }) {
    return h("div", { "data-testid": "route-layout" }, children);
}
""")
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("span", { "data-testid": "page" }, "hi");
}
""")

    @app.get("/", component="Page", layout="RouteLayout")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'data-testid="route-layout"' in r.text
        assert r.text.index('data-testid="route-layout"') < r.text.index('data-testid="page"')


async def test_concurrent_loaders_with_gather():
    app = Taiyaki()
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ a, b }) {
    return h("div", null, a + "+" + b);
}
""")

    async def load_a(ctx: Context):
        return {"a": "A"}

    async def load_b(ctx: Context):
        return {"b": "B"}

    @app.get("/", component="Page")
    async def index(ctx: Context):
        a, b = await asyncio.gather(load_a(ctx), load_b(ctx))
        return {**a, **b}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert "A+B" in r.text


async def test_layout_chain_global_group_route():
    """Three-level layout chain: global > group > route > page."""
    app = Taiyaki(layout="GlobalLayout")
    app.load_component("GlobalLayout", """
import { h } from "preact";
export default function GlobalLayout({ children }) {
    return h("main", { "data-testid": "global" }, children);
}
""")
    app.load_component("GroupLayout", """
import { h } from "preact";
export default function GroupLayout({ children }) {
    return h("section", { "data-testid": "group" }, children);
}
""")
    app.load_component("RouteLayout", """
import { h } from "preact";
export default function RouteLayout({ children }) {
    return h("div", { "data-testid": "route" }, children);
}
""")
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("p", { "data-testid": "page" }, "content");
}
""")

    grp = app.group("/admin", layout="GroupLayout")

    @grp.get("/dash", component="Page", layout="RouteLayout")
    async def dash(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/admin/dash")
        assert r.status_code == 200
        html = r.text
        global_pos = html.index('data-testid="global"')
        group_pos = html.index('data-testid="group"')
        route_pos = html.index('data-testid="route"')
        page_pos = html.index('data-testid="page"')
        assert global_pos < group_pos < route_pos < page_pos
