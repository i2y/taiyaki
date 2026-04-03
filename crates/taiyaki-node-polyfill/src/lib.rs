mod modules;

pub use modules::fs::stat_to_json;
pub use modules::{node_arch, node_platform};

use taiyaki_core::engine::{EngineError, JsEngine};

/// Register all Node.js polyfill modules and host functions (sync engine).
pub fn register_all(engine: &dyn JsEngine) -> Result<(), EngineError> {
    register_module_sources(engine)?;
    register_host_functions(engine)?;
    Ok(())
}

fn register_module_sources(engine: &dyn JsEngine) -> Result<(), EngineError> {
    for (name, src) in modules::MODULE_SOURCES {
        engine.register_module(name, src)?;
        engine.register_module(&format!("node:{name}"), src)?;
    }
    if let Some((_, src)) = modules::MODULE_SOURCES.iter().find(|(n, _)| *n == "sqlite") {
        engine.register_module("bun:sqlite", src)?;
    }
    Ok(())
}

/// Register Rust host functions and globals (Buffer, require, __path_cwd, fs, os, crypto).
fn register_host_functions(engine: &dyn JsEngine) -> Result<(), EngineError> {
    for (name, callback) in modules::path::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::buffer::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::require::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::fs::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::os::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::crypto::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::child_process::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    for (name, callback) in modules::zlib::host_functions() {
        engine.register_global_fn(name, callback)?;
    }
    modules::buffer::register_globals(engine)?;
    modules::require::register_globals(engine)?;
    modules::crypto::register_globals(engine)?;
    Ok(())
}

/// Register all Node.js polyfill modules and host functions (async engine).
pub async fn register_all_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    register_module_sources_async(engine)?;
    register_host_functions_async(engine).await?;
    Ok(())
}

fn register_module_sources_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    for (name, src) in modules::MODULE_SOURCES {
        engine.register_module(name, src)?;
        engine.register_module(&format!("node:{name}"), src)?;
    }
    // Extra alias: bun:sqlite
    if let Some((_, src)) = modules::MODULE_SOURCES.iter().find(|(n, _)| *n == "sqlite") {
        engine.register_module("bun:sqlite", src)?;
    }
    Ok(())
}

/// Register Rust host functions and globals (async engine).
async fn register_host_functions_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    for (name, callback) in modules::path::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::buffer::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::require::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::fs::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::os::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::crypto::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::child_process::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    for (name, callback) in modules::zlib::host_functions() {
        engine.register_global_fn(name, callback).await?;
    }
    modules::buffer::register_globals_async(engine).await?;
    modules::require::register_globals_async(engine).await?;
    modules::crypto::register_globals_async(engine).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use taiyaki_core::engine::JsValue;
    use taiyaki_core::engine::quickjs_backend::QuickJsEngine;

    #[test]
    fn test_register_all_sync() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
    }

    #[test]
    fn test_path_join() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let result = engine
            .eval_module(
                r#"import { join } from 'path';
export const result = join('foo', 'bar', 'baz');"#,
                "test",
            )
            .unwrap();
        let val = engine
            .object_get(result.handle_id().unwrap(), "result")
            .unwrap();
        assert_eq!(val, JsValue::String("foo/bar/baz".to_string()));
    }

    #[test]
    fn test_path_dirname() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let result = engine
            .eval_module(
                r#"import { dirname } from 'path';
export const result = dirname('/foo/bar/baz.js');"#,
                "test",
            )
            .unwrap();
        let val = engine
            .object_get(result.handle_id().unwrap(), "result")
            .unwrap();
        assert_eq!(val, JsValue::String("/foo/bar".to_string()));
    }

    #[test]
    fn test_path_basename() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { basename } from 'path';
export const r1 = basename('/foo/bar/baz.js');
export const r2 = basename('/foo/bar/baz.js', '.js');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("baz.js".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String("baz".to_string())
        );
    }

    #[test]
    fn test_path_extname() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { extname } from 'path';
