pub mod buffer;
pub mod child_process;
pub mod crypto;
pub mod events;
pub mod fs;
pub mod os;
pub mod path;
pub mod require;
pub mod url;
pub mod util;
pub mod zlib;

use taiyaki_core::engine::{EngineError, JsValue};

pub fn require_string_arg<'a>(
    args: &'a [JsValue],
    index: usize,
    fn_name: &str,
) -> Result<&'a str, EngineError> {
    match args.get(index) {
        Some(JsValue::String(s)) => Ok(s.as_str()),
        _ => Err(EngineError::TypeError(format!(
            "{fn_name}: expected string argument at position {index}"
        ))),
    }
}

/// Map Rust `std::env::consts::OS` to Node.js convention.
pub fn node_platform() -> &'static str {
    match std::env::consts::OS {
        "macos" => "darwin",
        other => other,
    }
}

/// Map Rust `std::env::consts::ARCH` to Node.js convention.
pub fn node_arch() -> &'static str {
    match std::env::consts::ARCH {
        "aarch64" => "arm64",
        "x86_64" => "x64",
        "x86" => "ia32",
        other => other,
    }
}

/// Module source entries: (short_name, JS source).
/// Each is registered under both "name" and "node:name".
pub const MODULE_SOURCES: &[(&str, &str)] = &[
    ("path", include_str!("../js/path.js")),
    ("events", include_str!("../js/events.js")),
    ("util", include_str!("../js/util.js")),
    ("url", include_str!("../js/url.js")),
    ("buffer", include_str!("../js/buffer.js")),
    ("fs", include_str!("../js/fs.js")),
    ("os", include_str!("../js/os.js")),
    ("crypto", include_str!("../js/crypto.js")),
    ("assert", include_str!("../js/assert.js")),
    ("stream", include_str!("../js/stream.js")),
    ("child_process", include_str!("../js/child_process.js")),
    ("zlib", include_str!("../js/zlib.js")),
    ("dns", include_str!("../js/dns.js")),
    ("net", include_str!("../js/net.js")),
    ("tls", include_str!("../js/tls.js")),
    ("http", include_str!("../js/http.js")),
    ("sqlite", include_str!("../js/sqlite.js")),
    ("worker_threads", include_str!("../js/worker_threads.js")),
    ("vm", include_str!("../js/vm.js")),
    ("readline", include_str!("../js/readline.js")),
];
