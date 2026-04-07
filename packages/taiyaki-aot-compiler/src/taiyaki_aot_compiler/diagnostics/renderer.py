"""Rust/Elm-style diagnostic renderer with source snippets and underlines."""

from __future__ import annotations

from taiyaki_aot_compiler.diagnostics.diagnostic import Diagnostic, Level


class DiagnosticRenderer:
    """Renders diagnostics in Rust/Elm style with source code excerpts."""

    COLORS = {
        "error": "\033[1;31m",
        "warning": "\033[1;33m",
        "info": "\033[1;36m",
        "hint": "\033[1;32m",
        "bold": "\033[1m",
        "blue": "\033[1;34m",
        "reset": "\033[0m",
    }

    def __init__(self, color: bool = True):
        self._color = color

    def _c(self, key: str) -> str:
        if not self._color:
            return ""
        return self.COLORS.get(key, "")

    def render_all(self, diagnostics: list[Diagnostic], sources: dict[str, str]) -> str:
        parts = []
        for diag in diagnostics:
            parts.append(self.render_one(diag, sources))
        return "\n".join(parts)

    def render_one(self, diag: Diagnostic, sources: dict[str, str]) -> str:
        lines: list[str] = []
        lines.append(self._render_header(diag))

        source = None
        if diag.location:
            lines.append(self._render_location(diag))
            source = sources.get(diag.location.file)

        if source and diag.location:
            lines.append(self._render_snippet(diag, source))
        elif diag.location:
            lines.append(self._gutter("") + "")

        if diag.hint:
            lines.append(self._render_hint(diag))

        return "\n".join(lines)

    def _render_header(self, diag: Diagnostic) -> str:
        level = diag.level.value
        color_key = level
        return f"{self._c(color_key)}{level}{self._c('reset')}: {self._c('bold')}{diag.message}{self._c('reset')}"

    def _render_location(self, diag: Diagnostic) -> str:
        loc = diag.location
        return f"  {self._c('blue')}-->{self._c('reset')} {loc}"

    def _render_snippet(self, diag: Diagnostic, source: str) -> str:
        loc = diag.location
        source_lines = source.splitlines()
        line_idx = loc.line - 1

        if line_idx < 0 or line_idx >= len(source_lines):
            return self._gutter("") + ""

        line_text = source_lines[line_idx]
        line_num = str(loc.line)
        gutter_width = len(line_num) + 1

        parts: list[str] = []
        parts.append(self._gutter_pad(gutter_width) + self._c("blue") + "|" + self._c("reset"))
        parts.append(
            f" {self._c('blue')}{line_num:>{gutter_width - 1}}{self._c('reset')} "
            f"{self._c('blue')}|{self._c('reset')} {line_text}"
        )

        col = loc.col
        end_col = loc.end_col if loc.end_col is not None else col + 1
        if end_col <= col:
            end_col = col + 1

        underline = " " * col + "^" * (end_col - col)
        level_color = diag.level.value
        parts.append(
            self._gutter_pad(gutter_width)
            + self._c("blue") + "|" + self._c("reset")
            + " " + self._c(level_color) + underline + self._c("reset")
        )
        parts.append(
            self._gutter_pad(gutter_width)
            + self._c("blue") + "|" + self._c("reset")
            + " " * (col + 2) + self._c(level_color) + diag.message + self._c("reset")
        )
        parts.append(self._gutter_pad(gutter_width) + self._c("blue") + "|" + self._c("reset"))

        return "\n".join(parts)

    def _render_hint(self, diag: Diagnostic) -> str:
        return f"   {self._c('hint')}={self._c('reset')} {self._c('bold')}hint{self._c('reset')}: {diag.hint}"

    def _gutter(self, text: str) -> str:
        return f"   {self._c('blue')}{text}{self._c('reset')}"

    def _gutter_pad(self, width: int) -> str:
        return " " * width + " "
