use std::collections::HashMap;
use std::sync::Arc;

use taiyaki_core::engine::{AsyncJsEngine, EngineError};
use taiyaki_core::permissions::Permissions;

pub async fn register_all(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    register_fetch(engine, perms).await?;
    register_timers(engine).await?;

    engine
        .eval(
            r#"globalThis.fetch = async (resource, opts) => {
    let url, method, body, headers;
    if (resource instanceof Request) {
        url = resource.url;
        method = resource.method;
        body = resource._body != null ? String(resource._body) : '';
        headers = JSON.stringify(resource.headers.toObject());
        if (opts) {
            if (opts.method) method = opts.method.toUpperCase();
            if (opts.headers) headers = JSON.stringify(new Headers(opts.headers).toObject());
            if (opts.body !== undefined) body = opts.body != null ? String(opts.body) : '';
        }
    } else {
        url = String(resource);
        method = (opts && opts.method) ? String(opts.method).toUpperCase() : 'GET';
        body = (opts && opts.body != null) ? String(opts.body) : '';
        headers = (opts && opts.headers) ? JSON.stringify(new Headers(opts.headers).toObject()) : '{}';
    }
    const raw = JSON.parse(await __fetch_raw(url, method, body, headers));
    const resp = new Response(raw.body, {
        status: raw.status,
        statusText: raw.statusText,
        headers: raw.headers,
    });
    resp.url = raw.url || url;
    resp.redirected = raw.redirected || false;
    resp.type = 'basic';
    resp._bodyBase64 = raw.bodyBase64;
    return resp;
};"#,
        )
        .await?;

    Ok(())
}

async fn register_fetch(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    let perms = perms.clone();
    let client = reqwest::Client::new();

    engine
        .register_async_host_fn(
            "__fetch_raw",
            Box::new(move |args| {
                let url = args.first().cloned().unwrap_or_default();
                let method = args.get(1).cloned().unwrap_or_default();
                let body = args.get(2).cloned().unwrap_or_default();
                let headers_json = args.get(3).cloned().unwrap_or_default();
                let client = client.clone();
                let perms = perms.clone();
                Box::pin(async move {
                    // Check net permission based on URL host.
                    if let Ok(parsed) = url::Url::parse(&url) {
                        if let Some(host) = parsed.host_str() {
                            perms.check_net(host).map_err(|e| e.to_string())?;
                        }
                    }
                    let mut req = match method.as_str() {
                        "POST" => client.post(&url),
                        "PUT" => client.put(&url),
                        "DELETE" => client.delete(&url),
                        "PATCH" => client.patch(&url),
                        "HEAD" => client.head(&url),
                        _ => client.get(&url),
                    };

                    if let Ok(hdrs) = serde_json::from_str::<HashMap<String, String>>(&headers_json)
                    {
                        for (k, v) in hdrs {
                            req = req.header(k, v);
                        }
                    }

                    if !body.is_empty() && method != "GET" && method != "HEAD" {
                        req = req.body(body);
                    }

                    let resp = req
                        .send()
                        .await
                        .map_err(|e| format!("network error: {e}"))?;

                    let status = resp.status().as_u16();
                    let status_text = resp.status().canonical_reason().unwrap_or("").to_string();
                    let final_url = resp.url().to_string();
                    let redirected = final_url != url;

                    let resp_headers: HashMap<String, String> = resp
                        .headers()
                        .iter()
                        .map(|(k, v)| {
                            (k.as_str().to_string(), v.to_str().unwrap_or("").to_string())
                        })
                        .collect();

                    let body_bytes = resp.bytes().await.map_err(|e| format!("body error: {e}"))?;

                    let body_text = String::from_utf8_lossy(&body_bytes).into_owned();
                    use base64::Engine as _;
                    let body_base64 = base64::engine::general_purpose::STANDARD.encode(&body_bytes);

                    let result = serde_json::json!({
                        "status": status,
                        "statusText": status_text,
                        "headers": resp_headers,
                        "body": body_text,
                        "bodyBase64": body_base64,
                        "url": final_url,
                        "redirected": redirected,
                    });

                    Ok(result.to_string())
                })
            }),
        )
        .await?;

    Ok(())
}

async fn register_timers(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    // __delay(ms) -> async, resolves after ms milliseconds
    engine
        .register_async_host_fn(
            "__delay",
            Box::new(|args| {
                let ms: u64 = args.first().and_then(|s| s.parse().ok()).unwrap_or(0);
                Box::pin(async move {
                    tokio::time::sleep(std::time::Duration::from_millis(ms)).await;
                    Ok(String::new())
                })
            }),
        )
        .await?;

    engine
        .eval(
            r#"globalThis.__timers = new Map();
globalThis.__nextTimerId = 1;

globalThis.setTimeout = (callback, ms) => {
    var id = __nextTimerId++;
    __timers.set(id, { cancelled: false });
    __delay(ms || 0).then(() => {
        var timer = __timers.get(id);
        if (timer && !timer.cancelled) callback();
        __timers.delete(id);
    });
    return id;
};

globalThis.clearTimeout = (id) => {
    var timer = __timers.get(id);
    if (timer) {
        timer.cancelled = true;
        __timers.delete(id);
    }
};

globalThis.setInterval = (callback, ms) => {
    var id = __nextTimerId++;
    __timers.set(id, { cancelled: false });
    var tick = () => {
        __delay(ms || 0).then(() => {
            var timer = __timers.get(id);
            if (timer && !timer.cancelled) {
                callback();
                tick();
            }
        });
    };
    tick();
    return id;
};

globalThis.clearInterval = clearTimeout;"#,
        )
        .await?;

    Ok(())
}
