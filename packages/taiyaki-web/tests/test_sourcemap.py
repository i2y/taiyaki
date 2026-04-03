"""Tests for source map parsing and error position mapping."""

from __future__ import annotations

import base64
import json

from taiyaki_web.sourcemap import (
    SourceMap,
    decode_vlq,
    map_error_positions,
    parse_inline_source_map,
)


# ── VLQ decoding ──

def test_decode_vlq_simple():
    # 'A' = 0, 'C' = 1 (positive)
    assert decode_vlq("A") == [0]
    assert decode_vlq("C") == [1]


def test_decode_vlq_negative():
    # 'D' = -1
    assert decode_vlq("D") == [-1]


def test_decode_vlq_multi():
    # 'AACA' → [0, 0, 1, 0]
    vals = decode_vlq("AACA")
    assert vals == [0, 0, 1, 0]


def test_decode_vlq_large():
    # 'gB' = 16 (continuation bit)
    vals = decode_vlq("gB")
    assert vals == [16]


# ── SourceMap parsing ──

def _make_inline_map(sources, mappings):
    raw = {"version": 3, "sources": sources, "mappings": mappings, "names": []}
    encoded = base64.b64encode(json.dumps(raw).encode()).decode()
    return f"var x;\n//# sourceMappingURL=data:application/json;base64,{encoded}\n"


def test_parse_inline_source_map():
    js = _make_inline_map(["input.tsx"], "AAAA;AACA")
    sm = parse_inline_source_map(js)
    assert sm is not None
    assert sm.sources == ["input.tsx"]


def test_parse_inline_source_map_none():
    assert parse_inline_source_map("var x = 1;") is None


# ── Lookup ──

def test_lookup_basic():
    # Line 1 col 0 → source 0, line 0, col 0
    # Line 2 col 0 → source 0, line 1, col 0
    js = _make_inline_map(["test.tsx"], "AAAA;AACA")
    sm = parse_inline_source_map(js)
    assert sm is not None

    pos = sm.lookup(1, 0)
    assert pos is not None
    assert pos.source == "test.tsx"
    assert pos.line == 1
    assert pos.column == 0

    pos2 = sm.lookup(2, 0)
    assert pos2 is not None
    assert pos2.line == 2


def test_lookup_out_of_range():
    js = _make_inline_map(["x.tsx"], "AAAA")
    sm = parse_inline_source_map(js)
    assert sm is not None
    assert sm.lookup(999, 0) is None


# ── Error mapping ──

def test_map_error_positions():
    js = _make_inline_map(["comp.tsx"], "AAAA;AACA;AACA")
    sm = parse_inline_source_map(js)
    assert sm is not None

    msg = "Error at <eval>:2:0 something"
    mapped = map_error_positions(msg, sm)
    assert "comp.tsx:2:0" in mapped


def test_map_error_no_match():
    js = _make_inline_map(["x.tsx"], "AAAA")
    sm = parse_inline_source_map(js)
    assert sm is not None
    msg = "some error without positions"
    assert map_error_positions(msg, sm) == msg
