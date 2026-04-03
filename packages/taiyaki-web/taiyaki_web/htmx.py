"""htmx integration helpers."""

from __future__ import annotations

from starlette.requests import Request


def is_htmx_request(request: Request) -> bool:
    """Check if the request was made by htmx."""
    return request.headers.get("hx-request") == "true"


def hx_attrs(**kwargs: str) -> str:
    """Generate htmx attributes string for use in HTML/JSX.

    Usage:
        hx_attrs(get="/api/data", target="#result", swap="innerHTML")
        # → 'hx-get="/api/data" hx-target="#result" hx-swap="innerHTML"'
    """
    parts = []
    for key, value in kwargs.items():
        attr = f"hx-{key.replace('_', '-')}"
        parts.append(f'{attr}="{value}"')
    return " ".join(parts)