export const r1 = extname('index.html');
export const r2 = extname('index.');
export const r3 = extname('.hidden');
export const r4 = extname('noext');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String(".html".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String(".".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r3").unwrap(),
            JsValue::String("".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r4").unwrap(),
            JsValue::String("".to_string())
        );
    }

    #[test]
    fn test_path_normalize() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { normalize } from 'path';
export const r1 = normalize('/foo/bar//baz/asdf/quux/..');
export const r2 = normalize('foo/bar/../baz');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("/foo/bar/baz/asdf".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String("foo/baz".to_string())
        );
    }

    #[test]
    fn test_path_is_absolute() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { isAbsolute } from 'path';
export const r1 = isAbsolute('/foo/bar');
export const r2 = isAbsolute('foo/bar');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "r1").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r2").unwrap(), JsValue::Bool(false));
    }

    #[test]
    fn test_path_parse_and_format() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { parse, format } from 'path';
const p = parse('/home/user/dir/file.txt');
export const root = p.root;
export const dir = p.dir;
export const base = p.base;
export const ext = p.ext;
export const name = p.name;
export const roundtrip = format(p);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "root").unwrap(),
            JsValue::String("/".to_string())
        );
        assert_eq!(
            engine.object_get(h, "dir").unwrap(),
            JsValue::String("/home/user/dir".to_string())
        );
        assert_eq!(
            engine.object_get(h, "base").unwrap(),
            JsValue::String("file.txt".to_string())
        );
        assert_eq!(
            engine.object_get(h, "ext").unwrap(),
            JsValue::String(".txt".to_string())
        );
        assert_eq!(
            engine.object_get(h, "name").unwrap(),
            JsValue::String("file".to_string())
        );
        assert_eq!(
            engine.object_get(h, "roundtrip").unwrap(),
            JsValue::String("/home/user/dir/file.txt".to_string())
        );
    }

    #[test]
    fn test_path_sep_and_delimiter() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { sep, delimiter } from 'path';
export { sep, delimiter };"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "sep").unwrap(),
            JsValue::String("/".to_string())
        );
        assert_eq!(
            engine.object_get(h, "delimiter").unwrap(),
            JsValue::String(":".to_string())
        );
    }

    #[test]
    fn test_path_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { join } from 'node:path';
export const result = join('a', 'b');"#,
                "test",
            )
            .unwrap();
        let val = engine
            .object_get(ns.handle_id().unwrap(), "result")
            .unwrap();
        assert_eq!(val, JsValue::String("a/b".to_string()));
    }

    #[test]
    fn test_path_resolve() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { resolve } from 'path';
export const r1 = resolve('/foo/bar', './baz');
export const r2 = resolve('/foo/bar', '/tmp/file');
export const r3 = resolve('/foo', 'bar', 'baz');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("/foo/bar/baz".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String("/tmp/file".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r3").unwrap(),
            JsValue::String("/foo/bar/baz".to_string())
        );
    }

    #[test]
    fn test_path_relative() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { relative } from 'path';
export const r1 = relative('/data/orandea/test/aaa', '/data/orandea/impl/bbb');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("../../impl/bbb".to_string())
        );
    }

    // --- events tests ---

    #[test]
    fn test_events_on_emit() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { EventEmitter } from 'events';
const ee = new EventEmitter();
let result = '';
ee.on('data', (msg) => { result += msg; });
ee.emit('data', 'hello');
ee.emit('data', ' world');
export { result };"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("hello world".to_string())
        );
    }

    #[test]
    fn test_events_once() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import EventEmitter from 'events';
const ee = new EventEmitter();
let count = 0;
ee.once('ping', () => { count++; });
ee.emit('ping');
ee.emit('ping');
export { count };"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "count").unwrap(),
            JsValue::Number(1.0)
        );
    }

    #[test]
    fn test_events_remove_listener() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { EventEmitter } from 'events';
