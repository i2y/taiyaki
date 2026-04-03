"""Tests for renderer support (preact/react configuration)."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context
from taiyaki_web.renderers import RENDERERS


_PAGE = """
import { h } from "preact";
export default function Page({ msg }) {
    return h("div", { "data-testid": "page" }, msg);
}
"""


async def test_preact_renderer_default():
    """Default renderer is preact and produces valid HTML."""
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"msg": "preact-ok"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert r.status_code == 200
        assert "preact-ok" in r.text
        # Import map should reference preact
        assert "preact-client.bundle.js" in r.text


async def test_preact_import_map_in_html():
    """Import map should contain preact entries."""
    app = Taiyaki(renderer="preact")
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"msg": "map-test"}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        assert "importmap" in r.text
        assert "preact" in r.text


def test_renderers_config_has_both():
    """Both preact and react configs exist."""
    assert "preact" in RENDERERS
    assert "react" in RENDERERS
    for key in ("ssr_bundle", "client_bundle", "import_map", "module_shims",
                "bootstrap_imports", "create_element", "hydrate_import", "hydrate_call"):
        assert key in RENDERERS["preact"]
        assert key in RENDERERS["react"]


def test_react_renderer_fails_without_bundle():
    """React renderer should fail with clear error when bundle is missing."""
    with pytest.raises(FileNotFoundError, match="react-all.bundle.js"):
        Taiyaki(renderer="react")
