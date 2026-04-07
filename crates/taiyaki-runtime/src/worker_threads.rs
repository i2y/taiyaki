use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use taiyaki_core::permissions::Permissions;
use tokio::sync::mpsc;

use crate::util::require_str;

struct WorkerEvent {
    kind: &'static str, // "message", "error", "exit"
    data: String,
}

struct WorkerHandle {
    msg_tx: mpsc::UnboundedSender<String>,
    event_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<WorkerEvent>>>,
    _join_handle: std::thread::JoinHandle<()>,
}

struct WorkerState {
    workers: std::sync::Mutex<HashMap<u64, WorkerHandle>>,
    next_id: AtomicU64,
    script_dir: PathBuf,
    permissions: Arc<Permissions>,
}

pub async fn register_worker_threads(
    engine: &impl AsyncJsEngine,
    script_path: &Path,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    let state = Arc::new(WorkerState {
        workers: std::sync::Mutex::new(HashMap::new()),
        next_id: AtomicU64::new(1),
        script_dir: script_path.parent().unwrap_or(Path::new(".")).to_path_buf(),
        permissions: perms.clone(),
    });

    // __worker_spawn(script_path, worker_data_json) -> JSON {id, threadId}
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__worker_spawn",
                Box::new(move |args: &[JsValue]| {
                    let script_rel = require_str(args, 0);
                    let worker_data_json = require_str(args, 1);

                    let worker_id = state.next_id.fetch_add(1, Ordering::Relaxed);
                    let thread_id = worker_id;

                    // Resolve script path relative to parent script directory
                    let script_path = if Path::new(&script_rel).is_absolute() {
                        PathBuf::from(&script_rel)
                    } else {
                        state.script_dir.join(&script_rel)
                    };

                    // Channels
                    let (main_to_worker_tx, main_to_worker_rx) =
                        mpsc::unbounded_channel::<String>();
                    let (worker_to_main_tx, worker_to_main_rx) =
                        mpsc::unbounded_channel::<WorkerEvent>();

                    let perms = state.permissions.clone();
                    let script_path_clone = script_path.clone();

                    let join_handle = std::thread::spawn(move || {
                        run_worker(
                            script_path_clone,
                            worker_data_json,
                            thread_id,
                            perms,
                            main_to_worker_rx,
                            worker_to_main_tx,
                        );
                    });

                    state.workers.lock().unwrap().insert(
                        worker_id,
                        WorkerHandle {
                            msg_tx: main_to_worker_tx,
                            event_rx: Arc::new(tokio::sync::Mutex::new(worker_to_main_rx)),
                            _join_handle: join_handle,
                        },
                    );

                    Ok(JsValue::String(
                        serde_json::json!({"id": worker_id, "threadId": thread_id}).to_string(),
                    ))
                }),
            )
            .await?;
    }

    // __worker_post_message(worker_id, message_json)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__worker_post_message",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let msg = require_str(args, 1);
                    let workers = state.workers.lock().unwrap();
                    if let Some(handle) = workers.get(&id) {
                        let _ = handle.msg_tx.send(msg);
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __worker_poll_event(worker_id) -> async, JSON string or empty
    {
        let state = state.clone();
        engine
            .register_async_host_fn(
                "__worker_poll_event",
                Box::new(move |args| {
                    let id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let rx = {
                            let workers = state.workers.lock().unwrap();
                            match workers.get(&id) {
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
                                });
                                // Clean up on exit
                                if event.kind == "exit" {
                                    drop(rx_guard);
                                    state.workers.lock().unwrap().remove(&id);
                                }
                                Ok(json.to_string())
                            }
                            None => {
                                drop(rx_guard);
                                state.workers.lock().unwrap().remove(&id);
                                Ok(String::new())
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __worker_terminate(worker_id)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__worker_terminate",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    // Dropping the sender will cause the worker's recv to return None
                    state.workers.lock().unwrap().remove(&id);
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    Ok(())
}

fn run_worker(
    script_path: PathBuf,
    worker_data_json: String,
    thread_id: u64,
    perms: Arc<Permissions>,
    main_to_worker_rx: mpsc::UnboundedReceiver<String>,
    worker_to_main_tx: mpsc::UnboundedSender<WorkerEvent>,
) {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("worker tokio runtime");

    let tx = worker_to_main_tx.clone();

    rt.block_on(async move {
        let result = run_worker_inner(
            &script_path,
            &worker_data_json,
            thread_id,
            &perms,
            main_to_worker_rx,
            &worker_to_main_tx,
        )
        .await;

        match result {
            Ok(()) => {
                let _ = tx.send(WorkerEvent {
                    kind: "exit",
                    data: "0".into(),
                });
            }
            Err(e) => {
                let _ = tx.send(WorkerEvent {
                    kind: "error",
                    data: e.to_string(),
                });
                let _ = tx.send(WorkerEvent {
                    kind: "exit",
                    data: "1".into(),
                });
            }
        }
    });
}

async fn run_worker_inner(
    script_path: &Path,
    worker_data_json: &str,
    thread_id: u64,
    perms: &Arc<Permissions>,
    main_to_worker_rx: mpsc::UnboundedReceiver<String>,
    worker_to_main_tx: &mpsc::UnboundedSender<WorkerEvent>,
) -> Result<(), Box<dyn std::error::Error>> {
    let engine = crate::Engine::new().await?;

    let script_dir = script_path.parent().unwrap_or(Path::new("."));
    engine.enable_file_loader(script_dir).await;

    // Bootstrap all builtins/polyfills
    crate::bootstrap_engine(&engine, script_path, &[], perms).await?;

    // Register worker-side host functions
    register_worker_child_fns(&engine, main_to_worker_rx, worker_to_main_tx.clone()).await?;

    // Set worker-specific globals — use JSON.parse with a JSON-encoded string
    // to safely embed arbitrary workerData without JS injection concerns.
    let json_str_literal =
        serde_json::to_string(worker_data_json).unwrap_or_else(|_| "\"null\"".into());
    let shim = format!(
        r#"(function() {{
    var _s = globalThis.__worker_threads_state || {{}};
    _s.isMainThread = false;
    _s.threadId = {thread_id};
    try {{ _s.workerData = JSON.parse({json_str_literal}); }} catch(e) {{ _s.workerData = undefined; }}
    globalThis.__worker_threads_state = _s;
}})();"#,
    );
    engine.eval(&shim).await?;

    // Read and execute worker script
    let raw_source = std::fs::read_to_string(script_path)
        .map_err(|e| format!("Worker script read failed: {e}"))?;
    let source = crate::strip_shebang(&raw_source);

    let ext = script_path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("");
    let code = match ext {
        "tsx" | "jsx" => taiyaki_core::transpiler::transform_jsx(source, &Default::default())?,
        "ts" => taiyaki_core::transpiler::strip_types(source)?,
        _ => source.to_string(),
    };

    let is_module = crate::has_module_syntax(&code);
    if is_module {
        let name = script_path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("worker");
        engine.eval_module_async(&code, name).await?;
    } else {
        engine.eval_async(&code).await?;
    }

    Ok(())
}

async fn register_worker_child_fns(
    engine: &crate::Engine,
    main_to_worker_rx: mpsc::UnboundedReceiver<String>,
    worker_to_main_tx: mpsc::UnboundedSender<WorkerEvent>,
) -> Result<(), EngineError> {
    // __worker_parent_post(message_json) — sync
    {
        let tx = worker_to_main_tx;
        engine
            .register_global_fn(
                "__worker_parent_post",
                Box::new(move |args: &[JsValue]| {
                    let msg = require_str(args, 0);
                    let _ = tx.send(WorkerEvent {
                        kind: "message",
                        data: msg,
                    });
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __worker_parent_poll() — async
    {
        let rx = Arc::new(tokio::sync::Mutex::new(main_to_worker_rx));
        engine
            .register_async_host_fn(
                "__worker_parent_poll",
                Box::new(move |_args| {
                    let rx = rx.clone();
                    Box::pin(async move {
                        let mut rx_guard = rx.lock().await;
                        match rx_guard.recv().await {
                            Some(msg) => Ok(msg),
                            None => Ok(String::new()),
                        }
                    })
                }),
            )
            .await?;
    }

    Ok(())
}
