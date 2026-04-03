use std::path::Path;

use crate::util::collect_files;

struct LintDiagnostic {
    file: String,
    line: usize,
    col: usize,
    rule: &'static str,
    message: String,
}

/// Lint a single file's source code, returning diagnostics.
fn lint_source(source: &str, filename: &str) -> Vec<LintDiagnostic> {
    let mut diags = Vec::new();

    for (line_num, line) in source.lines().enumerate() {
        let trimmed = line.trim();
        let ln = line_num + 1;

        // no-debugger
        if trimmed == "debugger;" || trimmed == "debugger" {
            diags.push(LintDiagnostic {
                file: filename.into(),
                line: ln,
                col: line.find("debugger").unwrap_or(0) + 1,
                rule: "no-debugger",
                message: "Unexpected 'debugger' statement".into(),
            });
        }

        // no-console (warn only for console.log in non-test files)
        // Skip — too noisy for a runtime

        // eqeqeq: warn on == and != (but not === and !==)
        if let Some(pos) = find_loose_equality(line) {
            let op = if line[pos..].starts_with("!=") {
                "!="
            } else {
                "=="
            };
            diags.push(LintDiagnostic {
                file: filename.into(),
                line: ln,
                col: pos + 1,
                rule: "eqeqeq",
                message: format!("Use '{op}=' instead of '{op}'"),
            });
        }

        // no-var
        if trimmed.starts_with("var ") {
            diags.push(LintDiagnostic {
                file: filename.into(),
                line: ln,
                col: line.find("var ").unwrap_or(0) + 1,
                rule: "no-var",
                message: "Use 'let' or 'const' instead of 'var'".into(),
            });
        }

        // no-eval
        if trimmed.contains("eval(") && !trimmed.starts_with("//") && !trimmed.starts_with("*") {
            diags.push(LintDiagnostic {
                file: filename.into(),
                line: ln,
                col: line.find("eval(").unwrap_or(0) + 1,
                rule: "no-eval",
                message: "Avoid using 'eval()'".into(),
            });
        }

        // no-alert
        for func in &["alert(", "confirm(", "prompt("] {
            if trimmed.contains(func) && !trimmed.starts_with("//") && !trimmed.starts_with("*") {
                let name = &func[..func.len() - 1];
                diags.push(LintDiagnostic {
                    file: filename.into(),
                    line: ln,
                    col: line.find(func).unwrap_or(0) + 1,
                    rule: "no-alert",
                    message: format!("Unexpected '{name}'"),
                });
            }
        }

        // no-trailing-spaces
        if !line.is_empty() && (line.ends_with(' ') || line.ends_with('\t')) {
            diags.push(LintDiagnostic {
                file: filename.into(),
                line: ln,
                col: line.len(),
                rule: "no-trailing-spaces",
                message: "Trailing whitespace".into(),
            });
        }
    }

    diags
}

/// Find loose equality (== or !=) that isn't strict (=== or !==).
fn find_loose_equality(line: &str) -> Option<usize> {
    let bytes = line.as_bytes();
    let mut i = 0;
    let mut in_string = false;
    let mut string_char = b'"';

    while i < bytes.len() {
        if in_string {
            if bytes[i] == b'\\' {
                i += 2;
                continue;
            }
            if bytes[i] == string_char {
                in_string = false;
            }
            i += 1;
            continue;
        }

        if bytes[i] == b'"' || bytes[i] == b'\'' || bytes[i] == b'`' {
            in_string = true;
            string_char = bytes[i];
            i += 1;
            continue;
        }

        // Check for // comment
        if bytes[i] == b'/' && i + 1 < bytes.len() && bytes[i + 1] == b'/' {
            break;
        }

        // Check for == or != (but not === or !==)
        if bytes[i] == b'=' && i + 1 < bytes.len() && bytes[i + 1] == b'=' {
            if i + 2 < bytes.len() && bytes[i + 2] == b'=' {
                i += 3; // skip ===
                continue;
            }
            // Check it's not <=, >=
            if i > 0 && (bytes[i - 1] == b'<' || bytes[i - 1] == b'>' || bytes[i - 1] == b'!') {
                if bytes[i - 1] == b'!' {
                    // != but not !==
                    return Some(i - 1);
                }
                i += 2;
                continue;
            }
            return Some(i);
        }

        if bytes[i] == b'!' && i + 1 < bytes.len() && bytes[i + 1] == b'=' {
            if i + 2 < bytes.len() && bytes[i + 2] == b'=' {
                i += 3; // skip !==
                continue;
            }
            return Some(i);
        }

        i += 1;
    }
    None
}

pub fn lint(paths: &[&Path]) -> Result<(), Box<dyn std::error::Error>> {
    let paths = if paths.is_empty() {
        vec![Path::new(".")]
    } else {
        paths.to_vec()
    };
    let files = collect_files(&paths);
    if files.is_empty() {
        println!("No files to lint.");
        return Ok(());
    }

    let mut total_warnings = 0;
    let mut files_with_warnings = 0;

    for file in &files {
        let source = std::fs::read_to_string(file)?;
        let diags = lint_source(&source, &file.display().to_string());

        if !diags.is_empty() {
            files_with_warnings += 1;
            for d in &diags {
                total_warnings += 1;
                println!(
                    "  {}:{}:{} \x1b[33m{}\x1b[0m {}",
                    d.file, d.line, d.col, d.rule, d.message
                );
            }
        }
    }

    if total_warnings > 0 {
        println!(
            "\n{total_warnings} warning(s) in {files_with_warnings} file(s) ({} file(s) checked)",
            files.len()
        );
        Err(format!("{total_warnings} lint warning(s)").into())
    } else {
        println!("{} file(s) checked, no warnings.", files.len());
        Ok(())
    }
}
