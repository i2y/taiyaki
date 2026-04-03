use std::sync::Arc;

use taiyaki_core::engine::{AsyncJsEngine, EngineError};
use taiyaki_core::permissions::Permissions;
use tokio::net::TcpStream;

use crate::net::NetState;

pub async fn register_tls(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
    net_state: &Arc<NetState>,
) -> Result<(), EngineError> {
    // Ensure ring CryptoProvider is installed for rustls
    let _ = tokio_rustls::rustls::crypto::ring::default_provider().install_default();

    // __tls_connect(host, port, opts_json) -> async
    {
        let perms = perms.clone();
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__tls_connect",
                Box::new(move |args| {
                    let host = args.first().cloned().unwrap_or_default();
                    let port: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
                    let opts_json = args.get(2).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    let state = state.clone();
                    Box::pin(async move {
                        perms.check_net(&host).map_err(|e| e.to_string())?;

                        let opts: serde_json::Value =
                            serde_json::from_str(&opts_json).unwrap_or_default();
                        let servername = opts
                            .get("servername")
                            .and_then(|v| v.as_str())
                            .unwrap_or(&host)
                            .to_string();
                        let reject_unauthorized = opts
                            .get("rejectUnauthorized")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(true);

                        let config = build_client_config(&opts, reject_unauthorized)
                            .map_err(|e| format!("TLS config: {e}"))?;
                        let connector = tokio_rustls::TlsConnector::from(Arc::new(config));

                        let tcp = TcpStream::connect(format!("{host}:{port}"))
                            .await
                            .map_err(|e| format!("connect {host}:{port}: {e}"))?;

                        let local_addr =
                            tcp.local_addr().map(|a| a.to_string()).unwrap_or_default();
                        let remote_addr =
                            tcp.peer_addr().map(|a| a.to_string()).unwrap_or_default();

                        let domain = rustls_pki_types::ServerName::try_from(servername.clone())
                            .map_err(|e| format!("invalid servername '{servername}': {e}"))?
                            .to_owned();

                        let tls_stream = connector
                            .connect(domain, tcp)
                            .await
                            .map_err(|e| format!("TLS handshake: {e}"))?;

                        let (read_half, write_half) = tokio::io::split(tls_stream);
                        let id = state.insert_split_stream(
                            read_half,
                            write_half,
                            local_addr.clone(),
                            remote_addr.clone(),
                        );

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

    // __tls_create_server(cert_pem, key_pem, port, host) -> async
    {
        let perms = perms.clone();
        let state = net_state.clone();
        engine
            .register_async_host_fn(
                "__tls_create_server",
                Box::new(move |args| {
                    let cert_pem = args.first().cloned().unwrap_or_default();
                    let key_pem = args.get(1).cloned().unwrap_or_default();
                    let port: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(0);
                    let host = args.get(3).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    let state = state.clone();
                    Box::pin(async move {
                        perms.check_net(&host).map_err(|e| e.to_string())?;

                        let config = build_server_config(&cert_pem, &key_pem)
                            .map_err(|e| format!("TLS server config: {e}"))?;
                        let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(config));

                        let listener = tokio::net::TcpListener::bind(format!("{host}:{port}"))
                            .await
                            .map_err(|e| format!("bind {host}:{port}: {e}"))?;
                        let actual_port = listener.local_addr().unwrap().port();

                        let (id, _addr) = state.insert_tls_server(listener, acceptor);
                        let json = serde_json::json!({
                            "id": id,
                            "port": actual_port,
                        });
                        Ok(json.to_string())
                    })
                }),
            )
            .await?;
    }

    Ok(())
}

fn build_client_config(
    opts: &serde_json::Value,
    reject_unauthorized: bool,
) -> Result<tokio_rustls::rustls::ClientConfig, Box<dyn std::error::Error>> {
    use tokio_rustls::rustls::ClientConfig;

    if !reject_unauthorized {
        let config = ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(NoCertVerifier))
            .with_no_client_auth();
        return Ok(config);
    }

    let mut root_store = tokio_rustls::rustls::RootCertStore::empty();
    root_store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());

    if let Some(ca_pem) = opts.get("ca").and_then(|v| v.as_str()) {
        let certs: Vec<_> = rustls_pemfile::certs(&mut ca_pem.as_bytes())
            .filter_map(|r| r.ok())
            .collect();
        for cert in certs {
            root_store.add(cert)?;
        }
    }

    let config = ClientConfig::builder()
        .with_root_certificates(root_store)
        .with_no_client_auth();
    Ok(config)
}

fn build_server_config(
    cert_pem: &str,
    key_pem: &str,
) -> Result<tokio_rustls::rustls::ServerConfig, Box<dyn std::error::Error>> {
    use tokio_rustls::rustls::ServerConfig;

    let certs: Vec<_> = rustls_pemfile::certs(&mut cert_pem.as_bytes())
        .filter_map(|r| r.ok())
        .collect();
    let key = rustls_pemfile::private_key(&mut key_pem.as_bytes())?
        .ok_or("no private key found in PEM")?;

    let config = ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(certs, key)?;
    Ok(config)
}

// --- NoCertVerifier for rejectUnauthorized: false ---

#[derive(Debug)]
struct NoCertVerifier;

impl tokio_rustls::rustls::client::danger::ServerCertVerifier for NoCertVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &rustls_pki_types::CertificateDer<'_>,
        _intermediates: &[rustls_pki_types::CertificateDer<'_>],
        _server_name: &rustls_pki_types::ServerName<'_>,
        _ocsp_response: &[u8],
        _now: rustls_pki_types::UnixTime,
    ) -> Result<tokio_rustls::rustls::client::danger::ServerCertVerified, tokio_rustls::rustls::Error>
    {
        Ok(tokio_rustls::rustls::client::danger::ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &rustls_pki_types::CertificateDer<'_>,
        _dss: &tokio_rustls::rustls::DigitallySignedStruct,
    ) -> Result<
        tokio_rustls::rustls::client::danger::HandshakeSignatureValid,
        tokio_rustls::rustls::Error,
    > {
        Ok(tokio_rustls::rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &rustls_pki_types::CertificateDer<'_>,
        _dss: &tokio_rustls::rustls::DigitallySignedStruct,
    ) -> Result<
        tokio_rustls::rustls::client::danger::HandshakeSignatureValid,
        tokio_rustls::rustls::Error,
    > {
        Ok(tokio_rustls::rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<tokio_rustls::rustls::SignatureScheme> {
        tokio_rustls::rustls::crypto::CryptoProvider::get_default()
            .map(|p| p.signature_verification_algorithms.supported_schemes())
            .unwrap_or_default()
    }
}
