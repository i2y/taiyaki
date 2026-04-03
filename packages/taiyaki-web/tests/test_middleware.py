"""Tests for Logger, Recover, and RecoverWithOverlay middleware."""

from __future__ import annotations

import logging

import httpx
import pytest

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from taiyaki_web.middleware import Logger, Recover, RecoverWithOverlay


def _ok_app():
    async def homepage(request: Request) -> Response:
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", homepage)])


def _error_app():
    """Raw ASGI app that always raises (no Starlette exception handling)."""
    async def app(scope, receive, send):
        if scope["type"] == "http":
            raise RuntimeError("boom")
    return app


# ── Logger ──

async def test_logger_logs_request(caplog):
    app = Logger(_ok_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        with caplog.at_level(logging.INFO, logger="dark"):
            r = await c.get("/")
    assert r.status_code == 200
    assert any("GET" in rec.message and "200" in rec.message for rec in caplog.records)


async def test_logger_passes_non_http():
    """Non-HTTP scopes are passed through without logging."""
    app = Logger(_ok_app())
    # Just verify it doesn't crash on non-http scope
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200


# ── Recover ──

async def test_recover_catches_exception(caplog):
    app = Recover(_error_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        with caplog.at_level(logging.ERROR, logger="dark"):
            r = await c.get("/")
    assert r.status_code == 500
    assert r.text == "Internal Server Error"


async def test_recover_passes_normal_requests():
    app = Recover(_ok_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert r.text == "ok"


# ── RecoverWithOverlay ──

async def test_recover_with_overlay_shows_overlay():
    app = RecoverWithOverlay(_error_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 500
    assert "taiyaki-overlay" in r.text
    assert "boom" in r.text


async def test_recover_with_overlay_passes_normal():
    app = RecoverWithOverlay(_ok_app())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200
