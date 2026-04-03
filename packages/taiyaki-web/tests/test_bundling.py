"""Tests for island asset bundling (content hashing + modulepreload)."""

from __future__ import annotations

from taiyaki_web.islands import IslandRegistry, content_hash


# ── content_hash ──

def test_content_hash_deterministic():
    h1 = content_hash("console.log('hello');")
    h2 = content_hash("console.log('hello');")
    assert h1 == h2
    assert len(h1) == 8


def test_content_hash_different_content():
    h1 = content_hash("a")
    h2 = content_hash("b")
    assert h1 != h2


# ── hydration_script with hashes ──

def test_hydration_script_uses_hashed_urls():
    hashes = {"Counter": "abc12345"}
    script = IslandRegistry.hydration_script(
        {"Counter"}, island_hashes=hashes,
    )
    assert "/_taiyaki/islands/Counter-abc12345.js" in script


def test_hydration_script_without_hashes():
    script = IslandRegistry.hydration_script({"Counter"})
    assert "/_taiyaki/islands/Counter.js" in script
    assert "modulepreload" not in script


def test_modulepreload_links_present():
    hashes = {"Counter": "abc12345", "Toggle": "def67890"}
    script = IslandRegistry.hydration_script(
        {"Counter", "Toggle"}, island_hashes=hashes,
    )
    assert '<link rel="modulepreload" href="/_taiyaki/islands/Counter-abc12345.js">' in script
    assert '<link rel="modulepreload" href="/_taiyaki/islands/Toggle-def67890.js">' in script


def test_no_script_for_empty_islands():
    result = IslandRegistry.hydration_script(set())
    assert result == ""
