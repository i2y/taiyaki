use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

fn run_js(code: &str) -> (bool, String, String) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, code).unwrap();
    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    (
        output.status.success(),
        String::from_utf8_lossy(&output.stdout).to_string(),
        String::from_utf8_lossy(&output.stderr).to_string(),
    )
}

// --- URL ---

#[test]
fn test_url_parse() {
    let (ok, stdout, _) = run_js(
        r#"
const u = new URL("https://example.com:8080/path?q=1#hash");
console.log(u.protocol);
console.log(u.hostname);
console.log(u.port);
console.log(u.pathname);
console.log(u.search);
console.log(u.hash);
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "https:");
    assert_eq!(lines[1], "example.com");
    assert_eq!(lines[2], "8080");
    assert_eq!(lines[3], "/path");
    assert_eq!(lines[4], "?q=1");
    assert_eq!(lines[5], "#hash");
}

#[test]
fn test_url_search_params() {
    let (ok, stdout, _) = run_js(
        r#"
const u = new URL("https://example.com/?a=1&b=2");
console.log(u.searchParams.get("a"));
console.log(u.searchParams.get("b"));
u.searchParams.set("c", "3");
console.log(u.searchParams.toString());
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "1");
    assert_eq!(lines[1], "2");
    assert!(lines[2].contains("c=3"));
}

// --- AbortController ---

#[test]
fn test_abort_controller_basic() {
    let (ok, stdout, _) = run_js(
        r#"
const ac = new AbortController();
console.log(ac.signal.aborted);
ac.abort();
console.log(ac.signal.aborted);
console.log(ac.signal.reason instanceof DOMException);
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "false");
    assert_eq!(lines[1], "true");
    assert_eq!(lines[2], "true");
}

#[test]
fn test_abort_controller_listener() {
    let (ok, stdout, _) = run_js(
        r#"
const ac = new AbortController();
let called = false;
ac.signal.addEventListener('abort', () => { called = true; });
ac.abort();
console.log(called);
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "true");
}

#[test]
fn test_abort_signal_abort() {
    let (ok, stdout, _) = run_js(
        r#"
const s = AbortSignal.abort("custom reason");
console.log(s.aborted);
console.log(s.reason);
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "true");
    assert_eq!(lines[1], "custom reason");
}

// --- Headers ---

#[test]
fn test_headers_basic() {
    let (ok, stdout, _) = run_js(
        r#"
const h = new Headers({"Content-Type": "text/html"});
console.log(h.get("content-type"));
console.log(h.has("content-type"));
h.set("X-Custom", "value");
console.log(h.get("x-custom"));
h.delete("x-custom");
console.log(h.has("x-custom"));
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "text/html");
    assert_eq!(lines[1], "true");
    assert_eq!(lines[2], "value");
    assert_eq!(lines[3], "false");
}

#[test]
fn test_headers_append() {
    let (ok, stdout, _) = run_js(
        r#"
const h = new Headers();
h.append("x-val", "a");
h.append("x-val", "b");
console.log(h.get("x-val"));
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "a, b");
}

#[test]
fn test_headers_iterator() {
    let (ok, stdout, _) = run_js(
        r#"
const h = new Headers({"B": "2", "A": "1"});
const entries = [];
for (const [k, v] of h) entries.push(k + "=" + v);
console.log(entries.join(","));
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "a=1,b=2");
}

// --- ReadableStream ---

#[test]
fn test_readable_stream_basic() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const rs = new ReadableStream({
        start(controller) {
            controller.enqueue("a");
            controller.enqueue("b");
            controller.close();
        }
    });
    const reader = rs.getReader();
    const r1 = await reader.read();
    const r2 = await reader.read();
    const r3 = await reader.read();
    console.log(r1.value, r2.value, r3.done);
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "a b true");
}

#[test]
fn test_readable_stream_async_iterator() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const rs = new ReadableStream({
        start(controller) {
            controller.enqueue(1);
            controller.enqueue(2);
            controller.enqueue(3);
            controller.close();
        }
    });
    const chunks = [];
    for await (const chunk of rs) chunks.push(chunk);
    console.log(chunks.join(","));
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "1,2,3");
}

#[test]
fn test_readable_stream_tee() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const rs = new ReadableStream({
        start(controller) {
            controller.enqueue("x");
            controller.enqueue("y");
            controller.close();
        }
    });
    const [b1, b2] = rs.tee();
    const r1 = b1.getReader();
    const r2 = b2.getReader();
    const a = await r1.read();
    const b = await r2.read();
    console.log(a.value, b.value);
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "x x");
}

#[test]
fn test_readable_stream_from() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const rs = ReadableStream.from([10, 20, 30]);
    const reader = rs.getReader();
    const chunks = [];
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        chunks.push(value);
    }
    console.log(chunks.join(","));
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "10,20,30");
}

// --- WritableStream ---

#[test]
fn test_writable_stream_basic() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const chunks = [];
    const ws = new WritableStream({
        write(chunk) { chunks.push(chunk); }
    });
    const writer = ws.getWriter();
    await writer.write("hello");
    await writer.write("world");
    await writer.close();
    console.log(chunks.join(" "));
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "hello world");
}

// --- TransformStream ---

#[test]
fn test_transform_stream() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const ts = new TransformStream({
        transform(chunk, controller) {
            controller.enqueue(chunk.toUpperCase());
        }
    });
    const writer = ts.writable.getWriter();
    const reader = ts.readable.getReader();
    writer.write("hello");
    writer.close();
    const r = await reader.read();
    console.log(r.value);
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "HELLO");
}

