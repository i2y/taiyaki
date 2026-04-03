"""Tests for island hydration markers and scripts."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_COUNTER = """
import { h } from "preact";
import { useState } from "preact/hooks";
export default function Counter({ initial }) {
    const [count, setCount] = useState(initial || 0);
    return h("button", { onClick: () => setCount(count + 1), "data-testid": "counter" }, count);
}
"""


async def test_island_has_data_attributes():
    app = Taiyaki()
    app.load_component("Counter", _COUNTER)
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ counterHtml }) {
    return h("div", { dangerouslySetInnerHTML: { __html: counterHtml } });
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        counter = await app.island("Counter", _ctx=ctx, initial=5)
        return {"counterHtml": counter}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'data-island="Counter"' in r.text
        assert "data-props=" in r.text
        assert '"initial": 5' in r.text or '"initial":5' in r.text


async def test_island_hydration_script_present():
    app = Taiyaki()
    app.load_component("Counter", _COUNTER)
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ counterHtml }) {
    return h("div", { dangerouslySetInnerHTML: { __html: counterHtml } });
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        counter = await app.island("Counter", _ctx=ctx, initial=0)
        return {"counterHtml": counter}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'import { h, hydrate } from "preact"' in r.text
        assert '/_taiyaki/islands/Counter.js' in r.text


async def test_island_idle_load_strategy():
    app = Taiyaki()
    app.load_component("Counter", _COUNTER)
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ counterHtml }) {
    return h("div", { dangerouslySetInnerHTML: { __html: counterHtml } });
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        counter = await app.island("Counter", load="idle", _ctx=ctx, initial=0)
        return {"counterHtml": counter}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'data-load="idle"' in r.text


async def test_island_visible_load_strategy():
    app = Taiyaki()
    app.load_component("Counter", _COUNTER)
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ counterHtml }) {
    return h("div", { dangerouslySetInnerHTML: { __html: counterHtml } });
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        counter = await app.island("Counter", load="visible", _ctx=ctx, initial=0)
        return {"counterHtml": counter}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'data-load="visible"' in r.text
        assert "IntersectionObserver" in r.text


async def test_no_hydration_script_without_islands():
    app = Taiyaki()
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("div", null, "static");
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'import { h, hydrate }' not in r.text
