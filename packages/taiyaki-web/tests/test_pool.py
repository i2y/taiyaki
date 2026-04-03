"""Tests for runtime pool."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_PAGE = """
import { h } from "preact";
export default function Page({ message }) {
    return h("div", { "data-testid": "page" }, message || "hello");
}
"""


async def test_pool_basic_rendering():
    app = Taiyaki(pool_size=2)
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "pooled"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "pooled" in r.text


async def test_pool_concurrent_renders():
    app = Taiyaki(pool_size=3)
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "ok"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        results = await asyncio.gather(
            c.get("/"), c.get("/"), c.get("/"),
        )
        for r in results:
            assert r.status_code == 200
            assert "ok" in r.text


async def test_pool_component_loaded_after_init():
    app = Taiyaki(pool_size=2)
    app.load_component("Page", _PAGE)

    # Load another component after pool would have been initialized
    app.load_component("Other", """
import { h } from "preact";
export default function Other({ text }) {
    return h("span", { id: "other" }, text);
}
""")

    @app.get("/", component="Other")
    async def index(ctx: Context):
        return {"text": "late-loaded"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "late-loaded" in r.text
