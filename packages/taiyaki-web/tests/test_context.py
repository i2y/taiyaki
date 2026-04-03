"""Tests for Context: redirect, cookies, title, meta, field errors."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_PAGE = """
import { h } from "preact";
export default function Page({ message, _errors }) {
    const errs = _errors ? JSON.stringify(_errors) : "none";
    return h("div", { "data-testid": "page" }, (message || "") + " errors:" + errs);
}
"""


async def test_redirect():
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
        r = await c.get("/old")
        assert r.status_code == 302
        assert r.headers["location"] == "/new"


async def test_set_cookie():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        ctx.set_cookie("flavor", "chocolate")
        return {"message": "ok"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "flavor=chocolate" in r.headers.get("set-cookie", "")


async def test_set_title():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        ctx.set_title("Custom Title")
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert "<title>Custom Title</title>" in r.text


async def test_add_meta():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        ctx.add_meta("description", "test page")
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert 'name="description"' in r.text
        assert 'content="test page"' in r.text


async def test_field_errors():
    app = Taiyaki()
    app.load_component("Form", _PAGE)

    @app.post("/submit", component="Form")
    async def submit(ctx: Context):
        ctx.add_field_error("email", "required")
        ctx.add_field_error("email", "invalid format")

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/submit")
        assert r.status_code == 200
        assert "required" in r.text
        assert "invalid format" in r.text
