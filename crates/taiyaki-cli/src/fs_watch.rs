use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use notify_debouncer_mini::new_debouncer;
use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use tokio::sync::mpsc;

struct WatchEventData {
    event_type: String,
    filename: String,
}

struct WatcherHandle {
    _debouncer: notify_debouncer_mini::Debouncer<notify::RecommendedWatcher>,
    event_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<WatchEventData>>>,
}

struct FsWatchState {
    watchers: std::sync::Mutex<HashMap<u64, WatcherHandle>>,
    next_id: AtomicU64,
}

pub async fn register_fs_watch(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    let state = Arc::new(FsWatchState {
        watchers: std::sync::Mutex::new(HashMap::new()),
        next_id: AtomicU64::new(1),
    });

    // __fs_watch_start(path, recursive) -> watcher_id string (SYNC)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__fs_watch_start",
                Box::new(move |args: &[JsValue]| {
                    let path = args.first().map(|v| v.coerce_string()).unwrap_or_default();
                    let recursive = args.get(1).map(|v| v.coerce_bool()).unwrap_or(false);

                    let state = state.clone();
                    let watched_path = PathBuf::from(&path);
                    let (event_tx, event_rx) = mpsc::unbounded_channel::<WatchEventData>();

                    // Canonicalize to handle symlinks (e.g., /tmp -> /private/tmp on macOS)
                    let base_path = watched_path.canonicalize().unwrap_or(watched_path.clone());
                    let debouncer = new_debouncer(
                        std::time::Duration::from_millis(300),
                        move |res: Result<
                            Vec<notify_debouncer_mini::DebouncedEvent>,
                            notify::Error,
                        >| {
                            if let Ok(events) = res {
                                for event in events {
                                    let file_path = &event.path;
                                    let filename = file_path
                                        .strip_prefix(&base_path)
                                        .unwrap_or(file_path)
                                        .to_string_lossy()
                                        .into_owned();
                                    let event_type = if file_path.exists() {
                                        "change"
                                    } else {
                                        "rename"
                                    };
                                    let _ = event_tx.send(WatchEventData {
                                        event_type: event_type.to_string(),
                                        filename,
                                    });
                                }
                            }
                        },
                    );

                    let mut debouncer = debouncer.map_err(|e| EngineError::JsException {
                        message: format!("watcher error: {e}"),
                    })?;

                    let mode = if recursive {
                        notify::RecursiveMode::Recursive
                    } else {
                        notify::RecursiveMode::NonRecursive
                    };

                    debouncer
                        .watcher()
                        .watch(&watched_path, mode)
                        .map_err(|e| EngineError::JsException {
                            message: format!("watch error: {e}"),
                        })?;

                    let id = state.next_id.fetch_add(1, Ordering::Relaxed);
                    let handle = WatcherHandle {
                        _debouncer: debouncer,
                        event_rx: Arc::new(tokio::sync::Mutex::new(event_rx)),
                    };
                    state.watchers.lock().unwrap().insert(id, handle);

                    Ok(JsValue::String(id.to_string()))
                }),
            )
            .await?;
    }

    // __fs_watch_poll(watcher_id) -> JSON event or "" (ASYNC)
    {
        let state = state.clone();
        engine
            .register_async_host_fn(
                "__fs_watch_poll",
                Box::new(move |args| {
                    let id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let rx = {
                            let watchers = state.watchers.lock().unwrap();
                            match watchers.get(&id) {
                                Some(handle) => handle.event_rx.clone(),
                                None => return Ok(String::new()),
                            }
                        };

                        let mut rx_guard = rx.lock().await;
                        match rx_guard.recv().await {
                            Some(event) => {
                                let json = serde_json::json!({
                                    "eventType": event.event_type,
                                    "filename": event.filename,
                                });
                                Ok(json.to_string())
                            }
                            None => Ok(String::new()),
                        }
                    })
                }),
            )
            .await?;
    }

    // __fs_watch_close(watcher_id) -> void (SYNC)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__fs_watch_close",
                Box::new(move |args: &[JsValue]| {
                    let id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    state.watchers.lock().unwrap().remove(&id);
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    Ok(())
}
