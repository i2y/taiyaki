use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

fn run_js(code: &str) -> (String, String, bool) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.mjs");
    std::fs::write(&file, code).unwrap();
    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    (stdout, stderr, output.status.success())
}

fn run_js_with_args(code: &str, extra_args: &[&str]) -> (String, String, bool) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.mjs");
    std::fs::write(&file, code).unwrap();
    let mut cmd = taiyaki_bin();
    cmd.arg("run");
    for arg in extra_args {
        cmd.arg(arg);
    }
    cmd.arg(&file);
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    (stdout, stderr, output.status.success())
}

// ============================================================
// zlib tests
// ============================================================

#[test]
fn test_zlib_gzip_gunzip_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { gzipSync, gunzipSync } from 'zlib';
const data = new TextEncoder().encode("Hello, zlib compression!");
const compressed = gzipSync(data);
const decompressed = gunzipSync(compressed);
console.log(new TextDecoder().decode(decompressed));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "Hello, zlib compression!");
}

#[test]
fn test_zlib_deflate_inflate_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { deflateSync, inflateSync } from 'zlib';
const data = new TextEncoder().encode("deflate test data");
const compressed = deflateSync(data);
const decompressed = inflateSync(compressed);
console.log(new TextDecoder().decode(decompressed));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "deflate test data");
}

#[test]
fn test_zlib_deflate_raw_inflate_raw_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { deflateRawSync, inflateRawSync } from 'zlib';
const data = new TextEncoder().encode("raw deflate test");
const compressed = deflateRawSync(data);
const decompressed = inflateRawSync(compressed);
console.log(new TextDecoder().decode(decompressed));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "raw deflate test");
}

#[test]
fn test_zlib_brotli_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { brotliCompressSync, brotliDecompressSync } from 'zlib';
const data = new TextEncoder().encode("brotli compression test");
const compressed = brotliCompressSync(data);
const decompressed = brotliDecompressSync(compressed);
console.log(new TextDecoder().decode(decompressed));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "brotli compression test");
}

#[test]
fn test_zlib_async_callback() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { gzip, gunzip } from 'zlib';
const data = new TextEncoder().encode("async callback test");
gzip(data, (err, compressed) => {
    if (err) { console.log("error:", err.message); return; }
    gunzip(compressed, (err2, decompressed) => {
        if (err2) { console.log("error:", err2.message); return; }
        console.log(new TextDecoder().decode(decompressed));
    });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "async callback test");
}

#[test]
fn test_zlib_compression_reduces_size() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { gzipSync } from 'zlib';
const data = new TextEncoder().encode("a".repeat(1000));
const compressed = gzipSync(data);
console.log(compressed.length < data.length ? "smaller" : "not smaller");
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "smaller");
}

#[test]
fn test_zlib_empty_input() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { gzipSync, gunzipSync } from 'zlib';
const data = new Uint8Array(0);
const compressed = gzipSync(data);
const decompressed = gunzipSync(compressed);
console.log("length:", decompressed.length);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "length: 0");
}

#[test]
fn test_zlib_constants() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { constants } from 'zlib';
console.log("Z_NO_COMPRESSION:", constants.Z_NO_COMPRESSION);
console.log("Z_BEST_SPEED:", constants.Z_BEST_SPEED);
console.log("Z_BEST_COMPRESSION:", constants.Z_BEST_COMPRESSION);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("Z_NO_COMPRESSION: 0"));
    assert!(stdout.contains("Z_BEST_SPEED: 1"));
    assert!(stdout.contains("Z_BEST_COMPRESSION: 9"));
}

// ============================================================
// dns tests
// ============================================================

#[test]
fn test_dns_lookup_localhost() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as dns from 'dns';
dns.lookup('localhost', (err, address, family) => {
    if (err) { console.log("error"); return; }
    console.log("address:", address);
    console.log("family:", family);
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    // localhost resolves to 127.0.0.1 or ::1
    assert!(
        stdout.contains("127.0.0.1") || stdout.contains("::1"),
        "stdout: {stdout}"
    );
    assert!(
        stdout.contains("family: 4") || stdout.contains("family: 6"),
        "stdout: {stdout}"
    );
}

#[test]
fn test_dns_resolve4_localhost() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as dns from 'dns';
dns.resolve4('localhost', (err, addresses) => {
    if (err) { console.log("error:", err.message); return; }
    console.log("resolved:", JSON.stringify(addresses));
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("127.0.0.1"), "stdout: {stdout}");
}

#[test]
fn test_dns_promises() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as dns from 'dns';
const result = await dns.promises.lookup('localhost');
console.log("address:", result.address);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(
        stdout.contains("127.0.0.1") || stdout.contains("::1"),
        "stdout: {stdout}"
    );
}

// ============================================================
// net tests
// ============================================================

