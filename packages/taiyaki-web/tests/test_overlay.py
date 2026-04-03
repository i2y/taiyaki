"""Tests for dev error overlay."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_BROKEN = """
import { h } from "preact";
export default function Broken() {
    throw new Error("component crash");
}
"""


async def test_dev_overlay_on_ssr_error():
    app = Taiyaki(dev_mode=True)
    app.load_component("Broken", _BROKEN)

    @app.get("/", component="Broken")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 500
        assert "taiyaki-overlay" in r.text
        assert "component crash" in r.text
        assert "Dismiss" in r.text


async def test_no_overlay_in_prod_mode():
    app = Taiyaki(dev_mode=False)
    app.load_component("Broken", _BROKEN)

    @app.get("/", component="Broken")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # In prod mode, the error should propagate as an exception
        with pytest.raises(RuntimeError, match="component crash"):
            await c.get("/")
