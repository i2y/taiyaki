# Tsuchi Language Reference

Tsuchi compiles a **subset** of JavaScript/TypeScript to standalone native binaries. This document explains what works, what doesn't, and what behaves differently from standard JS/TS.

## Quick Summary

| Category | Status |
|----------|--------|
| Arithmetic, strings, booleans | Full support |
| Arrays (homogeneous) | Full support |
| Objects (typed fields) | Full support |
| Classes & inheritance | Supported |
| Closures & higher-order functions | Full support |
| async/await | Supported (no await in loops yet) |
| Modules (ES import/export) | Supported |
| Regex | Via JS runtime fallback |
| Generators, Symbols | Via JS runtime fallback |
| Set, Map, WeakMap, WeakSet | Via JS runtime fallback |
| Generics (TS `<T>`) | Supported (via monomorphization) |
| Union types, literal types | Work (stripped by TS, resolved at runtime) |
| Conditional/mapped types | Not supported |

---

## Type System

Tsuchi uses **Hindley-Milner type inference**. You don't need type annotations — types are inferred from how values are used.

### Supported Types

| Type | JS Example | Compiled As |
|------|-----------|-------------|
| `number` | `42`, `3.14` | f64 (always float64) |
| `boolean` | `true`, `false` | i1 (1-bit integer) |
| `string` | `"hello"` | `const char*` |
| `void` | no return value | void |
| `null` | `null` | null pointer |
| `T[]` | `[1, 2, 3]` | `TsuchiArray*` (heap) |
| `{x: T}` | `{x: 1, y: 2}` | C struct (stack) |
| `Promise<T>` | `async function` return | `TsuchiPromise*` |

### Not Supported

- **Explicit generic constraints** (`T extends U`) — Tsuchi monomorphizes automatically from call sites instead
- **Heterogeneous arrays/tuples** (`[1, "two", true]`) — arrays must be homogeneous
- **Conditional/Mapped types** — TypeScript-only features
- **`await` inside loops** — await in if/else works, but loop-based await is not yet supported

Note: `any`, union types (`string | number`), and literal types are stripped by the TypeScript type stripper and work at runtime via type inference or JS fallback.

### How Inference Works

```javascript
function add(a, b) { return a + b; }
add(1, 2);  // Infers: add(number, number) => number
```

If Tsuchi can't infer types (no call site, or ambiguous usage), the function falls back to the JS runtime (QuickJS or JSC).

**Tip**: Add a call site for every function you define. Unused functions can't be type-inferred.

---

## Syntax Support

### Fully Supported

```javascript
// Variables
const x = 10;
let y = "hello";

// Functions
function greet(name) { return "Hello, " + name; }
const double = (x) => x * 2;

// Control flow
if (x > 5) { ... } else { ... }
for (let i = 0; i < 10; i++) { ... }
for (const item of array) { ... }
for (const key in object) { ... }
while (condition) { ... }
switch (value) { case 1: ...; break; }

// Error handling
try { ... } catch (e) { ... } finally { ... }
throw "error message";

// Destructuring
const { x, y } = point;
const [first, ...rest] = array;

// Spread
const merged = [...arr1, ...arr2];

// Template literals
const msg = `Hello, ${name}!`;

// Ternary & nullish
const val = x ?? defaultValue;
const result = condition ? a : b;

// Classes
class Animal {
    constructor(name) { this.name = name; }
    speak() { return this.name + " speaks"; }
}
class Dog extends Animal {
    speak() { return this.name + " barks"; }
}

// Modules
import { readFile } from './utils.js';
export function process(data) { ... }

// Async/await
async function fetchData() {
    const data = await fetch(url);
    return data;
}
```

### Works via JS Runtime Fallback

These features are not natively compiled but work through the QuickJS/JSC fallback runtime (slower than native, but fully functional):

