use std::path::Path;

use taiyaki_core::transpiler;

use crate::util::collect_files;

pub fn check(paths: &[&Path]) -> Result<(), Box<dyn std::error::Error>> {
    let paths = if paths.is_empty() {
        vec![Path::new(".")]
    } else {
        paths.to_vec()
    };
    let files = collect_files(&paths);
    if files.is_empty() {
        println!("No files to check.");
        return Ok(());
    }

    let mut errors = 0;
    let mut checked = 0;

    for file in &files {
        let source = std::fs::read_to_string(file)?;
        let ext = file.extension().and_then(|e| e.to_str()).unwrap_or("");

        let result = match ext {
            "tsx" | "jsx" => transpiler::transform_jsx(&source, &Default::default()),
            "ts" | "mts" => transpiler::strip_types(&source),
            _ => transpiler::strip_types(&source),
        };

        checked += 1;
        if let Err(e) = result {
            errors += 1;
            eprintln!("{}: {}", file.display(), e);
        }
    }

    if errors > 0 {
        eprintln!("\n{errors} error(s) in {checked} file(s)");
        Err(format!("{errors} file(s) had errors").into())
    } else {
        println!("Checked {checked} file(s), no errors found.");
        Ok(())
    }
}
