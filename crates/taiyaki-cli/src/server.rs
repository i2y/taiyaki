use std::collections::HashMap;
use std::convert::Infallible;
use std::sync::Arc;

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode};
use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use tokio::net::TcpListener;
use tokio::sync::{Mutex, mpsc, oneshot};

struct HttpRequest {
    id: u64,
    method: String,
    url: String,
    headers_json: String,
    body: String,
    is_upgrade: bool,
}

struct HttpResponse {
    status: u16,
    headers: HashMap<String, String>,
    body: String,
}

enum WsEventKind {
    Open,
    Message,
    Close,
    Error,
}

impl WsEventKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Message => "message",
            Self::Close => "close",
            Self::Error => "error",
        }
    }
}

struct WsEvent {
    kind: WsEventKind,
    conn_id: u64,
    data: String,
}

struct WsConn {
    tx: mpsc::UnboundedSender<tungstenite::Message>,
}

/// Shared server state passed as `Arc<ServerState>` to each connection handler.
struct ServerState {
    tx: mpsc::UnboundedSender<HttpRequest>,
    pending: std::sync::Mutex<HashMap<u64, oneshot::Sender<HttpResponse>>>,
    next_id: std::sync::atomic::AtomicU64,
    ws_event_tx: mpsc::UnboundedSender<WsEvent>,
    ws_conns: std::sync::Mutex<HashMap<u64, WsConn>>,
    ws_next_conn_id: std::sync::atomic::AtomicU64,
    upgrade_map: std::sync::Mutex<HashMap<u64, oneshot::Sender<bool>>>,
}

fn build_hyper_response(resp: HttpResponse) -> Response<Full<Bytes>> {
    let mut builder = Response::builder()
        .status(StatusCode::from_u16(resp.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR));
    for (k, v) in &resp.headers {
        builder = builder.header(k.as_str(), v.as_str());
    }
    builder
        .body(Full::new(Bytes::from(resp.body)))
        .unwrap_or_else(|_| {
            Response::builder()
                .status(500)
                .body(Full::new(Bytes::from("Internal Server Error")))
                .unwrap()
        })
}

