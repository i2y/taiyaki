use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use taiyaki_core::permissions::Permissions;

pub async fn register_all(
    engine: &impl AsyncJsEngine,
    script_path: &Path,
    user_args: &[String],
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    let start_time = Arc::new(Instant::now());
    let perf_start = Arc::clone(&start_time);

    // Batch all sync host function registrations in one context access
    for (name, handler) in [
        (
            "__console_log",
            Box::new(|args: &[JsValue]| {
                println!("{}", extract_single_string(args));
                Ok(JsValue::Undefined)
            }) as Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>,
        ),
        (
            "__console_warn",
            Box::new(|args| {
                eprintln!("{}", extract_single_string(args));
                Ok(JsValue::Undefined)
            }),
        ),
        (
            "__console_error",
            Box::new(|args| {
                eprintln!("{}", extract_single_string(args));
                Ok(JsValue::Undefined)
            }),
        ),
        {
            let perms = perms.clone();
            (
                "readFile",
                Box::new(move |args: &[JsValue]| {
                    let path = require_string_arg(args, 0, "readFile")?;
                    perms
                        .check_read(path)
                        .map_err(|e| EngineError::JsException {
                            message: e.to_string(),
                        })?;
                    match std::fs::read_to_string(path) {
                        Ok(content) => Ok(JsValue::String(content)),
                        Err(e) => Err(EngineError::JsException {
                            message: format!("readFile failed: {e}"),
                        }),
                    }
                }) as Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>,
            )
        },
        {
            let perms = perms.clone();
            (
                "writeFile",
                Box::new(move |args: &[JsValue]| {
                    let path = require_string_arg(args, 0, "writeFile")?;
                    perms
                        .check_write(path)
                        .map_err(|e| EngineError::JsException {
                            message: e.to_string(),
                        })?;
                    let content = require_string_arg(args, 1, "writeFile")?;
                    match std::fs::write(path, content) {
                        Ok(()) => Ok(JsValue::Undefined),
                        Err(e) => Err(EngineError::JsException {
                            message: format!("writeFile failed: {e}"),
                        }),
                    }
                }) as Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>,
            )
        },
        (
            "__base64_decode",
            Box::new(|args| {
                use base64::Engine as _;
                let encoded = require_string_arg(args, 0, "__base64_decode")?;
                let bytes = base64::engine::general_purpose::STANDARD
                    .decode(encoded)
                    .map_err(|e| EngineError::JsException {
                        message: format!("base64 decode failed: {e}"),
                    })?;
                // Return as JSON array of byte values for Uint8Array construction
                let json = serde_json::to_string(&bytes).expect("byte array serialization");
                Ok(JsValue::Array(json))
            }),
        ),
        (
            "__perf_now",
            Box::new(move |_args: &[JsValue]| {
                let elapsed = perf_start.elapsed();
                Ok(JsValue::Number(elapsed.as_secs_f64() * 1000.0))
            }),
        ),
        (
            "__process_hrtime",
            Box::new(move |_args: &[JsValue]| {
                let elapsed = start_time.elapsed();
                let secs = elapsed.as_secs();
                let nanos = elapsed.subsec_nanos();
                Ok(JsValue::String(format!("[{secs},{nanos}]")))
            }),
        ),
        (
            "__process_cwd",
            Box::new(|_args: &[JsValue]| {
                let cwd = std::env::current_dir()
                    .map(|p| p.to_string_lossy().into_owned())
                    .unwrap_or_default();
                Ok(JsValue::String(cwd))
            }),
        ),
        (
            "__process_chdir",
            Box::new(|args: &[JsValue]| {
                let dir = require_string_arg(args, 0, "process.chdir")?;
                std::env::set_current_dir(dir).map_err(|e| EngineError::JsException {
                    message: format!("process.chdir failed: {e}"),
                })?;
                Ok(JsValue::Undefined)
            }),
        ),
        (
            "__process_stdout_write",
            Box::new(|args: &[JsValue]| {
                use std::io::Write;
                let s = extract_single_string(args);
                print!("{s}");
                let _ = std::io::stdout().flush();
                Ok(JsValue::Bool(true))
            }),
        ),
        (
            "__process_stderr_write",
            Box::new(|args: &[JsValue]| {
                use std::io::Write;
                let s = extract_single_string(args);
                eprint!("{s}");
                let _ = std::io::stderr().flush();
                Ok(JsValue::Bool(true))
            }),
        ),
    ] {
        engine.register_global_fn(name, handler).await?;
    }

    engine
        .eval(
            r#"globalThis.__inspect = function(value, depth, seen) {
    if (depth === undefined) depth = 2;
    if (seen === undefined) seen = new Set();

    if (value === null) return 'null';
    if (value === undefined) return 'undefined';

    var type = typeof value;
    if (type === 'string') return depth < 2 ? "'" + value + "'" : value;
    if (type === 'number' || type === 'boolean' || type === 'bigint') return String(value);
    if (type === 'symbol') return value.toString();
    if (type === 'function') return '[Function: ' + (value.name || '(anonymous)') + ']';

    if (seen.has(value)) return '[Circular]';
    seen.add(value);

    if (depth < 0) return Array.isArray(value) ? '[Array]' : '[Object]';

    if (value instanceof Error) return value.stack || value.toString();
    if (value instanceof Date) return value.toISOString();
    if (value instanceof RegExp) return value.toString();

    if (Array.isArray(value)) {
        if (value.length === 0) return '[]';
        var items = value.map(function(v) { return __inspect(v, depth - 1, seen); });
        return '[ ' + items.join(', ') + ' ]';
    }

    var keys = Object.keys(value);
    if (keys.length === 0) return '{}';
    var pairs = keys.map(function(k) {
        return k + ': ' + __inspect(value[k], depth - 1, seen);
    });
    return '{ ' + pairs.join(', ') + ' }';
};

(function() {
    var _entries = [];

    function PerformanceEntry(name, entryType, startTime, duration) {
        this.name = name;
        this.entryType = entryType;
        this.startTime = startTime;
        this.duration = duration;
    }
    PerformanceEntry.prototype.toJSON = function() {
        return { name: this.name, entryType: this.entryType, startTime: this.startTime, duration: this.duration };
    };

    function PerformanceMark(name, options) {
        options = options || {};
        PerformanceEntry.call(this, name, 'mark', options.startTime !== undefined ? options.startTime : __perf_now(), 0);
        this.detail = options.detail !== undefined ? options.detail : null;
    }
    PerformanceMark.prototype = Object.create(PerformanceEntry.prototype);
    PerformanceMark.prototype.constructor = PerformanceMark;

    function PerformanceMeasure(name, startTime, duration, detail) {
        PerformanceEntry.call(this, name, 'measure', startTime, duration);
        this.detail = detail !== undefined ? detail : null;
    }
    PerformanceMeasure.prototype = Object.create(PerformanceEntry.prototype);
    PerformanceMeasure.prototype.constructor = PerformanceMeasure;

    function findMark(name) {
        for (var i = _entries.length - 1; i >= 0; i--) {
            if (_entries[i].entryType === 'mark' && _entries[i].name === name) return _entries[i];
        }
        return null;
    }

    globalThis.PerformanceEntry = PerformanceEntry;
    globalThis.PerformanceMark = PerformanceMark;
    globalThis.PerformanceMeasure = PerformanceMeasure;

    globalThis.performance = {
        now: function() { return __perf_now(); },
        timeOrigin: 0,
        mark: function(name, options) {
            var m = new PerformanceMark(name, options);
            _entries.push(m);
            return m;
        },
        measure: function(name, startOrOpts, endMark) {
            var start, end, detail;
            if (startOrOpts && typeof startOrOpts === 'object') {
                // Options object form: measure(name, { start, end, duration, detail })
                detail = startOrOpts.detail;
                if (startOrOpts.start !== undefined) {
                    if (typeof startOrOpts.start === 'string') {
                        var sm = findMark(startOrOpts.start);
                        if (!sm) throw new Error("Failed to execute 'measure': The mark '" + startOrOpts.start + "' does not exist.");
                        start = sm.startTime;
                    } else {
                        start = startOrOpts.start;
                    }
                } else {
                    start = 0;
                }
                if (startOrOpts.end !== undefined) {
                    if (typeof startOrOpts.end === 'string') {
                        var em = findMark(startOrOpts.end);
                        if (!em) throw new Error("Failed to execute 'measure': The mark '" + startOrOpts.end + "' does not exist.");
                        end = em.startTime;
                    } else {
                        end = startOrOpts.end;
                    }
                } else if (startOrOpts.duration !== undefined) {
                    end = start + startOrOpts.duration;
                } else {
                    end = __perf_now();
                }
            } else if (typeof startOrOpts === 'string') {
                // measure(name, startMark, endMark)
                var sm2 = findMark(startOrOpts);
                if (!sm2) throw new Error("Failed to execute 'measure': The mark '" + startOrOpts + "' does not exist.");
                start = sm2.startTime;
                if (typeof endMark === 'string') {
                    var em2 = findMark(endMark);
                    if (!em2) throw new Error("Failed to execute 'measure': The mark '" + endMark + "' does not exist.");
                    end = em2.startTime;
                } else {
                    end = __perf_now();
                }
            } else {
                // measure(name)
                start = 0;
                end = __perf_now();
            }
            var m = new PerformanceMeasure(name, start, end - start, detail);
            _entries.push(m);
            return m;
        },
        getEntries: function() { return _entries.slice(); },
        getEntriesByName: function(name, type) {
            return _entries.filter(function(e) {
                return e.name === name && (type === undefined || e.entryType === type);
            });
        },
        getEntriesByType: function(type) {
            return _entries.filter(function(e) { return e.entryType === type; });
        },
        clearMarks: function(name) {
            _entries = _entries.filter(function(e) {
                return e.entryType !== 'mark' || (name !== undefined && e.name !== name);
            });
        },
        clearMeasures: function(name) {
            _entries = _entries.filter(function(e) {
                return e.entryType !== 'measure' || (name !== undefined && e.name !== name);
            });
        },
        clearResourceTimings: function() {}
    };
})();

(function() {
    const _timers = new Map();
    const _counters = new Map();
    let _indent = 0;
    const _pad = () => _indent > 0 ? ' '.repeat(_indent) : '';

    globalThis.console = {
        log: (...args) => __console_log(_pad() + args.map(a => __inspect(a)).join(' ')),
        warn: (...args) => __console_warn(_pad() + args.map(a => __inspect(a)).join(' ')),
        error: (...args) => __console_error(_pad() + args.map(a => __inspect(a)).join(' ')),
    };
    console.debug = console.log;
    console.info = console.log;

    console.assert = (cond, ...args) => {
        if (!cond) {
            const msg = args.length ? args.map(a => __inspect(a)).join(' ') : 'console.assert';
            __console_error('Assertion failed: ' + msg);
        }
    };

    console.count = (label) => {
        label = label === undefined ? 'default' : String(label);
        const c = (_counters.get(label) || 0) + 1;
        _counters.set(label, c);
        __console_log(_pad() + label + ': ' + c);
    };
    console.countReset = (label) => {
        label = label === undefined ? 'default' : String(label);
        _counters.set(label, 0);
    };

    console.time = (label) => {
        label = label === undefined ? 'default' : String(label);
        _timers.set(label, performance.now());
    };
    console.timeEnd = (label) => {
        label = label === undefined ? 'default' : String(label);
        const start = _timers.get(label);
        if (start === undefined) { __console_warn(label + ': Timer does not exist'); return; }
        _timers.delete(label);
        __console_log(_pad() + label + ': ' + (performance.now() - start).toFixed(3) + 'ms');
    };
    console.timeLog = (label, ...args) => {
        label = label === undefined ? 'default' : String(label);
        const start = _timers.get(label);
        if (start === undefined) { __console_warn(label + ': Timer does not exist'); return; }
        const elapsed = label + ': ' + (performance.now() - start).toFixed(3) + 'ms';
        __console_log(_pad() + (args.length ? elapsed + ' ' + args.map(a => __inspect(a)).join(' ') : elapsed));
    };

    console.clear = () => __console_log('\x1B[2J\x1B[H');
    console.dir = (obj, opts) => __console_log(_pad() + __inspect(obj, (opts && opts.depth != null) ? opts.depth : 2));
    console.trace = (...args) => {
        const msg = args.length ? args.map(a => __inspect(a)).join(' ') : 'Trace';
        __console_error(msg + '\n' + new Error().stack);
    };
    console.table = (data) => __console_log(_pad() + __inspect(data));
    console.group = (...args) => { if (args.length) __console_log(_pad() + args.map(a => __inspect(a)).join(' ')); _indent += 2; };
    console.groupEnd = () => { _indent = Math.max(0, _indent - 2); };
})();"#,
        )
        .await?;

    // TextEncoder / TextDecoder (UTF-8 only)
    engine
        .eval(
            r#"globalThis.TextEncoder = class TextEncoder {
    get encoding() { return 'utf-8'; }
    encode(str) {
        str = String(str);
        const bytes = [];
        for (let i = 0; i < str.length; i++) {
            let c = str.charCodeAt(i);
            if (c < 0x80) { bytes.push(c); }
            else if (c < 0x800) { bytes.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f)); }
            else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
                const next = str.charCodeAt(++i);
                const cp = 0x10000 + ((c - 0xd800) << 10) + (next - 0xdc00);
                bytes.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 0x3f), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
            } else { bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f)); }
        }
        return new Uint8Array(bytes);
    }
    encodeInto(str, dest) {
        const encoded = this.encode(str);
        const written = Math.min(encoded.length, dest.length);
        dest.set(encoded.subarray(0, written));
        // Count how many chars of str were fully encoded into 'written' bytes
        let read = 0, bytes = 0;
        while (read < str.length && bytes < written) {
            const c = str.codePointAt(read);
            const charBytes = c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
            if (bytes + charBytes > written) break;
            bytes += charBytes;
            read += c > 0xffff ? 2 : 1;
        }
        return { read, written };
    }
};

