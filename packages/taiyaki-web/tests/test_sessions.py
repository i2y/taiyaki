"""Tests for session middleware."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context, Sessions


_PAGE = """
import { h } from "preact";
export default function Page({ value }) {
    return h("div", { "data-testid": "page" }, value || "empty");
}
"""


async def test_session_set_and_get():
    app = Taiyaki()
    app.use(Sessions("test-secret"))
    app.load_component("Page", _PAGE)

    @app.get("/set", component="Page")
    async def set_session(ctx: Context):
        ctx.session()["user"] = "alice"
        return {"value": "set"}

    @app.get("/get", component="Page")
    async def get_session(ctx: Context):
        return {"value": ctx.session().get("user", "none")}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/set")
        assert r1.status_code == 200
        # Extract session cookie
        cookies = r1.cookies
        r2 = await c.get("/get")
        assert "alice" in r2.text


async def test_flash_messages():
    app = Taiyaki()
    app.use(Sessions("test-secret"))
    app.load_component("Page", _PAGE)

    @app.get("/flash", component="Page")
    async def flash(ctx: Context):
        ctx.flash("hello!", "success")
        return {"value": "flashed"}

    @app.get("/read", component="Page")
    async def read(ctx: Context):
        msgs = ctx.get_flashed_messages()
        text = msgs[0]["message"] if msgs else "none"
        return {"value": text}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/flash")
        r = await c.get("/read")
        assert "hello!" in r.text


async def test_session_persists_across_requests():
    app = Taiyaki()
    app.use(Sessions("test-secret"))
    app.load_component("Page", _PAGE)

    @app.get("/inc", component="Page")
    async def inc(ctx: Context):
        session = ctx.session()
        count = session.get("count", 0) + 1
        session["count"] = count
        return {"value": str(count)}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/inc")
        await c.get("/inc")
        r = await c.get("/inc")
        assert "3" in r.text


async def test_session_tamper_rejected():
    app = Taiyaki()
    app.use(Sessions("test-secret"))
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"value": ctx.session().get("user", "anonymous")}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Set a tampered cookie
        c.cookies.set("taiyaki_session", "tampered-value")
        r = await c.get("/")
        # Tampered session should be ignored, user gets anonymous
        assert "anonymous" in r.text
