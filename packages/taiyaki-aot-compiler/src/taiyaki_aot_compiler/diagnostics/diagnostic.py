"""Diagnostic messages for the Tsuchi compiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Level(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Location:
    file: str
    line: int
    col: int
    end_line: int | None = None
    end_col: int | None = None

    def __str__(self):
        return f"{self.file}:{self.line}:{self.col}"


@dataclass
class Diagnostic:
    level: Level
    message: str
    location: Location | None = None
    hint: str | None = None

    def format(self) -> str:
        prefix = self.level.value
        loc = f" at {self.location}" if self.location else ""
        msg = f"[{prefix}]{loc}: {self.message}"
        if self.hint:
            msg += f"\n  hint: {self.hint}"
        return msg


class DiagnosticCollector:
    def __init__(self):
        self.diagnostics: list[Diagnostic] = []
        self._sources: dict[str, str] = {}

    def register_source(self, filename: str, source: str):
        self._sources[filename] = source

    def get_source(self, filename: str) -> str | None:
        return self._sources.get(filename)

    def info(self, message: str, location: Location | None = None, hint: str | None = None):
        self.diagnostics.append(Diagnostic(Level.INFO, message, location, hint))

    def warning(self, message: str, location: Location | None = None, hint: str | None = None):
        self.diagnostics.append(Diagnostic(Level.WARNING, message, location, hint))

    def error(self, message: str, location: Location | None = None, hint: str | None = None):
        self.diagnostics.append(Diagnostic(Level.ERROR, message, location, hint))

    def has_errors(self) -> bool:
        return any(d.level == Level.ERROR for d in self.diagnostics)

    def format_all(self) -> str:
        return "\n".join(d.format() for d in self.diagnostics)

    def render_all(self, color: bool = True) -> str:
        """Rust/Elm-style formatted output."""
        from taiyaki_aot_compiler.diagnostics.renderer import DiagnosticRenderer
        renderer = DiagnosticRenderer(color=color)
        return renderer.render_all(self.diagnostics, self._sources)