globalThis.TextDecoder = class TextDecoder {
    constructor(label) { this._encoding = (label || 'utf-8').toLowerCase().replace(/[-_]/g, ''); }
    get encoding() { return this._encoding === 'utf8' ? 'utf-8' : this._encoding; }
    decode(input) {
        if (!input) return '';
        const bytes = new Uint8Array(input instanceof ArrayBuffer ? input : input.buffer || input);
        let str = '', i = 0;
        while (i < bytes.length) {
            let c = bytes[i++];
            if (c < 0x80) str += String.fromCharCode(c);
            else if ((c & 0xe0) === 0xc0) { str += String.fromCharCode(((c & 0x1f) << 6) | (bytes[i++] & 0x3f)); }
            else if ((c & 0xf0) === 0xe0) { str += String.fromCharCode(((c & 0x0f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f)); }
            else if ((c & 0xf8) === 0xf0) {
                const cp = ((c & 0x07) << 18) | ((bytes[i++] & 0x3f) << 12) | ((bytes[i++] & 0x3f) << 6) | (bytes[i++] & 0x3f);
                str += String.fromCodePoint(cp);
            }
        }
        return str;
    }
};"#,
        )
        .await?;

    // queueMicrotask
    engine
        .eval("globalThis.queueMicrotask = globalThis.queueMicrotask || (fn => Promise.resolve().then(fn));")
        .await?;

    // structuredClone
    engine
        .eval(
            r#"globalThis.structuredClone = globalThis.structuredClone || function structuredClone(value, _options) {
    function _clone(v, seen) {
        if (v === null || typeof v !== 'object') return v;
        if (seen.has(v)) throw new DOMException('Circular reference', 'DataCloneError');
        seen.add(v);
        if (v instanceof Date) return new Date(v.getTime());
        if (v instanceof RegExp) return new RegExp(v.source, v.flags);
        if (v instanceof ArrayBuffer) return v.slice(0);
        if (ArrayBuffer.isView(v)) { const c = new v.constructor(v.length); c.set(v); return c; }
        if (v instanceof Map) { const m = new Map(); for (const [k, val] of v) m.set(_clone(k, seen), _clone(val, seen)); return m; }
        if (v instanceof Set) { const s = new Set(); for (const val of v) s.add(_clone(val, seen)); return s; }
        if (Array.isArray(v)) return v.map(val => _clone(val, seen));
        const obj = {};
        for (const key of Object.keys(v)) obj[key] = _clone(v[key], seen);
        return obj;
    }
    return _clone(value, new Set());
};"#,
        )
        .await?;

    register_process(engine, script_path, user_args).await?;
    register_url(engine).await?;
    register_abort_controller(engine).await?;
    register_headers(engine).await?;
    register_blob_formdata(engine).await?;
    register_web_streams(engine).await?;
    register_request_response(engine).await?;

    Ok(())
}

