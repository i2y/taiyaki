"""Tests for streaming SSR."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


async def test_streaming_with_markers():
    app = Taiyaki()
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("div", null,
        h("header", null, "HEAD"),
        h("taiyaki-stream-marker", null),
        h("main", null, "BODY"),
        h("taiyaki-stream-marker", null),
        h("footer", null, "FOOT")
    );
}
""")

    @app.get("/", component="Page", stream=True)
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "HEAD" in r.text
        assert "BODY" in r.text
        assert "FOOT" in r.text
        assert "<!DOCTYPE html>" in r.text
        # Markers should be consumed (not in output)
        assert "<taiyaki-stream-marker>" not in r.text


async def test_streaming_without_markers():
    app = Taiyaki()
    app.load_component("Page", """
import { h } from "preact";
export default function Page({ msg }) {
    return h("div", null, msg);
}
""")

    @app.get("/", component="Page", stream=True)
    async def index(ctx: Context):
        return {"msg": "no-markers"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "no-markers" in r.text
        assert "<!DOCTYPE html>" in r.text
