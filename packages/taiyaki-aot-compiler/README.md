# taiyaki-aot-compiler

**JavaScript/TypeScript AOT compiler** — compile JS/TS to standalone native binaries via LLVM.

```javascript
// hello.js
function add(a, b) { return a + b; }
console.log(add(3, 4));
```

```bash
$ taiyaki-aot compile hello.js
✓ hello.js → ./hello  (1.0 MB, 0.15s)

$ ./hello
7
```

### Features

- **Single-file binaries** — compiles to a standalone executable with QuickJS-NG or JavaScriptCore embedded as fallback runtime
- **Automatic type inference** — Hindley-Milner inference from call sites, no annotations required
- **TypeScript support** — type annotations stripped and used as inference hints
- **Native GUI & games** — built-in raylib and Clay UI bindings, JSX support
- **async/await** — libuv event loop with Promise-based APIs (no await in loops yet)
- **JS fallback** — Set, Map, Regex, generators, etc. work via the embedded JS runtime

> **Status**: Experimental. Works well for CLI tools, games, and compute-heavy code.

## Install

> **Coming soon**: `pip install taiyaki-aot-compiler` — pre-built wheels with bundled runtime library (no Rust toolchain required).

Currently requires building from the [taiyaki monorepo](https://github.com/i2y/taiyaki).

**Prerequisites**: Python 3.12+, Rust toolchain, C compiler (clang)

```bash
git clone https://github.com/i2y/taiyaki.git
cd taiyaki

# Build the runtime static library (pick one)
cargo build --release -p taiyaki-runtime                                       # QuickJS
cargo build --release -p taiyaki-runtime --features jsc --no-default-features  # JSC (macOS)

# Install the AOT compiler
cd packages/taiyaki-aot-compiler
uv sync
```

Optional: [raylib](https://www.raylib.com/) for game/GUI examples (`brew install raylib` on macOS).

## Quick Start

### Compile

```bash
taiyaki-aot compile hello.js        # → ./hello
taiyaki-aot compile app.ts          # TypeScript (types auto-stripped)
taiyaki-aot compile app.js -o dist/ # Custom output directory
```

### Eval

```bash
taiyaki-aot eval 'console.log(42 * 2)'
taiyaki-aot eval --ts 'function add(a: number, b: number): number { return a+b; } console.log(add(1,2));'
echo 'console.log("hello")' | taiyaki-aot eval
```

### REPL

```
$ taiyaki-aot repl
[1] › function fib(n) { if (n <= 1) return n; return fib(n-1) + fib(n-2); }
Function defined.
[2] › fib(10)
55
[3] › const x = fib(20)
6765
[4] › x * 2
13530
```

Supports: readline history, variable/function persistence, `.defs` to list definitions, `--ts` for TypeScript mode.

### Type Check

```bash
taiyaki-aot check app.js
```

## Backends

```bash
taiyaki-aot compile app.js --backend quickjs   # Default (~1 MB, portable)
taiyaki-aot compile app.js --backend jsc       # JavaScriptCore (~59 KB on macOS)
```

`--backend` also works with `eval` and `repl`.

| | QuickJS | JSC |
|---|---------|-----|
| Binary size | ~1 MB for simple programs (QuickJS statically linked) | ~59 KB on macOS (JSC is a system framework) |
| Portability | Everywhere | macOS native, Linux via WebKitGTK |
| Fallback speed | Interpreter | JIT compiled |

## Language Support

### Natively compiled

```javascript
// Arithmetic, strings, booleans
const result = "Hello, " + name + "! " + (x + y);

// Arrays (homogeneous)
const nums = [1, 2, 3];
nums.push(4);
const big = nums.map(x => x * 2).filter(x => x > 4);

// Objects with typed fields
const point = { x: 10, y: 20 };

// Classes with inheritance
class Animal {
    constructor(name) { this.name = name; }
    speak() { return this.name + " speaks"; }
}
class Dog extends Animal {
    speak() { return this.name + " barks"; }
}
function main() {
    const d = new Dog("Rex");
    console.log(d.speak());  // "Rex barks"
}
main();

// Closures and higher-order functions
const make_adder = (n) => (x) => x + n;

// Destructuring, spread, rest, defaults
const { x, y } = point;
const [first, ...rest] = nums;

// async/await
async function main() {
    const data = await fetch("https://api.example.com/data");
    await setTimeout(100);
    console.log(data);
}

// ES modules
import { add } from './math.js';
export function multiply(a, b) { return a * b; }

// TypeScript generics (monomorphized automatically)
function identity<T>(x: T): T { return x; }
identity(42);       // → number variant
identity("hello");  // → string variant
```

Also: template literals, ternary, nullish coalescing (`??`), for/while/for-of/for-in, switch, try/catch/finally.

### Works via JS runtime fallback

Not natively compiled, but fully functional through QuickJS/JSC:

- Set, Map, WeakMap, WeakSet, Symbol
- Proxy, Reflect
- Generators (`function*`, `yield`)
- `eval()`, `arguments`, Regex

### Not supported

- Dynamic `import()`, `require()`
- Heterogeneous arrays/tuples (`[1, "two", true]`)
- `await` inside loops

### Key differences from standard JS

| Standard JS | Tsuchi |
|------------|--------|
| Numbers: int or float | Always f64 |
| Arrays: mixed types | Single element type |
| Objects: dynamic shape | Fixed at compile time |
| GC: automatic | No GC (scope-based) |
| `setTimeout(fn, ms)` | `await setTimeout(ms)` |
| `fetch()` → Response | `fetch()` → body string |

For full API reference, see [docs/language-reference.md](docs/language-reference.md).

## Built-in APIs

### File system

```javascript
fs.readFileSync(path)             // → string
fs.writeFileSync(path, content)   // → void
fs.existsSync(path)               // → boolean
fs.mkdirSync(path)
fs.readdirSync(path)              // → string[]
fs.unlinkSync(path)
fs.renameSync(oldPath, newPath)
fs.appendFileSync(path, content)
fs.copyFileSync(src, dst)

// Async (requires async/await)
const data = await fs.readFile(path)
await fs.writeFile(path, content)
```

### Path, OS, Process

```javascript
path.join("/tmp", "file.txt")   // → "/tmp/file.txt"
path.dirname(p)                 // → parent directory
path.basename(p)                // → file name
path.extname(p)                 // → ".txt"
path.resolve(p)                 // → absolute path

os.platform()    // → "darwin" or "linux"
os.arch()        // → "arm64" or "x64"
os.homedir()     // → "/Users/you"
os.cpus()        // → core count (number)
os.totalmem()    // → bytes

process.argv     // → string[]
process.env.HOME // → env variable
process.exit(0)
```

### Async & HTTP

```javascript
async function main() {
    await setTimeout(1000);                      // sleep
    const body = await fetch("https://...");     // HTTP GET → string
    const file = await fs.readFile("data.txt");  // async file read
    console.log(body);
}
main();
```

### More

`console.log/error/warn`, `Math.*` (20+ methods), `JSON.stringify`/`parse`, `Date.now()`, `parseInt`, `parseFloat`, `exec(cmd)`, `httpGet(url)`, `httpPost(url, body, contentType)`, string methods (20+), array methods (25+).

## Examples

### CLI & Algorithms

```bash
taiyaki-aot compile examples/hello.js
taiyaki-aot compile examples/fibonacci.js
```

### Games (requires [raylib](https://www.raylib.com/)) — [Demo videos](https://www.youtube.com/playlist?list=PLNY4o1idpxTNJHb5iU--D8h6K4HEfKBvx)

```bash
# macOS
brew install raylib
# Ubuntu/Debian
sudo apt install libraylib-dev
```

| Game | Source | Description |
|------|--------|-------------|
| Breakout | [breakout.js](examples/breakout.js) | Classic brick breaker |
| Pong | [pong.js](examples/pong.js) | Two-player pong |
| Neon Drive | [neon_drive.js](examples/neon_drive.js) | Synthwave racing |
| Neon Arena | [neon_arena.js](examples/neon_arena.js) | Top-down shooter |
| Void Hunter | [void_hunter.js](examples/void_hunter.js) | Space combat |
| Star Voyager | [star_voyager.js](examples/star_voyager.js) | Space exploration |
| Raycaster | [raycaster.js](examples/raycaster.js) | Wolfenstein-style 3D |
| Mandelbrot | [mandelbrot.js](examples/mandelbrot.js) | Fractal renderer |
| Particles | [particles.js](examples/particles.js) | Particle system |
| Voxel Terrain | [voxel_terrain.js](examples/voxel_terrain.js) | 3D voxel landscape |
| Pixel Forest | [pixel_forest.js](examples/pixel_forest.js) | Bitmap platformer |

```bash
taiyaki-aot compile examples/neon_drive.js && ./neon_drive
```

### GUI & TUI with JSX

Tsuchi supports JSX syntax for building desktop GUI (via [Clay](https://github.com/nicbarker/clay) + raylib) and terminal UI (via Clay + termbox2). Clay and termbox2 are vendored — no extra install needed. GUI apps require raylib (see above). TUI apps work without raylib.

```jsx
// dashboard.jsx — GUI app with Clay layout
<Box direction="column" gap={16} padding={20}>
    <Text fontSize={24} color={0xFF0000FF}>Dashboard</Text>
    <Box direction="row" gap={8}>
        <Button label="Click me" onClick={handleClick} />
        <Text>Count: {count}</Text>
    </Box>
</Box>
```

```bash
taiyaki-aot compile examples/clay_dashboard.jsx && ./clay_dashboard     # GUI
taiyaki-aot compile examples/tui_filemanager.jsx --tui && ./tui_filemanager  # TUI
```

| App | Source | Type | Description |
|-----|--------|------|-------------|
| Dashboard | [clay_dashboard.jsx](examples/clay_dashboard.jsx) | GUI | Dashboard layout |
| Calculator | [calc.jsx](examples/calc.jsx) | GUI | Desktop calculator |
| Widgets | [widgets.jsx](examples/widgets.jsx) | GUI | Widget showcase |
| UI Dashboard | [ui_dashboard.jsx](examples/ui_dashboard.jsx) | GUI | Interactive widgets |
| File Manager | [tui_filemanager.jsx](examples/tui_filemanager.jsx) | TUI | Terminal file browser |
| Pomodoro | [tui_pomodoro.jsx](examples/tui_pomodoro.jsx) | TUI | Terminal pomodoro timer |
| Sysinfo | [tui_sysinfo.jsx](examples/tui_sysinfo.jsx) | TUI | Terminal system monitor |

## Architecture

```
src/taiyaki_aot_compiler/
  parser/
    js_parser.py          # tree-sitter JS → AST
    ts_stripper.py        # Strip TS types, extract hints
    jsx_transformer.py    # Transform JSX to Clay/UI function calls
    module_merger.py      # Resolve imports, merge modules
  type_checker/
    js_inferrer.py        # Hindley-Milner type inference
    types.py              # NumberType, StringType, ArrayType, PromiseType, ...
  hir/
    builder.py            # AST → SSA-form HIR
    optimizer.py          # Dead code elimination, constant folding
    nodes.py              # HIR instruction definitions
  codegen/
    llvm_generator.py     # HIR → LLVM IR
    backend_base.py       # Shared C runtime (strings, arrays, fs, path, os, async)
    quickjs_backend.py    # QuickJS-NG linking & JS bindings
    jsc_backend.py        # JavaScriptCore linking & JS bindings
  cli.py                  # CLI: compile, check, eval, repl
  compiler.py             # Compilation pipeline orchestration

zig-src/                  # Zig rewrite (see below)
```

> **Zig rewrite**: The compiler is being rewritten in Zig in parallel (`zig-src/`). This is a work in progress — the Python implementation above is the current stable version.

## How it works

```
JS/TS source → Parse (tree-sitter) → Type Inference (HM) → HIR (SSA) → LLVM IR → Native Binary
```

1. **Parse** — tree-sitter-javascript parses source into AST. TypeScript types are stripped. JSX is transformed to function calls.
2. **Infer** — Hindley-Milner type inference resolves types from call sites across multiple passes. No annotations needed.
3. **HIR** — Typed AST is lowered to SSA-form basic blocks with phi nodes.
4. **LLVM** — HIR is compiled to LLVM IR with O3 optimization. Async functions become C state machines.
5. **Link** — Object code is linked with C runtime, QuickJS/JSC, and optional libraries (raylib, libuv, libcurl) into a standalone binary.

Functions that can't be fully type-inferred fall back to the JS runtime (QuickJS-NG or JavaScriptCore), statically linked into the binary.

## Development

```bash
uv sync                                    # Install dependencies (including dev)
uv run pytest                              # Run all tests (1000+)
uv run pytest tests/test_e2e.py -v         # End-to-end tests
uv run pytest tests/test_js_parser.py -v   # Parser tests
uv run pytest tests/test_js_inferrer.py -v # Type inferrer tests
```

## License

MIT
