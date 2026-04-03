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

// ============================================================
// performance.mark / performance.measure
// ============================================================

#[test]
fn test_performance_mark_basic() {
    let (out, err, ok) = run_js(
        r#"
const m = performance.mark('test');
console.log(m.name, m.entryType, m.duration, typeof m.startTime);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "test mark 0 number");
}

#[test]
fn test_performance_measure_between_marks() {
    let (out, err, ok) = run_js(
        r#"
performance.mark('a');
for (let i = 0; i < 100000; i++) {}
performance.mark('b');
const m = performance.measure('ab', 'a', 'b');
console.log(m.entryType, m.duration >= 0, m.name);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "measure true ab");
}

#[test]
fn test_performance_get_entries_by_type() {
    let (out, err, ok) = run_js(
        r#"
performance.mark('x');
performance.mark('y');
performance.measure('m1', 'x', 'y');
console.log(performance.getEntriesByType('mark').length);
console.log(performance.getEntriesByType('measure').length);
console.log(performance.getEntries().length);
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["2", "1", "3"]);
}

#[test]
fn test_performance_clear_marks() {
    let (out, err, ok) = run_js(
        r#"
performance.mark('a');
performance.mark('b');
performance.mark('a');
console.log(performance.getEntriesByType('mark').length);
performance.clearMarks('a');
console.log(performance.getEntriesByType('mark').length);
performance.clearMarks();
console.log(performance.getEntriesByType('mark').length);
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["3", "1", "0"]);
}

#[test]
fn test_performance_measure_options() {
    let (out, err, ok) = run_js(
        r#"
const m = performance.measure('dur', { start: 10, duration: 5, detail: 'info' });
console.log(m.startTime, m.duration, m.detail);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "10 5 info");
}

// ============================================================
// Blob / File / FormData
// ============================================================

#[test]
fn test_blob_basic() {
    let (out, err, ok) = run_js(
        r#"
const b = new Blob(['hello', ' world'], { type: 'text/plain' });
console.log(b.size, b.type, b instanceof Blob);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "11 text/plain true");
}

#[test]
fn test_blob_text_and_arraybuffer() {
    let (out, err, ok) = run_js(
        r#"
const b = new Blob(['abc']);
const t = await b.text();
const ab = await b.arrayBuffer();
console.log(t, ab.byteLength);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "abc 3");
}

#[test]
fn test_blob_slice() {
    let (out, err, ok) = run_js(
        r#"
const b = new Blob(['hello world']);
const s = b.slice(0, 5, 'text/plain');
const t = await s.text();
console.log(t, s.size, s.type);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "hello 5 text/plain");
}

#[test]
fn test_file_basic() {
    let (out, err, ok) = run_js(
        r#"
const f = new File(['content'], 'readme.txt', { type: 'text/plain', lastModified: 1000 });
console.log(f.name, f.size, f.type, f.lastModified, f instanceof Blob);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "readme.txt 7 text/plain 1000 true");
}

#[test]
fn test_formdata_crud() {
    let (out, err, ok) = run_js(
        r#"
const fd = new FormData();
fd.append('a', '1');
fd.append('a', '2');
fd.set('b', '3');
console.log(fd.get('a'), fd.getAll('a').length, fd.has('b'));
fd.delete('a');
console.log(fd.has('a'), fd.get('b'));
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["1 2 true", "false 3"]);
}

#[test]
fn test_formdata_iteration() {
    let (out, err, ok) = run_js(
        r#"
const fd = new FormData();
fd.append('x', '1');
fd.append('y', '2');
const keys = [];
for (const [k, v] of fd) { keys.push(k + '=' + v); }
console.log(keys.join(','));
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "x=1,y=2");
}

#[test]
fn test_response_blob() {
    let (out, err, ok) = run_js(
        r#"
const r = new Response('hello', { headers: { 'content-type': 'text/plain' } });
const b = await r.blob();
console.log(b instanceof Blob, b.size, b.type);
const t = await b.text();
console.log(t);
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["true 5 text/plain", "hello"]);
}

