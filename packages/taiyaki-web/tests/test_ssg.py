"""Tests for static site generation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from taiyaki_web import Taiyaki, Context


_PAGE = """
import { h } from "preact";
export default function Page({ message }) {
    return h("div", { "data-testid": "page" }, message || "home");
}
"""

_ABOUT = """
import { h } from "preact";
export default function About() {
    return h("div", { "data-testid": "about" }, "about page");
}
"""


async def test_ssg_generates_index_html():
    app = Taiyaki()
    app.load_component("Page", _PAGE)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "static home"}

    with tempfile.TemporaryDirectory() as tmpdir:
        await app.generate_static_site(tmpdir, ["/"])
        index_path = Path(tmpdir) / "index.html"
        assert index_path.exists()
        content = index_path.read_text()
        assert "static home" in content
        assert "<!DOCTYPE html>" in content


async def test_ssg_generates_nested_routes():
    app = Taiyaki()
    app.load_component("Page", _PAGE)
    app.load_component("About", _ABOUT)

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {"message": "home"}

    @app.get("/about", component="About")
    async def about(ctx: Context):
        return {}

    with tempfile.TemporaryDirectory() as tmpdir:
        await app.generate_static_site(tmpdir, ["/", "/about"])
        assert (Path(tmpdir) / "index.html").exists()
        about_path = Path(tmpdir) / "about" / "index.html"
        assert about_path.exists()
        assert "about page" in about_path.read_text()
