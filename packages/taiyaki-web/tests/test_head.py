"""Tests for <taiyaki-head> extraction."""

from __future__ import annotations

import httpx
import pytest

from taiyaki_web import Taiyaki, Context
from taiyaki_web.head import extract_taiyaki_head, strip_taiyaki_head, extract_title


# ── Unit tests ──

def test_extract_single_block():
    html = '<div><taiyaki-head><title>Hi</title></taiyaki-head><p>body</p></div>'
    cleaned, head = extract_taiyaki_head(html)
    assert "<taiyaki-head>" not in cleaned
    assert "<title>Hi</title>" in head
    assert "<p>body</p>" in cleaned


def test_extract_multiple_blocks():
    html = (
        '<taiyaki-head><title>A</title></taiyaki-head>'
        '<p>body</p>'
        '<taiyaki-head><link rel="stylesheet" href="/x.css"></taiyaki-head>'
    )
    cleaned, head = extract_taiyaki_head(html)
    assert "<taiyaki-head>" not in cleaned
    assert "<title>A</title>" in head
    assert 'href="/x.css"' in head


def test_extract_no_blocks():
    html = "<div>hello</div>"
    cleaned, head = extract_taiyaki_head(html)
    assert cleaned == html
    assert head == ""


def test_strip_taiyaki_head():
    html = '<taiyaki-head><title>X</title></taiyaki-head><p>keep</p>'
    assert strip_taiyaki_head(html) == "<p>keep</p>"


def test_extract_title():
    assert extract_title("<title>Hello</title><link>") == "Hello"
    assert extract_title("<link>") is None


def test_extract_title_empty():
    assert extract_title("<title></title>") == ""


# ── Integration test ──

async def test_dark_head_in_rendered_page():
    app = Taiyaki()
    app.load_component("Page", """
import { h } from "preact";
export default function Page() {
    return h("div", null,
        h("taiyaki-head", null,
            h("title", null, "Custom Title"),
            h("link", { rel: "stylesheet", href: "/style.css" })
        ),
        h("p", null, "Content")
    );
}
""")

    @app.get("/", component="Page")
    async def index(ctx: Context):
        return {}

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
        # Custom title should be in <head>
        assert "<title>Custom Title</title>" in r.text
        # <taiyaki-head> tags should be stripped from body
        assert "<taiyaki-head>" not in r.text
        # Body content preserved
        assert "<p>Content</p>" in r.text


async def test_dark_head_stripped_in_partial():
    app = Taiyaki()
    app.load_component("Widget", """
import { h } from "preact";
export default function Widget() {
    return h("div", null,
        h("taiyaki-head", null, h("title", null, "Ignored")),
        h("span", null, "partial content")
    );
}
""")

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await app.partial("Widget")
        body = resp.body.decode()
        assert "<taiyaki-head>" not in body
        assert "partial content" in body
