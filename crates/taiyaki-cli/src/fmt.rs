use std::path::Path;

use taiyaki_core::transpiler;

use crate::util::collect_files;

fn is_ts(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()),
        Some("ts" | "tsx" | "mts")
    )
}

pub fn fmt(paths: &[&Path], check_only: bool) -> Result<(), Box<dyn std::error::Error>> {
    let paths = if paths.is_empty() {
        vec![Path::new(".")]
    } else {
        paths.to_vec()
    };
    let files = collect_files(&paths);
    if files.is_empty() {
        println!("No files to format.");
        return Ok(());
    }

    let mut changed = 0;
    let mut total = 0;

    for file in &files {
        let source = std::fs::read_to_string(file)?;
        let ts = is_ts(file);

        match transpiler::format_code(&source, ts) {
            Ok(formatted) => {
                total += 1;
                let formatted = if formatted.ends_with('\n') {
                    formatted
                } else {
                    format!("{formatted}\n")
                };
                if formatted != source {
                    changed += 1;
                    if check_only {
                        println!("{}", file.display());
                    } else {
                        std::fs::write(file, &formatted)?;
                    }
                }
            }
            Err(e) => {
                eprintln!("{}: {}", file.display(), e);
            }
        }
    }

    if check_only {
        if changed > 0 {
            Err(format!("{changed} file(s) need formatting").into())
        } else {
            println!("All {total} file(s) formatted correctly.");
            Ok(())
        }
    } else {
        if changed > 0 {
            println!("Formatted {changed} file(s) ({total} checked).");
        } else {
            println!("All {total} file(s) already formatted.");
        }
        Ok(())
    }
}