async fn register_process(
    engine: &impl AsyncJsEngine,
    script_path: &Path,
    user_args: &[String],
) -> Result<(), EngineError> {
    engine
        .register_global_fn(
            "__process_exit",
            Box::new(|args: &[JsValue]| {
                let code = match args.first() {
                    Some(JsValue::Number(n)) => *n as i32,
                    _ => 0,
                };
                std::process::exit(code);
            }),
        )
        .await?;

    let script_str = script_path.to_string_lossy();
    let mut argv_parts: Vec<String> = vec!["taiyaki".to_string(), script_str.into_owned()];
    argv_parts.extend(user_args.iter().cloned());
    let argv_json = serde_json::to_string(&argv_parts).expect("argv serialization");

    let env_map: std::collections::HashMap<String, String> = std::env::vars().collect();
    let env_json = serde_json::to_string(&env_map).expect("env serialization");

    let pid = std::process::id();
    let ppid = unsafe { libc::getppid() };
    let platform = taiyaki_node_polyfill::node_platform();
    let arch = taiyaki_node_polyfill::node_arch();
    let version = env!("CARGO_PKG_VERSION");

    let shim = format!(
        r#"globalThis.process = {{
    argv: {argv_json},
    env: {env_json},
    exit: (code) => __process_exit(code ?? 0),
    cwd: () => __process_cwd(),
    chdir: (dir) => __process_chdir(dir),
    pid: {pid},
    ppid: {ppid},
    platform: '{platform}',
    arch: '{arch}',
    version: 'v{version}',
    versions: {{ taiyaki: '{version}' }},
    stdout: {{ write: (s) => __process_stdout_write(String(s)) }},
    stderr: {{ write: (s) => __process_stderr_write(String(s)) }},
    hrtime: Object.assign(
        function hrtime(prev) {{
            const t = JSON.parse(__process_hrtime());
            if (prev) {{ let s = t[0] - prev[0]; let n = t[1] - prev[1]; if (n < 0) {{ s--; n += 1e9; }} return [s, n]; }}
            return t;
        }},
        {{ bigint: function() {{ const t = JSON.parse(__process_hrtime()); return BigInt(t[0]) * 1000000000n + BigInt(t[1]); }} }}
    ),
}};"#
    );
    engine.eval(&shim).await?;
    Ok(())
}

