"""Runtime pool for concurrent SSR."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import taiyaki

from taiyaki_web.runtime import JsRuntime


class RuntimePool:
    """Pool of JsRuntime instances for concurrent rendering.

    Uses asyncio.Queue for async acquire/release.
    All runtimes are bootstrapped identically.
    """

    def __init__(self, pool_size: int = 4, renderer: str = "preact") -> None:
        self._pool_size = pool_size
        self._renderer = renderer
        self._runtimes: list[JsRuntime] = []
        self._queue: asyncio.Queue[JsRuntime] = asyncio.Queue()
        self._component_js: dict[str, str] = {}  # name → pre-transpiled JS
        self._initialized = False

    def initialize(self) -> None:
        """Create all runtime instances and populate the queue."""
        if self._initialized:
            return
        for _ in range(self._pool_size):
            rt = JsRuntime(renderer=self._renderer)
            for name, js_code in self._component_js.items():
                rt.load_component_js(name, js_code)
            self._runtimes.append(rt)
            self._queue.put_nowait(rt)
        self._initialized = True

    async def acquire(self) -> JsRuntime:
        """Acquire a runtime from the pool. Blocks if none available."""
        if not self._initialized:
            self.initialize()
        return await self._queue.get()

    def release(self, runtime: JsRuntime) -> None:
        """Release a runtime back to the pool."""
        self._queue.put_nowait(runtime)

    def load_component(self, name: str, source: str) -> None:
        """Transpile once, then register on all runtimes."""
        import_source = "react" if self._renderer == "react" else "preact"
        js_code = taiyaki.transform_jsx(source, import_source)
        self._component_js[name] = js_code
        for rt in self._runtimes:
            rt.load_component_js(name, js_code)

    def load_component_file(self, path: Path | str) -> str:
        """Load a component file on all runtimes."""
        path = Path(path)
        name = path.stem
        source = path.read_text()
        self.load_component(name, source)
        return name

    def invalidate_component(self, name: str) -> None:
        """Remove a component from all runtimes."""
        self._component_js.pop(name, None)
        for rt in self._runtimes:
            rt.invalidate_component(name)

    def invalidate_all(self) -> None:
        """Clear all components from all runtimes."""
        self._component_js.clear()
        for rt in self._runtimes:
            rt.invalidate_all()