#[test]
fn test_pipe_through() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const source = new ReadableStream({
        start(controller) {
            controller.enqueue("abc");
            controller.enqueue("def");
            controller.close();
        }
    });
    const upper = new TransformStream({
        transform(chunk, ctrl) { ctrl.enqueue(chunk.toUpperCase()); }
    });
    const reader = source.pipeThrough(upper).getReader();
    const chunks = [];
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        chunks.push(value);
    }
    console.log(chunks.join(","));
}
main();
"#,
    );
    assert!(ok);
    assert_eq!(stdout.trim(), "ABC,DEF");
}

// --- Request ---

#[test]
fn test_request_basic() {
    let (ok, stdout, _) = run_js(
        r#"
const req = new Request("https://example.com/api", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: '{"key":"value"}'
});
console.log(req.method);
console.log(req.url);
console.log(req.headers.get("content-type"));
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "POST");
    assert_eq!(lines[1], "https://example.com/api");
    assert_eq!(lines[2], "application/json");
}

#[test]
fn test_request_body() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const req = new Request("https://example.com", { method: "POST", body: "hello" });
    console.log(await req.text());
    console.log(req.bodyUsed);
}
main();
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "hello");
    assert_eq!(lines[1], "true");
}

#[test]
fn test_request_clone() {
    let (ok, stdout, _) = run_js(
        r#"
const req = new Request("https://example.com", { method: "PUT", body: "data" });
const clone = req.clone();
console.log(clone.method);
console.log(clone.url);
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "PUT");
    assert_eq!(lines[1], "https://example.com");
}

// --- Response ---

#[test]
fn test_response_basic() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const res = new Response("hello", { status: 201, statusText: "Created" });
    console.log(res.status);
    console.log(res.statusText);
    console.log(res.ok);
    console.log(await res.text());
}
main();
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "201");
    assert_eq!(lines[1], "Created");
    assert_eq!(lines[2], "true");
    assert_eq!(lines[3], "hello");
}

#[test]
fn test_response_json() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const res = Response.json({ x: 42 });
    console.log(res.status);
    console.log(res.headers.get("content-type"));
    const data = await res.json();
    console.log(data.x);
}
main();
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "200");
    assert_eq!(lines[1], "application/json");
    assert_eq!(lines[2], "42");
}

#[test]
fn test_response_redirect() {
    let (ok, stdout, _) = run_js(
        r#"
const res = Response.redirect("https://example.com", 301);
console.log(res.status);
console.log(res.headers.get("location"));
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "301");
    assert_eq!(lines[1], "https://example.com");
}

#[test]
fn test_response_clone() {
    let (ok, stdout, _) = run_js(
        r#"
async function main() {
    const res = new Response("body", { status: 200 });
    const clone = res.clone();
    console.log(await res.text());
    console.log(await clone.text());
}
main();
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "body");
    assert_eq!(lines[1], "body");
}

// --- HTTP Server ---

#[test]
fn test_http_server_basic() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    fetch(req) {
        return new Response("Hello from Katana");
    }
});

const res = await fetch("http://localhost:" + server.port + "/");
console.log(res.status);
console.log(await res.text());
server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "200");
    assert_eq!(lines[1], "Hello from Katana");
}

#[test]
fn test_http_server_json() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    fetch(req) {
        return Response.json({ ok: true, method: req.method });
    }
});

const res = await fetch("http://localhost:" + server.port + "/");
const data = await res.json();
console.log(data.ok);
console.log(data.method);
server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "true");
    assert_eq!(lines[1], "GET");
}

#[test]
fn test_http_server_routing() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    fetch(req) {
        const url = new URL(req.url);
        if (url.pathname === "/hello") return new Response("world");
        if (url.pathname === "/status") return new Response("ok", { status: 201 });
        return new Response("not found", { status: 404 });
    }
});

const r1 = await fetch("http://localhost:" + server.port + "/hello");
console.log(await r1.text());

const r2 = await fetch("http://localhost:" + server.port + "/status");
console.log(r2.status);

const r3 = await fetch("http://localhost:" + server.port + "/unknown");
console.log(r3.status);

server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "world");
    assert_eq!(lines[1], "201");
    assert_eq!(lines[2], "404");
}

#[test]
fn test_http_server_post_body() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    async fetch(req) {
        if (req.method === "POST") {
            const body = await req.text();
            return new Response("received: " + body);
        }
        return new Response("get");
    }
});

const res = await fetch("http://localhost:" + server.port + "/", {
    method: "POST",
    body: "hello world"
});
console.log(await res.text());
server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "received: hello world");
}

#[test]
fn test_http_server_response_headers() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    fetch(req) {
        return new Response("ok", {
            headers: { "X-Custom": "test-value", "Content-Type": "text/plain" }
        });
    }
});

const res = await fetch("http://localhost:" + server.port + "/");
console.log(res.headers.get("x-custom"));
console.log(res.headers.get("content-type"));
server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "test-value");
    assert_eq!(lines[1], "text/plain");
}

#[test]
fn test_http_server_async_handler() {
    let (ok, stdout, stderr) = run_js(
        r#"
const server = await Katana.serve({
    port: 0,
    async fetch(req) {
        await new Promise(r => setTimeout(r, 10));
        return new Response("async response");
    }
});

const res = await fetch("http://localhost:" + server.port + "/");
console.log(await res.text());
server.stop();
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "async response");
}

// --- DOMException ---

#[test]
fn test_dom_exception() {
    let (ok, stdout, _) = run_js(
        r#"
const e = new DOMException("test message", "TestError");
console.log(e.message);
console.log(e.name);
console.log(e instanceof Error);
"#,
    );
    assert!(ok);
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "test message");
    assert_eq!(lines[1], "TestError");
    assert_eq!(lines[2], "true");
}
