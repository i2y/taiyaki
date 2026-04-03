use std::path::{Path, PathBuf};

use taiyaki_core::engine::{EngineError, HostCallback, JsValue};

use super::require_string_arg;

const REQUIRE_JS: &str = include_str!("../js/require.js");

/// Built-in module names that require() should resolve without filesystem lookup.
const BUILTIN_NAMES: &[&str] = &[
    "path",
    "events",
    "util",
    "url",
    "buffer",
    "fs",
    "os",
    "assert",
    "crypto",
    "stream",
    "child_process",
    "zlib",
    "dns",
    "net",
    "tls",
    "http",
];

pub fn register_globals(engine: &dyn taiyaki_core::engine::JsEngine) -> Result<(), EngineError> {
    engine.eval(REQUIRE_JS)?;
    Ok(())
}

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__require_resolve", Box::new(require_resolve)),
        ("__require_read_file", Box::new(require_read_file)),
        ("__require_is_file", Box::new(require_is_file)),
    ]
}

pub async fn register_globals_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    engine.eval(REQUIRE_JS).await?;
    Ok(())
}

/// Node.js-style module resolution algorithm.
///
/// 1. Built-in names (path, events, etc.) → return as-is
/// 2. Relative/absolute paths → try extensions (.js, .json, /index.js)
/// 3. Bare specifiers → walk up node_modules
fn require_resolve(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let specifier = require_string_arg(args, 0, "__require_resolve")?;
    let from_dir = require_string_arg(args, 1, "__require_resolve")?;

    // Strip node: prefix
    let name = specifier.strip_prefix("node:").unwrap_or(specifier);

    // 1. Built-in module
    if BUILTIN_NAMES.contains(&name) {
        return Ok(JsValue::String(name.to_string()));
    }

    // 2. Relative or absolute path
    if specifier.starts_with("./") || specifier.starts_with("../") || specifier.starts_with('/') {
        let base = Path::new(from_dir);
        let candidate = base.join(specifier);
        if let Some(resolved) = resolve_file_or_dir(&candidate) {
            return Ok(JsValue::String(resolved));
        }
        return Err(EngineError::JsException {
            message: format!("Cannot find module '{specifier}' from '{from_dir}'"),
        });
    }

    // 3. Bare specifier — walk node_modules
    let mut dir = PathBuf::from(from_dir);
    loop {
        let nm = dir.join("node_modules").join(specifier);
        if let Some(resolved) = resolve_file_or_dir(&nm) {
            return Ok(JsValue::String(resolved));
        }
        if let Some(resolved) = resolve_package(&nm) {
            return Ok(JsValue::String(resolved));
        }
        if !dir.pop() {
            break;
        }
    }

    Err(EngineError::JsException {
        message: format!("Cannot find module '{specifier}' from '{from_dir}'"),
    })
}

/// Try to resolve a path as a file (with extension fallbacks) or directory (index.js).
/// Uses a single metadata() call to determine file type, avoiding redundant syscalls.
fn resolve_file_or_dir(candidate: &Path) -> Option<String> {
    // Exact match
    if let Ok(meta) = candidate.metadata() {
        if meta.is_file() {
            return Some(candidate.to_string_lossy().into_owned());
        }
        if meta.is_dir() {
            return resolve_index(candidate);
        }
    }

    // Try extensions
    for ext in &["js", "ts", "json"] {
        let with_ext = candidate.with_extension(ext);
        if with_ext.is_file() {
            return Some(with_ext.to_string_lossy().into_owned());
        }
    }

    None
}

fn resolve_index(dir: &Path) -> Option<String> {
    for name in &["index.js", "index.ts", "index.json"] {
        let index = dir.join(name);
        if index.is_file() {
            return Some(index.to_string_lossy().into_owned());
        }
    }
    None
}

/// Resolve via package.json "main" field.
fn resolve_package(dir: &Path) -> Option<String> {
    let pkg = dir.join("package.json");
    let content = std::fs::read_to_string(&pkg).ok()?;
    let json: serde_json::Value = serde_json::from_str(&content).ok()?;
    let main = json.get("main")?.as_str()?;
    let main_path = dir.join(main);
    resolve_file_or_dir(&main_path)
}

fn require_read_file(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "__require_read_file")?;
    match std::fs::read_to_string(path) {
        Ok(content) => Ok(JsValue::String(content)),
        Err(e) => Err(EngineError::JsException {
            message: format!("Cannot read module '{path}': {e}"),
        }),
    }
}

fn require_is_file(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "__require_is_file")?;
    Ok(JsValue::Bool(Path::new(path).is_file()))
}