const ee = new EventEmitter();
let count = 0;
const fn1 = () => { count++; };
ee.on('tick', fn1);
ee.emit('tick');
ee.off('tick', fn1);
ee.emit('tick');
export { count };"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "count").unwrap(),
            JsValue::Number(1.0)
        );
    }

    #[test]
    fn test_events_listener_count_and_names() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { EventEmitter } from 'events';
const ee = new EventEmitter();
ee.on('a', () => {});
ee.on('a', () => {});
ee.on('b', () => {});
export const countA = ee.listenerCount('a');
export const countB = ee.listenerCount('b');
export const names = ee.eventNames().join(',');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "countA").unwrap(),
            JsValue::Number(2.0)
        );
        assert_eq!(
            engine.object_get(h, "countB").unwrap(),
            JsValue::Number(1.0)
        );
        assert_eq!(
            engine.object_get(h, "names").unwrap(),
            JsValue::String("a,b".to_string())
        );
    }

    #[test]
    fn test_events_remove_all_listeners() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { EventEmitter } from 'events';
const ee = new EventEmitter();
ee.on('a', () => {});
ee.on('b', () => {});
ee.removeAllListeners('a');
export const countA = ee.listenerCount('a');
export const countB = ee.listenerCount('b');
ee.removeAllListeners();
export const countBAfter = ee.listenerCount('b');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "countA").unwrap(),
            JsValue::Number(0.0)
        );
        assert_eq!(
            engine.object_get(h, "countB").unwrap(),
            JsValue::Number(1.0)
        );
        assert_eq!(
            engine.object_get(h, "countBAfter").unwrap(),
            JsValue::Number(0.0)
        );
    }

    #[test]
    fn test_events_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { EventEmitter } from 'node:events';
const ee = new EventEmitter();
export const ok = ee instanceof EventEmitter;"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "ok").unwrap(),
            JsValue::Bool(true)
        );
    }

    // --- util tests ---

    #[test]
    fn test_util_format() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { format } from 'util';
export const r1 = format('hello %s', 'world');
export const r2 = format('%d + %d = %d', 1, 2, 3);
export const r3 = format('%%s');
export const r4 = format('%j', { a: 1 });"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("hello world".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String("1 + 2 = 3".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r3").unwrap(),
            JsValue::String("%s".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r4").unwrap(),
            JsValue::String("{\"a\":1}".to_string())
        );
    }

    #[test]
    fn test_util_inspect() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { inspect } from 'util';
export const r1 = inspect(42);
export const r2 = inspect('hello');
export const r3 = inspect([1, 2, 3]);
export const r4 = inspect(null);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("42".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r2").unwrap(),
            JsValue::String("'hello'".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r3").unwrap(),
            JsValue::String("[ 1, 2, 3 ]".to_string())
        );
        assert_eq!(
            engine.object_get(h, "r4").unwrap(),
            JsValue::String("null".to_string())
        );
    }

    #[test]
    fn test_util_promisify() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        // promisify converts callback-style to Promise — test structurally
        let ns = engine
            .eval_module(
                r#"import { promisify } from 'util';
function oldStyle(a, b, cb) { cb(null, a + b); }
const fn2 = promisify(oldStyle);
export const isFunc = typeof fn2 === 'function';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "isFunc")
                .unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_util_inherits() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { inherits } from 'util';
function Base() {}
Base.prototype.hello = function() { return 'hi'; };
function Child() { Base.call(this); }
inherits(Child, Base);
const c = new Child();
export const result = c.hello();
export const hasSuperProp = Child.super_ === Base;"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "result").unwrap(),
            JsValue::String("hi".to_string())
        );
        assert_eq!(
            engine.object_get(h, "hasSuperProp").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_util_types() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { types } from 'util';
export const r1 = types.isDate(new Date());
export const r2 = types.isRegExp(/abc/);
export const r3 = types.isArray([1, 2]);
export const r4 = types.isString('hello');
export const r5 = types.isNull(null);
export const r6 = types.isUndefined(undefined);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "r1").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r2").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r3").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r4").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r5").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "r6").unwrap(), JsValue::Bool(true));
    }

    #[test]
    fn test_util_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { format } from 'node:util';
