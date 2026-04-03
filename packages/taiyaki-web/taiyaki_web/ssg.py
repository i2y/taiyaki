"""Static Site Generation (SSG) — pre-render routes to HTML files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from taiyaki_web.app import Taiyaki


class StaticSiteGenerator:
    """Pre-renders routes to static HTML files using httpx async transport."""

    def __init__(self, app: Taiyaki) -> None:
        self._app = app

    async def generate(
        self,
        output_dir: str,
        routes: list[str | dict[str, Any]],
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        """Generate static HTML for each route.

        Args:
            output_dir: Directory to write HTML files to.
            routes: List of paths or dicts with parameterized routes.
                - str: A single path, e.g. "/"
                - dict: {"path": "/posts/{id}", "params": [{"id": "1"}, {"id": "2"}]}
        """
        import httpx

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        transport = httpx.ASGITransport(app=self._app.asgi)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            for route in routes:
                if isinstance(route, str):
                    paths = [route]
                else:
                    template = route["path"]
                    paths = [template.format(**params) for params in route["params"]]

                for path in paths:
                    response = await client.get(path)
                    # Determine output file path
                    rel = path.strip("/")
                    if rel:
                        file_path = out / rel / "index.html"
                    else:
                        file_path = out / "index.html"
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(response.text)
                    if on_progress is not None:
                        on_progress(path)