pub async fn register_server(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    let (tx, rx) = mpsc::unbounded_channel::<HttpRequest>();
    let rx = Arc::new(Mutex::new(rx));

    let (ws_event_tx, ws_event_rx) = mpsc::unbounded_channel::<WsEvent>();
    let ws_event_rx = Arc::new(Mutex::new(ws_event_rx));

    let state = Arc::new(ServerState {
        tx,
        pending: std::sync::Mutex::new(HashMap::new()),
        next_id: std::sync::atomic::AtomicU64::new(1),
        ws_event_tx,
        ws_conns: std::sync::Mutex::new(HashMap::new()),
        ws_next_conn_id: std::sync::atomic::AtomicU64::new(1),
        upgrade_map: std::sync::Mutex::new(HashMap::new()),
    });

    let shutdown_tx: Arc<std::sync::Mutex<Option<tokio::sync::watch::Sender<bool>>>> =
        Arc::new(std::sync::Mutex::new(None));

    let (stop_notify_tx, stop_notify_rx) = tokio::sync::watch::channel(false);
    let stop_notify_tx = Arc::new(std::sync::Mutex::new(Some(stop_notify_tx)));

    // __serve_start(port) -> async, returns actual port as string
    {
        let state = state.clone();
        let shutdown_tx = shutdown_tx.clone();
        engine
            .register_async_host_fn(
                "__serve_start",
                Box::new(move |args| {
                    let port: u32 = args.first().and_then(|s| s.parse().ok()).unwrap_or(3000);
                    let state = state.clone();
                    let shutdown_tx = shutdown_tx.clone();
                    Box::pin(async move {
                        let addr = format!("0.0.0.0:{port}");
                        let listener = TcpListener::bind(&addr)
                            .await
                            .map_err(|e| format!("bind error: {e}"))?;
                        let actual_port = listener.local_addr().unwrap().port();

                        let (stop_tx, stop_rx) = tokio::sync::watch::channel(false);
                        {
                            let mut guard = shutdown_tx.lock().unwrap();
                            *guard = Some(stop_tx);
                        }

                        tokio::spawn(async move {
                            loop {
                                let mut stop = stop_rx.clone();
                                tokio::select! {
                                    result = listener.accept() => {
                                        match result {
                                            Ok((stream, _)) => {
                                                let state = state.clone();
                                                let io = hyper_util::rt::TokioIo::new(stream);
                                                tokio::spawn(async move {
                                                    let svc = service_fn(move |req: Request<Incoming>| {
                                                        let state = state.clone();
                                                        async move { handle_request(req, state).await }
                                                    });
                                                    let _ = http1::Builder::new()
                                                        .serve_connection(io, svc)
                                                        .with_upgrades()
                                                        .await;
                                                });
                                            }
                                            Err(_) => break,
                                        }
                                    }
                                    _ = stop.changed() => {
                                        break;
                                    }
                                }
                            }
                        });

                        Ok(actual_port.to_string())
                    })
                }),
            )
            .await?;
    }

    // __serve_next_request() -> async, returns JSON or ""
    {
        let rx_next = rx.clone();
        let stop_rx = stop_notify_rx.clone();
        engine
            .register_async_host_fn(
                "__serve_next_request",
                Box::new(move |_args| {
                    let rx = rx_next.clone();
                    let mut stop = stop_rx.clone();
                    Box::pin(async move {
                        tokio::select! {
                            result = async {
                                let mut guard = rx.lock().await;
                                guard.recv().await
                            } => {
                                match result {
                                    Some(req) => {
                                        let json = serde_json::json!({
                                            "id": req.id,
                                            "method": req.method,
                                            "url": req.url,
                                            "headers": req.headers_json,
                                            "body": req.body,
                                            "upgrade": req.is_upgrade,
                                        });
                                        Ok(json.to_string())
                                    }
                                    None => Ok(String::new()),
                                }
                            }
                            _ = stop.changed() => {
                                Ok(String::new())
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __serve_respond(id, status, headers_json, body) -> sync
    {
        let state_respond = state.clone();
        engine
            .register_global_fn(
                "__serve_respond",
                Box::new(move |args: &[JsValue]| {
                    let id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let status = args.get(1).map(|v| v.coerce_u16()).unwrap_or(200);
                    let headers_json = args
                        .get(2)
                        .map(|v| v.coerce_string())
                        .unwrap_or_else(|| "{}".to_string());
                    let body = args.get(3).map(|v| v.coerce_string()).unwrap_or_default();
                    let headers: HashMap<String, String> =
                        serde_json::from_str(&headers_json).unwrap_or_default();
                    let mut map = state_respond.pending.lock().unwrap();
                    if let Some(tx) = map.remove(&id) {
                        let _ = tx.send(HttpResponse {
                            status,
                            headers,
                            body,
                        });
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __serve_stop() -> sync
    {
        let shutdown = shutdown_tx.clone();
        let stop_notifier = stop_notify_tx.clone();
        engine
            .register_global_fn(
                "__serve_stop",
                Box::new(move |_args: &[JsValue]| {
                    let mut guard = shutdown.lock().unwrap();
                    if let Some(tx) = guard.take() {
                        let _ = tx.send(true);
                    }
                    let mut sn = stop_notifier.lock().unwrap();
                    if let Some(tx) = sn.take() {
                        let _ = tx.send(true);
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __ws_upgrade(reqId) -> sync, returns bool
    {
        let state_upgrade = state.clone();
        engine
            .register_global_fn(
                "__ws_upgrade",
                Box::new(move |args: &[JsValue]| {
                    let req_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let mut map = state_upgrade.upgrade_map.lock().unwrap();
                    if let Some(tx) = map.remove(&req_id) {
                        let _ = tx.send(true);
                        Ok(JsValue::Bool(true))
                    } else {
                        Ok(JsValue::Bool(false))
                    }
                }),
            )
            .await?;
    }

    // __ws_next_event() -> async, returns JSON or ""
    {
        let ws_rx = ws_event_rx.clone();
        let ws_stop = stop_notify_rx.clone();
        engine
            .register_async_host_fn(
                "__ws_next_event",
                Box::new(move |_args| {
                    let rx = ws_rx.clone();
                    let mut stop = ws_stop.clone();
                    Box::pin(async move {
                        tokio::select! {
                            result = async {
                                let mut guard = rx.lock().await;
                                guard.recv().await
                            } => {
                                match result {
                                    Some(ev) => {
                                        let json = serde_json::json!({
                                            "kind": ev.kind.as_str(),
                                            "connId": ev.conn_id,
                                            "data": ev.data,
                                        });
                                        Ok(json.to_string())
                                    }
                                    None => Ok(String::new()),
                                }
                            }
                            _ = stop.changed() => {
                                Ok(String::new())
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __ws_send(connId, data) -> sync
    {
        let state_ws_send = state.clone();
        engine
            .register_global_fn(
                "__ws_send",
                Box::new(move |args: &[JsValue]| {
                    let conn_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let data = args.get(1).map(|v| v.coerce_string()).unwrap_or_default();
                    let conns = state_ws_send.ws_conns.lock().unwrap();
                    if let Some(conn) = conns.get(&conn_id) {
                        let _ = conn.tx.send(tungstenite::Message::Text(data.into()));
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __ws_close(connId) -> sync
    {
        let state_ws_close = state.clone();
        engine
            .register_global_fn(
                "__ws_close",
                Box::new(move |args: &[JsValue]| {
                    let conn_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let conns = state_ws_close.ws_conns.lock().unwrap();
                    if let Some(conn) = conns.get(&conn_id) {
                        let _ = conn.tx.send(tungstenite::Message::Close(None));
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // JS glue
    engine
        .eval(
            r#"globalThis.Katana = globalThis.Katana || {};
Katana.serve = async function(opts) {
    var port = (opts.port !== undefined && opts.port !== null) ? opts.port : 3000;
    var actualPort = Number(await __serve_start(port));
    var handler = opts.fetch;
    var wsHandlers = opts.websocket || null;

    var __wsConns = {};

    async function processLoop() {
        while (globalThis.__serverRunning) {
            var reqJSON = await __serve_next_request();
            if (!reqJSON) break;
            handleRequest(reqJSON).catch(function(e) {
                console.error('Unhandled server error:', e);
            });
        }
    }

    async function handleRequest(reqJSON) {
        var raw = JSON.parse(reqJSON);
        var reqHeaders = typeof raw.headers === 'string' ? JSON.parse(raw.headers) : raw.headers;
        var req = new Request('http://localhost:' + actualPort + raw.url, {
            method: raw.method,
            headers: reqHeaders,
            body: (raw.method !== 'GET' && raw.method !== 'HEAD' && raw.body) ? raw.body : undefined,
        });
        req._reqId = raw.id;
        try {
            var response = await handler(req, server);
            if (response === undefined && raw.upgrade) return;
            if (!(response instanceof Response)) {
                response = new Response(String(response || ''), { status: 200 });
            }
            var body = '';
            if (!response._bodyUsed && response._body != null) {
                body = String(response._body);
            }
            __serve_respond(raw.id, response.status, JSON.stringify(response.headers.toObject()), body);
        } catch(e) {
            __serve_respond(raw.id, 500, '{}', String(e));
        }
    }

    async function wsEventLoop() {
        while (globalThis.__serverRunning) {
            var evJSON = await __ws_next_event();
            if (!evJSON) break;
            var ev = JSON.parse(evJSON);
            if (ev.kind === 'open') {
                var ws = { _id: ev.connId, data: null, readyState: 1, send: function(msg) { __ws_send(this._id, String(msg)); }, close: function() { this.readyState = 3; __ws_close(this._id); } };
                __wsConns[ev.connId] = ws;
                if (wsHandlers && wsHandlers.open) try { wsHandlers.open(ws); } catch(e) {}
            } else if (ev.kind === 'message') {
                var ws = __wsConns[ev.connId];
                if (ws && wsHandlers && wsHandlers.message) try { wsHandlers.message(ws, ev.data); } catch(e) {}
            } else if (ev.kind === 'close') {
                var ws = __wsConns[ev.connId];
                if (ws) { ws.readyState = 3; if (wsHandlers && wsHandlers.close) try { wsHandlers.close(ws); } catch(e) {} delete __wsConns[ev.connId]; }
            } else if (ev.kind === 'error') {
                var ws = __wsConns[ev.connId];
                if (ws && wsHandlers && wsHandlers.error) try { wsHandlers.error(ws, new Error(ev.data)); } catch(e) {}
            }
        }
    }

    globalThis.__serverRunning = true;
    processLoop();
    if (wsHandlers) wsEventLoop();

    var server = {
        port: actualPort,
        hostname: 'localhost',
        upgrade: function(req) {
            if (!req._reqId) return false;
            return __ws_upgrade(req._reqId);
        },
        stop: function() {
            globalThis.__serverRunning = false;
            __serve_stop();
        }
    };
    return server;
};"#,
        )
        .await?;

    Ok(())
}

async fn handle_request(
    req: Request<Incoming>,
    state: Arc<ServerState>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    use http_body_util::BodyExt;
    use std::sync::atomic::Ordering::Relaxed;

    let id = state.next_id.fetch_add(1, Relaxed);
    let method = req.method().to_string();
    let url = req
        .uri()
        .path_and_query()
        .map(|pq| pq.to_string())
        .unwrap_or_else(|| "/".to_string());

    let is_upgrade = req
        .headers()
        .get("upgrade")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.eq_ignore_ascii_case("websocket"));

    let headers: HashMap<String, String> = req
        .headers()
        .iter()
        .map(|(k, v)| (k.as_str().to_string(), v.to_str().unwrap_or("").to_string()))
        .collect();
    let headers_json = serde_json::to_string(&headers).unwrap_or_else(|_| "{}".to_string());

    let timeout_resp = HttpResponse {
        status: 504,
        headers: HashMap::new(),
        body: "Gateway Timeout".to_string(),
    };

    if is_upgrade {
        let (upgrade_tx, upgrade_rx) = oneshot::channel::<bool>();
        state.upgrade_map.lock().unwrap().insert(id, upgrade_tx);

        let (resp_tx, resp_rx) = oneshot::channel();
        state.pending.lock().unwrap().insert(id, resp_tx);

        let _ = state.tx.send(HttpRequest {
            id,
            method,
            url,
            headers_json,
            body: String::new(),
            is_upgrade: true,
        });

        tokio::select! {
            Ok(true) = upgrade_rx => {
                state.pending.lock().unwrap().remove(&id);

                let ws_key = headers.get("sec-websocket-key").cloned().unwrap_or_default();
                let accept_key = compute_ws_accept_key(&ws_key);
                let on_upgrade = hyper::upgrade::on(req);

                let response = Response::builder()
                    .status(StatusCode::SWITCHING_PROTOCOLS)
                    .header("Upgrade", "websocket")
                    .header("Connection", "Upgrade")
                    .header("Sec-WebSocket-Accept", accept_key)
                    .body(Full::new(Bytes::new()))
                    .unwrap();

                let conn_id = state.ws_next_conn_id.fetch_add(1, Relaxed);
                let state_ws = state.clone();
                tokio::spawn(async move {
                    match on_upgrade.await {
                        Ok(upgraded) => {
                            let io = hyper_util::rt::TokioIo::new(upgraded);
                            let ws_stream = tokio_tungstenite::WebSocketStream::from_raw_socket(
                                io, tungstenite::protocol::Role::Server, None,
                            ).await;
                            handle_ws_connection(conn_id, ws_stream, &state_ws).await;
                        }
                        Err(e) => {
                            let _ = state_ws.ws_event_tx.send(WsEvent {
                                kind: WsEventKind::Error, conn_id, data: format!("upgrade failed: {e}"),
                            });
                        }
                    }
                });

                return Ok(response);
            }
            Ok(resp) = resp_rx => {
                return Ok(build_hyper_response(resp));
            }
            _ = tokio::time::sleep(std::time::Duration::from_secs(30)) => {
                state.pending.lock().unwrap().remove(&id);
                state.upgrade_map.lock().unwrap().remove(&id);
                return Ok(build_hyper_response(timeout_resp));
            }
        }
    }

    // Normal HTTP request.
    let body_bytes = req
        .collect()
        .await
        .map(|b| b.to_bytes())
        .unwrap_or_default();
    let body = String::from_utf8_lossy(&body_bytes).into_owned();

    let (resp_tx, resp_rx) = oneshot::channel();
    state.pending.lock().unwrap().insert(id, resp_tx);

    let _ = state.tx.send(HttpRequest {
        id,
        method,
        url,
        headers_json,
        body,
        is_upgrade: false,
    });

    match tokio::time::timeout(std::time::Duration::from_secs(30), resp_rx).await {
        Ok(Ok(resp)) => Ok(build_hyper_response(resp)),
        _ => {
            state.pending.lock().unwrap().remove(&id);
            Ok(build_hyper_response(timeout_resp))
        }
    }
}

async fn handle_ws_connection<S>(
    conn_id: u64,
    ws_stream: tokio_tungstenite::WebSocketStream<S>,
    state: &ServerState,
) where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send + 'static,
{
    use futures_util::{SinkExt, StreamExt};

    let (mut write, mut read) = ws_stream.split();
    let (msg_tx, mut msg_rx) = mpsc::unbounded_channel::<tungstenite::Message>();

    state
        .ws_conns
        .lock()
        .unwrap()
        .insert(conn_id, WsConn { tx: msg_tx });

    let _ = state.ws_event_tx.send(WsEvent {
        kind: WsEventKind::Open,
        conn_id,
        data: String::new(),
    });

    let write_task = tokio::spawn(async move {
        while let Some(msg) = msg_rx.recv().await {
            if write.send(msg).await.is_err() {
                break;
            }
        }
    });

    while let Some(msg) = read.next().await {
        match msg {
            Ok(tungstenite::Message::Text(text)) => {
                let _ = state.ws_event_tx.send(WsEvent {
                    kind: WsEventKind::Message,
                    conn_id,
                    data: text.to_string(),
                });
            }
            Ok(tungstenite::Message::Binary(data)) => {
                let _ = state.ws_event_tx.send(WsEvent {
                    kind: WsEventKind::Message,
                    conn_id,
                    data: String::from_utf8_lossy(&data).into_owned(),
                });
            }
            Ok(tungstenite::Message::Close(_)) | Err(_) => break,
            _ => {}
        }
    }

    state.ws_conns.lock().unwrap().remove(&conn_id);
    write_task.abort();

    let _ = state.ws_event_tx.send(WsEvent {
        kind: WsEventKind::Close,
        conn_id,
        data: String::new(),
    });
}

fn compute_ws_accept_key(key: &str) -> String {
    use base64::Engine as _;
    use sha1::{Digest, Sha1};
    const MAGIC: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    let mut hasher = Sha1::new();
    hasher.update(key.as_bytes());
    hasher.update(MAGIC.as_bytes());
    base64::engine::general_purpose::STANDARD.encode(hasher.finalize())
}
