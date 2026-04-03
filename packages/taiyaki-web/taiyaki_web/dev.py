"""Hot reload support for development mode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route


class DevReloader:
    """File watcher + SSE endpoint for dev hot reload.

    Watches component and island directories for changes. When a file
    changes, notifies all connected browsers via Server-Sent Events to
    reload the page.

    Requires `watchfiles` package (optional dev dependency).
    """

    def __init__(
        self,
        watch_dirs: list[Path],
        on_change: Callable[[set[str]], None] | None = None,
    ) -> None:
        self._watch_dirs = [d for d in watch_dirs if d.exists()]
        self._on_change = on_change
        self._clients: list[asyncio.Queue[str]] = []
        self._watcher_task: asyncio.Task[None] | None = None

    def routes(self) -> list[Route]:
        """Return routes for the SSE endpoint."""
        return [Route("/_taiyaki/reload", self._sse_endpoint)]

    async def start(self) -> None:
        """Start the file watcher in the background."""
        if not self._watch_dirs:
            return
        self._watcher_task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop the file watcher."""
        if self._watcher_task:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        """Watch directories for changes and notify clients."""
        try:
            import watchfiles
        except ImportError:
            return

        async for changes in watchfiles.awatch(*self._watch_dirs):
            changed_files = {str(path) for _, path in changes}
            if self._on_change:
                self._on_change(changed_files)
            for queue in list(self._clients):
                try:
                    await queue.put("reload")
                except Exception:
                    pass

    async def _sse_endpoint(self, request: Request) -> Response:
        """SSE endpoint that pushes reload events to the browser."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._clients.append(queue)

        async def event_stream() -> Any:
            try:
                yield "data: connected\n\n"
                while True:
                    data = await queue.get()
                    yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                if queue in self._clients:
                    self._clients.remove(queue)

        from starlette.responses import StreamingResponse

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
