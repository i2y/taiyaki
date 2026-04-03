use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

fn run_js(code: &str) -> (String, String, bool) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, code).unwrap();
    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    (stdout, stderr, output.status.success())
}

fn run_js_with_args(code: &str, extra_args: &[&str]) -> (String, String, bool) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
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
// Stream module tests
// ============================================================

#[test]
fn test_stream_readable_push_data() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Readable } from 'stream';
const r = new Readable({ read() {} });
let received = '';
r.on('data', (chunk) => { received += chunk; });
r.on('end', () => { console.log('data:', received); });
r.push('hello ');
r.push('world');
r.push(null);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "data: hello world");
}

#[test]
fn test_stream_writable_finish() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Writable } from 'stream';
let chunks = [];
const w = new Writable({
    write(chunk, enc, cb) { chunks.push(chunk); cb(); }
});
const result = await new Promise((resolve) => {
    w.on('finish', () => { resolve(JSON.stringify(chunks)); });
    w.write('a');
    w.write('b');
    w.end('c');
});
console.log('chunks:', result);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), r#"chunks: ["a","b","c"]"#);
}

#[test]
fn test_stream_pipe() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Readable, Writable } from 'stream';
const r = new Readable({ read() {} });
let out = '';
const w = new Writable({
    write(chunk, enc, cb) { out += chunk; cb(); }
});
w.on('finish', () => { console.log('piped:', out); });
r.pipe(w);
r.push('hello');
r.push(' world');
r.push(null);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "piped: hello world");
}

#[test]
fn test_stream_transform() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Transform } from 'stream';
const t = new Transform({
    transform(chunk, enc, cb) { cb(null, chunk.toUpperCase()); }
});
let out = '';
t.on('data', (d) => { out += d; });
const result = await new Promise((resolve) => {
    t.on('end', () => { resolve(out); });
    t.write('hello');
    t.end(' world');
});
console.log('transformed:', result);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "transformed: HELLO WORLD");
}

#[test]
fn test_stream_passthrough() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { PassThrough } from 'stream';
const pt = new PassThrough();
let out = '';
pt.on('data', (d) => { out += d; });
const result = await new Promise((resolve) => {
    pt.on('end', () => { resolve(out); });
    pt.write('abc');
    pt.end('def');
});
console.log('pass:', result);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "pass: abcdef");
}

#[test]
fn test_stream_pipeline() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Readable, Writable, Transform, pipeline } from 'stream';
const src = new Readable({ read() {} });
const upper = new Transform({
    transform(chunk, enc, cb) { cb(null, chunk.toUpperCase()); }
});
let out = '';
const dest = new Writable({
    write(chunk, enc, cb) { out += chunk; cb(); }
});
pipeline(src, upper, dest, (err) => {
    if (err) console.log('error:', err.message);
    else console.log('result:', out);
});
src.push('hello');
src.push(null);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "result: HELLO");
}

#[test]
fn test_stream_readable_from() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Readable } from 'stream';
const r = Readable.from(['a', 'b', 'c']);
let out = '';
const result = await new Promise((resolve) => {
    r.on('data', (d) => { out += d; });
    r.on('end', () => { resolve(out); });
});
console.log('from:', result);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "from: abc");
}

#[test]
fn test_stream_duplex() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { Duplex } from 'stream';
const d = new Duplex({
    read() {},
    write(chunk, enc, cb) { this.push(chunk.toUpperCase()); cb(); }
});
let out = '';
d.on('data', (chunk) => { out += chunk; });
d.on('end', () => { console.log('duplex:', out); });
d.write('hello');
d.end();
d.push(null);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "duplex: HELLO");
}

// ============================================================
// child_process sync tests
// ============================================================

#[test]
fn test_exec_sync_echo() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { execSync } from 'child_process';
const r = execSync('echo hello');
console.log(r.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "hello");
}

#[test]
fn test_spawn_sync_echo() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { spawnSync } from 'child_process';
const r = spawnSync('echo', ['hello', 'world']);
console.log('status:', r.status);
console.log('stdout:', r.stdout.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("status: 0"), "stdout: {stdout}");
    assert!(stdout.contains("stdout: hello world"), "stdout: {stdout}");
}

#[test]
fn test_exec_sync_failure() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { execSync } from 'child_process';
try {
    execSync('false');
    console.log('should not reach');
} catch (e) {
    console.log('caught:', String(e).includes('exit code'));
}
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "caught: true");
}

#[test]
fn test_exec_file_sync() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { execFileSync } from 'child_process';
const r = execFileSync('/bin/echo', ['test', 'file']);
console.log(r.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "test file");
}

// ============================================================
// child_process async tests
// ============================================================

#[test]
fn test_spawn_async_echo() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { spawn } from 'child_process';
const result = await new Promise((resolve, reject) => {
    const cp = spawn('echo', ['async', 'hello']);
    let out = '';
    cp.stdout.on('data', (d) => { out += d; });
    cp.on('close', (code) => resolve({ code, out }));
    cp.on('error', reject);
});
console.log('code:', result.code);
console.log('out:', result.out.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("code: 0"), "stdout: {stdout}");
    assert!(stdout.contains("out: async hello"), "stdout: {stdout}");
}