```javascript
// Collections
const set = new Set([1, 2, 3]);       // Works via fallback
const map = new Map();                // Works via fallback

// Generators
function* range(n) { for (let i = 0; i < n; i++) yield i; }  // Works via fallback

// Symbols, Proxy, Reflect
const sym = Symbol("id");            // Works via fallback
const p = new Proxy(obj, handler);   // Works via fallback

// eval, arguments
eval("console.log(42)");             // Works via fallback
function f() { return arguments[0]; } // Works via fallback

// Regex
"hello".match(/ell/);                // Works via fallback
```

### Not Supported

```javascript
// Dynamic import — only static ES module imports
const mod = await import('./mod.js');

// CommonJS
const fs = require('fs');
```

---

## Built-in APIs

### Console

```javascript
console.log(value)    // Print to stdout
console.error(value)  // Print to stdout (alias for log)
console.warn(value)   // Print to stdout (alias for log)
```

Note: Unlike Node.js, `error` and `warn` are not redirected to stderr — all three print to stdout.

### Math

All standard numeric methods:

```javascript
Math.floor(3.7)    // 3
Math.ceil(3.2)     // 4
Math.abs(-5)       // 5
Math.sqrt(16)      // 4
Math.round(3.5)    // 4
Math.min(a, b)     // smaller value
Math.max(a, b)     // larger value
Math.pow(2, 10)    // 1024
Math.random()      // 0..1
Math.PI            // 3.14159...
// Also: trunc, sign, log, log2, log10, exp, sin, cos, tan, hypot, clz32
```

Not available: `asin`, `acos`, `atan`, `atan2`, `sinh`, `cosh`, `tanh`

### String Methods

```javascript
str.length              // character count
str.indexOf("sub")      // first occurrence
str.slice(1, 5)         // substring
str.toUpperCase()       // "HELLO"
str.trim()              // strip whitespace
str.split(",")          // ["a", "b", "c"]
str.replace("a", "b")   // first occurrence
str.replaceAll("a", "b")// all occurrences
str.includes("sub")     // boolean
str.startsWith("pre")   // boolean
str.repeat(3)           // "abcabcabc"
str.padStart(5, "0")    // "00042"
str.charAt(0)           // first character
str.charCodeAt(0)       // char code
// Also: at, lastIndexOf, substring, trimStart, trimEnd, endsWith, padEnd
```

Not available: `match`, `matchAll`, `search` (no regex support)

### Array Methods

```javascript
arr.push(item)          // add to end
arr.pop()               // remove from end
arr.shift()             // remove from start
arr.unshift(item)       // add to start
arr.slice(1, 3)         // sub-array
arr.splice(1, 2)        // remove elements
arr.concat(other)       // merge arrays
arr.join(", ")          // to string
arr.reverse()           // mutates
arr.indexOf(item)       // find index
arr.includes(item)      // boolean
arr.forEach(fn)         // iterate
arr.map(fn)             // transform
arr.filter(fn)          // select
arr.reduce(fn, init)    // accumulate
arr.find(fn)            // first match
arr.findIndex(fn)       // first match index
arr.some(fn)            // any match?
arr.every(fn)           // all match?
arr.sort(compareFn)     // sort (mutates)
arr.fill(value)         // fill all
arr.flat()              // flatten one level
// Also: at, lastIndexOf, reduceRight
```

### JSON

```javascript
JSON.stringify(value)   // value to JSON string
JSON.parse(text)        // JSON string to value (returns string)
```

Note: `JSON.parse` currently always returns a string due to a type inference limitation. Use `parseFloat(JSON.parse(...))` to convert to number.

### Date

```javascript
Date.now()              // milliseconds since epoch
```

Only the static `now()` method is available. No `new Date()` or instance methods.

### Global Functions

```javascript
parseInt("42")          // 42
parseFloat("3.14")      // 3.14
setTimeout(ms)          // async: returns Promise<void> (NOT Node's setTimeout(fn, ms))
fetch(url)              // async: returns Promise<string> (body text, NOT Response object)
readFile(path)          // sync: returns string (legacy alias for fs.readFileSync)
writeFile(path, data)   // sync: void (legacy alias for fs.writeFileSync)
exec(cmd)               // sync: returns stdout as string
httpGet(url)            // sync: returns body as string
httpPost(url, body, ct) // sync: returns body as string
String.fromCharCode(n)  // returns single-character string
```

