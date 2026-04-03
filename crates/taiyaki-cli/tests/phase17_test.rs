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

fn run_js_with_stdin(code: &str, stdin_data: &str) -> (String, String, bool) {
    use std::io::Write;
    use std::process::Stdio;

    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.mjs");
    std::fs::write(&file, code).unwrap();
    let mut child = taiyaki_bin()
        .arg("run")
        .arg(&file)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .as_mut()
        .unwrap()
        .write_all(stdin_data.as_bytes())
        .unwrap();
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    (stdout, stderr, output.status.success())
}

// ============================================================
// vm module
// ============================================================

#[test]
fn test_vm_run_in_new_context() {
    let (out, err, ok) = run_js(
        r#"
import vm from 'vm';
const result = vm.runInNewContext('x + y', { x: 10, y: 20 });
console.log(result);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "30");
}

#[test]
fn test_vm_run_in_this_context() {
    let (out, err, ok) = run_js(
        r#"
import { runInThisContext } from 'vm';
const result = runInThisContext('1 + 2 + 3');
console.log(result);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "6");
}

#[test]
fn test_vm_script_class() {
    let (out, err, ok) = run_js(
        r#"
import { Script } from 'vm';
const script = new Script('a * b');
console.log(script.runInNewContext({ a: 5, b: 6 }));
console.log(script.runInNewContext({ a: 3, b: 7 }));
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["30", "21"]);
}

#[test]
fn test_vm_create_context() {
    let (out, err, ok) = run_js(
        r#"
import vm from 'vm';
const ctx = vm.createContext({ greeting: 'hello' });
console.log(vm.isContext(ctx));
console.log(vm.isContext({}));
const r = vm.runInNewContext('greeting + " world"', ctx);
console.log(r);
"#,
    );
    assert!(ok, "stderr: {err}");
    let lines: Vec<&str> = out.trim().lines().collect();
    assert_eq!(lines, vec!["true", "false", "hello world"]);
}

#[test]
fn test_vm_sandbox_isolation() {
    let (out, err, ok) = run_js(
        r#"
import vm from 'vm';
const globalVal = 42;
const result = vm.runInNewContext('typeof globalVal', {});
console.log(result);
"#,
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "undefined");
}

// ============================================================
// readline module
// ============================================================

#[test]
fn test_readline_question() {
    let (out, err, ok) = run_js_with_stdin(
        r#"
import { createInterface } from 'readline';
const rl = createInterface({});
rl.question('Name? ', (answer) => {
    console.log('Hi ' + answer);
    rl.close();
});
"#,
        "Alice\n",
    );
    assert!(ok, "stderr: {err}");
    assert!(out.contains("Hi Alice"), "stdout: {out}");
}

#[test]
fn test_readline_on_line() {
    let (out, err, ok) = run_js_with_stdin(
        r#"
import { createInterface } from 'readline';
const rl = createInterface({});
const lines = [];
rl.on('line', (line) => { lines.push(line); });
rl.on('close', () => { console.log(lines.join(',')); });
"#,
        "aaa\nbbb\nccc\n",
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "aaa,bbb,ccc");
}

#[test]
fn test_readline_close_event() {
    let (out, err, ok) = run_js_with_stdin(
        r#"
import { createInterface } from 'readline';
const rl = createInterface({});
rl.on('close', () => { console.log('closed'); });
rl.on('line', () => {});
"#,
        "",
    );
    assert!(ok, "stderr: {err}");
    assert_eq!(out.trim(), "closed");
}

#[test]
fn test_readline_node_prefix() {
    let (out, err, ok) = run_js_with_stdin(
        r#"
import { createInterface } from 'node:readline';
const rl = createInterface({});
rl.question('> ', (a) => { console.log(a); rl.close(); });
"#,
        "test\n",
    );
    assert!(ok, "stderr: {err}");
    assert!(out.contains("test"), "stdout: {out}");
}
