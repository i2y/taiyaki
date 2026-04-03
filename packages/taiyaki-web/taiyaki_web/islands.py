"""Island hydration helpers."""

from __future__ import annotations

import hashlib
import json

from taiyaki_web.renderers import RENDERERS


def content_hash(content: str) -> str:
    """Return an 8-char hex SHA-256 digest of *content*."""
    return hashlib.sha256(content.encode()).hexdigest()[:8]


class IslandRegistry:
    """Static helpers for island SSR markers and hydration scripts."""

    @staticmethod
    def wrap_html(
        name: str,
        html: str,
        props: dict,
        load: str = "immediate",
    ) -> str:
        """Wrap SSR output with hydration markers."""
        props_attr = json.dumps(props).replace("&", "&amp;").replace("'", "&#39;")
        name_attr = name.replace("&", "&amp;").replace('"', "&quot;")
        load_attr = f' data-load="{load}"' if load != "immediate" else ""
        return (
            f"<div data-island=\"{name_attr}\" data-props='{props_attr}'{load_attr}>"
            f"{html}</div>"
        )

    @staticmethod
    def hydration_script(
        island_names: set[str],
        renderer: str = "preact",
        island_hashes: dict[str, str] | None = None,
    ) -> str:
        """Generate client-side hydration <script> tag for the given islands.

        When *island_hashes* is provided, hashed URLs are used and
        ``<link rel="modulepreload">`` hints are emitted for immediate islands.
        """
        if not island_names:
            return ""

        cfg = RENDERERS.get(renderer, RENDERERS["preact"])
        hydrate_import = cfg["hydrate_import"]
        hydrate_call = cfg["hydrate_call"]

        hashes = island_hashes or {}

        def _island_url(name: str) -> str:
            h = hashes.get(name)
            if h:
                return f"/_taiyaki/islands/{name}-{h}.js"
            return f"/_taiyaki/islands/{name}.js"

        # Modulepreload hints for immediate-load islands
        preload_links = ""
        if hashes:
            for n in sorted(island_names):
                url = _island_url(n)
                preload_links += f'<link rel="modulepreload" href="{url}">\n'

        imports = "\n".join(
            f'import {n} from "{_island_url(n)}";' for n in sorted(island_names)
        )
        names = ", ".join(sorted(island_names))
        script = (
            '<script type="module">\n'
            f"{hydrate_import}\n"
            f"{imports}\n"
            f"const islands = {{ {names} }};\n"
            "document.querySelectorAll('[data-island]').forEach(el => {\n"
            "  const C = islands[el.dataset.island];\n"
            "  const props = JSON.parse(el.dataset.props || '{}');\n"
            "  if (!C) return;\n"
            "  const strategy = el.dataset.load || 'immediate';\n"
            f"  const activate = () => {hydrate_call};\n"
            "  if (strategy === 'idle') {\n"
            "    (window.requestIdleCallback || (cb => setTimeout(cb, 200)))(activate);\n"
            "  } else if (strategy === 'visible') {\n"
            "    const obs = new IntersectionObserver(entries => {\n"
            "      if (entries[0].isIntersecting) { obs.disconnect(); activate(); }\n"
            "    });\n"
            "    obs.observe(el);\n"
            "  } else {\n"
            "    activate();\n"
            "  }\n"
            "});\n"
            "</script>\n"
        )
        return preload_links + script
