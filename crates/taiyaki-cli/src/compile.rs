use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

use taiyaki_core::transpiler;

/// Compile a JS/TS file into a standalone executable.
/// Strategy: copy the current taiyaki binary and append the script as a trailer.
/// On execution, the binary detects the trailer and runs it instead of parsing CLI args.
pub fn compile(entry: &Path, output: Option<&Path>) -> Result<(), Box<dyn std::error::Error>> {
    if !entry.exists() {
        return Err(format!("Entry point not found: {}", entry.display()).into());
    }

    let source = std::fs::read_to_string(entry)?;
    let ext = entry.extension().and_then(|e| e.to_str()).unwrap_or("");

    let code = match ext {
        "tsx" | "jsx" => transpiler::transform_jsx(&source, &Default::default())?,
        "ts" | "mts" => transpiler::strip_types(&source)?,
        _ => source,
    };

    let out = match output {
        Some(p) => p.to_path_buf(),
        None => {
            let stem = entry
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("compiled");
            std::env::current_dir()?.join(stem)
        }
    };

    let self_exe = std::env::current_exe()?;

    // Stream the copy: exe → output file, then append script + trailer
    {
        let mut reader = std::io::BufReader::new(std::fs::File::open(&self_exe)?);
        let mut writer = std::io::BufWriter::new(std::fs::File::create(&out)?);
        std::io::copy(&mut reader, &mut writer)?;

        let script_bytes = code.as_bytes();
        let script_len = script_bytes.len() as u64;
        let magic = b"TAIYAKI\0";

        writer.write_all(script_bytes)?;
        writer.write_all(&script_len.to_le_bytes())?;
        writer.write_all(magic)?;
        writer.flush()?;
    }

    // Make executable on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = std::fs::metadata(&out)?.permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&out, perms)?;
    }

    let size = std::fs::metadata(&out)?.len();
    let size_str = if size > 1024 * 1024 {
        format!("{:.1} MB", size as f64 / (1024.0 * 1024.0))
    } else {
        format!("{:.1} KB", size as f64 / 1024.0)
    };

    println!(
        "Compiled {} → {} ({})",
        entry.display(),
        out.display(),
        size_str
    );
    Ok(())
}

/// Check if the current binary has an embedded script trailer.
/// Only reads the last 16 bytes (trailer) first, then the script payload if found.
pub fn extract_embedded_script() -> Option<String> {
    let self_exe = std::env::current_exe().ok()?;
    let mut file = std::fs::File::open(&self_exe).ok()?;
    let file_len = file.metadata().ok()?.len();

    if file_len < 16 {
        return None;
    }

    // Read only the 16-byte trailer: [script_len: u64 LE] [magic: "TAIYAKI\\0"]
    file.seek(SeekFrom::End(-16)).ok()?;
    let mut trailer = [0u8; 16];
    file.read_exact(&mut trailer).ok()?;

    if &trailer[8..] != b"TAIYAKI\0" {
        return None;
    }

    let script_len = u64::from_le_bytes(trailer[..8].try_into().ok()?) as usize;
    if (file_len as usize) < 16 + script_len {
        return None;
    }

    // Seek to script start and read only the script
    file.seek(SeekFrom::End(-(16 + script_len as i64))).ok()?;
    let mut script_buf = vec![0u8; script_len];
    file.read_exact(&mut script_buf).ok()?;

    String::from_utf8(script_buf).ok()
}
