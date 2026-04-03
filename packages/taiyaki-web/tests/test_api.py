"""Tests for API endpoints (JSON responses)."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


async def test_api_get_json():
    app = Taiyaki()

    @app.api_get("/api/time")
    async def time_api(ctx: Context):
        return {"time": "12:00", "zone": "UTC"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/time")
        assert r.status_code == 200
        data = r.json()
        assert data["time"] == "12:00"
        assert data["zone"] == "UTC"


async def test_api_post():
    app = Taiyaki()

    @app.api_post("/api/items")
    async def create_item(ctx: Context):
        body = await ctx.json()
        return {"created": True, "name": body.get("name")}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/items", json={"name": "widget"})
        assert r.status_code == 200
        assert r.json()["created"] is True
        assert r.json()["name"] == "widget"


async def test_api_returns_custom_response():
    from starlette.responses import Response

    app = Taiyaki()

    @app.api_get("/api/custom")
    async def custom(ctx: Context):
        return Response("plain text", media_type="text/plain", status_code=201)

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/custom")
        assert r.status_code == 201
        assert r.text == "plain text"