---

## Node.js-Compatible APIs

### fs (File System)

```javascript
// Synchronous
fs.readFileSync(path)              // string
fs.writeFileSync(path, content)    // void
fs.existsSync(path)                // boolean
fs.mkdirSync(path)                 // void
fs.rmdirSync(path)                 // void
fs.unlinkSync(path)                // void
fs.renameSync(oldPath, newPath)    // void
fs.appendFileSync(path, content)   // void
fs.copyFileSync(src, dst)          // void
fs.readdirSync(path)               // string[]

// Async (requires async/await)
const data = await fs.readFile(path)   // Promise<string>
await fs.writeFile(path, content)      // Promise<void>
```

### path

```javascript
path.join("/tmp", "file.txt")   // "/tmp/file.txt"
path.dirname("/tmp/file.txt")   // "/tmp"
path.basename("/tmp/file.txt")  // "file.txt"
path.extname("file.txt")        // ".txt"
path.resolve("relative")        // absolute path
path.isAbsolute("/tmp")         // true
path.normalize(p)               // cleaned path
```

### os

```javascript
os.platform()    // "darwin" or "linux"
os.arch()        // "arm64" or "x64"
os.homedir()     // "/Users/you"
os.tmpdir()      // "/tmp"
os.hostname()    // "machine-name"
os.cpus()        // number of CPU cores (number, not array like Node.js)
os.totalmem()    // total memory in bytes
os.freemem()     // free memory in bytes
```

### process

```javascript
process.argv     // string[] of command-line arguments
process.env.HOME // environment variable access
process.exit(0)  // exit with code
```

### HTTP & Shell

```javascript
// Synchronous
const body = httpGet(url)                        // GET request, returns body
const resp = httpPost(url, body, contentType)     // POST request, returns body
const output = exec("ls -la")                     // Run shell command, returns stdout

// Async
const data = await fetch(url)   // GET request, returns body as string (requires async)
```

Note: `httpGet`/`httpPost` require libcurl. `fetch` uses libcurl + libuv for async execution.

---

## Async/Await

Tsuchi compiles async functions to C state machines with libuv for I/O.

```javascript
async function main() {
    console.log("start");
    await setTimeout(1000);         // wait 1 second
    const data = await fetch(url);  // async HTTP
    console.log(data);
}
main();
```

### Limitations

- **No `await` inside loops** — `await` in `if/else` branches works, but loop-based `await` is not yet supported
- **No `Promise.all`** — await each promise sequentially
- **No `Promise.race`/`any`/`allSettled`**
- **No `try/catch` around `await`** — error handling in async is limited
- **No async generators** (`async function*`)

---

## Classes

```javascript
class Vector {
    constructor(x, y) {
        this.x = x;
        this.y = y;
    }
    length() {
        return Math.sqrt(this.x * this.x + this.y * this.y);
    }
    static zero() {
        return new Vector(0, 0);
    }
}

class Vector3 extends Vector {
    constructor(x, y, z) {
        super(x, y);
        this.z = z;
    }
}
```

Supported: constructors, methods, static methods, fields, getters/setters, `extends`, `super`.

Not supported: private fields (`#field`), decorators, abstract classes.

---

## Modules

```javascript
// math.js
export function add(a, b) { return a + b; }
export const PI = 3.14159;

// main.js
import { add, PI } from './math.js';
console.log(add(1, 2));
```

Supported: named imports/exports, default imports/exports, namespace imports (`import * as`), re-exports.

Not supported: dynamic `import()`, CommonJS `require()`, `node_modules` resolution.

---

## Compilation Behavior

### Native vs Fallback

Tsuchi tries to compile every function to native code. Functions that can't be type-inferred fall back to the JS runtime:

```
$ taiyaki-aot compile app.js
Compiling app.js ...
✓ app.js → ./app  (1.0 MB, 0.15s)
  Type      Count    Functions
  Native        3    add, multiply, main     ← compiled to LLVM → machine code
  Fallback      1    dynamic_func            ← interpreted by QuickJS/JSC
```