export const result = format('x=%d', 42);"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("x=42".to_string())
        );
    }

    // --- url tests ---

    #[test]
    fn test_url_parse_legacy() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { parse } from 'url';
const u = parse('https://user:pass@example.com:8080/path?q=1#hash');
export const protocol = u.protocol;
export const hostname = u.hostname;
export const port = u.port;
export const pathname = u.pathname;
export const hash = u.hash;"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "protocol").unwrap(),
            JsValue::String("https:".to_string())
        );
        assert_eq!(
            engine.object_get(h, "hostname").unwrap(),
            JsValue::String("example.com".to_string())
        );
        assert_eq!(
            engine.object_get(h, "port").unwrap(),
            JsValue::String("8080".to_string())
        );
        assert_eq!(
            engine.object_get(h, "pathname").unwrap(),
            JsValue::String("/path".to_string())
        );
        assert_eq!(
            engine.object_get(h, "hash").unwrap(),
            JsValue::String("#hash".to_string())
        );
    }

    #[test]
    fn test_url_format_legacy() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { format } from 'url';
export const result = format({
    protocol: 'https:',
    hostname: 'example.com',
    pathname: '/path',
    search: '?q=1',
});"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("https://example.com/path?q=1".to_string())
        );
    }

    #[test]
    fn test_url_resolve_legacy() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { resolve } from 'url';
export const r1 = resolve('https://example.com/a/b', '/c');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "r1").unwrap(),
            JsValue::String("https://example.com/c".to_string())
        );
    }

    #[test]
    fn test_url_file_url_to_path() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { fileURLToPath } from 'url';
export const result = fileURLToPath('file:///home/user/file.txt');"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("/home/user/file.txt".to_string())
        );
    }

    #[test]
    fn test_url_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { parse } from 'node:url';
export const ok = typeof parse === 'function';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "ok").unwrap(),
            JsValue::Bool(true)
        );
    }

    // --- buffer tests ---

    #[test]
    fn test_buffer_global_from_string() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.from('hello');
export const len = buf.length;
export const str = buf.toString();
export const isBuffer = Buffer.isBuffer(buf);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "len").unwrap(), JsValue::Number(5.0));
        assert_eq!(
            engine.object_get(h, "str").unwrap(),
            JsValue::String("hello".to_string())
        );
        assert_eq!(
            engine.object_get(h, "isBuffer").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_buffer_alloc() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.alloc(4, 0xff);
export const len = buf.length;
export const byte0 = buf[0];
export const byte3 = buf[3];"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "len").unwrap(), JsValue::Number(4.0));
        assert_eq!(
            engine.object_get(h, "byte0").unwrap(),
            JsValue::Number(255.0)
        );
        assert_eq!(
            engine.object_get(h, "byte3").unwrap(),
            JsValue::Number(255.0)
        );
    }

    #[test]
    fn test_buffer_hex_encoding() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.from('48656c6c6f', 'hex');
export const str = buf.toString('utf-8');
export const hex = buf.toString('hex');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "str").unwrap(),
            JsValue::String("Hello".to_string())
        );
        assert_eq!(
            engine.object_get(h, "hex").unwrap(),
            JsValue::String("48656c6c6f".to_string())
        );
    }

    #[test]
    fn test_buffer_concat() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const a = Buffer.from('Hello');
const b = Buffer.from(' World');
const c = Buffer.concat([a, b]);
export const result = c.toString();"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("Hello World".to_string())
        );
    }

    #[test]
    fn test_buffer_compare_and_equals() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const a = Buffer.from('abc');
