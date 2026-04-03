use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use taiyaki_core::permissions::Permissions;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;

// --- State types ---

struct SocketEvent {
    kind: &'static str, // "data" | "end" | "error" | "close"
    data: String,       // base64 for "data", error message for "error", empty otherwise
}

struct SocketHandle {
    read_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<SocketEvent>>>,
    write_tx: mpsc::UnboundedSender<Vec<u8>>,
    local_addr: String,
    remote_addr: String,
}

struct ServerHandle {
    accept_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<u64>>>,
    shutdown_tx: tokio::sync::watch::Sender<bool>,
    #[allow(dead_code)]
    local_addr: String,
}

pub struct NetState {
    sockets: std::sync::Mutex<HashMap<u64, SocketHandle>>,
    servers: std::sync::Mutex<HashMap<u64, ServerHandle>>,
    next_id: AtomicU64,
    rt_handle: tokio::runtime::Handle,
}

impl NetState {
    pub fn new() -> Self {
        Self {
            sockets: std::sync::Mutex::new(HashMap::new()),
            servers: std::sync::Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
            rt_handle: tokio::runtime::Handle::current(),
        }
    }

    /// Insert a TcpStream, spawning read/write background tasks.
    pub fn insert_stream(self: &Arc<Self>, stream: TcpStream) -> u64 {
        let local_addr = stream
            .local_addr()
            .map(|a| a.to_string())
            .unwrap_or_default();
        let remote_addr = stream
            .peer_addr()
            .map(|a| a.to_string())
            .unwrap_or_default();
        let (read_half, write_half) = stream.into_split();
        self.insert_split_stream_inner(read_half, write_half, local_addr, remote_addr)
    }

    /// Insert generic AsyncRead + AsyncWrite halves (used by TLS).
    pub fn insert_split_stream<R, W>(
        self: &Arc<Self>,
        read_half: R,
        write_half: W,
        local_addr: String,
        remote_addr: String,
    ) -> u64
    where
        R: AsyncRead + Unpin + Send + 'static,
        W: AsyncWrite + Unpin + Send + 'static,
    {
        self.insert_split_stream_inner(read_half, write_half, local_addr, remote_addr)
    }

    fn insert_split_stream_inner<R, W>(
        self: &Arc<Self>,
        read_half: R,
        write_half: W,
        local_addr: String,
        remote_addr: String,
    ) -> u64
    where
        R: AsyncRead + Unpin + Send + 'static,
        W: AsyncWrite + Unpin + Send + 'static,
    {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (event_tx, event_rx) = mpsc::unbounded_channel();
        let (write_tx, write_rx) = mpsc::unbounded_channel::<Vec<u8>>();

        // Read task
        self.rt_handle.spawn(async move {
            let mut read_half = read_half;
            let mut buf = vec![0u8; 8192];
            loop {
                match read_half.read(&mut buf).await {
                    Ok(0) => {
                        let _ = event_tx.send(SocketEvent {
                            kind: "end",
                            data: String::new(),
                        });
                        break;
                    }
                    Ok(n) => {
                        use base64::Engine as _;
                        let b64 = base64::engine::general_purpose::STANDARD.encode(&buf[..n]);
                        let _ = event_tx.send(SocketEvent {
                            kind: "data",
                            data: b64,
                        });
                    }
                    Err(e) => {
                        let _ = event_tx.send(SocketEvent {
                            kind: "error",
                            data: e.to_string(),
                        });
                        break;
                    }
                }
            }
            let _ = event_tx.send(SocketEvent {
                kind: "close",
                data: String::new(),
            });
        });

        // Write task
        self.rt_handle.spawn(async move {
            let mut write_half = write_half;
            let mut write_rx = write_rx;
            while let Some(data) = write_rx.recv().await {
                if data.is_empty() {
                    break; // close signal
                }
                if write_half.write_all(&data).await.is_err() {
                    break;
                }
            }
            let _ = write_half.shutdown().await;
        });

        self.sockets.lock().unwrap().insert(
            id,
            SocketHandle {
                read_rx: Arc::new(tokio::sync::Mutex::new(event_rx)),
                write_tx,
                local_addr,
                remote_addr,
            },
        );
        id
    }