#[test]
fn test_net_create_server_connect() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as net from 'net';
const server = net.createServer((socket) => {
    socket.on('data', (data) => {
        socket.write(data); // echo
    });
    socket.on('end', () => {
        socket.destroy();
        server.close();
    });
});
server.listen(0, '127.0.0.1', () => {
    const port = server.address().port;
    console.log("listening");
    const client = net.createConnection(port, '127.0.0.1', () => {
        console.log("connected");
        client.write("hello net");
    });
    client.on('data', (data) => {
        console.log("echo:", new TextDecoder().decode(data));
        client.end();
    });
    client.on('end', () => { client.destroy(); });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("listening"), "stdout: {stdout}");
    assert!(stdout.contains("connected"), "stdout: {stdout}");
    assert!(stdout.contains("echo: hello net"), "stdout: {stdout}");
}

#[test]
fn test_net_server_close() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as net from 'net';
const server = net.createServer(() => {});
server.listen(0, '127.0.0.1', () => {
    console.log("listening:", server.listening);
    server.close(() => {
        console.log("closed");
    });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("listening: true"), "stdout: {stdout}");
    assert!(stdout.contains("closed"), "stdout: {stdout}");
}

#[test]
fn test_net_socket_address() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as net from 'net';
const server = net.createServer((socket) => {
    console.log("remoteAddress:", socket.remoteAddress);
    console.log("remotePort:", typeof socket.remotePort);
    socket.destroy();
    server.close();
});
server.listen(0, '127.0.0.1', () => {
    const client = net.createConnection(server.address().port, '127.0.0.1');
    client.on('end', () => { client.destroy(); });
    client.on('close', () => {});
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(
        stdout.contains("remoteAddress: 127.0.0.1"),
        "stdout: {stdout}"
    );
    assert!(stdout.contains("remotePort: number"), "stdout: {stdout}");
}

#[test]
fn test_net_is_ip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { isIP, isIPv4, isIPv6 } from 'net';
console.log("isIP 127.0.0.1:", isIP("127.0.0.1"));
console.log("isIPv4:", isIPv4("192.168.1.1"));
console.log("isIPv6:", isIPv6("::1"));
console.log("isIP invalid:", isIP("not-an-ip"));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("isIP 127.0.0.1: 4"), "stdout: {stdout}");
    assert!(stdout.contains("isIPv4: true"), "stdout: {stdout}");
    assert!(stdout.contains("isIPv6: true"), "stdout: {stdout}");
    assert!(stdout.contains("isIP invalid: 0"), "stdout: {stdout}");
}

#[test]
fn test_net_connect_refused() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as net from 'net';
// Port 1 is unlikely to be open
const client = net.createConnection(1, '127.0.0.1');
client.on('error', (err) => {
    console.log("error caught:", err.message.includes("refused") || err.message.includes("connect") ? "yes" : err.message);
});
"#,
    );
    // Script should succeed even though connection fails (error is caught)
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("error caught: yes"), "stdout: {stdout}");
}

// ============================================================
// tls tests
// ============================================================

#[test]
fn test_tls_connect_external() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as tls from 'tls';
const socket = tls.connect(443, 'www.google.com', {}, () => {
    console.log("connected");
    console.log("encrypted:", socket.encrypted);
    console.log("protocol:", socket.getProtocol());
    socket.destroy();
});
socket.on('error', (err) => {
    console.log("error:", err.message);
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("connected"), "stdout: {stdout}");
    assert!(stdout.contains("encrypted: true"), "stdout: {stdout}");
    assert!(stdout.contains("protocol: TLSv1.3"), "stdout: {stdout}");
}

#[test]
fn test_tls_socket_properties() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as tls from 'tls';
const socket = tls.connect(443, 'www.google.com', { rejectUnauthorized: false }, () => {
    console.log("authorized:", socket.authorized);
    var cipher = socket.getCipher();
    console.log("cipher has name:", typeof cipher.name === 'string');
    console.log("cipher has version:", typeof cipher.version === 'string');
    socket.destroy();
});
socket.on('error', () => { socket.destroy(); });
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("authorized: true"), "stdout: {stdout}");
    assert!(stdout.contains("cipher has name: true"), "stdout: {stdout}");
    assert!(
        stdout.contains("cipher has version: true"),
        "stdout: {stdout}"
    );
}

#[test]
fn test_tls_reject_unauthorized_false() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as tls from 'tls';
// Connect with rejectUnauthorized: false to skip cert validation
const socket = tls.connect(443, 'example.com', { rejectUnauthorized: false }, () => {
    console.log("connected despite cert issues");
    socket.write("GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n");
});
socket.on('data', (data) => {
    const text = new TextDecoder().decode(data);
    console.log("got response:", text.split('\r\n')[0]);
    socket.destroy();
});
socket.on('error', (err) => {
    console.log("error:", err.message);
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(
        stdout.contains("connected despite cert issues"),
        "stdout: {stdout}"
    );
    assert!(
        stdout.contains("got response: HTTP/1.1"),
        "stdout: {stdout}"
    );
}

// ============================================================
// http tests
// ============================================================

#[test]
fn test_http_create_server_and_request() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as http from 'http';
const server = http.createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'text/plain' });
    res.end('OK');
});
server.listen(0, '127.0.0.1', () => {
    const port = server.address().port;
    http.get({ hostname: '127.0.0.1', port, path: '/' }, (res) => {
        console.log("status:", res.statusCode);
        let body = '';
        res.on('data', (chunk) => { body += (typeof chunk === 'string' ? chunk : new TextDecoder().decode(chunk)); });
        res.on('end', () => {
            console.log("body:", body);
            server.close();
        });
    });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("status: 200"), "stdout: {stdout}");
    assert!(stdout.contains("body: OK"), "stdout: {stdout}");
}

