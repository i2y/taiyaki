"""Tests for CSRF protection middleware."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context, Sessions, CSRF


_PAGE = """
import { h } from "preact";
export default function Page({ message }) {
    return h("div", { "data-testid": "page" }, message || "ok");
}
"""


def _make_app():
    app = Taiyaki()
    app.use(Sessions("test-secret"))
    app.use(CSRF())
    app.load_component("Page", _PAGE)

    @app.get("/form", component="Page")
    async def form(ctx: Context):
        return {"message": "form"}

    @app.post("/submit", component="Page")
    async def submit(ctx: Context):
        return {}

    return app


async def test_get_includes_csrf_meta_tag():
    app = _make_app()
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/form")
        assert r.status_code == 200
        assert 'name="csrf-token"' in r.text


async def test_post_without_csrf_token_returns_403():
    app = _make_app()
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # First GET to establish session
        await c.get("/form")
        # POST without token
        r = await c.post("/submit")
        assert r.status_code == 403


async def test_post_with_csrf_header_succeeds():
    app = _make_app()
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # GET to establish session and get token
        r1 = await c.get("/form")
        # Extract token from meta tag
        import re
        match = re.search(r'name="csrf-token" content="([^"]+)"', r1.text)
        assert match, "CSRF token not found in response"
        token = match.group(1)

        r2 = await c.post("/submit", headers={"X-CSRF-Token": token})
        assert r2.status_code == 200


async def test_post_with_wrong_csrf_token_returns_403():
    app = _make_app()
    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/form")
        r = await c.post("/submit", headers={"X-CSRF-Token": "wrong-token"})
        assert r.status_code == 403
