mod aot_compile;
mod async_builtins;
mod async_fs;
mod build;
mod builtins;
mod check;
mod child_process;
mod compile;
mod dns;
mod fmt;
mod fs_watch;
mod http_node;
mod lint;
mod net;
mod package_manager;
mod readline;
mod repl;
mod server;
#[cfg(feature = "sqlite")]
mod sqlite;
mod test_runner;
mod tls;
mod util;
mod watch;
mod worker_threads;

use std::borrow::Cow;
use std::io::IsTerminal;
use std::path::{Path, PathBuf};
use std::process;

use std::sync::Arc;

use clap::{Parser, Subcommand};
use taiyaki_core::engine::JsValue;
use taiyaki_core::permissions::Permissions;
use taiyaki_core::transpiler;

/// Backend engine type alias — switch via feature flags.
#[cfg(feature = "quickjs")]
pub type Engine = taiyaki_core::engine::async_quickjs_backend::AsyncQuickJsEngine;

#[cfg(feature = "jsc")]
pub type Engine = taiyaki_core::engine::async_jsc_backend::AsyncJscEngine;

#[derive(Parser)]
#[command(name = "taiyaki", about = "JS/TS runtime", version)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Execute a JavaScript or TypeScript file
    Run {
        /// Path to .js or .ts file
        file: PathBuf,
        /// Load environment variables from file
        #[arg(long)]
        env_file: Option<PathBuf>,
        /// Deny all permissions (whitelist with --allow-*)
        #[arg(long)]
        sandbox: bool,
        /// Allow file read access (comma-separated paths, or empty for all)
        #[arg(long, value_delimiter = ',')]
        allow_read: Option<Vec<String>>,
        /// Allow file write access
        #[arg(long, value_delimiter = ',')]
        allow_write: Option<Vec<String>>,
        /// Allow network access (comma-separated hosts)
        #[arg(long, value_delimiter = ',')]
        allow_net: Option<Vec<String>>,
        /// Allow environment variable access
        #[arg(long, value_delimiter = ',')]
        allow_env: Option<Vec<String>>,
        /// Allow command execution
        #[arg(long, value_delimiter = ',')]
        allow_run: Option<Vec<String>>,
        /// Arguments passed to the script
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
    /// Evaluate a JavaScript/TypeScript expression
    Eval {
        /// Code to evaluate
        code: String,
    },
    /// Run test files (*.test.{js,ts} / *.spec.{js,ts})
    Test {
        /// Directory or file to test (default: current directory)
        path: Option<PathBuf>,
        /// Filter test files by name
        #[arg(short, long)]
        filter: Option<String>,
        /// Watch for file changes and re-run tests
        #[arg(short, long)]
        watch: bool,
    },
    /// Start interactive REPL
    Repl,
    /// Initialize a new project (create package.json)
    Init,
    /// Install dependencies from package.json
    Install,
    /// Add a package
    Add {
        /// Package name (optionally with @version)
        packages: Vec<String>,
        /// Add as dev dependency
        #[arg(short = 'D', long)]
        dev: bool,
    },
    /// Remove a package
    Remove {
        /// Package names to remove
        packages: Vec<String>,
    },
    /// Bundle JavaScript/TypeScript files
    Build {
        /// Entry point file
        entry: PathBuf,
        /// Output file (default: out.js)
        #[arg(short, long, default_value = "out.js")]
        outfile: PathBuf,
        /// Minify output
        #[arg(long)]
        minify: bool,
    },
    /// Check TypeScript/JavaScript for errors
    Check {
        /// Files or directories to check
        paths: Vec<PathBuf>,
    },
    /// Format JavaScript/TypeScript files
    Fmt {
        /// Files or directories to format
        paths: Vec<PathBuf>,
        /// Check formatting without modifying files
        #[arg(long)]
        check: bool,
    },
    /// Lint JavaScript/TypeScript files
    Lint {
        /// Files or directories to lint
        paths: Vec<PathBuf>,
    },
    /// Compile to a standalone executable
    Compile {
        /// Entry point file
        entry: PathBuf,
        /// Output binary path
        #[arg(short, long)]
        output: Option<PathBuf>,
        /// AOT compile via tsuchi (native binary with LLVM)
        #[arg(long)]
        aot: bool,
    },
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    // Check for embedded script (compiled binary)
    if let Some(code) = compile::extract_embedded_script() {
        let perms = Arc::new(Permissions::default());
        let engine = Engine::new().await.expect("engine init");
        bootstrap_engine(&engine, Path::new("<compiled>"), &[], &perms)
            .await
            .expect("bootstrap");
        let is_module = has_module_syntax(&code);
        let result = if is_module {
            engine.eval_module_async(&code, "main").await
        } else {
            engine.eval_async(&code).await
        };
        if let Err(e) = print_result(result) {
            format_error(&e);
            process::exit(1);
        }
        return;
    }

    let cli = Cli::parse();
    match cli.command {
        Some(Commands::Run {
            file,
            env_file,
            sandbox,
            allow_read,
            allow_write,
            allow_net,
            allow_env,
            allow_run,
            args,
        }) => {
            if let Some(env_path) = env_file {
                load_env_file(&env_path);
            }
            let perms = build_permissions(
                sandbox,
                allow_read,
                allow_write,
                allow_net,
                allow_env,
                allow_run,
            );
            if let Err(e) = run_file(&file, &args, &perms).await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Eval { code }) => {
            if let Err(e) = run_eval(&code).await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Test {
            path,
            filter,
            watch,
        }) => {
            let dir = path.unwrap_or_else(|| PathBuf::from("."));
            if watch {
                if dir.is_file() {
                    eprintln!("Watch mode requires a directory, not a file.");
                    process::exit(1);
                }
                match crate::watch::run_watch(&dir, filter.as_deref()).await {
                    Ok(()) => {}
                    Err(e) => {
                        format_error(&e);
                        process::exit(1);
                    }
                }
            } else {
                let target = if dir.is_file() {
                    match test_runner::run_test_file(&dir).await {
                        Ok((pass, fail, output)) => {
                            print!("{output}");
                            if fail > 0 {
                                println!("{fail} failed, {pass} passed");
                                process::exit(1);
                            }
                            println!("{pass} passed");
                            return;
                        }
                        Err(e) => {
                            format_error(&e);
                            process::exit(1);
                        }
                    }
                } else {
                    dir
                };
                match test_runner::run_tests(&target, filter.as_deref()).await {
                    Ok(true) => {}
                    Ok(false) => process::exit(1),
                    Err(e) => {
                        format_error(&e);
                        process::exit(1);
                    }
                }
            }
        }
        Some(Commands::Repl) | None => {
            if let Err(e) = repl::start_repl().await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Init) => {
            if let Err(e) = package_manager::init().await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Install) => {
            if let Err(e) = package_manager::install().await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Add { packages, dev }) => {
            if let Err(e) = package_manager::add(&packages, dev).await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Remove { packages }) => {
            if let Err(e) = package_manager::remove(&packages).await {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Build {
            entry,
            outfile,
            minify,
        }) => {
            if let Err(e) = build::build(&entry, &outfile, minify) {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Check { paths }) => {
            let paths: Vec<&Path> = paths.iter().map(|p| p.as_path()).collect();
            if let Err(e) = check::check(&paths) {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Fmt {
            paths,
            check: check_only,
        }) => {
            let paths: Vec<&Path> = paths.iter().map(|p| p.as_path()).collect();
            if let Err(e) = fmt::fmt(&paths, check_only) {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Lint { paths }) => {
            let paths: Vec<&Path> = paths.iter().map(|p| p.as_path()).collect();
            if let Err(e) = lint::lint(&paths) {
                format_error(&e);
                process::exit(1);
            }
        }
        Some(Commands::Compile { entry, output, aot }) => {
            if aot {
                if let Err(e) = aot_compile::run(&entry, output.as_deref()) {
                    format_error(&e);
                    process::exit(1);
                }
            } else if let Err(e) = compile::compile(&entry, output.as_deref()) {
                format_error(&e);
                process::exit(1);
            }
        }
    }
}

fn format_error(e: &dyn std::fmt::Display) {
    let msg = e.to_string();
    if std::io::stderr().is_terminal() {
        // Red for error message, dim for stack trace lines
        let mut lines = msg.lines();
        if let Some(first) = lines.next() {
            eprintln!("\x1b[31m{first}\x1b[0m");
        }
        for line in lines {
            eprintln!("\x1b[2m{line}\x1b[0m");
        }
    } else {
        eprintln!("{msg}");
    }
}

/// Register all builtins, polyfills, and modules on the given engine.
/// Shared by run_eval, run_file, and worker_threads bootstrap.
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

    // JSX automatic runtime shim — transform_jsx() generates
    // `import { jsx } from "preact/jsx-runtime"`, so we need this module.
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
    // Return a vnode-like object for non-component elements
    return { type, props: children !== undefined ? Object.assign(rest, { children }) : rest, key };
}
export { jsx, jsx as jsxs, jsx as jsxDEV };
export const Fragment = '__fragment__';
"#,
    )?;

    Ok(())
}

async fn run_eval(code: &str) -> Result<(), Box<dyn std::error::Error>> {
    let perms = Arc::new(Permissions::default());
    let engine = Engine::new().await?;
    bootstrap_engine(&engine, Path::new("<eval>"), &[], &perms).await?;

    let result = engine.eval_async(code).await;
    print_result(result)?;
    Ok(())
}

async fn run_file(
    file: &Path,
    user_args: &[String],
    perms: &Permissions,
) -> Result<(), Box<dyn std::error::Error>> {
    let raw_source = std::fs::read_to_string(file)?;
    let source = strip_shebang(&raw_source);
    let script_dir = file.parent().unwrap_or(Path::new("."));
    let is_module = detect_module_mode(source, script_dir);

    let perms = Arc::new(perms.clone());
    let engine = Engine::new().await?;

    engine.enable_file_loader(script_dir).await;

    bootstrap_engine(&engine, file, user_args, &perms).await?;

    let ext = file.extension().and_then(|e| e.to_str()).unwrap_or("");
    let is_jsx = matches!(ext, "tsx" | "jsx");
    let code: Cow<str> = match ext {
        "tsx" | "jsx" => Cow::Owned(transpiler::transform_jsx(source, &Default::default())?),
        "ts" => Cow::Owned(transpiler::strip_types(source)?),
        _ => Cow::Borrowed(source),
    };

    // JSX/TSX always need module mode because automatic runtime generates
    // `import { jsx } from "preact/jsx-runtime"`.
    let result = if is_module || is_jsx {
        // Use the full file path as module name so the resolver can determine the base directory
        let name = file
            .canonicalize()
            .unwrap_or_else(|_| file.to_path_buf())
            .to_string_lossy()
            .into_owned();
        engine.eval_module_async(&code, &name).await
    } else {
        engine.eval_async(&code).await
    };

    print_result(result)?;
    Ok(())
}

fn print_result(
    result: Result<JsValue, taiyaki_core::engine::EngineError>,
) -> Result<(), Box<dyn std::error::Error>> {
    match result {
        Ok(val) => match &val {
            JsValue::Undefined | JsValue::Null => {}
            JsValue::Number(n) => {
                if n.fract() == 0.0 {
                    println!("{}", *n as i64);
                } else {
                    println!("{n}");
                }
            }
            JsValue::String(s) => println!("{s}"),
            JsValue::Bool(b) => println!("{b}"),
            _ => {}
        },
        Err(e) => {
            eprintln!("{e}");
            process::exit(1);
        }
    }
    Ok(())
}

fn build_permissions(
    sandbox: bool,
    allow_read: Option<Vec<String>>,
    allow_write: Option<Vec<String>>,
    allow_net: Option<Vec<String>>,
    allow_env: Option<Vec<String>>,
    allow_run: Option<Vec<String>>,
) -> Permissions {
    if !sandbox
        && allow_read.is_none()
        && allow_write.is_none()
        && allow_net.is_none()
        && allow_env.is_none()
        && allow_run.is_none()
    {
        return Permissions::default();
    }
    let mut perms = if sandbox {
        Permissions::none()
    } else {
        Permissions::default()
    };
    if let Some(paths) = allow_read {
        perms.read = if paths.is_empty() { None } else { Some(paths) };
    }
    if let Some(paths) = allow_write {
        perms.write = if paths.is_empty() { None } else { Some(paths) };
    }
    if let Some(hosts) = allow_net {
        perms.net = if hosts.is_empty() { None } else { Some(hosts) };
    }
    if let Some(names) = allow_env {
        perms.env = if names.is_empty() { None } else { Some(names) };
    }
    if let Some(cmds) = allow_run {
        perms.run = if cmds.is_empty() { None } else { Some(cmds) };
    }
    perms
}

fn load_env_file(path: &Path) {
    let Ok(content) = std::fs::read_to_string(path) else {
        eprintln!("Warning: could not read env file: {}", path.display());
        return;
    };
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((key, value)) = line.split_once('=') {
            let key = key.trim();
            let mut value = value.trim();
            // Strip surrounding quotes.
            if (value.starts_with('"') && value.ends_with('"'))
                || (value.starts_with('\'') && value.ends_with('\''))
            {
                value = &value[1..value.len() - 1];
            }
            unsafe { std::env::set_var(key, value) };
        }
    }
}

/// Strip shebang line (e.g. `#!/usr/bin/env taiyaki run`).
pub fn strip_shebang(source: &str) -> &str {
    if source.starts_with("#!") {
        source.find('\n').map(|i| &source[i + 1..]).unwrap_or("")
    } else {
        source
    }
}

/// Detect ES module mode via syntax heuristic or package.json "type": "module".
fn detect_module_mode(source: &str, script_dir: &Path) -> bool {
    if has_module_syntax(source) {
        return true;
    }
    let mut dir = script_dir.to_path_buf();
    loop {
        let pkg = dir.join("package.json");
        if let Ok(content) = std::fs::read_to_string(&pkg) {
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&content) {
                return json.get("type").and_then(|v| v.as_str()) == Some("module");
            }
            break;
        }
        if !dir.pop() {
            break;
        }
    }
    false
}

/// Simple heuristic — may false-positive on string literals containing these keywords.
pub fn has_module_syntax(source: &str) -> bool {
    source.contains("import ") || source.contains("export ") || source.contains("await ")
}
