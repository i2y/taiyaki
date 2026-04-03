"""Tests for LRU response cache with ETag."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_PAGE = """
import { h } from "preact";
export default function Page({ message }) {
    return h("div", { "data-testid": "page" }, message || "cached");
}
"""


async def test_cache_hit_has_etag():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    call_count = 0

    @app.get("/", component="Page", cache=True)
    async def index(ctx: Context):
        nonlocal call_count
        call_count += 1
        return {"message": "hello"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/")
        assert r1.status_code == 200
        assert "ETag" in r1.headers
        etag = r1.headers["ETag"]

        # Second request should be a cache hit
        r2 = await c.get("/")
        assert r2.status_code == 200
        assert r2.headers["ETag"] == etag
        # Loader should only have been called once
        assert call_count == 1


async def test_if_none_match_returns_304():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page", cache=True)
    async def index(ctx: Context):
        return {"message": "etag-test"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/")
        etag = r1.headers["ETag"]

        r2 = await c.get("/", headers={"If-None-Match": etag})
        assert r2.status_code == 304


async def test_cache_invalidation():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    call_count = 0

    @app.get("/", component="Page", cache=True)
    async def index(ctx: Context):
        nonlocal call_count
        call_count += 1
        return {"message": f"v{call_count}"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/")
        assert "v1" in r1.text

        # Invalidate
        app._invalidate_components()
        # Re-register component after invalidation
        app.load_component("Page", _PAGE)

        r2 = await c.get("/")
        assert "v2" in r2.text
