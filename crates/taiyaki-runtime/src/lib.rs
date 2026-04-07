//! Full JS/TS runtime with HTTP server, Web APIs, and Node.js polyfills.
//!
//! This crate extracts the taiyaki CLI's runtime builtins into a reusable library
//! that can be linked into AOT-compiled binaries via C ABI.

pub mod async_builtins;
pub mod async_fs;
pub mod builtins;
pub mod child_process;
pub mod dns;
pub mod ffi;
pub mod fs_watch;
pub mod http_node;
pub mod net;
pub mod readline;
pub mod server;
#[cfg(feature = "sqlite")]
pub mod sqlite;
pub mod tls;
pub mod util;
pub mod worker_threads;

use std::path::Path;
use std::sync::Arc;

use taiyaki_core::engine::AsyncJsEngine;
use taiyaki_core::permissions::Permissions;

/// Backend engine type alias — switch via feature flags.
#[cfg(feature = "quickjs")]
pub type Engine = taiyaki_core::engine::async_quickjs_backend::AsyncQuickJsEngine;

#[cfg(feature = "jsc")]
pub type Engine = taiyaki_core::engine::async_jsc_backend::AsyncJscEngine;

/// Register all builtins, polyfills, and modules on the given engine.
pub async fn bootstrap_engine(
    engine: &Engine,
    script_path: &Path,
    user_args: &[String],
    perms: &Arc<Permissions>,
) -> Result<(), Box<dyn std::error::Error>> {
    builtins::register_all(engine, script_path, user_args, perms).await?;
    async_builtins::register_all(engine, perms).await?;
    async_fs::register_async_fs(engine, perms).await?;
    child_process::register_child_process(engine, perms).await?;
    fs_watch::register_fs_watch(engine).await?;
    server::register_server(engine).await?;
    dns::register_dns(engine, perms).await?;
    let net_state = Arc::new(net::NetState::new());
    net::register_net(engine, perms, &net_state).await?;
    tls::register_tls(engine, perms, &net_state).await?;
    http_node::register_http_node(engine, perms).await?;
    #[cfg(feature = "sqlite")]
    sqlite::register_sqlite(engine).await?;
    worker_threads::register_worker_threads(engine, script_path, perms).await?;
    readline::register_readline(engine).await?;
    taiyaki_node_polyfill::register_all_async(engine).await?;

    engine.register_module(
        "preact/jsx-runtime",
        r#"
function jsx(type, props, key) {
    const { children, ...rest } = props || {};
    if (Array.isArray(children)) {
        return type(Object.assign(rest, { children }));
    }
    if (typeof type === 'function') {
        return type(children !== undefined ? Object.assign(rest, { children }) : rest);
    }
    return { type, props: children !== undefined ? Object.assign(rest, { children }) : rest, key };
}
export { jsx, jsx as jsxs, jsx as jsxDEV };
export const Fragment = '__fragment__';
"#,
    )?;

    Ok(())
}

/// Strip shebang line (e.g. `#!/usr/bin/env taiyaki run`).
pub fn strip_shebang(source: &str) -> &str {
    if source.starts_with("#!") {
        source.find('\n').map(|i| &source[i + 1..]).unwrap_or("")
    } else {
        source
    }
}

/// Simple heuristic for ES module syntax detection.
pub fn has_module_syntax(source: &str) -> bool {
    source.contains("import ") || source.contains("export ") || source.contains("await ")
}
