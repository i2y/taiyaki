"""Tests for CLI scaffolding commands."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from taiyaki_web.__main__ import _cmd_new, _cmd_generate


class _Args:
    """Simple namespace for argparse args."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_new_creates_project_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            _cmd_new(_Args(name="myapp"))

            project = Path("myapp")
            assert project.is_dir()
            assert (project / "app.py").is_file()
            assert (project / "pyproject.toml").is_file()
            assert (project / "components").is_dir()
            assert (project / "islands").is_dir()
            assert (project / "static").is_dir()

            # Check content
            app_content = (project / "app.py").read_text()
            assert "Taiyaki" in app_content
            assert "myapp" in app_content

            toml_content = (project / "pyproject.toml").read_text()
            assert 'name = "myapp"' in toml_content
        finally:
            os.chdir(old_cwd)


def test_generate_component():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            _cmd_generate(_Args(kind="component", name="Header"))

            path = Path("components/Header.tsx")
            assert path.is_file()
            content = path.read_text()
            assert "function Header" in content
            assert "export default" in content
        finally:
            os.chdir(old_cwd)


def test_generate_island():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            _cmd_generate(_Args(kind="island", name="Toggle"))

            path = Path("islands/Toggle.tsx")
            assert path.is_file()
            content = path.read_text()
            assert "function Toggle" in content
            assert "useState" in content
        finally:
            os.chdir(old_cwd)
