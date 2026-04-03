"""Streaming SSR support."""

from __future__ import annotations

from typing import AsyncGenerator

_STREAM_MARKER = "<taiyaki-stream-marker></taiyaki-stream-marker>"


def split_at_markers(html: str) -> list[str]:
    """Split rendered HTML at <taiyaki-stream-marker> boundaries."""
    parts = html.split(_STREAM_MARKER)
    return [p for p in parts if p]


async def streaming_chunks(
    head: str,
    body_chunks: list[str],
    tail: str,
) -> AsyncGenerator[str, None]:
    """Yield HTML chunks for StreamingResponse."""
    # First chunk: head + first body piece (for fast TTFB)
    first = head
    if body_chunks:
        first += body_chunks[0]
    yield first

    # Middle chunks
    for chunk in body_chunks[1:]:
        yield chunk

    # Final chunk: scripts + closing tags
    yield tail
