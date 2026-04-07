use std::cell::RefCell;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use rquickjs::loader::{Loader, Resolver};
use rquickjs::module::Declared;
use rquickjs::{Ctx, Module, Result};

/// Resolver that checks the shared module source store.
pub(crate) struct SharedResolver {
    pub(crate) modules: Rc<RefCell<HashMap<String, String>>>,
}

impl Resolver for SharedResolver {
    fn resolve<'js>(&mut self, _ctx: &Ctx<'js>, base: &str, name: &str) -> Result<String> {
        let store = self.modules.borrow();
        if store.contains_key(name) {
            Ok(name.to_string())
        } else {
            // Return Resolving error (not Loading) so the next resolver in the chain is tried
            Err(rquickjs::Error::new_resolving(base, name))
        }
    }
}

/// Loader that reads (clones) source from the shared store.
/// Unlike rquickjs BuiltinLoader, this does NOT remove the module on load,
/// so the same module can be imported multiple times.
pub(crate) struct SharedLoader {
    pub(crate) modules: Rc<RefCell<HashMap<String, String>>>,
}

impl Loader for SharedLoader {
    fn load<'js>(&mut self, ctx: &Ctx<'js>, name: &str) -> Result<Module<'js, Declared>> {
        let store = self.modules.borrow();
        let source = store
            .get(name)
            .ok_or_else(|| rquickjs::Error::new_loading(name))?
            .clone();
        drop(store);
        Module::declare(ctx.clone(), name, source)
    }
}

// ---------------------------------------------------------------------------
// Node-style ESM resolver (bare specifiers → node_modules)
// ---------------------------------------------------------------------------

/// Resolver that handles bare specifiers via node_modules and relative paths.
pub(crate) struct NodeModuleResolver;

impl Resolver for NodeModuleResolver {
    fn resolve<'js>(&mut self, _ctx: &Ctx<'js>, base: &str, name: &str) -> Result<String> {
        // Determine the directory of the importing module
        let base_dir = if base.is_empty() || base == "." || base == "<input>" || base == "<eval>" {
            std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
        } else {
            let p = Path::new(base);
            if p.is_file() {
                p.parent().unwrap_or(Path::new(".")).to_path_buf()
            } else {
                p.to_path_buf()
            }
        };

        // 1. Relative or absolute path
        if name.starts_with("./") || name.starts_with("../") || name.starts_with('/') {
            let candidate = base_dir.join(name);
            if let Some(resolved) = resolve_file_or_dir(&candidate) {
                // Canonicalize to avoid infinite loops with ../foo -> ./bar/../foo cycles
                return Ok(canonicalize_or_clean(&resolved));
            }
            return Err(rquickjs::Error::new_loading(name));
        }

        // 2. Bare specifier — walk up node_modules
        let mut dir = base_dir;
        loop {
            let nm = dir.join("node_modules").join(name);
            if let Some(resolved) = resolve_file_or_dir(&nm) {
                return Ok(canonicalize_or_clean(&resolved));
            }
            if let Some(resolved) = resolve_package_esm(&nm) {
                return Ok(canonicalize_or_clean(&resolved));
            }
            if !dir.pop() {
                break;
            }
        }

        Err(rquickjs::Error::new_loading(name))
    }
}

/// Canonicalize a path to avoid cycles (e.g. ./utils/../request.js → /abs/request.js).
fn canonicalize_or_clean(path: &str) -> String {
    std::fs::canonicalize(path)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| path.to_string())
}

/// Try to resolve a path as a file (with extension fallbacks) or directory (index.js).
fn resolve_file_or_dir(candidate: &Path) -> Option<String> {
    if let Ok(meta) = candidate.metadata() {
        if meta.is_file() {
            return Some(candidate.to_string_lossy().into_owned());
        }
        if meta.is_dir() {
            return resolve_index(candidate);
        }
    }
    for ext in &["js", "mjs", "ts"] {
        let with_ext = candidate.with_extension(ext);
        if with_ext.is_file() {
            return Some(with_ext.to_string_lossy().into_owned());
        }
    }
    None
}

fn resolve_index(dir: &Path) -> Option<String> {
    for name in &["index.js", "index.mjs", "index.ts"] {
        let index = dir.join(name);
        if index.is_file() {
            return Some(index.to_string_lossy().into_owned());
        }
    }
    None
}

/// Resolve via package.json — prefers "module" (ESM) over "main" (CJS).
/// Also checks "exports" → "." → "import" for conditional exports.
fn resolve_package_esm(dir: &Path) -> Option<String> {
    let pkg = dir.join("package.json");
    let content = std::fs::read_to_string(&pkg).ok()?;

    // Try "exports" → "." → "import" (conditional exports, most modern packages)
    if let Some(entry) = extract_exports_import(&content) {
        let entry_path = dir.join(entry);
        if let Some(resolved) = resolve_file_or_dir(&entry_path) {
            return Some(resolved);
        }
    }

    // Try "module" field (ESM entry point)
    if let Some(entry) = extract_json_string_field(&content, "module") {
        let entry_path = dir.join(entry);
        if let Some(resolved) = resolve_file_or_dir(&entry_path) {
            return Some(resolved);
        }
    }

    // Fallback to "main"
    if let Some(entry) = extract_json_string_field(&content, "main") {
        let entry_path = dir.join(entry);
        return resolve_file_or_dir(&entry_path);
    }

    // Fallback to index.js
    resolve_index(dir)
}

/// Extract a simple string field from JSON without a full parser.
/// Looks for `"field": "value"` pattern.
fn extract_json_string_field<'a>(json: &'a str, field: &str) -> Option<&'a str> {
    let pattern = format!("\"{}\"", field);
    let idx = json.find(&pattern)?;
    let after_key = &json[idx + pattern.len()..];
    // Skip whitespace and colon
    let after_colon = after_key.trim_start().strip_prefix(':')?;
    let after_colon = after_colon.trim_start();
    // Extract string value
    let after_quote = after_colon.strip_prefix('"')?;
    let end = after_quote.find('"')?;
    Some(&after_quote[..end])
}

/// Extract "exports" → "." → "import" from package.json.
/// Handles the common pattern: `"exports": { ".": { "import": "./dist/index.js" } }`
fn extract_exports_import(json: &str) -> Option<&str> {
    // Find "exports"
    let exports_idx = json.find("\"exports\"")?;
    let after = &json[exports_idx..];

    // Find the "." entry within exports
    let dot_idx = after.find("\".\"")? ;
    let after_dot = &after[dot_idx..];

    // Find "import" within the "." entry
    let import_idx = after_dot.find("\"import\"")?;
    let after_import_key = &after_dot[import_idx + 8..]; // len("\"import\"") = 8

    // Extract value
    let after_colon = after_import_key.trim_start().strip_prefix(':')?;
    let after_colon = after_colon.trim_start();
    let after_quote = after_colon.strip_prefix('"')?;
    let end = after_quote.find('"')?;
    Some(&after_quote[..end])
}
