use std::fs;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::time::UNIX_EPOCH;

use taiyaki_core::engine::{EngineError, HostCallback, JsValue};

use super::require_string_arg;

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__fs_read_file_sync", Box::new(fs_read_file_sync)),
        ("__fs_write_file_sync", Box::new(fs_write_file_sync)),
        ("__fs_exists_sync", Box::new(fs_exists_sync)),
        ("__fs_mkdir_sync", Box::new(fs_mkdir_sync)),
        ("__fs_readdir_sync", Box::new(fs_readdir_sync)),
        ("__fs_stat_sync", Box::new(fs_stat_sync)),
        ("__fs_lstat_sync", Box::new(fs_lstat_sync)),
        ("__fs_unlink_sync", Box::new(fs_unlink_sync)),
        ("__fs_rename_sync", Box::new(fs_rename_sync)),
        ("__fs_rm_sync", Box::new(fs_rm_sync)),
        ("__fs_copy_file_sync", Box::new(fs_copy_file_sync)),
        ("__fs_append_file_sync", Box::new(fs_append_file_sync)),
        ("__fs_realpath_sync", Box::new(fs_realpath_sync)),
        ("__fs_chmod_sync", Box::new(fs_chmod_sync)),
    ]
}

fn fs_err(op: &str, e: std::io::Error) -> EngineError {
    EngineError::JsException {
        message: format!("{op}: {e}"),
    }
}

fn fs_read_file_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "readFileSync")?;
    let encoding = args
        .get(1)
        .and_then(|v| match v {
            JsValue::String(s) => Some(s.as_str()),
            _ => None,
        })
        .unwrap_or("utf8");

    match encoding {
        "utf8" | "utf-8" => {
            let content = fs::read_to_string(path).map_err(|e| fs_err("readFileSync", e))?;
            Ok(JsValue::String(content))
        }
        _ => {
            // Return base64-encoded for non-utf8 (Buffer construction on JS side)
            use base64::Engine as _;
            let bytes = fs::read(path).map_err(|e| fs_err("readFileSync", e))?;
            let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
            Ok(JsValue::String(b64))
        }
    }
}

fn fs_write_file_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "writeFileSync")?;
    let data = require_string_arg(args, 1, "writeFileSync")?;
    fs::write(path, data).map_err(|e| fs_err("writeFileSync", e))?;
    Ok(JsValue::Undefined)
}

fn fs_exists_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "existsSync")?;
    Ok(JsValue::Bool(Path::new(path).exists()))
}

fn fs_mkdir_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "mkdirSync")?;
    let recursive = args
        .get(1)
        .and_then(|v| match v {
            JsValue::Bool(b) => Some(*b),
            _ => None,
        })
        .unwrap_or(false);

    if recursive {
        fs::create_dir_all(path).map_err(|e| fs_err("mkdirSync", e))?;
    } else {
        fs::create_dir(path).map_err(|e| fs_err("mkdirSync", e))?;
    }
    Ok(JsValue::Undefined)
}

fn fs_readdir_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "readdirSync")?;
    let mut entries: Vec<String> = Vec::new();
    for entry in fs::read_dir(path).map_err(|e| fs_err("readdirSync", e))? {
        let entry = entry.map_err(|e| fs_err("readdirSync", e))?;
        if let Some(name) = entry.file_name().to_str() {
            entries.push(name.to_string());
        }
    }
    let json = serde_json::to_string(&entries).expect("entries serialization");
    Ok(JsValue::String(json))
}

pub fn stat_to_json(meta: &fs::Metadata) -> String {
    let mtime = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as f64)
        .unwrap_or(0.0);
    let atime = meta
        .accessed()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as f64)
        .unwrap_or(0.0);
    let ctime = meta
        .created()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as f64)
        .unwrap_or(mtime);

    serde_json::json!({
        "size": meta.len(),
        "isFile": meta.is_file(),
        "isDir": meta.is_dir(),
        "isSymlink": meta.is_symlink(),
        "mode": meta.mode(),
        "mtime": mtime,
        "atime": atime,
        "ctime": ctime,
        "dev": meta.dev(),
        "ino": meta.ino(),
        "nlink": meta.nlink(),
        "uid": meta.uid(),
        "gid": meta.gid(),
    })
    .to_string()
}

fn fs_stat_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "statSync")?;
    let meta = fs::metadata(path).map_err(|e| fs_err("statSync", e))?;
    Ok(JsValue::String(stat_to_json(&meta)))
}

fn fs_lstat_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "lstatSync")?;
    let meta = fs::symlink_metadata(path).map_err(|e| fs_err("lstatSync", e))?;
    Ok(JsValue::String(stat_to_json(&meta)))
}

fn fs_unlink_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "unlinkSync")?;
    fs::remove_file(path).map_err(|e| fs_err("unlinkSync", e))?;
    Ok(JsValue::Undefined)
}

fn fs_rename_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let old = require_string_arg(args, 0, "renameSync")?;
    let new = require_string_arg(args, 1, "renameSync")?;
    fs::rename(old, new).map_err(|e| fs_err("renameSync", e))?;
    Ok(JsValue::Undefined)
}

fn fs_rm_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path_str = require_string_arg(args, 0, "rmSync")?;
    let recursive = args
        .get(1)
        .and_then(|v| match v {
            JsValue::Bool(b) => Some(*b),
            _ => None,
        })
        .unwrap_or(false);
    let force = args
        .get(2)
        .and_then(|v| match v {
            JsValue::Bool(b) => Some(*b),
            _ => None,
        })
        .unwrap_or(false);

    let path = Path::new(path_str);

    // Try remove_file first; on directory error, fall back to remove_dir
    match fs::remove_file(path) {
        Ok(()) => return Ok(JsValue::Undefined),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound && force => {
            return Ok(JsValue::Undefined);
        }
        Err(e)
            if e.raw_os_error() == Some(libc::EISDIR) || e.raw_os_error() == Some(libc::EPERM) =>
        {
            // It's a directory
            if recursive {
                fs::remove_dir_all(path).map_err(|e| fs_err("rmSync", e))?;
            } else {
                fs::remove_dir(path).map_err(|e| fs_err("rmSync", e))?;
            }
        }
        Err(e) => return Err(fs_err("rmSync", e)),
    }
    Ok(JsValue::Undefined)
}

fn fs_copy_file_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let src = require_string_arg(args, 0, "copyFileSync")?;
    let dest = require_string_arg(args, 1, "copyFileSync")?;
    fs::copy(src, dest).map_err(|e| fs_err("copyFileSync", e))?;
    Ok(JsValue::Undefined)
}

fn fs_append_file_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "appendFileSync")?;
    let data = require_string_arg(args, 1, "appendFileSync")?;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| fs_err("appendFileSync", e))?;
    file.write_all(data.as_bytes())
        .map_err(|e| fs_err("appendFileSync", e))?;
    Ok(JsValue::Undefined)
}

fn fs_realpath_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let path = require_string_arg(args, 0, "realpathSync")?;
    let real = fs::canonicalize(path).map_err(|e| fs_err("realpathSync", e))?;
    Ok(JsValue::String(real.to_string_lossy().into_owned()))
}

fn fs_chmod_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    use std::os::unix::fs::PermissionsExt;
    let path = require_string_arg(args, 0, "chmodSync")?;
    let mode = match args.get(1) {
        Some(JsValue::Number(n)) => *n as u32,
        _ => {
            return Err(EngineError::TypeError(
                "chmodSync: expected number for mode".into(),
            ));
        }
    };
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
        .map_err(|e| fs_err("chmodSync", e))?;
    Ok(JsValue::Undefined)
}
