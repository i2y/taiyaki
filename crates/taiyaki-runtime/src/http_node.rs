use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response, StatusCode};
use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};
use taiyaki_core::permissions::Permissions;
use tokio::net::TcpListener;
use tokio::sync::{mpsc, oneshot};

// --- Types ---

struct HttpNodeRequest {
    id: u64,
    method: String,
    url: String,
    headers: HashMap<String, String>,
    body: String, // base64
    http_version: String,
}

struct HttpNodeResponse {
    status: u16,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}

struct HttpServerHandle {
    req_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<HttpNodeRequest>>>,
    pending: Arc<std::sync::Mutex<HashMap<u64, oneshot::Sender<HttpNodeResponse>>>>,
    #[allow(dead_code)]
    next_req_id: Arc<AtomicU64>,
    shutdown_tx: tokio::sync::watch::Sender<bool>,
    stop_rx: tokio::sync::watch::Receiver<bool>,
}

struct HttpNodeState {
    servers: std::sync::Mutex<HashMap<u64, HttpServerHandle>>,
    next_server_id: AtomicU64,
}

// --- Registration ---

pub async fn register_http_node(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    let state = Arc::new(HttpNodeState {
        servers: std::sync::Mutex::new(HashMap::new()),
        next_server_id: AtomicU64::new(1),
    });

    // __http_create_server() -> sync, returns server_id
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__http_create_server",
                Box::new(move |_args: &[JsValue]| {
                    let id = state.next_server_id.fetch_add(1, Ordering::Relaxed);
                    Ok(JsValue::String(id.to_string()))
                }),
            )
            .await?;
    }

    // __http_server_listen(server_id, port, host) -> async, returns JSON {"port"}
    {
        let state = state.clone();
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__http_server_listen",
                Box::new(move |args| {
                    let server_id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let port: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
                    let host = args.get(2).cloned().unwrap_or_default();
                    let state = state.clone();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_net(&host).map_err(|e| e.to_string())?;

                        let (req_tx, req_rx) = mpsc::unbounded_channel();
                        let (shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
                        let (stop_tx, stop_rx) = tokio::sync::watch::channel(false);
                        let pending = Arc::new(std::sync::Mutex::new(HashMap::new()));
                        let next_req_id = Arc::new(AtomicU64::new(1));

                        state.servers.lock().unwrap().insert(
                            server_id,
                            HttpServerHandle {
                                req_rx: Arc::new(tokio::sync::Mutex::new(req_rx)),
                                pending: pending.clone(),
                                next_req_id: next_req_id.clone(),
                                shutdown_tx,
                                stop_rx,
                            },
                        );
                        let mut shutdown_rx_clone = shutdown_rx.clone();
                        tokio::spawn(async move {
                            let _ = shutdown_rx_clone.changed().await;
                            let _ = stop_tx.send(true);
                        });

                        let listener =
                            TcpListener::bind(format!("{host}:{port}"))
                                .await
                                .map_err(|e| format!("bind: {e}"))?;
                        let actual_port = listener.local_addr().unwrap().port();

                        let pending_clone = pending.clone();
                        let next_id_clone = next_req_id.clone();
                        tokio::spawn(async move {
                            let mut shutdown_rx = shutdown_rx;
                            loop {
                                tokio::select! {
                                    result = listener.accept() => {
                                        match result {
                                            Ok((stream, _)) => {
                                                let req_tx = req_tx.clone();
                                                let pending = pending_clone.clone();
                                                let next_id = next_id_clone.clone();
                                                let io = hyper_util::rt::TokioIo::new(stream);
                                                tokio::spawn(async move {
                                                    let svc = service_fn(move |req: Request<Incoming>| {
                                                        let req_tx = req_tx.clone();
                                                        let pending = pending.clone();
                                                        let next_id = next_id.clone();
                                                        async move {
                                                            handle_http_request(req, req_tx, pending, next_id).await
                                                        }
                                                    });
                                                    let _ = http1::Builder::new()
                                                        .serve_connection(io, svc)
                                                        .await;
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

                        let json = serde_json::json!({ "port": actual_port });
                        Ok(json.to_string())
                    })
                }),
            )
            .await?;
    }

    // __http_server_next_request(server_id) -> async, returns JSON or ""
    {
        let state = state.clone();
        engine
            .register_async_host_fn(
                "__http_server_next_request",
                Box::new(move |args| {
                    let server_id: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                    let state = state.clone();
                    Box::pin(async move {
                        let (rx, mut stop) = {
                            let servers = state.servers.lock().unwrap();
                            match servers.get(&server_id) {
                                Some(h) => (h.req_rx.clone(), h.stop_rx.clone()),
                                None => return Ok(String::new()),
                            }
                        };
                        let mut rx_guard = rx.lock().await;
                        tokio::select! {
                            result = rx_guard.recv() => {
                                match result {
                                    Some(req) => {
                                        let json = serde_json::json!({
                                            "id": req.id,
                                            "method": req.method,
                                            "url": req.url,
                                            "headers": req.headers,
                                            "body": req.body,
                                            "httpVersion": req.http_version,
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

    // __http_server_respond(server_id, req_id, status, headers_json, body_b64) -> sync
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__http_server_respond",
                Box::new(move |args: &[JsValue]| {
                    let server_id = args.first().map(|v| v.coerce_u64()).unwrap_or(0);
                    let req_id = args.get(1).map(|v| v.coerce_u64()).unwrap_or(0);
                    let status = args.get(2).map(|v| v.coerce_u16()).unwrap_or(200);
                    let headers_json = args
                        .get(3)
                        .map(|v| v.coerce_string())
                        .unwrap_or_else(|| "{}".to_string());
                    let body_b64 = args.get(4).map(|v| v.coerce_string()).unwrap_or_default();

                    let headers: HashMap<String, String> =
                        serde_json::from_str(&headers_json).unwrap_or_default();

                    use base64::Engine as _;
                    let body = base64::engine::general_purpose::STANDARD
                        .decode(&body_b64)
                        .unwrap_or_else(|_| body_b64.into_bytes());

                    let servers = state.servers.lock().unwrap();
                    if let Some(handle) = servers.get(&server_id) {
                        let tx = handle.pending.lock().unwrap().remove(&req_id);
                        if let Some(tx) = tx {
                            let _ = tx.send(HttpNodeResponse {
                                status,
                                headers,
                                body,
                            });
                        }
                    }
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __http_server_close(server_id) -> sync
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__http_server_close",
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

    // __http_request(opts_json) -> async, returns JSON response
    {
        let perms = perms.clone();
        let http_client = reqwest::Client::new();
        engine
            .register_async_host_fn(
                "__http_request",
                Box::new(move |args| {
                    let opts_json = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    let client = http_client.clone();
                    Box::pin(async move {
                        let opts: serde_json::Value =
                            serde_json::from_str(&opts_json).unwrap_or_default();
                        let hostname = opts
                            .get("hostname")
                            .or_else(|| opts.get("host"))
                            .and_then(|v| v.as_str())
                            .unwrap_or("localhost");
                        let port = opts.get("port").and_then(|v| v.as_u64()).unwrap_or(80) as u16;
                        let path = opts.get("path").and_then(|v| v.as_str()).unwrap_or("/");
                        let method = opts.get("method").and_then(|v| v.as_str()).unwrap_or("GET");
                        let protocol = opts
                            .get("protocol")
                            .and_then(|v| v.as_str())
                            .unwrap_or("http:");
                        let body = opts.get("body").and_then(|v| v.as_str()).unwrap_or("");

                        perms.check_net(hostname).map_err(|e| e.to_string())?;

                        let scheme = if protocol == "https:" {
                            "https"
                        } else {
                            "http"
                        };
                        let url = format!("{scheme}://{hostname}:{port}{path}");

                        let mut req_builder = match method.to_uppercase().as_str() {
                            "POST" => client.post(&url),
                            "PUT" => client.put(&url),
                            "DELETE" => client.delete(&url),
                            "PATCH" => client.patch(&url),
                            "HEAD" => client.head(&url),
                            _ => client.get(&url),
                        };

                        if let Some(headers) = opts.get("headers").and_then(|v| v.as_object()) {
                            for (k, v) in headers {
                                if let Some(val) = v.as_str() {
                                    req_builder = req_builder.header(k.as_str(), val);
                                }
                            }
                        }

                        if !body.is_empty() {
                            req_builder = req_builder.body(body.to_string());
                        }

                        let resp = req_builder
                            .send()
                            .await
                            .map_err(|e| format!("request: {e}"))?;

                        let status = resp.status().as_u16();
                        let status_text =
                            resp.status().canonical_reason().unwrap_or("").to_string();
                        let headers: HashMap<String, String> = resp
                            .headers()
                            .iter()
                            .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
                            .collect();
                        let body_bytes = resp.bytes().await.map_err(|e| format!("body: {e}"))?;
                        let body_text = String::from_utf8_lossy(&body_bytes).into_owned();

                        let json = serde_json::json!({
                            "status": status,
                            "statusText": status_text,
                            "headers": headers,
                            "body": body_text,
                        });
                        Ok(json.to_string())
                    })
                }),
            )
            .await?;
    }

    Ok(())
}

async fn handle_http_request(
    req: Request<Incoming>,
    req_tx: mpsc::UnboundedSender<HttpNodeRequest>,
    pending: Arc<std::sync::Mutex<HashMap<u64, oneshot::Sender<HttpNodeResponse>>>>,
    next_id: Arc<AtomicU64>,
) -> Result<Response<Full<Bytes>>, std::convert::Infallible> {
    use http_body_util::BodyExt;

    let id = next_id.fetch_add(1, Ordering::Relaxed);
    let method = req.method().to_string();
    let uri = req.uri().to_string();
    let http_version = match req.version() {
        hyper::Version::HTTP_10 => "1.0".to_string(),
        hyper::Version::HTTP_11 => "1.1".to_string(),
        hyper::Version::HTTP_2 => "2.0".to_string(),
        hyper::Version::HTTP_3 => "3.0".to_string(),
        _ => "1.1".to_string(),
    };

    let headers: HashMap<String, String> = req
        .headers()
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
        .collect();

    let body_bytes = req
        .collect()
        .await
        .map(|b| b.to_bytes())
        .unwrap_or_default();

    use base64::Engine as _;
    let body_b64 = base64::engine::general_purpose::STANDARD.encode(&body_bytes);

    let (resp_tx, resp_rx) = oneshot::channel();
    pending.lock().unwrap().insert(id, resp_tx);

    if req_tx
        .send(HttpNodeRequest {
            id,
            method,
            url: uri,
            headers,
            body: body_b64,
            http_version,
        })
        .is_err()
    {
        pending.lock().unwrap().remove(&id);
        return Ok(Response::builder()
            .status(503)
            .body(Full::new(Bytes::from("Service Unavailable")))
            .unwrap());
    }

    match tokio::time::timeout(std::time::Duration::from_secs(30), resp_rx).await {
        Ok(Ok(resp)) => {
            let mut builder = Response::builder().status(
                StatusCode::from_u16(resp.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
            );
            for (k, v) in &resp.headers {
                builder = builder.header(k.as_str(), v.as_str());
            }
            Ok(builder
                .body(Full::new(Bytes::from(resp.body)))
                .unwrap_or_else(|_| {
                    Response::builder()
                        .status(500)
                        .body(Full::new(Bytes::from("Internal Server Error")))
                        .unwrap()
                }))
        }
        _ => {
            pending.lock().unwrap().remove(&id);
            Ok(Response::builder()
                .status(504)
                .body(Full::new(Bytes::from("Gateway Timeout")))
                .unwrap())
        }
    }
}
