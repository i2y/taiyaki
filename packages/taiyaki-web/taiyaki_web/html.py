"""HTML document shell generation."""

from __future__ import annotations

import json

from taiyaki_web.renderers import RENDERERS

_DEFAULT_IMPORT_MAP = RENDERERS["preact"]["import_map"]


def _build_import_map(imports: dict[str, str]) -> str:
    return (
        '<script type="importmap">\n'
        f"{json.dumps({'imports': imports}, indent=2)}\n"
        "</script>\n"
    )


def document(
    title: str,
    body: str,
    *,
    head_extra: str = "",
    scripts: str = "",
    meta_tags: list[tuple[str, str]] | None = None,
    import_map: dict[str, str] | None = None,
    dark_head_content: str = "",
) -> str:
    """Wrap body HTML in a full HTML document."""
    head, _, tail = document_parts(
        title,
        [body],
        head_extra=head_extra,
        scripts=scripts,
        meta_tags=meta_tags,
        import_map=import_map,
        dark_head_content=dark_head_content,
    )
    return head + body + "\n" + tail


def document_parts(
    title: str,
    body_chunks: list[str],
    *,
    head_extra: str = "",
    scripts: str = "",
    meta_tags: list[tuple[str, str]] | None = None,
    import_map: dict[str, str] | None = None,
    dark_head_content: str = "",
) -> tuple[str, list[str], str]:
    """Return (head, body_chunks, tail) for streaming responses."""
    effective_title = title
    if dark_head_content:
        from taiyaki_web.head import extract_title, strip_title

        override = extract_title(dark_head_content)
        if override is not None:
            effective_title = override
            dark_head_content = strip_title(dark_head_content)

    meta_html = ""
    for name, content in meta_tags or []:
        meta_html += f'  <meta name="{_escape(name)}" content="{_escape(content)}">\n'
    imap = _build_import_map(import_map or _DEFAULT_IMPORT_MAP)
    dark_head_section = f"  {dark_head_content}\n" if dark_head_content else ""
    head = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{_escape(effective_title)}</title>\n"
        f"{meta_html}"
        f"{head_extra}"
        f"{dark_head_section}"
        "</head>\n"
        "<body>\n"
    )
    tail = f"\n{imap}{scripts}</body>\n</html>"
    return head, body_chunks, tail


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
