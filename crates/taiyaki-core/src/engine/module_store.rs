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
/// Caches resolved paths to avoid redundant filesystem operations.
pub(crate) struct NodeModuleResolver {
    cache: RefCell<HashMap<(String, String), String>>,
}

impl NodeModuleResolver {
    pub(crate) fn new() -> Self {
        Self {
            cache: RefCell::new(HashMap::new()),
        }
    }
}

impl Resolver for NodeModuleResolver {
    fn resolve<'js>(&mut self, _ctx: &Ctx<'js>, base: &str, name: &str) -> Result<String> {
        let cache_key = (base.to_string(), name.to_string());
        if let Some(cached) = self.cache.borrow().get(&cache_key) {
            return Ok(cached.clone());
        }

        let base_dir = if base.is_empty() || base == "." || base == "<input>" || base == "<eval>" {
            std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
        } else {
            // base is always a resolved file path from a previous resolution
            let p = Path::new(base);
            p.parent().unwrap_or(Path::new(".")).to_path_buf()
        };

        let resolved = if name.starts_with("./") || name.starts_with("../") || name.starts_with('/')
        {
            let candidate = base_dir.join(name);
            resolve_file_or_dir(&candidate)
                .ok_or_else(|| rquickjs::Error::new_resolving(base, name))
        } else {
            // Bare specifier — walk up node_modules
            resolve_bare_specifier(&base_dir, name)
                .ok_or_else(|| rquickjs::Error::new_resolving(base, name))
        }?;

        // Canonicalize to prevent infinite cycles from circular relative imports
        let canonical = std::fs::canonicalize(&resolved)
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or(resolved);

        self.cache
            .borrow_mut()
            .insert(cache_key, canonical.clone());
        Ok(canonical)
    }
}

fn resolve_bare_specifier(start_dir: &Path, name: &str) -> Option<String> {
    let mut dir = start_dir.to_path_buf();
    loop {
        let nm = dir.join("node_modules").join(name);
        if let Some(resolved) = resolve_package_esm(&nm) {
            return Some(resolved);
        }
        // Also try as a direct file (rare but valid)
        if let Some(resolved) = resolve_file_or_dir(&nm) {
            return Some(resolved);
        }
        if !dir.pop() {
            break;
        }
    }
    None
}

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

/// Resolve via package.json — prefers exports.".".import > "module" > "main".
fn resolve_package_esm(dir: &Path) -> Option<String> {
    let pkg = dir.join("package.json");
    let content = std::fs::read_to_string(&pkg).ok()?;
    let json: serde_json::Value = serde_json::from_str(&content).ok()?;

    // "exports" → "." → "import" (conditional exports)
    if let Some(entry) = json
        .get("exports")
        .and_then(|e| e.get("."))
        .and_then(|dot| {
            // Handle both { ".": { "import": "..." } } and { ".": "..." }
            dot.get("import")
                .and_then(|v| v.as_str())
                .or_else(|| dot.as_str())
        })
    {
        let entry_path = dir.join(entry);
        if let Some(resolved) = resolve_file_or_dir(&entry_path) {
            return Some(resolved);
        }
    }

    // "exports" as a direct string: "exports": "./dist/index.js"
    if let Some(entry) = json.get("exports").and_then(|v| v.as_str()) {
        let entry_path = dir.join(entry);
        if let Some(resolved) = resolve_file_or_dir(&entry_path) {
            return Some(resolved);
        }
    }

    // "module" field (ESM entry)
    if let Some(entry) = json.get("module").and_then(|v| v.as_str()) {
        let entry_path = dir.join(entry);
        if let Some(resolved) = resolve_file_or_dir(&entry_path) {
            return Some(resolved);
        }
    }

    // "main" fallback
    if let Some(entry) = json.get("main").and_then(|v| v.as_str()) {
        let entry_path = dir.join(entry);
        return resolve_file_or_dir(&entry_path);
    }

    resolve_index(dir)
}