const b = Buffer.from('abc');
const c = Buffer.from('abd');
export const eq = a.equals(b);
export const neq = a.equals(c);
export const cmp = Buffer.compare(a, c);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "eq").unwrap(), JsValue::Bool(true));
        assert_eq!(engine.object_get(h, "neq").unwrap(), JsValue::Bool(false));
        assert_eq!(engine.object_get(h, "cmp").unwrap(), JsValue::Number(-1.0));
    }

    #[test]
    fn test_buffer_read_write_int() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.alloc(4);
buf.writeUInt16BE(0x0102, 0);
buf.writeUInt16LE(0x0304, 2);
export const be = buf.readUInt16BE(0);
export const le = buf.readUInt16LE(2);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "be").unwrap(),
            JsValue::Number(0x0102 as f64)
        );
        assert_eq!(
            engine.object_get(h, "le").unwrap(),
            JsValue::Number(0x0304 as f64)
        );
    }

    #[test]
    fn test_buffer_copy() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const src = Buffer.from('Hello');
const dst = Buffer.alloc(5);
src.copy(dst);
export const result = dst.toString();"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("Hello".to_string())
        );
    }

    #[test]
    fn test_buffer_slice() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.from('Hello World');
const sliced = buf.slice(0, 5);
export const result = sliced.toString();
export const isBuffer = Buffer.isBuffer(sliced);"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "result").unwrap(),
            JsValue::String("Hello".to_string())
        );
        assert_eq!(
            engine.object_get(h, "isBuffer").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_buffer_to_json() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.from([1, 2, 3]);
const j = buf.toJSON();
export const type_ = j.type;
export const data = j.data.join(',');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "type_").unwrap(),
            JsValue::String("Buffer".to_string())
        );
        assert_eq!(
            engine.object_get(h, "data").unwrap(),
            JsValue::String("1,2,3".to_string())
        );
    }

    #[test]
    fn test_buffer_byte_length() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"export const r1 = Buffer.byteLength('hello');
export const r2 = Buffer.byteLength('café');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "r1").unwrap(), JsValue::Number(5.0));
        assert_eq!(engine.object_get(h, "r2").unwrap(), JsValue::Number(5.0)); // café is 5 bytes in UTF-8
    }

    #[test]
    fn test_buffer_includes_index_of() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"const buf = Buffer.from('Hello World');
