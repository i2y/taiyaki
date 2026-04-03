"""Dev error overlay — shows SSR errors in the browser."""

from __future__ import annotations

import html
import re
import traceback as tb_mod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from taiyaki_web.sourcemap import SourceMap


def render_error_overlay(
    error: Exception,
    component: str | None = None,
    source: str | None = None,
    source_file: str | None = None,
    source_map: SourceMap | None = None,
) -> str:
    """Return a full HTML page with a styled error overlay."""
    msg_raw = str(error)
    if source_map:
        from taiyaki_web.sourcemap import map_error_positions

        msg_raw = map_error_positions(msg_raw, source_map)
    msg = html.escape(msg_raw)
    tb = html.escape(tb_mod.format_exc())

    title_parts = [type(error).__name__]
    if component:
        title_parts.append(f"in &lt;{html.escape(component)}&gt;")
    title = " ".join(title_parts)

    source_section = ""
    if source and source_file:
        error_line = _parse_error_line(msg_raw, source_map=source_map)
        lines = source.splitlines()
        source_lines = []
        for i, line in enumerate(lines, 1):
            escaped = html.escape(line)
            if i == error_line:
                source_lines.append(
                    f'<span style="background:#ff000033;display:block">'
                    f"{i:4d} | {escaped}</span>"
                )
            else:
                source_lines.append(f"{i:4d} | {escaped}")
        source_html = "\n".join(source_lines)
        source_section = (
            f'<div style="margin-top:16px">'
            f'<div style="color:#999;margin-bottom:4px">'
            f"{html.escape(source_file)}</div>"
            f'<pre style="background:#1e1e1e;color:#d4d4d4;padding:12px;'
            f'border-radius:4px;overflow-x:auto;font-size:13px;line-height:1.5">'
            f"{source_html}</pre></div>"
        )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Taiyaki — Error</title>\n"
        "</head>\n"
        '<body style="margin:0;font-family:-apple-system,system-ui,sans-serif">\n'
        '<div id="taiyaki-overlay" style="background:#1a1a2e;color:#eee;'
        'min-height:100vh;padding:24px">\n'
        f'  <div style="background:#e74c3c;color:white;padding:16px 20px;'
        f'border-radius:8px;font-size:18px;font-weight:600">{title}</div>\n'
        f'  <div style="margin-top:12px;font-size:16px;color:#ff6b6b">{msg}</div>\n'
        f'  <pre style="background:#16213e;color:#ccc;padding:16px;'
        f"border-radius:8px;margin-top:16px;overflow-x:auto;font-size:13px;"
        f'line-height:1.5">{tb}</pre>\n'
        f"{source_section}\n"
        "  <button onclick=\"document.getElementById('taiyaki-overlay').remove()\" "
        'style="margin-top:16px;padding:8px 16px;background:#333;color:#eee;'
        "border:1px solid #555;border-radius:4px;cursor:pointer;"
        'font-size:14px">Dismiss</button>\n'
        "</div>\n"
        "</body>\n"
        "</html>"
    )


def _parse_error_line(
    error_msg: str, source_map: SourceMap | None = None
) -> int | None:
    """If a source_map is provided, translate the generated line to original."""
    match = re.search(r"(?:at |[Ll]ine |:)(\d+)(?::(\d+))?", error_msg)
    if not match:
        return None
    line = int(match.group(1))
    col = int(match.group(2)) if match.group(2) else 0
    if source_map:
        pos = source_map.lookup(line, col)
        if pos:
            return pos.line
    return line