#[test]
fn test_exec_async_echo() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { exec } from 'child_process';
const cp = exec('echo hello from exec');
const result = await cp._promise;
console.log('stdout:', result.stdout.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "stdout: hello from exec");
}

#[test]
fn test_spawn_async_stderr() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { spawn } from 'child_process';
const result = await new Promise((resolve, reject) => {
    const cp = spawn('sh', ['-c', 'echo errout >&2']);
    let err = '';
    cp.stderr.on('data', (d) => { err += d; });
    cp.on('close', (code) => resolve({ code, err }));
    cp.on('error', reject);
});
console.log('stderr:', result.err.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "stderr: errout");
}

#[test]
fn test_spawn_permission_denied() {
    let (stdout, _stderr, _ok) = run_js_with_args(
        r#"
import { execSync } from 'child_process';
try {
    execSync('echo hello');
    console.log('not denied');
} catch (e) {
    console.log('denied');
}
"#,
        &["--sandbox"],
    );
    assert_eq!(stdout.trim(), "denied");
}

#[test]
fn test_spawn_permission_allowed() {
    let (stdout, stderr, ok) = run_js_with_args(
        r#"
import { execSync } from 'child_process';
const r = execSync('echo allowed');
console.log(r.trim());
"#,
        &["--sandbox", "--allow-run=sh"],
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "allowed");
}

// ============================================================
// fs.promises true async tests
// ============================================================

#[test]
fn test_fs_promises_read_write() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';
const path = '/tmp/test_async_rw_' + Date.now() + '.txt';
await fs.promises.writeFile(path, 'async content');
const content = await fs.promises.readFile(path);
console.log(content);
await fs.promises.unlink(path);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "async content");
}

#[test]
fn test_fs_promises_stat() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';
const path = '/tmp/test_async_stat_' + Date.now() + '.txt';
await fs.promises.writeFile(path, 'hello');
const stat = await fs.promises.stat(path);
console.log('size:', stat.size);
console.log('isFile:', stat.isFile());
await fs.promises.unlink(path);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("size: 5"), "stdout: {stdout}");
    assert!(stdout.contains("isFile: true"), "stdout: {stdout}");
}

#[test]
fn test_fs_promises_readdir() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';
const dir = '/tmp/test_async_dir_' + Date.now();
await fs.promises.mkdir(dir);
await fs.promises.writeFile(dir + '/a.txt', 'a');
await fs.promises.writeFile(dir + '/b.txt', 'b');
const entries = await fs.promises.readdir(dir);
console.log('count:', entries.length);
console.log('has_a:', entries.includes('a.txt'));
console.log('has_b:', entries.includes('b.txt'));
await fs.promises.rm(dir, { recursive: true });
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("count: 2"), "stdout: {stdout}");
    assert!(stdout.contains("has_a: true"), "stdout: {stdout}");
    assert!(stdout.contains("has_b: true"), "stdout: {stdout}");
}

#[test]
fn test_fs_promises_rename_copy() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';
const a = '/tmp/test_async_rename_a_' + Date.now() + '.txt';
const b = '/tmp/test_async_rename_b_' + Date.now() + '.txt';
const c = '/tmp/test_async_rename_c_' + Date.now() + '.txt';
await fs.promises.writeFile(a, 'content');
await fs.promises.rename(a, b);
await fs.promises.copyFile(b, c);
const content = await fs.promises.readFile(c);
console.log(content);
await fs.promises.unlink(b);
await fs.promises.unlink(c);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "content");
}

// ============================================================
// fs.watch tests
// ============================================================

#[test]
fn test_fs_watch_fires_on_change() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';

const dir = '/tmp/test_fswatch_' + Date.now();
fs.mkdirSync(dir);

const result = await new Promise((resolve) => {
    const watcher = fs.watch(dir, (eventType, filename) => {
        watcher.close();
        resolve({ eventType, filename });
    });
    setTimeout(() => {
        fs.writeFileSync(dir + '/test.txt', 'data');
    }, 200);
    setTimeout(() => {
        watcher.close();
        resolve({ eventType: 'timeout', filename: '' });
    }, 3000);
});

console.log('event:', result.eventType);
fs.rmSync(dir, { recursive: true });
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(stdout.contains("event: change"), "stdout: {stdout}");
}

#[test]
fn test_fs_watch_close() {
    let (stdout, stderr, ok) = run_js(
        r#"
import fs from 'fs';

const dir = '/tmp/test_fswatch_close_' + Date.now();
fs.mkdirSync(dir);

let eventCount = 0;
const watcher = fs.watch(dir, () => { eventCount++; });

// Close immediately
watcher.close();

// Write a file after close — should not trigger
setTimeout(() => {
    fs.writeFileSync(dir + '/test.txt', 'data');
}, 200);

setTimeout(() => {
    console.log('events:', eventCount);
    fs.rmSync(dir, { recursive: true });
}, 1000);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "events: 0");
}

// ============================================================
// Integration: child_process + stream
// ============================================================

#[test]
fn test_spawn_with_stdin() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { spawn } from 'child_process';
const result = await new Promise((resolve, reject) => {
    const cp = spawn('cat', []);
    let out = '';
    cp.stdout.on('data', (d) => { out += d; });
    cp.on('close', (code) => resolve(out));
    cp.on('error', reject);
    cp.stdin.write('hello from stdin');
    cp.stdin.end();
});
console.log(result.trim());
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "hello from stdin");
}
