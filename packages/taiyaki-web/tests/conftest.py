"""Shared fixtures for dark tests."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


@pytest.fixture
def app():
    """Create a bare Dark app (no components pre-loaded)."""
    return Taiyaki()


@pytest.fixture
def client_for():
    """Factory: returns an async context manager httpx client for a Taiyaki app."""

    def _make(dark_app: Taiyaki):
        transport = httpx.ASGITransport(app=dark_app.asgi)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return _make
