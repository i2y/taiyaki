"""Tests for htmx integration: request detection, partials, HX-Redirect."""

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

_PARTIAL = """
import { h } from "preact";
export default function TimeDisplay({ time }) {
    return h("span", { id: "time" }, time);
}
"""


async def test_htmx_request_detection():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "htmx=" + str(ctx.is_htmx)}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Normal request
        r1 = await c.get("/")
        assert "htmx=False" in r1.text

        # htmx request
        r2 = await c.get("/", headers={"HX-Request": "true"})
        assert "htmx=True" in r2.text


async def test_partial_rendering():
    app = Taiyaki()
    app.load_component("TimeDisplay", _PARTIAL)

    @app.api_get("/api/time")
    async def time_partial(ctx: Context):
        return await app.partial("TimeDisplay", time="15:30")

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/time")
        assert r.status_code == 200
        assert "15:30" in r.text
        # Partial should NOT have full HTML document wrapper
        assert "<!DOCTYPE html>" not in r.text


async def test_htmx_redirect():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/old", component="Page")
    async def old(ctx: Context):
        ctx.redirect("/new")
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as c:
        # htmx redirect uses HX-Redirect header with 200 status
        r = await c.get("/old", headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert r.headers.get("HX-Redirect") == "/new"
