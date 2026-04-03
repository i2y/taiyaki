"""JS runtime for Preact/React SSR — wraps libts AsyncRuntime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import taiyaki

from taiyaki_web.renderers import RENDERERS

if TYPE_CHECKING:
    from taiyaki_web.sourcemap import SourceMap

_VENDOR = Path(__file__).parent / "vendor"

_SSR_POLYFILLS = """\
// TextEncoder polyfill (UTF-8)
if (typeof globalThis.TextEncoder === 'undefined') {
  globalThis.TextEncoder = class TextEncoder {
    get encoding() { return 'utf-8'; }
    encode(str) {
      str = String(str);
      var bytes = [];
      for (var i = 0; i < str.length; i++) {
        var c = str.charCodeAt(i);
        if (c < 0x80) { bytes.push(c); }
        else if (c < 0x800) { bytes.push(0xC0 | (c >> 6), 0x80 | (c & 0x3F)); }
        else if (c >= 0xD800 && c <= 0xDBFF && i + 1 < str.length) {
          var c2 = str.charCodeAt(++i);
          var cp = 0x10000 + ((c & 0x3FF) << 10 | (c2 & 0x3FF));
          bytes.push(0xF0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3F),
                     0x80 | ((cp >> 6) & 0x3F), 0x80 | (cp & 0x3F));
        } else {
          bytes.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F));
        }
      }
      return new Uint8Array(bytes);
    }
    encodeInto(str, dest) {
      var encoded = this.encode(str);
      var written = Math.min(encoded.length, dest.length);
      dest.set(encoded.subarray(0, written));
      var read = 0, bytes = 0;
      while (read < str.length && bytes < written) {
        var c = str.codePointAt(read);
        var cb = c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
        if (bytes + cb > written) break;
        bytes += cb;
        read += c > 0xffff ? 2 : 1;
      }
      return { read: read, written: written };
    }
  };
}

// TextDecoder polyfill (UTF-8)
if (typeof globalThis.TextDecoder === 'undefined') {
  globalThis.TextDecoder = class TextDecoder {
    constructor(label) { this._label = label || 'utf-8'; }
    get encoding() { return this._label; }
    decode(buf) {
      var bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
      var str = '', i = 0;
      while (i < bytes.length) {
        var b = bytes[i];
        var cp;
        if (b < 0x80) { cp = b; i++; }
        else if ((b & 0xE0) === 0xC0) { cp = (b & 0x1F) << 6 | (bytes[i+1] & 0x3F); i += 2; }
        else if ((b & 0xF0) === 0xE0) { cp = (b & 0x0F) << 12 | (bytes[i+1] & 0x3F) << 6 | (bytes[i+2] & 0x3F); i += 3; }
        else { cp = (b & 0x07) << 18 | (bytes[i+1] & 0x3F) << 12 | (bytes[i+2] & 0x3F) << 6 | (bytes[i+3] & 0x3F); i += 4; }
        if (cp > 0xFFFF) { str += String.fromCodePoint(cp); } else { str += String.fromCharCode(cp); }
      }
      return str;
    }
  };
}

// queueMicrotask polyfill
globalThis.queueMicrotask = globalThis.queueMicrotask || (fn => Promise.resolve().then(fn));

// MessageChannel polyfill (needed by React scheduler)
if (typeof globalThis.MessageChannel === 'undefined') {
  globalThis.MessageChannel = class MessageChannel {
    constructor() {
      this.port1 = { onmessage: null };
      this.port2 = { onmessage: null };
      var p1 = this.port1, p2 = this.port2;
      p1.postMessage = function(data) {
        if (typeof p2.onmessage === 'function') {
          queueMicrotask(function() { p2.onmessage({ data: data }); });
        }
      };
      p2.postMessage = function(data) {
        if (typeof p1.onmessage === 'function') {
          queueMicrotask(function() { p1.onmessage({ data: data }); });
        }
      };
    }
  };
}
"""

_RENDER_BOOTSTRAP_TEMPLATE = """\
{bootstrap_imports}

// Raw HTML wrapper for layout children injection
function __TaiyakiRawHTML({{ html }}) {{
    return {create_element}("taiyaki-raw", {{ dangerouslySetInnerHTML: {{ __html: html }} }});
}}

globalThis.__taiyakiRender = (componentName, propsJson) => {{
    const mod = globalThis.__taiyakiComponents[componentName];
    if (!mod) throw new Error("Component not registered: " + componentName);
    const Component = mod.default;
    const props = JSON.parse(propsJson);
    return renderToString({create_element}(Component, props));
}};