async fn register_url(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    if (typeof globalThis.URL !== 'undefined') return;

    function URLSearchParams(init) {
        this._params = [];
        if (typeof init === 'string') {
            var s = init.startsWith('?') ? init.slice(1) : init;
            if (s) s.split('&').forEach(function(pair) {
                var idx = pair.indexOf('=');
                if (idx === -1) this._params.push([decodeURIComponent(pair), '']);
                else this._params.push([decodeURIComponent(pair.slice(0, idx)), decodeURIComponent(pair.slice(idx + 1))]);
            }, this);
        } else if (init instanceof URLSearchParams) {
            this._params = init._params.slice();
        } else if (Array.isArray(init)) {
            this._params = init.map(function(p) { return [String(p[0]), String(p[1])]; });
        } else if (init && typeof init === 'object') {
            var keys = Object.keys(init);
            for (var i = 0; i < keys.length; i++) this._params.push([keys[i], String(init[keys[i]])]);
        }
    }
    URLSearchParams.prototype.append = function(name, value) { this._params.push([String(name), String(value)]); };
    URLSearchParams.prototype.delete = function(name) { this._params = this._params.filter(function(p) { return p[0] !== name; }); };
    URLSearchParams.prototype.get = function(name) { for (var i = 0; i < this._params.length; i++) if (this._params[i][0] === name) return this._params[i][1]; return null; };
    URLSearchParams.prototype.getAll = function(name) { return this._params.filter(function(p) { return p[0] === name; }).map(function(p) { return p[1]; }); };
    URLSearchParams.prototype.has = function(name) { return this._params.some(function(p) { return p[0] === name; }); };
    URLSearchParams.prototype.set = function(name, value) { var found = false; this._params = this._params.map(function(p) { if (p[0] === name && !found) { found = true; return [name, String(value)]; } if (p[0] === name) return null; return p; }).filter(Boolean); if (!found) this.append(name, value); };
    URLSearchParams.prototype.sort = function() { this._params.sort(function(a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; }); };
    URLSearchParams.prototype.toString = function() { return this._params.map(function(p) { return encodeURIComponent(p[0]) + '=' + encodeURIComponent(p[1]); }).join('&'); };
    URLSearchParams.prototype.forEach = function(callback, thisArg) { for (var i = 0; i < this._params.length; i++) callback.call(thisArg, this._params[i][1], this._params[i][0], this); };
    URLSearchParams.prototype.entries = function() { var i = 0, p = this._params; return { next: function() { return i >= p.length ? { done: true } : { value: p[i++], done: false }; }, [Symbol.iterator]: function() { return this; } }; };
    URLSearchParams.prototype.keys = function() { var i = 0, p = this._params; return { next: function() { return i >= p.length ? { done: true } : { value: p[i++][0], done: false }; }, [Symbol.iterator]: function() { return this; } }; };
    URLSearchParams.prototype.values = function() { var i = 0, p = this._params; return { next: function() { return i >= p.length ? { done: true } : { value: p[i++][1], done: false }; }, [Symbol.iterator]: function() { return this; } }; };
    URLSearchParams.prototype[Symbol.iterator] = URLSearchParams.prototype.entries;

    function URL(url, base) {
        if (base !== undefined) {
            var b = (base instanceof URL) ? base.href : String(base);
            if (url.match(/^[a-zA-Z][a-zA-Z0-9+\-.]*:/)) { /* absolute, ignore base */ }
            else if (url.startsWith('//')) url = b.split('//')[0] + url;
            else if (url.startsWith('/')) { var m = b.match(/^([a-zA-Z][a-zA-Z0-9+\-.]*:\/\/[^/?#]*)/); url = (m ? m[1] : '') + url; }
            else { url = b.replace(/[?#].*$/, '').replace(/\/[^/]*$/, '/') + url; }
        }
        var match = String(url).match(/^([a-zA-Z][a-zA-Z0-9+\-.]*:)\/\/(?:([^@/?#]*)@)?([^:/?#]*)(?::(\d+))?([^?#]*)(\?[^#]*)?(#.*)?$/);
        if (!match) { match = String(url).match(/^([a-zA-Z][a-zA-Z0-9+\-.]*:)(\/\/)?(?:([^@/?#]*)@)?([^:/?#]*)(?::(\d+))?([^?#]*)(\?[^#]*)?(#.*)?$/); if (!match) throw new TypeError("Invalid URL: " + url); this.protocol = match[1]; this.username = ''; this.password = ''; this.hostname = match[4] || ''; this.port = match[5] || ''; this.pathname = match[6] || ''; this.search = match[7] || ''; this.hash = match[8] || ''; }
        else { this.protocol = match[1]; if (match[2]) { var up = match[2].split(':'); this.username = decodeURIComponent(up[0]); this.password = up[1] ? decodeURIComponent(up[1]) : ''; } else { this.username = ''; this.password = ''; } this.hostname = match[3]; this.port = match[4] || ''; this.pathname = match[5] || '/'; this.search = match[6] || ''; this.hash = match[7] || ''; }
        this.searchParams = new URLSearchParams(this.search);
    }
    Object.defineProperty(URL.prototype, 'host', { get: function() { return this.port ? this.hostname + ':' + this.port : this.hostname; } });
    Object.defineProperty(URL.prototype, 'origin', { get: function() { return this.protocol + '//' + this.host; } });
    Object.defineProperty(URL.prototype, 'href', { get: function() { var s = this.protocol + '//' + (this.username ? encodeURIComponent(this.username) + (this.password ? ':' + encodeURIComponent(this.password) : '') + '@' : '') + this.host + this.pathname; var qs = this.searchParams.toString(); if (qs) s += '?' + qs; if (this.hash) s += this.hash; return s; }, set: function(v) { var u = new URL(v); this.protocol = u.protocol; this.hostname = u.hostname; this.port = u.port; this.pathname = u.pathname; this.search = u.search; this.hash = u.hash; this.searchParams = u.searchParams; } });
    URL.prototype.toString = function() { return this.href; };
    URL.prototype.toJSON = function() { return this.href; };

    globalThis.URL = URL;
    globalThis.URLSearchParams = URLSearchParams;
})();"#,
        )
        .await?;
    Ok(())
}

async fn register_abort_controller(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    function AbortSignal() {
        this.aborted = false;
        this.reason = undefined;
        this._listeners = [];
    }
    AbortSignal.prototype.addEventListener = function(type, fn) {
        if (type === 'abort') this._listeners.push(fn);
    };
    AbortSignal.prototype.removeEventListener = function(type, fn) {
        if (type === 'abort') this._listeners = this._listeners.filter(f => f !== fn);
    };
    AbortSignal.prototype.throwIfAborted = function() {
        if (this.aborted) throw this.reason;
    };
    AbortSignal.abort = function(reason) {
        var s = new AbortSignal();
        s.aborted = true;
        s.reason = reason !== undefined ? reason : new DOMException('The operation was aborted.', 'AbortError');
        return s;
    };
    AbortSignal.timeout = function(ms) {
        var ctrl = new AbortController();
        setTimeout(function() {
            ctrl.abort(new DOMException('The operation timed out.', 'TimeoutError'));
        }, ms);
        return ctrl.signal;
    };
    AbortSignal.any = function(signals) {
        var ctrl = new AbortController();
        for (var i = 0; i < signals.length; i++) {
            if (signals[i].aborted) { ctrl.abort(signals[i].reason); return ctrl.signal; }
            signals[i].addEventListener('abort', function() { ctrl.abort(this.reason); }.bind(signals[i]));
        }
        return ctrl.signal;
    };

    function AbortController() {
        this.signal = new AbortSignal();
    }
    AbortController.prototype.abort = function(reason) {
        if (this.signal.aborted) return;
        this.signal.aborted = true;
        this.signal.reason = reason !== undefined ? reason : new DOMException('The operation was aborted.', 'AbortError');
        var listeners = this.signal._listeners.slice();
        for (var i = 0; i < listeners.length; i++) {
            try { listeners[i].call(this.signal, { type: 'abort', target: this.signal }); } catch(e) {}
        }
    };

    if (typeof globalThis.DOMException === 'undefined') {
        globalThis.DOMException = class DOMException extends Error {
            constructor(message, name) { super(message); this.name = name || 'Error'; this.code = 0; }
        };
    }

    globalThis.AbortController = AbortController;
    globalThis.AbortSignal = AbortSignal;
})();"#,
        )
        .await?;
    Ok(())
}

async fn register_headers(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    function Headers(init) {
        this._map = {};
        if (init) {
            if (init instanceof Headers) {
                var self = this;
                init.forEach(function(v, k) { self.append(k, v); });
            } else if (Array.isArray(init)) {
                for (var i = 0; i < init.length; i++) this.append(init[i][0], init[i][1]);
            } else if (typeof init === 'object') {
                var keys = Object.keys(init);
                for (var i = 0; i < keys.length; i++) this.append(keys[i], init[keys[i]]);
            }
        }
    }
    Headers.prototype.append = function(name, value) {
        var key = name.toLowerCase();
        if (this._map[key] !== undefined) this._map[key] += ', ' + value;
        else this._map[key] = String(value);
    };
    Headers.prototype.delete = function(name) { delete this._map[name.toLowerCase()]; };
    Headers.prototype.get = function(name) { var v = this._map[name.toLowerCase()]; return v !== undefined ? v : null; };
    Headers.prototype.has = function(name) { return name.toLowerCase() in this._map; };
    Headers.prototype.set = function(name, value) { this._map[name.toLowerCase()] = String(value); };
    Headers.prototype.forEach = function(callback, thisArg) {
        var keys = Object.keys(this._map).sort();
        for (var i = 0; i < keys.length; i++) callback.call(thisArg, this._map[keys[i]], keys[i], this);
    };
    Headers.prototype.entries = function() {
        var keys = Object.keys(this._map).sort(), i = 0, map = this._map;
        return { next: function() { if (i >= keys.length) return { done: true }; var k = keys[i++]; return { value: [k, map[k]], done: false }; }, [Symbol.iterator]: function() { return this; } };
    };
    Headers.prototype.keys = function() {
        var keys = Object.keys(this._map).sort(), i = 0;
        return { next: function() { return i >= keys.length ? { done: true } : { value: keys[i++], done: false }; }, [Symbol.iterator]: function() { return this; } };
    };
    Headers.prototype.values = function() {
        var keys = Object.keys(this._map).sort(), i = 0, map = this._map;
        return { next: function() { return i >= keys.length ? { done: true } : { value: map[keys[i++]], done: false }; }, [Symbol.iterator]: function() { return this; } };
    };
    Headers.prototype[Symbol.iterator] = Headers.prototype.entries;
    Headers.prototype.toObject = function() { var o = {}; this.forEach(function(v, k) { o[k] = v; }); return o; };
    globalThis.Headers = Headers;
})();"#,
        )
        .await?;
    Ok(())
}

async fn register_web_streams(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    if (typeof globalThis.ReadableStream !== 'undefined') return;

    function ReadableStreamDefaultController(stream) {
        this._stream = stream;
        this._closeRequested = false;
    }
    ReadableStreamDefaultController.prototype.enqueue = function(chunk) {
        if (this._closeRequested) throw new TypeError('Cannot enqueue after close');
        this._stream._queue.push(chunk);
        this._stream._drainQueue();
    };
    ReadableStreamDefaultController.prototype.close = function() {
        if (this._closeRequested) return;
        this._closeRequested = true;
        this._stream._closeRequested = true;
        if (this._stream._queue.length === 0) this._stream._finishClose();
    };
    ReadableStreamDefaultController.prototype.error = function(e) { this._stream._error(e); };
    Object.defineProperty(ReadableStreamDefaultController.prototype, 'desiredSize', {
        get: function() {
            if (this._stream._state === 'errored') return null;
            if (this._stream._state === 'closed') return 0;
            return this._stream._highWaterMark - this._stream._queue.length;
        }
    });

    function ReadableStreamDefaultReader(stream) {
        if (stream._locked) throw new TypeError('ReadableStream is locked');
        this._stream = stream;
        stream._reader = this;
        stream._locked = true;
        this._closedResolve = null;
        this._closedReject = null;
        var self = this;
        this.closed = new Promise(function(resolve, reject) { self._closedResolve = resolve; self._closedReject = reject; });
        if (stream._state === 'closed') this._closedResolve(undefined);
        else if (stream._state === 'errored') this._closedReject(stream._storedError);
    }
    ReadableStreamDefaultReader.prototype.read = function() {
        var stream = this._stream;
        if (!stream) return Promise.reject(new TypeError('Reader has been released'));
        if (stream._queue.length > 0) {
            var chunk = stream._queue.shift();
            if (stream._closeRequested && stream._queue.length === 0) stream._finishClose();
            return Promise.resolve({ value: chunk, done: false });
        }
        if (stream._state === 'closed') return Promise.resolve({ value: undefined, done: true });
        if (stream._state === 'errored') return Promise.reject(stream._storedError);
        return new Promise(function(resolve, reject) {
            stream._pendingReads.push({ resolve: resolve, reject: reject });
            stream._pullIfNeeded();
        });
    };
    ReadableStreamDefaultReader.prototype.releaseLock = function() {
        if (!this._stream) return;
        this._stream._reader = null;
        this._stream._locked = false;
        this._stream = null;
    };
    ReadableStreamDefaultReader.prototype.cancel = function(reason) {
        if (!this._stream) return Promise.reject(new TypeError('Reader has been released'));
        return this._stream.cancel(reason);
    };

    function ReadableStream(underlyingSource, strategy) {
        this._queue = [];
        this._pendingReads = [];
        this._locked = false;
        this._reader = null;
        this._state = 'readable';
        this._storedError = undefined;
        this._closeRequested = false;
        this._pulling = false;
        this._pullAgain = false;
        this._highWaterMark = (strategy && strategy.highWaterMark !== undefined) ? strategy.highWaterMark : 1;
        this._controller = new ReadableStreamDefaultController(this);
        this._underlyingSource = underlyingSource || {};
        var self = this;
        if (this._underlyingSource.start) {
            try {
                var result = this._underlyingSource.start(this._controller);
                if (result && typeof result.then === 'function') {
                    result.then(function() { self._pullIfNeeded(); }, function(e) { self._error(e); });
                }
            } catch(e) { this._error(e); }
        }
    }
    ReadableStream.prototype._pullIfNeeded = function() {
        if (this._pulling || this._closeRequested || this._state !== 'readable') return;
        if (this._pendingReads.length === 0 && this._queue.length >= this._highWaterMark) return;
        if (!this._underlyingSource.pull) return;
        this._pulling = true;
        var self = this;
        try {
            var result = this._underlyingSource.pull(this._controller);
            if (result && typeof result.then === 'function') {
                result.then(function() { self._pulling = false; self._drainQueue(); if (self._pullAgain) { self._pullAgain = false; self._pullIfNeeded(); } }, function(e) { self._error(e); });
            } else { this._pulling = false; this._drainQueue(); }
        } catch(e) { this._error(e); }
    };
    ReadableStream.prototype._drainQueue = function() {
        while (this._pendingReads.length > 0 && this._queue.length > 0) {
            var reader = this._pendingReads.shift();
            reader.resolve({ value: this._queue.shift(), done: false });
        }
        if (this._closeRequested && this._queue.length === 0) this._finishClose();
    };
    ReadableStream.prototype._finishClose = function() {
        this._state = 'closed';
        while (this._pendingReads.length > 0) this._pendingReads.shift().resolve({ value: undefined, done: true });
        if (this._reader && this._reader._closedResolve) this._reader._closedResolve(undefined);
    };
    ReadableStream.prototype._error = function(e) {
        this._state = 'errored'; this._storedError = e;
        while (this._pendingReads.length > 0) this._pendingReads.shift().reject(e);
        if (this._reader && this._reader._closedReject) this._reader._closedReject(e);
    };
    ReadableStream.prototype.getReader = function() { return new ReadableStreamDefaultReader(this); };
    ReadableStream.prototype.cancel = function(reason) {
        if (this._state === 'closed') return Promise.resolve();
        if (this._state === 'errored') return Promise.reject(this._storedError);
        this._state = 'closed'; this._queue = [];
        while (this._pendingReads.length > 0) this._pendingReads.shift().resolve({ value: undefined, done: true });
        if (this._reader && this._reader._closedResolve) this._reader._closedResolve(undefined);
        if (this._underlyingSource.cancel) { try { return Promise.resolve(this._underlyingSource.cancel(reason)); } catch(e) { return Promise.reject(e); } }
        return Promise.resolve();
    };
    ReadableStream.prototype.tee = function() {
        var reader = this.getReader();
        var canceled1 = false, canceled2 = false, done = false;
        var branch1Controller, branch2Controller, buf1 = [], buf2 = [];
        function pullSource() {
            if (done) return Promise.resolve();
            return reader.read().then(function(result) {
                if (result.done) { done = true; if (!canceled1) branch1Controller.close(); if (!canceled2) branch2Controller.close(); return; }
                if (!canceled1) buf1.push(result.value);
                if (!canceled2) buf2.push(result.value);
            });
        }
        var branch1 = new ReadableStream({ start: function(c) { branch1Controller = c; }, pull: function(c) { if (buf1.length > 0) { c.enqueue(buf1.shift()); return; } return pullSource().then(function() { if (buf1.length > 0) c.enqueue(buf1.shift()); }); }, cancel: function() { canceled1 = true; if (canceled2) reader.cancel(); } });
        var branch2 = new ReadableStream({ start: function(c) { branch2Controller = c; }, pull: function(c) { if (buf2.length > 0) { c.enqueue(buf2.shift()); return; } return pullSource().then(function() { if (buf2.length > 0) c.enqueue(buf2.shift()); }); }, cancel: function() { canceled2 = true; if (canceled1) reader.cancel(); } });
        return [branch1, branch2];
    };
    ReadableStream.prototype.pipeTo = function(dest, options) {
        var reader = this.getReader(); var writer = dest.getWriter(); options = options || {};
        function pump() { return reader.read().then(function(result) { if (result.done) { if (!options.preventClose) return writer.close(); writer.releaseLock(); return; } return writer.write(result.value).then(pump); }); }
        return pump().catch(function(err) { if (!options.preventAbort) writer.abort(err); throw err; });
    };
    ReadableStream.prototype.pipeThrough = function(transform, options) { this.pipeTo(transform.writable, options); return transform.readable; };
    ReadableStream.prototype[Symbol.asyncIterator] = function() {
        var reader = this.getReader();
        return { next: function() { return reader.read(); }, return: function() { reader.releaseLock(); return Promise.resolve({ value: undefined, done: true }); } };
    };
    ReadableStream.from = function(iterable) {
        if (iterable && typeof iterable[Symbol.asyncIterator] === 'function') {
            var iter = iterable[Symbol.asyncIterator]();
            return new ReadableStream({ pull: function(controller) { return iter.next().then(function(result) { if (result.done) controller.close(); else controller.enqueue(result.value); }); }, cancel: function() { if (iter.return) iter.return(); } });
        }
        if (iterable && typeof iterable[Symbol.iterator] === 'function') {
            var iter = iterable[Symbol.iterator]();
            return new ReadableStream({ pull: function(controller) { var result = iter.next(); if (result.done) controller.close(); else controller.enqueue(result.value); }, cancel: function() { if (iter.return) iter.return(); } });
        }
        throw new TypeError('ReadableStream.from requires an iterable');
    };

    // WritableStream
    function WritableStreamDefaultController(stream) { this._stream = stream; }
    WritableStreamDefaultController.prototype.error = function(e) { this._stream._error(e); };

    function WritableStreamDefaultWriter(stream) {
        if (stream._locked) throw new TypeError('WritableStream is locked');
        this._stream = stream; stream._writer = this; stream._locked = true;
        var self = this;
        this._readyResolve = null;
        this.ready = new Promise(function(resolve) { self._readyResolve = resolve; });
        if (stream._state === 'writable') this._readyResolve();
        this._closedResolve = null; this._closedReject = null;
        this.closed = new Promise(function(resolve, reject) { self._closedResolve = resolve; self._closedReject = reject; });
        if (stream._state === 'closed') this._closedResolve(undefined);
        else if (stream._state === 'errored') this._closedReject(stream._storedError);
    }
    Object.defineProperty(WritableStreamDefaultWriter.prototype, 'desiredSize', {
        get: function() { if (!this._stream) return null; return this._stream._highWaterMark - this._stream._writeQueue.length; }
    });
    WritableStreamDefaultWriter.prototype.write = function(chunk) {
        var stream = this._stream;
        if (!stream) return Promise.reject(new TypeError('Writer has been released'));
        if (stream._state !== 'writable') return Promise.reject(new TypeError('Stream is not writable'));
        return stream._write(chunk);
    };
    WritableStreamDefaultWriter.prototype.close = function() {
        var stream = this._stream;
        if (!stream) return Promise.reject(new TypeError('Writer has been released'));
        return stream._close();
    };
    WritableStreamDefaultWriter.prototype.abort = function(reason) {
        var stream = this._stream;
        if (!stream) return Promise.reject(new TypeError('Writer has been released'));
        return stream.abort(reason);
    };
    WritableStreamDefaultWriter.prototype.releaseLock = function() {
        if (!this._stream) return;
        this._stream._writer = null; this._stream._locked = false; this._stream = null;
    };

    function WritableStream(underlyingSink, strategy) {
        this._writeQueue = []; this._locked = false; this._writer = null;
        this._state = 'writable'; this._storedError = undefined;
        this._highWaterMark = (strategy && strategy.highWaterMark !== undefined) ? strategy.highWaterMark : 1;
        this._controller = new WritableStreamDefaultController(this);
        this._underlyingSink = underlyingSink || {}; this._writing = false;
        if (this._underlyingSink.start) { try { this._underlyingSink.start(this._controller); } catch(e) { this._error(e); } }
    }
    WritableStream.prototype.getWriter = function() { return new WritableStreamDefaultWriter(this); };
    WritableStream.prototype._write = function(chunk) {
        var self = this;
        if (!this._underlyingSink.write) return Promise.resolve();
        return new Promise(function(resolve, reject) { self._writeQueue.push({ chunk: chunk, resolve: resolve, reject: reject }); self._processWrite(); });
    };
    WritableStream.prototype._processWrite = function() {
        if (this._writing || this._writeQueue.length === 0 || this._state !== 'writable') return;
        this._writing = true; var entry = this._writeQueue.shift(); var self = this;
        try {
            var result = this._underlyingSink.write(entry.chunk, this._controller);
            if (result && typeof result.then === 'function') { result.then(function() { self._writing = false; entry.resolve(); self._processWrite(); }, function(e) { self._writing = false; entry.reject(e); self._error(e); }); }
            else { this._writing = false; entry.resolve(); this._processWrite(); }
        } catch(e) { this._writing = false; entry.reject(e); this._error(e); }
    };
    WritableStream.prototype._close = function() {
        var self = this; this._state = 'closed';
        if (this._underlyingSink.close) { try { var result = this._underlyingSink.close(); if (result && typeof result.then === 'function') { return result.then(function() { if (self._writer && self._writer._closedResolve) self._writer._closedResolve(undefined); }); } } catch(e) {} }
        if (this._writer && this._writer._closedResolve) this._writer._closedResolve(undefined);
        return Promise.resolve();
    };
    WritableStream.prototype._error = function(e) {
        this._state = 'errored'; this._storedError = e;
        while (this._writeQueue.length > 0) this._writeQueue.shift().reject(e);
        if (this._writer && this._writer._closedReject) this._writer._closedReject(e);
    };
    WritableStream.prototype.abort = function(reason) {
        if (this._state === 'closed' || this._state === 'errored') return Promise.resolve();
        this._error(reason || new Error('Aborted'));
        if (this._underlyingSink.abort) { try { return Promise.resolve(this._underlyingSink.abort(reason)); } catch(e) { return Promise.reject(e); } }
        return Promise.resolve();
    };

    // TransformStream
    function TransformStream(transformer, writableStrategy, readableStrategy) {
        transformer = transformer || {};
        var readableController;
        this.readable = new ReadableStream({ start: function(c) { readableController = c; } }, readableStrategy);
        this.writable = new WritableStream({
            write: function(chunk) {
                if (transformer.transform) {
                    return new Promise(function(resolve, reject) {
                        try {
                            var result = transformer.transform(chunk, { enqueue: function(c) { readableController.enqueue(c); }, error: function(e) { readableController.error(e); }, terminate: function() { readableController.close(); } });
                            if (result && typeof result.then === 'function') result.then(resolve, reject); else resolve();
                        } catch(e) { reject(e); }
                    });
                }
                readableController.enqueue(chunk);
                return Promise.resolve();
            },
            close: function() {
                if (transformer.flush) { try { transformer.flush({ enqueue: function(c) { readableController.enqueue(c); }, error: function(e) { readableController.error(e); }, terminate: function() { readableController.close(); } }); } catch(e) { readableController.error(e); return; } }
                readableController.close();
            },
            abort: function(reason) { readableController.error(reason); }
        }, writableStrategy);
    }

    globalThis.ReadableStream = ReadableStream;
    globalThis.WritableStream = WritableStream;
    globalThis.TransformStream = TransformStream;
    globalThis.ReadableStreamDefaultReader = ReadableStreamDefaultReader;
    globalThis.WritableStreamDefaultWriter = WritableStreamDefaultWriter;
})();"#,
        )
        .await?;
    Ok(())
}

async fn register_blob_formdata(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    if (typeof globalThis.Blob !== 'undefined') return;

    function _concatBytes(parts, type) {
        if (!parts || parts.length === 0) return { bytes: new Uint8Array(0), type: type || '' };
        var enc = new TextEncoder();
        var arrays = [];
        var totalLen = 0;
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i];
            var arr;
            if (typeof p === 'string') {
                arr = enc.encode(p);
            } else if (p instanceof ArrayBuffer) {
                arr = new Uint8Array(p);
            } else if (ArrayBuffer.isView(p)) {
                arr = new Uint8Array(p.buffer, p.byteOffset, p.byteLength);
            } else if (p instanceof Blob) {
                arr = p._bytes;
            } else {
                arr = enc.encode(String(p));
            }
            arrays.push(arr);
            totalLen += arr.length;
        }
        var result = new Uint8Array(totalLen);
        var offset = 0;
        for (var j = 0; j < arrays.length; j++) {
            result.set(arrays[j], offset);
            offset += arrays[j].length;
        }
        return { bytes: result, type: type || '' };
    }

    function Blob(parts, options) {
        var r = _concatBytes(parts, options && options.type);
        this._bytes = r.bytes;
        this.type = r.type;
        this.size = this._bytes.length;
    }
    Blob.prototype.text = function() {
        return Promise.resolve(new TextDecoder().decode(this._bytes));
    };
    Blob.prototype.arrayBuffer = function() {
        var b = this._bytes;
        return Promise.resolve(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
    };
    Blob.prototype.slice = function(start, end, contentType) {
        var s = start || 0;
        var e = end !== undefined ? end : this._bytes.length;
        if (s < 0) s = Math.max(this._bytes.length + s, 0);
        if (e < 0) e = Math.max(this._bytes.length + e, 0);
        var sliced = this._bytes.slice(s, e);
        var b = new Blob([], { type: contentType || '' });
        b._bytes = sliced;
        b.size = sliced.length;
        return b;
    };
    Blob.prototype.stream = function() {
        var bytes = this._bytes;
        return new ReadableStream({
            start: function(controller) {
                if (bytes.length > 0) controller.enqueue(bytes);
                controller.close();
            }
        });
    };
    Blob.prototype[Symbol.toStringTag] = 'Blob';

    function File(parts, name, options) {
        options = options || {};
        Blob.call(this, parts, options);
        this.name = name;
        this.lastModified = options.lastModified !== undefined ? options.lastModified : Date.now();
    }
    File.prototype = Object.create(Blob.prototype);
    File.prototype.constructor = File;
    File.prototype[Symbol.toStringTag] = 'File';

    function FormData() {
        this._entries = [];
    }
    FormData.prototype.append = function(name, value, filename) {
        if (value instanceof Blob && !(value instanceof File)) {
            value = new File([value._bytes], filename || 'blob', { type: value.type });
        } else if (value instanceof File && filename !== undefined) {
            value = new File([value._bytes], filename, { type: value.type, lastModified: value.lastModified });
        }
        this._entries.push([String(name), value]);
    };
    FormData.prototype.delete = function(name) {
        name = String(name);
        this._entries = this._entries.filter(function(e) { return e[0] !== name; });
    };
    FormData.prototype.get = function(name) {
        name = String(name);
        for (var i = 0; i < this._entries.length; i++) {
            if (this._entries[i][0] === name) return this._entries[i][1];
        }
        return null;
    };
    FormData.prototype.getAll = function(name) {
        name = String(name);
        return this._entries.filter(function(e) { return e[0] === name; }).map(function(e) { return e[1]; });
    };
    FormData.prototype.has = function(name) {
        name = String(name);
        for (var i = 0; i < this._entries.length; i++) {
            if (this._entries[i][0] === name) return true;
        }
        return false;
    };
    FormData.prototype.set = function(name, value, filename) {
        name = String(name);
        this.delete(name);
        this.append(name, value, filename);
    };
    FormData.prototype.forEach = function(callback, thisArg) {
        for (var i = 0; i < this._entries.length; i++) {
            callback.call(thisArg, this._entries[i][1], this._entries[i][0], this);
        }
    };
    FormData.prototype.entries = function() {
        var idx = 0, entries = this._entries;
        return { next: function() {
            if (idx >= entries.length) return { done: true, value: undefined };
            return { done: false, value: entries[idx++].slice() };
        }, [Symbol.iterator]: function() { return this; } };
    };
    FormData.prototype.keys = function() {
        var idx = 0, entries = this._entries;
        return { next: function() {
            if (idx >= entries.length) return { done: true, value: undefined };
            return { done: false, value: entries[idx++][0] };
        }, [Symbol.iterator]: function() { return this; } };
    };
    FormData.prototype.values = function() {
        var idx = 0, entries = this._entries;
        return { next: function() {
            if (idx >= entries.length) return { done: true, value: undefined };
            return { done: false, value: entries[idx++][1] };
        }, [Symbol.iterator]: function() { return this; } };
    };
    FormData.prototype[Symbol.iterator] = FormData.prototype.entries;
    FormData.prototype[Symbol.toStringTag] = 'FormData';

    globalThis.Blob = Blob;
    globalThis.File = File;
    globalThis.FormData = FormData;
})();"#,
        )
        .await?;
    Ok(())
}

