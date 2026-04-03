use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use taiyaki_core::transpiler;

pub fn build(
    entry: &Path,
    outfile: &Path,
    _minify: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if !entry.exists() {
        return Err(format!("Entry point not found: {}", entry.display()).into());
    }

    let entry = entry.canonicalize()?;
    let base_dir = entry.parent().unwrap_or(Path::new("."));

    let mut modules: Vec<(String, String)> = Vec::new(); // (id, code)
    let mut visited: HashSet<PathBuf> = HashSet::new();
    let mut module_ids: HashMap<PathBuf, String> = HashMap::new();
    let mut id_counter = 0;

    // Recursively resolve and collect modules
    collect_module(
        &entry,
        base_dir,
        &mut modules,
        &mut visited,
        &mut module_ids,
        &mut id_counter,
    )?;

    // Generate bundle
    let mut bundle = String::new();
    bundle.push_str("(function() {\n");
    bundle.push_str("var __modules = {};\n");
    bundle.push_str("var __cache = {};\n");
    bundle.push_str("function __require(id) {\n");
    bundle.push_str("  if (__cache[id]) return __cache[id].exports;\n");
    bundle.push_str("  var module = { exports: {} };\n");
    bundle.push_str("  __cache[id] = module;\n");
    bundle.push_str("  __modules[id](module, module.exports, __require);\n");
    bundle.push_str("  return module.exports;\n");
    bundle.push_str("}\n");

    for (id, code) in &modules {
        bundle.push_str(&format!(
            "__modules[\"{id}\"] = function(module, exports, require) {{\n{code}\n}};\n"
        ));
    }

    // Run entry module
    let entry_id = module_ids.get(&entry).expect("entry module");
    bundle.push_str(&format!("__require(\"{entry_id}\");\n"));
    bundle.push_str("})();\n");

    // Write output
    if let Some(parent) = outfile.parent() {
        if !parent.exists() {
            std::fs::create_dir_all(parent)?;
        }
    }
    std::fs::write(outfile, &bundle)?;

    let size = bundle.len();
    let size_str = if size > 1024 * 1024 {
        format!("{:.1} MB", size as f64 / (1024.0 * 1024.0))
    } else if size > 1024 {
        format!("{:.1} KB", size as f64 / 1024.0)
    } else {
        format!("{size} B")
    };

    println!(
        "  {} → {} ({})",
        entry.file_name().unwrap_or_default().to_string_lossy(),
        outfile.display(),
        size_str
    );

    Ok(())
}

fn collect_module(
    file: &Path,
    base_dir: &Path,
    modules: &mut Vec<(String, String)>,
    visited: &mut HashSet<PathBuf>,
    module_ids: &mut HashMap<PathBuf, String>,
    id_counter: &mut usize,
) -> Result<(), Box<dyn std::error::Error>> {
    let canonical = file.canonicalize()?;
    if visited.contains(&canonical) {
        return Ok(());
    }
    visited.insert(canonical.clone());

    let id = format!("m{}", *id_counter);
    *id_counter += 1;
    module_ids.insert(canonical.clone(), id.clone());

    let source = std::fs::read_to_string(file)?;
    let ext = file.extension().and_then(|e| e.to_str()).unwrap_or("");

    // Transpile if needed
    let code = match ext {
        "tsx" | "jsx" => transpiler::transform_jsx(&source, &Default::default())?,
        "ts" | "mts" => transpiler::strip_types(&source)?,
        _ => source,
    };

    // Find imports and resolve them
    let dir = file.parent().unwrap_or(Path::new("."));
    let imports = extract_imports(&code);

    for import_path in &imports {
        if import_path.starts_with('.') {
            if let Some(resolved) = resolve_module(dir, import_path) {
                collect_module(
                    &resolved, base_dir, modules, visited, module_ids, id_counter,
                )?;
            }
        }
    }

    // Rewrite import/export to CJS
    let cjs = transpiler::transform_esm_to_cjs(&code)?;

    // Rewrite require('./foo') to require('m1') etc.
    let mut rewritten = cjs;
    for import_path in &imports {
        if import_path.starts_with('.') {
            if let Some(resolved) = resolve_module(dir, import_path) {
                let resolved = resolved.canonicalize().unwrap_or(resolved);
                if let Some(mid) = module_ids.get(&resolved) {
                    rewritten = rewritten.replace(
                        &format!("require(\"{import_path}\")"),
                        &format!("require(\"{mid}\")"),
                    );
                    rewritten = rewritten.replace(
                        &format!("require('{import_path}')"),
                        &format!("require(\"{mid}\")"),
                    );
                }
            }
        }
    }

    modules.push((id, rewritten));
    Ok(())
}

fn extract_imports(code: &str) -> Vec<String> {
    let mut imports = Vec::new();
    for line in code.lines() {
        let trimmed = line.trim();
        // import ... from 'xxx'
        if trimmed.starts_with("import ") {
            if let Some(path) = extract_string_after(trimmed, "from ") {
                imports.push(path);
            } else if let Some(path) = extract_import_string(trimmed) {
                imports.push(path);
            }
        }
        // export ... from 'xxx'
        if trimmed.starts_with("export ") && trimmed.contains(" from ") {
            if let Some(path) = extract_string_after(trimmed, "from ") {
                imports.push(path);
            }
        }
        // require('xxx')
        if let Some(pos) = trimmed.find("require(") {
            let rest = &trimmed[pos + 8..];
            if let Some(path) = extract_quoted(rest) {
                imports.push(path);
            }
        }
    }
    imports
}

fn extract_string_after(line: &str, keyword: &str) -> Option<String> {
    let pos = line.find(keyword)? + keyword.len();
    extract_quoted(&line[pos..])
}

fn extract_import_string(line: &str) -> Option<String> {
    // import 'xxx' or import "xxx"
    let trimmed = line.trim().strip_prefix("import ")?;
    extract_quoted(trimmed)
}

fn extract_quoted(s: &str) -> Option<String> {
    let s = s.trim();
    if s.starts_with('\'') || s.starts_with('"') {
        let quote = s.as_bytes()[0] as char;
        let end = s[1..].find(quote)?;
        Some(s[1..1 + end].to_string())
    } else {
        None
    }
}

fn resolve_module(dir: &Path, specifier: &str) -> Option<PathBuf> {
    let base = dir.join(specifier);

    // Try exact path
    if base.is_file() {
        return Some(base);
    }

    // Try with extensions
    for ext in &["js", "ts", "jsx", "tsx", "mjs", "mts"] {
        let with_ext = base.with_extension(ext);
        if with_ext.is_file() {
            return Some(with_ext);
        }
    }

    // Try as directory with index
    if base.is_dir() {
        for ext in &["js", "ts", "jsx", "tsx"] {
            let index = base.join(format!("index.{ext}"));
            if index.is_file() {
                return Some(index);
            }
        }
    }

    None
}