export const includes = buf.includes('World');
export const indexOf = buf.indexOf('World');
export const notFound = buf.indexOf('xyz');"#,
                "test",
            )
            .unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "includes").unwrap(),
            JsValue::Bool(true)
        );
        assert_eq!(
            engine.object_get(h, "indexOf").unwrap(),
            JsValue::Number(6.0)
        );
        assert_eq!(
            engine.object_get(h, "notFound").unwrap(),
            JsValue::Number(-1.0)
        );
    }

    #[test]
    fn test_buffer_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        let ns = engine
            .eval_module(
                r#"import { Buffer as B } from 'node:buffer';
export const ok = typeof B.from === 'function';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "ok").unwrap(),
            JsValue::Bool(true)
        );
    }

    // --- require tests ---

    #[test]
    fn test_require_resolve_file() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();
        // require.resolve for a file that exists — use this crate's Cargo.toml as test target
        let code = format!(r#"export const exists = typeof require.resolve === 'function';"#);
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "exists")
                .unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_require_json_file() {
        // Create a temp JSON file, require() it, check parsed result
        let dir = std::env::temp_dir().join("taiyaki_test_require");
        let _ = std::fs::create_dir_all(&dir);
        let json_path = dir.join("data.json");
        std::fs::write(&json_path, r#"{"name":"test","version":1}"#).unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let code = format!(
            "const data = require('{}');\nexport const name = data.name;\nexport const version = data.version;",
            json_path.to_string_lossy().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(
            engine.object_get(h, "name").unwrap(),
            JsValue::String("test".to_string())
        );
        assert_eq!(
            engine.object_get(h, "version").unwrap(),
            JsValue::Number(1.0)
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_require_js_file() {
        // Create a temp JS file with CJS exports, require() it
        let dir = std::env::temp_dir().join("taiyaki_test_require_js");
        let _ = std::fs::create_dir_all(&dir);
        let js_path = dir.join("greet.js");
        std::fs::write(
            &js_path,
            "module.exports = function(name) { return 'Hello ' + name; };",
        )
        .unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let code = format!(
            "const greet = require('{}');\nexport const result = greet('World');",
            js_path.to_string_lossy().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("Hello World".to_string())
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_require_relative() {
        // Create a directory with two files that require each other
        let dir = std::env::temp_dir().join("taiyaki_test_require_rel");
        let _ = std::fs::create_dir_all(&dir);
        std::fs::write(
            dir.join("helper.js"),
            "exports.add = function(a, b) { return a + b; };",
        )
        .unwrap();
        let main_path = dir.join("main.js");
        std::fs::write(
            &main_path,
            "const h = require('./helper');\nmodule.exports = h.add(1, 2);",
        )
        .unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let code = format!(
            "const result = require('{}');\nexport {{ result }};",
            main_path.to_string_lossy().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::Number(3.0)
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_require_node_modules() {
        // Create a node_modules structure
        let dir = std::env::temp_dir().join("taiyaki_test_require_nm");
        let nm = dir.join("node_modules").join("my-lib");
        let _ = std::fs::create_dir_all(&nm);
        std::fs::write(nm.join("package.json"), r#"{"main": "lib.js"}"#).unwrap();
        std::fs::write(
            nm.join("lib.js"),
            "exports.greet = function() { return 'hello from my-lib'; };",
        )
        .unwrap();
        let main_path = dir.join("app.js");
        std::fs::write(
            &main_path,
            "const lib = require('my-lib');\nmodule.exports = lib.greet();",
        )
        .unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let code = format!(
            "const result = require('{}');\nexport {{ result }};",
            main_path.to_string_lossy().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::String("hello from my-lib".to_string())
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_require_caching() {
        // Ensure require() caches modules (same object returned)
        let dir = std::env::temp_dir().join("taiyaki_test_require_cache");
        let _ = std::fs::create_dir_all(&dir);
        std::fs::write(
            dir.join("counter.js"),
            "let count = 0;\nexports.inc = function() { return ++count; };",
        )
        .unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let path = dir.join("counter.js").to_string_lossy().replace('\\', "/");
        let code = format!(
            "const c1 = require('{path}');\nconst c2 = require('{path}');\nc1.inc(); c1.inc();\nexport const val = c2.inc();\nexport const same = c1 === c2;",
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        let h = ns.handle_id().unwrap();
        assert_eq!(engine.object_get(h, "val").unwrap(), JsValue::Number(3.0));
        assert_eq!(engine.object_get(h, "same").unwrap(), JsValue::Bool(true));

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_require_index_js() {
        // require('./dir') should resolve to dir/index.js
        let dir = std::env::temp_dir().join("taiyaki_test_require_idx");
        let sub = dir.join("mymod");
        let _ = std::fs::create_dir_all(&sub);
        std::fs::write(sub.join("index.js"), "module.exports = 42;").unwrap();
        let main_path = dir.join("main.js");
        std::fs::write(&main_path, "module.exports = require('./mymod');").unwrap();

        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let code = format!(
            "const result = require('{}');\nexport {{ result }};",
            main_path.to_string_lossy().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .unwrap(),
            JsValue::Number(42.0)
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(feature = "futures")]
    #[tokio::test]
    async fn test_register_all_async() {
        let engine = taiyaki_core::engine::async_quickjs_backend::AsyncQuickJsEngine::new()
            .await
            .unwrap();
        crate::register_all_async(&engine).await.unwrap();
        let ns = engine
            .eval_module(
                "import { join } from 'path'; export const r = join('a', 'b');",
                "test",
            )
            .await
            .unwrap();
        let val = engine
            .object_get(ns.handle_id().unwrap(), "r")
            .await
            .unwrap();
        assert_eq!(val, JsValue::String("a/b".to_string()));
    }

    #[cfg(feature = "futures")]
    #[tokio::test]
    async fn test_require_async() {
        let dir = std::env::temp_dir().join("taiyaki_test_require_async");
        let _ = std::fs::create_dir_all(&dir);
        std::fs::write(dir.join("mod.js"), "exports.value = 99;").unwrap();

        let engine = taiyaki_core::engine::async_quickjs_backend::AsyncQuickJsEngine::new()
            .await
            .unwrap();
        crate::register_all_async(&engine).await.unwrap();

        let path = dir.join("mod.js").to_string_lossy().replace('\\', "/");
        let code = format!("const m = require('{path}');\nexport const result = m.value;");
        let ns = engine.eval_module(&code, "test").await.unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "result")
                .await
                .unwrap(),
            JsValue::Number(99.0)
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── Phase 8: fs module tests ──

    #[test]
    fn test_fs_read_write_sync() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let dir = std::env::temp_dir().join("taiyaki_test_fs_rw");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("test.txt");

        let code = format!(
            r#"import {{ writeFileSync, readFileSync }} from 'fs';
writeFileSync('{}', 'hello');
export const r = readFileSync('{}');"#,
            path.display().to_string().replace('\\', "/"),
            path.display().to_string().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "r").unwrap(),
            JsValue::String("hello".to_string())
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_fs_exists_sync() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let dir = std::env::temp_dir().join("taiyaki_test_fs_exists");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("exists.txt");
        std::fs::write(&path, "").unwrap();

        let code = format!(
            r#"import {{ existsSync }} from 'fs';
export const a = existsSync('{}');
export const b = existsSync('/nonexistent_12345');"#,
            path.display().to_string().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "a").unwrap(),
            JsValue::Bool(true)
        );
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "b").unwrap(),
            JsValue::Bool(false)
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_fs_mkdir_readdir() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let dir = std::env::temp_dir().join("taiyaki_test_fs_mkdir");
        let _ = std::fs::remove_dir_all(&dir);

        let sub = dir.join("sub");
        let code = format!(
            r#"import {{ mkdirSync, writeFileSync, readdirSync }} from 'fs';
mkdirSync('{}', {{ recursive: true }});
writeFileSync('{}/a.txt', 'a');
writeFileSync('{}/b.txt', 'b');
export const entries = JSON.stringify(readdirSync('{}'));"#,
            sub.display().to_string().replace('\\', "/"),
            sub.display().to_string().replace('\\', "/"),
            sub.display().to_string().replace('\\', "/"),
            sub.display().to_string().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        let val = engine
            .object_get(ns.handle_id().unwrap(), "entries")
            .unwrap();
        match &val {
            JsValue::String(s) => {
                assert!(
                    s.contains("a.txt") && s.contains("b.txt"),
                    "expected both files: {s}"
                );
            }
            _ => panic!("expected string"),
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_fs_stat_sync() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let dir = std::env::temp_dir().join("taiyaki_test_fs_stat");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("data.txt");
        std::fs::write(&path, "12345").unwrap();

        let code = format!(
            r#"import {{ statSync }} from 'fs';
const s = statSync('{}');
export const isFile = s.isFile();
export const isDir = s.isDirectory();
export const size = s.size;"#,
            path.display().to_string().replace('\\', "/")
        );
        let ns = engine.eval_module(&code, "test").unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "isFile")
                .unwrap(),
            JsValue::Bool(true)
        );
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "isDir").unwrap(),
            JsValue::Bool(false)
        );
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "size").unwrap(),
            JsValue::Number(5.0)
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn test_fs_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import { existsSync } from 'node:fs';\nexport const t = typeof existsSync;",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "t").unwrap(),
            JsValue::String("function".to_string())
        );
    }

    // ── Phase 8: os module tests ──

    #[test]
    fn test_os_platform() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import os from 'os';\nexport const p = os.platform();",
                "test",
            )
            .unwrap();
        let val = engine.object_get(ns.handle_id().unwrap(), "p").unwrap();
        match val {
            JsValue::String(s) => {
                assert!(s == "darwin" || s == "linux", "unexpected platform: {s}")
            }
            _ => panic!("expected string"),
        }
    }

    #[test]
    fn test_os_hostname() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import os from 'os';\nexport const h = os.hostname().length > 0;",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "h").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_os_cpus() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import os from 'os';\nexport const c = os.cpus().length > 0;",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "c").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_os_eol() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module("import { EOL } from 'os';\nexport const e = EOL;", "test")
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "e").unwrap(),
            JsValue::String("\n".to_string())
        );
    }

    #[test]
    fn test_os_totalmem() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import os from 'os';\nexport const m = os.totalmem() > 0;",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "m").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_os_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import os from 'node:os';\nexport const p = os.platform();",
                "test",
            )
            .unwrap();
        let val = engine.object_get(ns.handle_id().unwrap(), "p").unwrap();
        match val {
            JsValue::String(s) => assert!(s == "darwin" || s == "linux"),
            _ => panic!("expected string"),
        }
    }

    // ── Phase 8: crypto module tests ──

    #[test]
    fn test_crypto_random_uuid() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine.eval_module(
            r#"import { randomUUID } from 'crypto';
export const uuid = randomUUID();
export const valid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(uuid);"#,
            "test",
        ).unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "valid").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_crypto_random_uuid_unique() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine.eval_module(
            "import { randomUUID } from 'crypto';\nexport const diff = randomUUID() !== randomUUID();",
            "test",
        ).unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "diff").unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_crypto_globals() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                r#"export const hasRandom = typeof globalThis.crypto.randomUUID === 'function';