    /// Create a TCP server, spawning an accept loop.
    pub fn insert_server(self: &Arc<Self>, listener: TcpListener) -> (u64, String) {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let local_addr = listener
            .local_addr()
            .map(|a| a.to_string())
            .unwrap_or_default();
        let (accept_tx, accept_rx) = mpsc::unbounded_channel::<u64>();
        let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);

        let state = self.clone();
        self.rt_handle.spawn(async move {
            loop {
                tokio::select! {
                    result = listener.accept() => {
                        match result {
                            Ok((stream, _addr)) => {
                                let socket_id = state.insert_stream(stream);
                                if accept_tx.send(socket_id).is_err() {
                                    break;
                                }
                            }
                            Err(_) => break,
                        }
                    }
                    _ = shutdown_rx.changed() => {
                        break;
                    }
                }
            }
        });

        self.servers.lock().unwrap().insert(
            id,
            ServerHandle {
                accept_rx: Arc::new(tokio::sync::Mutex::new(accept_rx)),
                shutdown_tx,
                local_addr: local_addr.clone(),
            },
        );
        (id, local_addr)
    }

    /// Create a TLS server, spawning an accept loop that performs TLS handshake.
    #[allow(dead_code)]
    pub fn insert_tls_server(
        self: &Arc<Self>,
        listener: TcpListener,
        acceptor: tokio_rustls::TlsAcceptor,
    ) -> (u64, String) {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let local_addr = listener
            .local_addr()
            .map(|a| a.to_string())
            .unwrap_or_default();
        let (accept_tx, accept_rx) = mpsc::unbounded_channel::<u64>();
        let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);

        let state = self.clone();
        self.rt_handle.spawn(async move {
            loop {
                tokio::select! {
                    result = listener.accept() => {
                        match result {
                            Ok((stream, addr)) => {
                                let acceptor = acceptor.clone();
                                let state = state.clone();
                                let accept_tx = accept_tx.clone();
                                let local = stream.local_addr().map(|a| a.to_string()).unwrap_or_default();
                                let remote = addr.to_string();
                                tokio::spawn(async move {
                                    match acceptor.accept(stream).await {
                                        Ok(tls_stream) => {
                                            let (read_half, write_half) = tokio::io::split(tls_stream);
                                            let socket_id = state.insert_split_stream(read_half, write_half, local, remote);
                                            let _ = accept_tx.send(socket_id);
                                        }
                                        Err(_) => {}
                                    }
                                });
                            }
                            Err(_) => break,
                        }
                    }
                    _ = shutdown_rx.changed() => {
                        break;
                    }
                }
            }
        });

        self.servers.lock().unwrap().insert(
            id,
            ServerHandle {
                accept_rx: Arc::new(tokio::sync::Mutex::new(accept_rx)),
                shutdown_tx,
                local_addr: local_addr.clone(),
            },
        );
        (id, local_addr)
    }
}

// --- Registration ---