async fn register_request_response(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .eval(
            r#"(function() {
    function Request(input, init) {
        init = init || {};
        if (input instanceof Request) {
            this.url = input.url;
            this.method = input.method;
            this.headers = new Headers(input.headers);
            this._body = input._body;
        } else {
            this.url = String(input);
            this.method = 'GET';
            this.headers = new Headers();
            this._body = null;
        }
        if (init.method) this.method = init.method.toUpperCase();
        if (init.headers) this.headers = new Headers(init.headers);
        if (init.body !== undefined) this._body = init.body;
        this.signal = init.signal || null;
        this.redirect = init.redirect || 'follow';
        this._bodyUsed = false;
    }
    Object.defineProperty(Request.prototype, 'bodyUsed', { get: function() { return this._bodyUsed; } });
    Request.prototype.text = function() {
        if (this._bodyUsed) return Promise.reject(new TypeError('Body has already been consumed'));
        this._bodyUsed = true;
        return Promise.resolve(this._body != null ? String(this._body) : '');
    };
    Request.prototype.json = function() { return this.text().then(JSON.parse); };
    Request.prototype.arrayBuffer = function() {
        if (this._bodyUsed) return Promise.reject(new TypeError('Body has already been consumed'));
        this._bodyUsed = true;
        if (this._body == null) return Promise.resolve(new ArrayBuffer(0));
        var enc = new TextEncoder();
        return Promise.resolve(enc.encode(String(this._body)).buffer);
    };
    Request.prototype.clone = function() {
        if (this._bodyUsed) throw new TypeError('Cannot clone a used request');
        return new Request(this);
    };

    function Response(body, init) {
        init = init || {};
        this.status = init.status !== undefined ? init.status : 200;
        this.statusText = init.statusText || '';
        this.headers = new Headers(init.headers);
        this.ok = this.status >= 200 && this.status < 300;
        this.type = 'default';
        this.url = init.url || '';
        this.redirected = init.redirected || false;
        this._body = body !== undefined && body !== null ? body : null;
        this._bodyUsed = false;
    }
    Object.defineProperty(Response.prototype, 'bodyUsed', { get: function() { return this._bodyUsed; } });
    Response.prototype.text = function() {
        if (this._bodyUsed) return Promise.reject(new TypeError('Body has already been consumed'));
        this._bodyUsed = true;
        return Promise.resolve(this._body != null ? String(this._body) : '');
    };
    Response.prototype.json = function() { return this.text().then(JSON.parse); };
    Response.prototype.arrayBuffer = function() {
        if (this._bodyUsed) return Promise.reject(new TypeError('Body has already been consumed'));
        this._bodyUsed = true;
        if (this._body == null) return Promise.resolve(new ArrayBuffer(0));
        if (this._bodyBase64) {
            var bin = __base64_decode(this._bodyBase64);
            return Promise.resolve(new Uint8Array(bin).buffer);
        }
        var enc = new TextEncoder();
        return Promise.resolve(enc.encode(String(this._body)).buffer);
    };
    Response.prototype.blob = function() {
        var ct = this.headers ? this.headers.get('content-type') || '' : '';
        return this.arrayBuffer().then(function(buf) {
            return new Blob([buf], { type: ct });
        });
    };
    Response.prototype.clone = function() {
        if (this._bodyUsed) throw new TypeError('Cannot clone a used response');
        var r = new Response(this._body, { status: this.status, statusText: this.statusText, headers: new Headers(this.headers) });
        r.url = this.url;
        r.redirected = this.redirected;
        r.type = this.type;
        r._bodyBase64 = this._bodyBase64;
        return r;
    };
    Response.json = function(data, init) {
        init = init || {};
        var headers = new Headers(init.headers);
        if (!headers.has('content-type')) headers.set('content-type', 'application/json');
        return new Response(JSON.stringify(data), { status: init.status || 200, statusText: init.statusText, headers: headers });
    };
    Response.redirect = function(url, status) {
        status = status || 302;
        return new Response(null, { status: status, headers: { 'Location': url } });
    };

    globalThis.Request = Request;
    globalThis.Response = Response;
})();"#,
        )
        .await?;
    Ok(())
}

fn extract_single_string(args: &[JsValue]) -> &str {
    match args.first() {
        Some(JsValue::String(s)) => s.as_str(),
        _ => "",
    }
}

fn require_string_arg<'a>(
    args: &'a [JsValue],
    index: usize,
    fn_name: &str,
) -> Result<&'a str, EngineError> {
    match args.get(index) {
        Some(JsValue::String(s)) => Ok(s.as_str()),
        _ => Err(EngineError::TypeError(format!(
            "{fn_name}: expected string argument at position {index}"
        ))),
    }
}