globalThis.__taiyakiRenderWithLayout = (layoutName, innerHtml, propsJson) => {{
    const mod = globalThis.__taiyakiComponents[layoutName];
    if (!mod) throw new Error("Layout not registered: " + layoutName);
    const Layout = mod.default;
    const props = JSON.parse(propsJson);
    const children = {create_element}(__TaiyakiRawHTML, {{ html: innerHtml }});
    return renderToString({create_element}(Layout, {{ ...props, children }}));
}};

globalThis.__taiyakiComponents = {{}};
"""


def _js_escape(s: str) -> str:
    """Escape a string for embedding in a JS single-quoted string literal."""
    return (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


class JsRuntime:
    """Manages an AsyncRuntime with Preact/React modules pre-loaded."""

    def __init__(self, renderer: str = "preact") -> None:
        self._renderer = renderer
        self._config = RENDERERS[renderer]
        self._source_maps: dict[str, SourceMap] = {}
        self._rt = taiyaki.AsyncRuntime()
        self._rt.enable_node_polyfills()
        self._bootstrap()

    def _bootstrap(self) -> None:
        cfg = self._config
        ssr_bundle = _VENDOR / cfg["ssr_bundle"]
        if not ssr_bundle.exists():
            raise FileNotFoundError(
                f"SSR bundle not found: {ssr_bundle}. "
                f"Renderer '{self._renderer}' requires {cfg['ssr_bundle']} "
                f"in {_VENDOR}/"
            )

        # Inject polyfills needed by React SSR (harmless for Preact)
        self._rt.eval(_SSR_POLYFILLS)

        # Register combined bundle under internal name
        self._rt.register_module("__ssr_all", ssr_bundle.read_text())

        # Register re-export shims so user code imports naturally
        for name, code in cfg["module_shims"]:
            self._rt.register_module(name, code)

        # Eval bootstrap script
        bootstrap = _RENDER_BOOTSTRAP_TEMPLATE.format(
            bootstrap_imports=cfg["bootstrap_imports"],
            create_element=cfg["create_element"],
        )
        self._rt.eval_module(bootstrap, "__taiyaki_runtime")

    @property
    def renderer(self) -> str:
        return self._renderer

    @property
    def _import_source(self) -> str:
        return "react" if self._renderer == "react" else "preact"

    def load_component(self, name: str, source: str) -> None:
        """Transform JSX/TSX and register as an importable module."""
        js_code = taiyaki.transform_jsx(source, self._import_source)
        # Store source map for error position mapping
        from taiyaki_web.sourcemap import parse_inline_source_map

        sm = parse_inline_source_map(js_code)
        if sm:
            self._source_maps[name] = sm
        self.load_component_js(name, js_code)

    def load_component_js(self, name: str, js_code: str) -> None:
        """Register pre-transpiled JS as an importable module."""
        self._rt.register_module(name, js_code)
        self._rt.eval_module(
            f'import * as mod from "{name}";\n'
            f'globalThis.__taiyakiComponents["{name}"] = mod;',
            f"__reg_{name}",
        )

    def load_component_file(self, path: Path | str) -> str:
        """Load a .jsx/.tsx file, register as module, return component name."""
        path = Path(path)
        name = path.stem
        self.load_component(name, path.read_text())
        return name

    def render_to_string(self, component: str, props: dict | None = None) -> str:
        """SSR a registered component with given props. Returns HTML string."""
        safe = _js_escape(json.dumps(props or {}))
        return self._rt.eval(f"__taiyakiRender('{_js_escape(component)}', '{safe}')")

    def render_with_layout(
        self, layout: str, inner_html: str, props: dict | None = None
    ) -> str:
        """Render inner HTML wrapped in a layout component."""
        return self._rt.eval(
            f"__taiyakiRenderWithLayout('{_js_escape(layout)}', "
            f"'{_js_escape(inner_html)}', '{_js_escape(json.dumps(props or {}))}')"
        )

    def invalidate_component(self, name: str) -> None:
        """Remove a component from the JS-side registry."""
        self._rt.eval(f"delete globalThis.__taiyakiComponents['{_js_escape(name)}']")

    def invalidate_all(self) -> None:
        """Clear all registered components from the JS-side registry."""
        self._rt.eval("globalThis.__taiyakiComponents = {}")

    def get_source_map(self, name: str) -> SourceMap | None:
        """Return the SourceMap for a loaded component, or None."""
        return self._source_maps.get(name)

    @property
    def rt(self) -> taiyaki.AsyncRuntime:
        """Access the underlying AsyncRuntime for advanced use."""
        return self._rt
