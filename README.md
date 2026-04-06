# taiyaki

An embeddable JavaScript/TypeScript runtime written in Rust, with a Python web framework.

Built on QuickJS or JavaScriptCore, taiyaki provides synchronous and asynchronous JS/TS execution, Node.js-compatible APIs, HTTP server, WebSocket, worker threads, and more. Exposed via C ABI for use from any language. Ships with Python bindings (`import taiyaki`) and a web framework (`from taiyaki_web import Taiyaki`).

## Install

### CLI (pre-built binary)

Download from [GitHub Releases](https://github.com/i2y/taiyaki/releases):

| Platform | QuickJS (default) | JavaScriptCore |
|----------|-------------------|----------------|
| Linux x86_64 | `taiyaki-v*-linux-x86_64.tar.gz` | `taiyaki-v*-linux-x86_64-jsc.tar.gz` |
| Linux aarch64 | `taiyaki-v*-linux-aarch64.tar.gz` | — |
| macOS x86_64 | `taiyaki-v*-macos-x86_64.tar.gz` | `taiyaki-v*-macos-x86_64-jsc.tar.gz` |
| macOS aarch64 | `taiyaki-v*-macos-aarch64.tar.gz` | `taiyaki-v*-macos-aarch64-jsc.tar.gz` |

### Rust (crates.io)

```bash
cargo install taiyaki-cli

# JSC backend (requires libjavascriptcoregtk on Linux)
cargo install taiyaki-cli --no-default-features --features jsc
```

### Python (PyPI)

```bash
pip install taiyaki              # QuickJS backend
pip install taiyaki-jsc          # JavaScriptCore backend
pip install taiyaki-web[quickjs] # Web framework (QuickJS)
pip install taiyaki-web[jsc]     # Web framework (JSC)
```

## Architecture

```
taiyaki-core          Lightweight core — eval / register_fn / call only (zero Node APIs)
  |
taiyaki-node-polyfill Optional Node.js compatibility layer
  |                    path, fs, crypto, Buffer, require, http, net, tls ...
  |
  +-- taiyaki-cli     Async CLI (tokio)
  |                    taiyaki run / eval / repl / test / build / compile ...
  |
  +-- taiyaki-python  PyO3 bindings (import taiyaki)
        |
        taiyaki-web   Python web framework (from taiyaki_web import Taiyaki)
                       Starlette + Preact SSR + htmx + Islands
```

## Quick Start

### CLI

```bash
# Run JavaScript / TypeScript
taiyaki run hello.ts

# Interactive REPL (colored output, multi-line, .help/.load/.type/.clear)
taiyaki repl

# Test runner (Jest/Bun compatible)
taiyaki test tests/ --watch

# JSX/TSX supported
taiyaki run app.tsx
```

### Python Bindings

```python
import taiyaki

rt = taiyaki.AsyncRuntime()
rt.enable_node_polyfills()

# npm packages — fetched from registry, cached, no npm CLI needed
rt.install_dependencies(["lodash@4", "dayjs"])
result = rt.eval("lodash.chunk([1,2,3,4,5,6], 2)")

# Evaluate TypeScript
result = rt.eval_ts("const x: number = 1 + 1; x")

# Render JSX
html = rt.eval_jsx('<h1 style={{ color: "red" }}>Hello</h1>')

# Async (awaitable)
data = await rt.eval_await("fetch('https://api.example.com').then(r => r.json())")
```

### Web Framework

```python
from taiyaki_web import Taiyaki, Context

app = Taiyaki(
    components_dir="components",
    islands_dir="islands",
    layout="Layout",
    dependencies=["lodash@4"],  # npm packages available in SSR
)

@app.get("/", component="Home")
async def index(ctx: Context):
    counter = await app.island("Counter", _ctx=ctx, initial=0)
    return {"title": "Hello", "counterHtml": counter}

@app.api_get("/api/data")
async def data(ctx: Context):
    return {"message": "Hello from Taiyaki"}

app.run(port=8000)
```

```tsx
// components/Home.tsx
export default function Home({ title, counterHtml }) {
  return (
    <div>
      <taiyaki-head>
        <title>{title}</title>
        <link rel="stylesheet" href="/style.css" />
      </taiyaki-head>
      <h1>{title}</h1>
      <div dangerouslySetInnerHTML={{ __html: counterHtml }} />
    </div>
  );
}
```

```tsx
// islands/Counter.tsx — hydrated on the client
import { useState } from "preact/hooks";

export default function Counter({ initial = 0 }) {
  const [count, setCount] = useState(initial);
  return <button onClick={() => setCount(count + 1)}>Count: {count}</button>;
}
```

## Features

### Runtime (taiyaki-core)

- **Dual engine**: QuickJS (default) / JavaScriptCore (`--features jsc`)
- **TypeScript**: SWC-based type stripping
- **JSX/TSX**: SWC-based transform (automatic runtime — no `import { h }` needed)
- **ES Modules**: `import` / `export` / dynamic `import()`
- **Host functions**: Register Rust functions callable from JS
- **C ABI**: Use from C/C++ via `taiyaki.h`

### CLI (taiyaki-cli)

| Command | Description |
|---------|-------------|
| `taiyaki run <file>` | Execute JS/TS/JSX/TSX |
| `taiyaki eval <code>` | Evaluate code |
| `taiyaki repl` | Interactive REPL (multi-line, colored output) |
| `taiyaki test [dir]` | Test runner (describe/it/expect) |
| `taiyaki test --watch` | Watch mode with auto-rerun |
| `taiyaki init` | Generate package.json |
| `taiyaki install` | Install dependencies |
| `taiyaki add <pkg>` | Add a package |
| `taiyaki remove <pkg>` | Remove a package |
| `taiyaki build <entry>` | ESM to CJS bundle |
| `taiyaki compile <entry>` | Standalone executable |
| `taiyaki check [paths]` | Syntax check |
| `taiyaki fmt [paths]` | Code formatter |
| `taiyaki lint [paths]` | Linter |

**Built-in APIs**: console, fetch, setTimeout/setInterval, process, fs, crypto (subtle + Node), http (server + client), net, tls, dns, child_process, worker_threads, stream, WebSocket, URL, Headers, Request/Response, ReadableStream/WritableStream, AbortController, Blob/File/FormData, performance, SQLite

**Sandbox**: `--sandbox`, `--allow-read`, `--allow-write`, `--allow-net`, `--allow-env`, `--allow-run`

### Web Framework (taiyaki-web)

- **SSR**: Preact / React server-side rendering (TSX components)
- **Islands**: Partial hydration (immediate / idle / visible strategies)
- **`<taiyaki-head>`**: Inject title, meta, and CSS into `<head>` from components
- **htmx**: `hx-*` attribute interactions and partial rendering
- **Streaming SSR**: Chunked delivery via `<taiyaki-stream-marker>`
- **Middleware**: Logger, Sessions, CSRF, Recover, RecoverWithOverlay
- **Runtime pool**: Concurrent SSR with `pool_size=N`
- **Response cache**: LRU + ETag / 304 Not Modified
- **Source maps**: Map JSX/TSX errors back to original line numbers
- **Island bundling**: Content-hashed URLs + modulepreload hints
- **SSG**: Static site generation (`generate_static_site()`)
- **MCP**: Claude MCP server integration
- **TypeScript typegen**: Generate `.d.ts` from loader type hints
- **CLI**: `python -m taiyaki_web run`, `new`, `generate`, `build`, `typegen` (rich output)

## Build from Source

```bash
# Default (QuickJS)
cargo build
cargo test

# JSC backend (requires libjavascriptcoregtk-*-dev on Linux)
cargo build -p taiyaki-core --features jsc --no-default-features
cargo test -p taiyaki-core --features jsc --no-default-features

# Python bindings
cd crates/taiyaki-python && maturin develop

# Python bindings (JSC)
cd crates/taiyaki-python && maturin develop --no-default-features --features jsc

# Web framework tests
cd packages/taiyaki-web && uv run python -m pytest tests/ -v
```

## Project Structure

```
crates/
  taiyaki-core/           Sync + async core (C ABI)
  taiyaki-cli/            CLI binary + built-in APIs
  taiyaki-node-polyfill/  Node.js polyfills (optional)
  taiyaki-python/         PyO3 bindings
packages/
  taiyaki-web/            Python web framework
    taiyaki_web/
      app.py              Taiyaki application class
      runtime.py          JS runtime (Preact/React SSR)
      islands.py          Island registry + hydration
      head.py             <taiyaki-head> extraction
      middleware.py        Logger / Recover middleware
      sourcemap.py         Source map parsing
      ...
    tests/                93 tests
    examples/             Demo apps
```

## License

MIT