pub async fn register_net(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
    net_state: &Arc<NetState>,
) -> Result<(), EngineError> {
    // __net_connect(host, port) -> async, returns JSON {"id", "localAddr", "remoteAddr"}
    {
        let perms = perms.clone();
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__net_connect",
                Box::new(move |args| {
                    let host = args.first().cloned().unwrap_or_default();
                    let port: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
                    let perms = perms.clone();
                    let state = state.clone();
                    Box::pin(async move {
                        perms.check_net(&host).map_err(|e| e.to_string())?;
                        let stream = TcpStream::connect(format!("{host}:{port}"))
                            .await
                            .map_err(|e| format!("connect {host}:{port}: {e}"))?;
                        let local_addr = stream
                            .local_addr()
                            .map(|a| a.to_string())
                            .unwrap_or_default();
                        let remote_addr = stream
                            .peer_addr()
                            .map(|a| a.to_string())
                            .unwrap_or_default();
                        let id = state.insert_stream(stream);
                        let json = serde_json::json!({
                            "id": id,
                            "localAddr": local_addr,
                            "remoteAddr": remote_addr,
                        });
                        Ok(json.to_string())
                    })
                }),
            )
            .await?;
    }

    // __net_listen(port, host) -> async, returns JSON {"id", "address", "port"}
    {
        let perms = perms.clone();
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__net_listen",
                Box::new(move |args| {
                    let port: u32 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let host = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    let state = state.clone();
                    Box::pin(async move {
                        perms.check_net(&host).map_err(|e| e.to_string())?;
                        let listener = TcpListener::bind(format!("{host}:{port}"))
                            .await
                            .map_err(|e| format!("listen {host}:{port}: {e}"))?;
                        let actual_port = listener.local_addr().unwrap().port();
                        let (id, _addr) = state.insert_server(listener);
                        let json = serde_json::json!({
                            "id": id,
                            "address": host,
                            "port": actual_port,
                        });
                        Ok(json.to_string())
                    })
                }),
            )
            .await?;
    }

    // __net_accept(server_id) -> async, returns socket_id as string or "" on close
    {
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__net_accept",
                Box::new(move |args| {
                    let server_id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let rx = {
                            let servers = state.servers.lock().unwrap();
                            match servers.get(&server_id) {
                                Some(h) => h.accept_rx.clone(),
                                None => return Ok(String::new()),
                            }
                        };
                        let mut rx_guard = rx.lock().await;
                        match rx_guard.recv().await {
                            Some(socket_id) => Ok(socket_id.to_string()),
                            None => Ok(String::new()),
                        }
                    })
                }),
            )
            .await?;
    }

    // __net_read(socket_id) -> async, returns event JSON or "" on gone
    {
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__net_read",
                Box::new(move |args| {
                    let socket_id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let rx = {
                            let sockets = state.sockets.lock().unwrap();
                            match sockets.get(&socket_id) {
                                Some(h) => h.read_rx.clone(),
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
                                Ok(json.to_string())
                            }
                            None => {
                                drop(rx_guard);
                                state.sockets.lock().unwrap().remove(&socket_id);
                                Ok(String::new())
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __net_write(socket_id, data_b64) -> sync
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_write",
                Box::new(move |args: &[JsValue]| {
                    let socket_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let data_b64 = args.get(1).map(|v| v.coerce_string()).unwrap_or_default();
                    let sockets = state.sockets.lock().unwrap();
                    if let Some(handle) = sockets.get(&socket_id) {
                        use base64::Engine as _;
                        if let Ok(bytes) =
                            base64::engine::general_purpose::STANDARD.decode(&data_b64)
                        {
                            let _ = handle.write_tx.send(bytes);
                        }
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __net_close(socket_id) -> sync
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_close",
                Box::new(move |args: &[JsValue]| {
                    let socket_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let handle = state.sockets.lock().unwrap().remove(&socket_id);
                    if let Some(h) = handle {
                        let _ = h.write_tx.send(Vec::new());
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __net_shutdown(socket_id) -> sync, half-close
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_shutdown",
                Box::new(move |args: &[JsValue]| {
                    let socket_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let sockets = state.sockets.lock().unwrap();
                    if let Some(handle) = sockets.get(&socket_id) {
                        let _ = handle.write_tx.send(Vec::new());
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __net_server_close(server_id) -> sync
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_server_close",
                Box::new(move |args: &[JsValue]| {
                    let server_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let handle = state.servers.lock().unwrap().remove(&server_id);
                    if let Some(h) = handle {
                        let _ = h.shutdown_tx.send(true);
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __net_local_addr(socket_id) -> sync, returns address string
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_local_addr",
                Box::new(move |args: &[JsValue]| {
                    let socket_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let sockets = state.sockets.lock().unwrap();
                    let addr = sockets
                        .get(&socket_id)
                        .map(|h| h.local_addr.clone())
                        .unwrap_or_default();
                    Ok(JsValue::String(addr))
                }),
            )
            .await?;
    }

    // __net_remote_addr(socket_id) -> sync, returns address string
    {
        let state = net_state.clone();
        engine
            .register_global_fn(
                "__net_remote_addr",
                Box::new(move |args: &[JsValue]| {
                    let socket_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let sockets = state.sockets.lock().unwrap();
                    let addr = sockets
                        .get(&socket_id)
                        .map(|h| h.remote_addr.clone())
                        .unwrap_or_default();
                    Ok(JsValue::String(addr))
                }),
            )
            .await?;
    }

    Ok(())
}
