//! AOT compilation via taiyaki-aot-compiler (JS/TS → native binary via LLVM).
//!
//! Invokes the taiyaki AOT compiler (Python) as a subprocess with `--backend taiyaki`.

use std::path::Path;
use std::process::Command;

/// Locate the taiyaki-aot-compiler package directory.
/// Checks TAIYAKI_AOT_PATH env, then tries relative to the repo root.
fn find_aot_compiler_dir() -> Result<std::path::PathBuf, String> {
    // 1. Explicit env var
    if let Ok(p) = std::env::var("TAIYAKI_AOT_PATH") {
        let path = std::path::PathBuf::from(p);
        if path.exists() {
            return Ok(path);
        }
    }

    // 2. Relative to executable (development layout: target/{profile}/taiyaki -> ../../packages/taiyaki-aot-compiler)
    if let Ok(exe) = std::env::current_exe()
        && let Some(profile_dir) = exe.parent()
    {
        let repo_root = profile_dir.join("../..");
        let aot_dir = repo_root.join("packages/taiyaki-aot-compiler");
        if aot_dir.exists() {
            return Ok(aot_dir);
        }
    }

    // 3. Current directory relative
    let cwd_relative = std::path::PathBuf::from("packages/taiyaki-aot-compiler");
    if cwd_relative.exists() {
        return Ok(cwd_relative);
    }

    Err(
        "Cannot locate taiyaki-aot-compiler. Set TAIYAKI_AOT_PATH environment variable \
         or run from the taiyaki repo root."
            .to_string(),
    )
}

pub fn run(entry: &Path, output: Option<&Path>) -> Result<(), String> {
    let aot_dir = find_aot_compiler_dir()?;
    let cwd = std::env::current_dir().map_err(|e| format!("Cannot get cwd: {e}"))?;

    let abs_entry = if entry.is_absolute() {
        entry.to_path_buf()
    } else {
        cwd.join(entry)
    };

    let output_dir = if let Some(out) = output {
        if let Some(parent) = out.parent().filter(|p| !p.as_os_str().is_empty()) {
            if parent.is_absolute() {
                parent.to_path_buf()
            } else {
                cwd.join(parent)
            }
        } else {
            cwd.clone()
        }
    } else {
        cwd
    };

    let mut cmd = Command::new("uv");
    cmd.arg("run")
        .arg("taiyaki-aot")
        .arg("compile")
        .arg(&abs_entry)
        .arg("--backend")
        .arg("taiyaki")
        .arg("--output-dir")
        .arg(&output_dir)
        .current_dir(&aot_dir);

    let status = cmd
        .status()
        .map_err(|e| format!("Failed to run taiyaki-aot: {e}"))?;

    if !status.success() {
        return Err(format!(
            "AOT compilation failed with exit code {}",
            status.code().unwrap_or(-1)
        ));
    }

    Ok(())
}