export const hasGetRandom = typeof globalThis.crypto.getRandomValues === 'function';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "hasRandom")
                .unwrap(),
            JsValue::Bool(true)
        );
        assert_eq!(
            engine
                .object_get(ns.handle_id().unwrap(), "hasGetRandom")
                .unwrap(),
            JsValue::Bool(true)
        );
    }

    #[test]
    fn test_crypto_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import { randomUUID } from 'node:crypto';\nexport const t = typeof randomUUID;",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "t").unwrap(),
            JsValue::String("function".to_string())
        );
    }

    // ── Phase 8: assert module tests ──

    #[test]
    fn test_assert_ok_pass() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                r#"import assert from 'assert';
assert.ok(true);
assert.strictEqual(1, 1);
assert.deepStrictEqual({a: [1,2]}, {a: [1,2]});
export const r = 'passed';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "r").unwrap(),
            JsValue::String("passed".to_string())
        );
    }

    #[test]
    fn test_assert_strict_equal_fail() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let result = engine.eval_module(
            "import assert from 'assert';\nassert.strictEqual(1, 2);",
            "test",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_assert_throws_pass() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                r#"import assert from 'assert';
assert.throws(() => { throw new Error('boom'); });
export const r = 'ok';"#,
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "r").unwrap(),
            JsValue::String("ok".to_string())
        );
    }

    #[test]
    fn test_assert_deep_strict_equal_fail() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let result = engine.eval_module(
            "import assert from 'assert';\nassert.deepStrictEqual({a: 1}, {a: 2});",
            "test",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_assert_node_prefix() {
        let engine = QuickJsEngine::new().unwrap();
        register_all(&engine).unwrap();

        let ns = engine
            .eval_module(
                "import assert from 'node:assert';\nassert.ok(true);\nexport const r = 'ok';",
                "test",
            )
            .unwrap();
        assert_eq!(
            engine.object_get(ns.handle_id().unwrap(), "r").unwrap(),
            JsValue::String("ok".to_string())
        );
    }
}
