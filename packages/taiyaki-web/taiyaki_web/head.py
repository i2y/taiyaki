"""<taiyaki-head> extraction for component-driven head management."""

from __future__ import annotations

import re

_DARK_HEAD_RE = re.compile(r"(?s)<taiyaki-head>(.*?)</taiyaki-head>")
_TITLE_RE = re.compile(r"(?s)<title>(.*?)</title>")


def extract_taiyaki_head(html: str) -> tuple[str, str]:
    """Extract all <taiyaki-head> blocks from HTML.

    Returns (cleaned_html, head_content) where cleaned_html has the
    <taiyaki-head> tags removed and head_content is the concatenated inner
    content of all blocks.
    """
    parts: list[str] = []

    def _collect(m: re.Match) -> str:
        content = m.group(1).strip()
        if content:
            parts.append(content)
        return ""

    cleaned = _DARK_HEAD_RE.sub(_collect, html)
    return cleaned, "\n".join(parts)


def strip_taiyaki_head(html: str) -> str:
    """Remove all <taiyaki-head> blocks, discarding their content."""
    return _DARK_HEAD_RE.sub("", html)


def extract_title(content: str) -> str | None:
    """Extract the inner text of the first <title> tag, or None."""
    match = _TITLE_RE.search(content)
    if match:
        return match.group(1)
    return None


def strip_title(content: str) -> str:
    """Remove all <title> tags from content."""
    return _TITLE_RE.sub("", content).strip()
