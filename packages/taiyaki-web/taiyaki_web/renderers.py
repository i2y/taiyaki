"""Renderer configurations for Preact and React."""

from __future__ import annotations

RENDERERS: dict[str, dict] = {
    "preact": {
        "ssr_bundle": "preact-all.bundle.js",
        "client_bundle": "preact-client.bundle.js",
        "import_map": {
            "preact": "/_taiyaki/preact-client.bundle.js",
            "preact/hooks": "/_taiyaki/preact-client.bundle.js",
            "preact/jsx-runtime": "/_taiyaki/preact-jsx-runtime.js",
        },
        "module_shims": [
            (
                "preact",
                "export { h, Fragment, createElement, Component, "
                'toChildArray, createRef, options } from "__ssr_all";',
            ),
            (
                "preact/jsx-runtime",
                'import { h, Fragment } from "preact";\n'
                "export { Fragment };\n"
                "export function jsx(type, props) {\n"
                "  let { children, ...rest } = props || {};\n"
                "  return h(type, rest, children);\n"
                "}\n"
                "export { jsx as jsxs, jsx as jsxDEV };\n",
            ),
            (
                "preact/hooks",
                "export { useState, useEffect, useRef, useMemo, "
                'useCallback, useReducer, useContext } from "__ssr_all";',
            ),
            (
                "preact-render-to-string",
                'export { renderToString } from "__ssr_all";',
            ),
        ],
        "bootstrap_imports": (
            'import { h } from "preact";\n'
            'import { renderToString } from "preact-render-to-string";'
        ),
        "create_element": "h",
        "hydrate_import": 'import { h, hydrate } from "preact";',
        "hydrate_call": "hydrate(h(C, props), el)",
    },
    "react": {
        "ssr_bundle": "react-all.bundle.js",
        "client_bundle": "react-client.bundle.js",
        "import_map": {
            "react": "/_taiyaki/react-client.bundle.js",
            "react-dom/client": "/_taiyaki/react-client.bundle.js",
        },
        "module_shims": [
            (
                "react",
                "export { createElement, Fragment, Component, createRef, "
                "useState, useEffect, useRef, useMemo, useCallback, "
                "useReducer, useContext, createContext, forwardRef, memo, "
                'lazy, Suspense } from "__ssr_all";',
            ),
            (
                "react-dom/server",
                'export { renderToString } from "__ssr_all";',
            ),
            (
                "react-dom/client",
                'export { hydrateRoot } from "__ssr_all";',
            ),
        ],
        "bootstrap_imports": (
            'import { createElement } from "react";\n'
            'import { renderToString } from "react-dom/server";'
        ),
        "create_element": "createElement",
        "hydrate_import": (
            'import { createElement } from "react";\n'
            'import { hydrateRoot } from "react-dom/client";'
        ),
        "hydrate_call": "hydrateRoot(el, createElement(C, props))",
    },
}
