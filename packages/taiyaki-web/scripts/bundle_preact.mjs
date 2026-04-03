#!/usr/bin/env node
/**
 * Bundle Preact + hooks + render-to-string as a single combined module.
 *
 * Strategy: One big bundle with all exports, registered as "__preact_all".
 * Thin re-export shims are registered at runtime for "preact",
 * "preact/hooks", and "preact-render-to-string".
 *
 * This ensures all parts share the same preact internals (options, etc.).
 */

import { build } from "esbuild";
import { mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const vendorDir = join(__dirname, "..", "dark", "vendor");

mkdirSync(vendorDir, { recursive: true });

// Single combined bundle with all preact exports
await build({
  stdin: {
    contents: `
// Core
export { h, Fragment, createElement, Component, toChildArray, createRef, options } from "preact";
// Hooks
export { useState, useEffect, useRef, useMemo, useCallback, useReducer, useContext } from "preact/hooks";
// Render-to-string
export { renderToString } from "preact-render-to-string";
`,
    resolveDir: __dirname,
  },
  bundle: true,
  format: "esm",
  platform: "neutral",
  outfile: join(vendorDir, "preact-all.bundle.js"),
  minify: true,
});

// Client bundle (for browser hydration — includes hooks, no render-to-string)
// A single bundle so preact core and hooks share the same internals.
// The HTML uses an import map to resolve "preact" and "preact/hooks" to this file.
await build({
  stdin: {
    contents: `
export { h, Fragment, hydrate, render, Component, createRef, toChildArray, options } from "preact";
export { useState, useEffect, useRef, useMemo, useCallback, useReducer, useContext } from "preact/hooks";
`,
    resolveDir: __dirname,
  },
  bundle: true,
  format: "esm",
  platform: "browser",
  outfile: join(vendorDir, "preact-client.bundle.js"),
  minify: true,
});

console.log("Preact bundles written to", vendorDir);