Native functions are ~1000x faster than fallback functions.

### Backend Choice

```bash
taiyaki-aot compile app.js --backend quickjs   # Default: QuickJS-NG (static linked, ~1 MB)
taiyaki-aot compile app.js --backend jsc       # JavaScriptCore (system framework, ~59 KB on macOS)
```

### TypeScript

```bash
taiyaki-aot compile app.ts        # Auto-strips types, uses annotations as inference hints
taiyaki-aot eval --ts 'function add(a: number, b: number): number { return a+b; } console.log(add(1,2));'
taiyaki-aot repl --ts             # TypeScript REPL mode
```

Type annotations help Tsuchi infer types faster and reduce fallback functions. Interfaces and type aliases are stripped (not enforced).

---

## Key Differences from Standard JS

| Behavior | Standard JS | Tsuchi |
|----------|------------|--------|
| `number` type | int or float | always f64 |
| Array elements | heterogeneous | homogeneous (single type) |
| Object shape | dynamic | fixed at compile time |
| `typeof` | runtime check | compile-time only |
| Prototype chain | full prototype | class-based only |
| GC | automatic | no GC (scope-based cleanup) |
| `undefined` vs `null` | distinct | merged to void/null |
| Strict mode | opt-in | always (effectively) |
| `arguments` | available | not available (use `...rest`) |
| Property enumeration | ordered | compile-time fields only |
| `console.error` | prints to stderr | prints to stdout |

### Differences from Node.js APIs

| API | Node.js | Tsuchi |
|-----|---------|--------|
| `setTimeout` | `setTimeout(fn, ms)` → timer ID | `setTimeout(ms)` → `Promise<void>` |
| `fetch` | Returns `Response` object | Returns body text as `string` |
| `fs.readFile` | Callback or `Promise<Buffer>` | `Promise<string>` |
| `exec` | `child_process.exec(cmd, cb)` | `exec(cmd)` → string (sync) |
| `JSON.parse` | Returns parsed value (any type) | Returns string (current limitation) |
| `console.error` | Prints to stderr | Prints to stdout (same as `log`) |
| `os.cpus()` | Returns `Array<Object>` with CPU info | Returns `number` (core count) |

### Migration Tips

When porting existing JS/TS code to Tsuchi:

1. **Replace `setTimeout(fn, ms)` with `await setTimeout(ms)`** — Tsuchi's setTimeout is async-native, no callback
2. **Replace `fetch(url).then(r => r.text())` with `await fetch(url)`** — already returns body text
3. **Use separate functions for different types** — no union types, so `function handle(x: string | number)` must become two functions
4. **Add call sites for all functions** — if a function has no callers, it falls back to interpreted mode
5. **Use homogeneous arrays** — `[1, "two", true]` won't compile; use `[1, 2, 3]` or `["a", "b", "c"]`
6. **Replace `require()` with `import`** — CommonJS not supported

---

## CLI Reference

```bash
taiyaki-aot compile <file>         # Compile to standalone binary
  -o, --output-dir DIR        # Output directory (default: .)
  --backend quickjs|jsc       # Runtime backend
  --tui                       # Target terminal UI (Clay + termbox2)
  -v, --verbose               # Verbose output
  -q, --quiet                 # Suppress output

taiyaki-aot check <file>           # Type-check only (no binary)

taiyaki-aot eval 'code'            # Compile and run inline JS
  -e, --expression 'code'    # Alternative flag
  --ts                        # TypeScript mode
  echo 'code' | taiyaki-aot eval  # Pipe support

taiyaki-aot repl                   # Interactive REPL
  --ts                        # TypeScript mode
  --backend quickjs|jsc       # Runtime backend
```

### REPL Commands

| Command | Action |
|---------|--------|
| `.exit` | Quit |
| `.clear` | Forget all definitions |
| `.defs` | Show defined functions (syntax highlighted) |
| `.help` | Show help |
