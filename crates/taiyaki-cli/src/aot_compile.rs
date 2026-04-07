//! AOT compilation via tsuchi (JS/TS → native binary via LLVM).
//!
//! Invokes the tsuchi Python compiler as a subprocess with `--backend taiyaki`.

use std::path::Path;
use std::process::Command;

/// Locate the tsuchi package directory.
/// Checks TSUCHI_PATH env, then tries relative to the repo root.
fn find_tsuchi_dir() -> Result<std::path::PathBuf, String> {
    // 1. Explicit env var
    if let Ok(p) = std::env::var("TSUCHI_PATH") {
        let path = std::path::PathBuf::from(p);
        if path.exists() {
            return Ok(path);
        }
    }

    // 2. Relative to executable (development layout: target/debug/taiyaki-cli -> ../../packages/tsuchi)
    if let Ok(exe) = std::env::current_exe() {
        // exe is in target/debug/ or target/release/
        if let Some(target_dir) = exe.parent() {
            // Go up: target/{profile}/ -> target/ -> repo root
            let repo_root = target_dir.join("../../..");
            let tsuchi_dir = repo_root.join("packages/tsuchi");
            if tsuchi_dir.exists() {
                return Ok(tsuchi_dir);
            }
        }
    }

    // 3. Current directory relative
    let cwd_relative = std::path::PathBuf::from("packages/tsuchi");
    if cwd_relative.exists() {
        return Ok(cwd_relative);
    }

    Err(
        "Cannot locate tsuchi. Set TSUCHI_PATH environment variable \
         or run from the katana repo root."
            .to_string(),
    )
}

pub fn run(entry: &Path, output: Option<&Path>) -> Result<(), String> {
    let tsuchi_dir = find_tsuchi_dir()?;

    // Resolve entry to absolute path so tsuchi can find it from its own cwd
    let abs_entry = if entry.is_absolute() {
        entry.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|e| format!("Cannot get cwd: {e}"))?
            .join(entry)
    };

    // Default output dir to current working directory
    let output_dir = if let Some(out) = output {
        if let Some(parent) = out.parent() {
            if parent.as_os_str().is_empty() {
                std::env::current_dir()
                    .map_err(|e| format!("Cannot get cwd: {e}"))?
            } else if parent.is_absolute() {
                parent.to_path_buf()
            } else {
                std::env::current_dir()
                    .map_err(|e| format!("Cannot get cwd: {e}"))?
                    .join(parent)
            }
        } else {
            std::env::current_dir().map_err(|e| format!("Cannot get cwd: {e}"))?
        }
    } else {
        std::env::current_dir().map_err(|e| format!("Cannot get cwd: {e}"))?
    };

    let mut cmd = Command::new("uv");
    cmd.arg("run")
        .arg("tsuchi")
        .arg("compile")
        .arg(&abs_entry)
        .arg("--backend")
        .arg("taiyaki")
        .arg("--output-dir")
        .arg(&output_dir)
        .current_dir(&tsuchi_dir);

    let status = cmd
        .status()
        .map_err(|e| format!("Failed to run tsuchi: {e}"))?;

    if !status.success() {
        return Err(format!(
            "tsuchi compilation failed with exit code {}",
            status.code().unwrap_or(-1)
        ));
    }

    Ok(())
}
