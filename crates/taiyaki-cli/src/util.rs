use std::path::Path;

use taiyaki_core::engine::JsValue;
use walkdir::WalkDir;

/// Lenient string extraction: coerces any JsValue to String, returns empty on missing.
pub fn require_str(args: &[JsValue], idx: usize) -> String {
    match args.get(idx) {
        Some(JsValue::String(s)) => s.clone(),
        Some(v) => v.coerce_string(),
        None => String::new(),
    }
}

pub fn is_js_ts_file(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()),
        Some("js" | "jsx" | "ts" | "tsx" | "mjs" | "mts")
    )
}

pub fn collect_files(paths: &[&Path]) -> Vec<std::path::PathBuf> {
    let mut files = Vec::new();
    for path in paths {
        if path.is_file() {
            files.push(path.to_path_buf());
        } else if path.is_dir() {
            for entry in WalkDir::new(path)
                .into_iter()
                .filter_entry(|e| e.file_name() != "node_modules" && e.file_name() != ".git")
                .filter_map(|e| e.ok())
            {
                if entry.file_type().is_file() && is_js_ts_file(entry.path()) {
                    files.push(entry.into_path());
                }
            }
        }
    }
    files
}