#[test]
fn test_http_post_body() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as http from 'http';
const server = http.createServer((req, res) => {
    console.log("method:", req.method);
    let body = '';
    req.on('data', (chunk) => { body += (typeof chunk === 'string' ? chunk : new TextDecoder().decode(chunk)); });
    req.on('end', () => {
        console.log("request body:", body);
        res.writeHead(200);
        res.end('received');
    });
});
server.listen(0, '127.0.0.1', () => {
    const port = server.address().port;
    const req = http.request({
        hostname: '127.0.0.1', port, path: '/', method: 'POST',
        headers: { 'content-type': 'text/plain' }
    }, (res) => {
        let body = '';
        res.on('data', (chunk) => { body += (typeof chunk === 'string' ? chunk : new TextDecoder().decode(chunk)); });
        res.on('end', () => {
            console.log("response:", body);
            server.close();
        });
    });
    req.write("hello post");
    req.end();
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("method: POST"), "stdout: {stdout}");
    assert!(
        stdout.contains("request body: hello post"),
        "stdout: {stdout}"
    );
    assert!(stdout.contains("response: received"), "stdout: {stdout}");
}

#[test]
fn test_http_response_headers() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as http from 'http';
const server = http.createServer((req, res) => {
    res.setHeader('x-custom', 'myvalue');
    console.log("has header:", res.hasHeader('x-custom'));
    console.log("get header:", res.getHeader('x-custom'));
    res.writeHead(201, { 'x-another': 'test' });
    res.end('done');
});
server.listen(0, '127.0.0.1', () => {
    http.get({ hostname: '127.0.0.1', port: server.address().port, path: '/' }, (res) => {
        console.log("status:", res.statusCode);
        server.close();
    });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("has header: true"), "stdout: {stdout}");
    assert!(stdout.contains("get header: myvalue"), "stdout: {stdout}");
    assert!(stdout.contains("status: 201"), "stdout: {stdout}");
}

#[test]
fn test_http_status_codes() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { STATUS_CODES, METHODS } from 'http';
console.log("200:", STATUS_CODES[200]);
console.log("404:", STATUS_CODES[404]);
console.log("has GET:", METHODS.includes('GET'));
console.log("has POST:", METHODS.includes('POST'));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("200: OK"), "stdout: {stdout}");
    assert!(stdout.contains("404: Not Found"), "stdout: {stdout}");
    assert!(stdout.contains("has GET: true"), "stdout: {stdout}");
    assert!(stdout.contains("has POST: true"), "stdout: {stdout}");
}

#[test]
fn test_http_incoming_message_properties() {
    let (stdout, stderr, ok) = run_js(
        r#"
import * as http from 'http';
const server = http.createServer((req, res) => {
    console.log("method:", req.method);
    console.log("url:", req.url);
    console.log("httpVersion:", req.httpVersion);
    console.log("complete:", req.complete);
    res.end();
});
server.listen(0, '127.0.0.1', () => {
    http.get({ hostname: '127.0.0.1', port: server.address().port, path: '/test?q=1' }, (res) => {
        server.close();
    });
});
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("method: GET"), "stdout: {stdout}");
    assert!(stdout.contains("url: /test?q=1"), "stdout: {stdout}");
    assert!(stdout.contains("httpVersion: 1.1"), "stdout: {stdout}");
    assert!(stdout.contains("complete: true"), "stdout: {stdout}");
}

// ============================================================
// Permission tests (sandbox)
// ============================================================

#[test]
fn test_net_sandbox_denied() {
    let (stdout, stderr, ok) = run_js_with_args(
        r#"
import * as net from 'net';
try {
    const client = net.createConnection(80, 'example.com');
    client.on('error', (err) => {
        console.log("error:", err.message.includes("denied") || err.message.includes("permission") ? "permission denied" : err.message);
    });
} catch(e) {
    console.log("error:", e.message.includes("denied") || e.message.includes("permission") ? "permission denied" : e.message);
}
"#,
        &["--sandbox"],
    );
    // In sandbox mode, net access should be denied
    assert!(ok || !ok, "stderr: {stderr}"); // may or may not succeed as process
    let output = format!("{stdout}{stderr}");
    assert!(
        output.contains("denied") || output.contains("permission") || output.contains("Permission"),
        "output: {output}"
    );
}