// ============================================================
// SQLite (only compiled with --features sqlite)
// ============================================================

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_memory() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'bun:sqlite';
const db = new Database();
db.exec('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)');
db.run('INSERT INTO t (v) VALUES (?)', 'hello');
const rows = db.query('SELECT * FROM t').all();
console.log(JSON.stringify(rows));
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), r#"[{"id":1,"v":"hello"}]"#);
}

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_parameterized() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'sqlite';
const db = new Database(':memory:');
db.exec('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)');
db.run('INSERT INTO users (name, age) VALUES (?, ?)', 'Alice', 30);
db.run('INSERT INTO users (name, age) VALUES (?, ?)', 'Bob', 25);
const row = db.query('SELECT * FROM users WHERE name = ?').get('Alice');
console.log(row.name, row.age);
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "Alice 30");
}

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_run_changes() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'bun:sqlite';
const db = new Database(':memory:');
db.exec('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)');
db.run('INSERT INTO t (v) VALUES (?)', 'a');
db.run('INSERT INTO t (v) VALUES (?)', 'b');
const result = db.run('DELETE FROM t WHERE v = ?', 'a');
console.log(result.changes);
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "1");
}

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_get_null() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'bun:sqlite';
const db = new Database(':memory:');
db.exec('CREATE TABLE t (id INTEGER PRIMARY KEY)');
const row = db.query('SELECT * FROM t WHERE id = ?').get(999);
console.log(row);
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "null");
}

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_values() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'bun:sqlite';
const db = new Database(':memory:');
db.exec('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)');
db.run('INSERT INTO t (v) VALUES (?)', 'x');
db.run('INSERT INTO t (v) VALUES (?)', 'y');
const vals = db.query('SELECT id, v FROM t').values();
console.log(JSON.stringify(vals));
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), r#"[[1,"x"],[2,"y"]]"#);
}

#[cfg(feature = "sqlite")]
#[test]
fn test_sqlite_prepare_alias() {
    let (out, err, ok) = run_js(
        r#"
import { Database } from 'bun:sqlite';
const db = new Database(':memory:');
db.exec('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)');
db.run('INSERT INTO t (v) VALUES (?)', 'test');
const stmt = db.prepare('SELECT v FROM t');
const row = stmt.get();
console.log(row.v);
db.close();
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "test");
}

// ============================================================
// worker_threads
// ============================================================

#[test]
fn test_worker_is_main_thread() {
    let (out, err, ok) = run_js(
        r#"
import { isMainThread, threadId } from 'worker_threads';
console.log(isMainThread, threadId);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "true 0");
}

#[test]
fn test_worker_basic_message() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
import { parentPort } from 'worker_threads';
parentPort.on('message', (msg) => {
    parentPort.postMessage({ echo: msg });
});
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs');
w.on('message', (msg) => {
    console.log(JSON.stringify(msg));
    w.terminate();
});
w.postMessage('hello');
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    assert_eq!(stdout.trim(), r#"{"echo":"hello"}"#);
}

#[test]
fn test_worker_data() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
import { parentPort, workerData, isMainThread } from 'worker_threads';
parentPort.postMessage({ data: workerData, main: isMainThread });
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs', { workerData: { key: 'value' } });
w.on('message', (msg) => {
    console.log(JSON.stringify(msg));
    w.terminate();
});
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    assert_eq!(stdout.trim(), r#"{"data":{"key":"value"},"main":false}"#);
}

#[test]
fn test_worker_multiple_messages() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
import { parentPort } from 'worker_threads';
parentPort.on('message', (msg) => {
    parentPort.postMessage(msg * 2);
});
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs');
const results = [];
w.on('message', (msg) => {
    results.push(msg);
    if (results.length === 3) {
        console.log(results.join(','));
        w.terminate();
    }
});
w.postMessage(1);
w.postMessage(2);
w.postMessage(3);
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    assert_eq!(stdout.trim(), "2,4,6");
}

#[test]
fn test_worker_exit_event() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
// Worker does nothing, just exits
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs');
w.on('exit', (code) => {
    console.log('exit:' + code);
});
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    assert_eq!(stdout.trim(), "exit:0");
}

#[test]
fn test_worker_error_event() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
throw new Error('worker failed');
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs');
w.on('error', (err) => {
    console.log('error:' + err.message.includes('worker failed'));
});
w.on('exit', (code) => {
    console.log('exit:' + code);
});
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert!(lines.contains(&"error:true"), "stdout: {stdout}");
    assert!(lines.contains(&"exit:1"), "stdout: {stdout}");
}

#[test]
fn test_worker_terminate() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("worker.mjs"),
        r#"
import { parentPort } from 'worker_threads';
parentPort.on('message', () => {
    parentPort.postMessage('ack');
});
"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.mjs"),
        r#"
import { Worker } from 'worker_threads';
const w = new Worker('./worker.mjs');
w.on('message', () => {
    w.terminate().then((code) => {
        console.log('terminated:' + code);
    });
});
w.postMessage('go');
"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("run")
        .arg(dir.path().join("main.mjs"))
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "stderr: {stderr}");
    assert_eq!(stdout.trim(), "terminated:0");
}
