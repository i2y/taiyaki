use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use taiyaki_core::permissions::Permissions;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::mpsc;

struct ProcessEvent {
    kind: &'static str,
    data: String,
    code: Option<i32>,
    signal: Option<String>,
}

struct ProcessHandle {
    event_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<ProcessEvent>>>,
    stdin_tx: Option<mpsc::UnboundedSender<Vec<u8>>>,
}

struct ProcessState {
    processes: std::sync::Mutex<HashMap<u64, ProcessHandle>>,
    next_pid: AtomicU64,
    rt_handle: tokio::runtime::Handle,
}

pub async fn register_child_process(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    let state = Arc::new(ProcessState {
        processes: std::sync::Mutex::new(HashMap::new()),
        next_pid: AtomicU64::new(1),
        rt_handle: tokio::runtime::Handle::current(),
    });

    // __cp_spawn_async(cmd, args_json, opts_json) -> sync, returns JSON {"id", "pid"}
    {
        let state = state.clone();
        let perms = perms.clone();
        engine
            .register_global_fn(
                "__cp_spawn_async",
                Box::new(move |args: &[JsValue]| {
                    let cmd = args[0].coerce_string();
                    let args_json = args
                        .get(1)
                        .map(|v| v.coerce_string())
                        .unwrap_or_else(|| "[]".to_string());
                    let opts_json = args
                        .get(2)
                        .map(|v| v.coerce_string())
                        .unwrap_or_else(|| "{}".to_string());

                    // Permission check
                    perms
                        .check_run(&cmd)
                        .map_err(|e| EngineError::JsException {
                            message: e.to_string(),
                        })?;

                    let child_args: Vec<String> =
                        serde_json::from_str(&args_json).unwrap_or_default();
                    let opts: serde_json::Value =
                        serde_json::from_str(&opts_json).unwrap_or(serde_json::Value::Null);

                    let shell = opts.get("shell").and_then(|v| v.as_bool()).unwrap_or(false);
                    let stdio = opts.get("stdio").and_then(|v| v.as_str()).unwrap_or("pipe");
                    let cwd = opts.get("cwd").and_then(|v| v.as_str()).map(String::from);
                    let env: Option<HashMap<String, String>> = opts.get("env").and_then(|v| {
                        v.as_object().map(|m| {
                            m.iter()
                                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                                .collect()
                        })
                    });

                    let mut command = if shell {
                        let mut full = cmd.clone();
                        for a in &child_args {
                            full.push(' ');
                            full.push_str(a);
                        }
                        let mut c = tokio::process::Command::new("sh");
                        c.args(["-c", &full]);
                        c
                    } else {
                        let mut c = tokio::process::Command::new(&cmd);
                        c.args(&child_args);
                        c
                    };

                    if let Some(ref dir) = cwd {
                        command.current_dir(dir);
                    }
                    if let Some(ref env_map) = env {
                        command.env_clear();
                        for (k, v) in env_map {
                            command.env(k, v);
                        }
                    }

                    match stdio {
                        "inherit" => {
                            command
                                .stdin(std::process::Stdio::inherit())
                                .stdout(std::process::Stdio::inherit())
                                .stderr(std::process::Stdio::inherit());
                        }
                        "ignore" => {
                            command
                                .stdin(std::process::Stdio::null())
                                .stdout(std::process::Stdio::null())
                                .stderr(std::process::Stdio::null());
                        }
                        _ => {
                            command
                                .stdin(std::process::Stdio::piped())
                                .stdout(std::process::Stdio::piped())
                                .stderr(std::process::Stdio::piped());
                        }
                    }

                    let mut child = command.spawn().map_err(|e| EngineError::JsException {
                        message: format!("spawn error: {e}"),
                    })?;

                    let internal_id = state.next_pid.fetch_add(1, Ordering::Relaxed);
                    let os_pid = child.id().unwrap_or(0);
                    let (event_tx, event_rx) = mpsc::unbounded_channel();

                    let stdout = child.stdout.take();
                    let stderr = child.stderr.take();
                    let child_stdin = child.stdin.take();

                    // Set up stdin writer channel if stdin is piped
                    let stdin_tx = if let Some(mut stdin) = child_stdin {
                        let (tx, mut rx) = mpsc::unbounded_channel::<Vec<u8>>();
                        state.rt_handle.spawn(async move {
                            while let Some(data) = rx.recv().await {
                                if data.is_empty() {
                                    break;
                                }
                                if stdin.write_all(&data).await.is_err() {
                                    break;
                                }
                            }
                            drop(stdin);
                        });
                        Some(tx)
                    } else {
                        None
                    };

                    // Store handle
                    {
                        let handle = ProcessHandle {
                            event_rx: Arc::new(tokio::sync::Mutex::new(event_rx)),
                            stdin_tx,
                        };
                        state.processes.lock().unwrap().insert(internal_id, handle);
                    }

                    // Spawn background task via tokio runtime handle
                    state.rt_handle.spawn(async move {
                        let tx_out = event_tx.clone();
                        let stdout_handle = stdout.map(|mut out| {
                            tokio::spawn(async move {
                                let mut buf = vec![0u8; 4096];
                                loop {
                                    match out.read(&mut buf).await {
                                        Ok(0) => break,
                                        Ok(n) => {
                                            let data =
                                                String::from_utf8_lossy(&buf[..n]).into_owned();
                                            let _ = tx_out.send(ProcessEvent {
                                                kind: "stdout",
                                                data,
                                                code: None,
                                                signal: None,
                                            });
                                        }
                                        Err(_) => break,
                                    }
                                }
                            })
                        });

                        let tx_err = event_tx.clone();
                        let stderr_handle = stderr.map(|mut err| {
                            tokio::spawn(async move {
                                let mut buf = vec![0u8; 4096];
                                loop {
                                    match err.read(&mut buf).await {
                                        Ok(0) => break,
                                        Ok(n) => {
                                            let data =
                                                String::from_utf8_lossy(&buf[..n]).into_owned();
                                            let _ = tx_err.send(ProcessEvent {
                                                kind: "stderr",
                                                data,
                                                code: None,
                                                signal: None,
                                            });
                                        }
                                        Err(_) => break,
                                    }
                                }
                            })
                        });

                        if let Some(h) = stdout_handle {
                            let _ = h.await;
                        }
                        if let Some(h) = stderr_handle {
                            let _ = h.await;
                        }

                        match child.wait().await {
                            Ok(status) => {
                                let code = status.code();
                                let signal = if code.is_none() {
                                    #[cfg(unix)]
                                    {
                                        use std::os::unix::process::ExitStatusExt;
                                        status.signal().map(signal_name)
                                    }
                                    #[cfg(not(unix))]
                                    {
                                        None::<String>
                                    }
                                } else {
                                    None
                                };
                                let _ = event_tx.send(ProcessEvent {
                                    kind: "exit",
                                    data: String::new(),
                                    code,
                                    signal,
                                });
                            }
                            Err(e) => {
                                let _ = event_tx.send(ProcessEvent {
                                    kind: "error",
                                    data: e.to_string(),
                                    code: None,
                                    signal: None,
                                });
                            }
                        }
                    });

                    let result = serde_json::json!({
                        "id": internal_id,
                        "pid": os_pid,
                    });
                    Ok(JsValue::String(result.to_string()))
                }),
            )
            .await?;
    }

    // __cp_poll_event(pid_str) -> async, returns JSON event or ""
    {
        let state = state.clone();
        engine
            .register_async_host_fn(
                "__cp_poll_event",
                Box::new(move |args| {
                    let pid: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let rx = {
                            let procs = state.processes.lock().unwrap();
                            match procs.get(&pid) {
                                Some(handle) => handle.event_rx.clone(),
                                None => return Ok(String::new()),
                            }
                        };

                        let mut rx_guard = rx.lock().await;
                        match rx_guard.recv().await {
                            Some(event) => {
                                let json = serde_json::json!({
                                    "kind": event.kind,
                                    "data": event.data,
                                    "code": event.code,
                                    "signal": event.signal,
                                });
                                Ok(json.to_string())
                            }
                            None => {
                                drop(rx_guard);
                                state.processes.lock().unwrap().remove(&pid);
                                Ok(String::new())
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __cp_kill(os_pid_str, signal) -> sync
    {
        engine
            .register_global_fn(
                "__cp_kill",
                Box::new(|args: &[JsValue]| {
                    let os_pid = args.first().map(|v| v.coerce_i32()).unwrap_or(0);
                    let signal = args
                        .get(1)
                        .map(|v| v.coerce_string())
                        .unwrap_or_else(|| "SIGTERM".to_string());
                    if os_pid == 0 {
                        return Ok(JsValue::Undefined);
                    }
                    #[cfg(unix)]
                    {
                        let sig = parse_signal(&signal);
                        unsafe {
                            libc::kill(os_pid, sig);
                        }
                    }
                    #[cfg(not(unix))]
                    {
                        let _ = (os_pid, signal);
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __cp_stdin_write(pid_str, data) -> sync
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__cp_stdin_write",
                Box::new(move |args: &[JsValue]| {
                    let pid = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let data = args.get(1).map(|v| v.coerce_string()).unwrap_or_default();
                    let procs = state.processes.lock().unwrap();
                    if let Some(handle) = procs.get(&pid)
                        && let Some(ref tx) = handle.stdin_tx
                    {
                        let _ = tx.send(data.into_bytes());
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __cp_stdin_close(pid_str) -> sync
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__cp_stdin_close",
                Box::new(move |args: &[JsValue]| {
                    let pid = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let mut procs = state.processes.lock().unwrap();
                    if let Some(handle) = procs.get_mut(&pid)
                        && let Some(tx) = handle.stdin_tx.take()
                    {
                        let _ = tx.send(Vec::new());
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __check_run_permission(cmd) -> sync permission check for JS shim
    {
        let perms = perms.clone();
        engine
            .register_global_fn(
                "__check_run_permission",
                Box::new(move |args: &[JsValue]| {
                    let cmd = args.first().map(|v| v.coerce_string()).unwrap_or_default();
                    perms
                        .check_run(&cmd)
                        .map_err(|e| EngineError::JsException {
                            message: e.to_string(),
                        })?;
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    Ok(())
}

#[cfg(unix)]
fn signal_name(sig: i32) -> String {
    match sig {
        1 => "SIGHUP".into(),
        2 => "SIGINT".into(),
        3 => "SIGQUIT".into(),
        6 => "SIGABRT".into(),
        9 => "SIGKILL".into(),
        11 => "SIGSEGV".into(),
        13 => "SIGPIPE".into(),
        14 => "SIGALRM".into(),
        15 => "SIGTERM".into(),
        _ => format!("SIG{sig}"),
    }
}

#[cfg(unix)]
fn parse_signal(name: &str) -> i32 {
    match name {
        "SIGHUP" => libc::SIGHUP,
        "SIGINT" => libc::SIGINT,
        "SIGQUIT" => libc::SIGQUIT,
        "SIGABRT" => libc::SIGABRT,
        "SIGKILL" => libc::SIGKILL,
        "SIGSEGV" => libc::SIGSEGV,
        "SIGPIPE" => libc::SIGPIPE,
        "SIGALRM" => libc::SIGALRM,
        "SIGTERM" => libc::SIGTERM,
        _ => libc::SIGTERM,
    }
}
