use std::sync::Arc;

use taiyaki_core::engine::{AsyncJsEngine, EngineError};
use taiyaki_core::permissions::Permissions;

pub async fn register_dns(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    // __dns_lookup(hostname) -> JSON {"address": "...", "family": 4|6}
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__dns_lookup",
                Box::new(move |args| {
                    let hostname = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_net(&hostname).map_err(|e| e.to_string())?;

                        let host = hostname.clone();
                        let addrs = tokio::task::spawn_blocking(move || {
                            use std::net::ToSocketAddrs;
                            format!("{host}:0").to_socket_addrs()
                        })
                        .await
                        .map_err(|e| format!("lookup join: {e}"))?
                        .map_err(|e| format!("getaddrinfo ENOTFOUND {hostname}: {e}"))?;

                        if let Some(addr) = addrs.into_iter().next() {
                            let ip = addr.ip();
                            let family = if ip.is_ipv4() { 4 } else { 6 };
                            let json = serde_json::json!({
                                "address": ip.to_string(),
                                "family": family,
                            });
                            Ok(json.to_string())
                        } else {
                            Err(format!("getaddrinfo ENOTFOUND {hostname}"))
                        }
                    })
                }),
            )
            .await?;
    }

    // __dns_resolve(hostname, rrtype) -> JSON array of addresses
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__dns_resolve",
                Box::new(move |args| {
                    let hostname = args.first().cloned().unwrap_or_default();
                    let rrtype = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_net(&hostname).map_err(|e| e.to_string())?;

                        let host = hostname.clone();
                        let addrs = tokio::task::spawn_blocking(move || {
                            use std::net::ToSocketAddrs;
                            format!("{host}:0").to_socket_addrs()
                        })
                        .await
                        .map_err(|e| format!("resolve join: {e}"))?
                        .map_err(|e| format!("queryA ENOTFOUND {hostname}: {e}"))?;

                        let results: Vec<String> = addrs
                            .filter(|a| match rrtype.as_str() {
                                "AAAA" => a.ip().is_ipv6(),
                                _ => a.ip().is_ipv4(),
                            })
                            .map(|a| a.ip().to_string())
                            .collect();

                        Ok(serde_json::to_string(&results).unwrap())
                    })
                }),
            )
            .await?;
    }

    Ok(())
}
