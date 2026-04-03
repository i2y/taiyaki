use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

#[test]
fn test_run_js_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log('hello');\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello");
}

#[test]
fn test_run_ts_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.ts");
    std::fs::write(&file, "const x: number = 42;\nconsole.log(x);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "42");
}

#[test]
fn test_console_log_multiple_args() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log('a', 'b', 'c');\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "a b c");
}

#[test]
fn test_read_write_file() {
    let dir = tempfile::tempdir().unwrap();
    let data_file = dir.path().join("data.txt");
    let out_file = dir.path().join("out.txt");
    std::fs::write(&data_file, "hello from file").unwrap();

    let script = dir.path().join("test.js");
    std::fs::write(
        &script,
        format!(
            r#"
var content = readFile('{}');
writeFile('{}', content + ' modified');
console.log('done');
"#,
            data_file.display(),
            out_file.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&script).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "done");
    assert_eq!(
        std::fs::read_to_string(&out_file).unwrap(),
        "hello from file modified"
    );
}

#[test]
fn test_run_module_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "export const x = 10;\nconsole.log('module', x);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "module 10");
}

#[test]
fn test_run_error_exit_code() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "throw new Error('boom');\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(!output.status.success());
}

// ── Phase 5: console.log formatting ──

#[test]
fn test_console_log_object() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log({a: 1, b: 'hello'});\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "{ a: 1, b: 'hello' }"
    );
}

#[test]
fn test_console_log_array() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log([1, 'two', true]);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "[ 1, 'two', true ]"
    );
}

#[test]
fn test_console_log_nested() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log({a: {b: {c: 1}}});\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "{ a: { b: { c: 1 } } }"
    );
}

#[test]
fn test_console_log_circular() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "var a = {}; a.self = a; console.log(a);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "{ self: [Circular] }"
    );
}

#[test]
fn test_console_log_function() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(function foo() {});\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "[Function: foo]"
    );
}

#[test]
fn test_console_log_null_undefined() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(null, undefined);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "null undefined"
    );
}

// ── Phase 5: Timer APIs ──

#[test]
fn test_set_timeout_returns_id() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "var id = setTimeout(() => {}, 10); console.log(typeof id);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "number");
}

#[test]
fn test_clear_timeout() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
var id = setTimeout(() => console.log('should not fire'), 50);
clearTimeout(id);
setTimeout(() => console.log('done'), 100);
void 0;
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "done");
}

#[test]
fn test_set_interval_and_clear() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
var count = 0;
var id = setInterval(() => {
    count++;
    console.log('tick');
    if (count >= 3) clearInterval(id);
}, 30);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "tick\ntick\ntick"
    );
}

// ── Phase 5: process globals ──

#[test]
fn test_process_argv() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.argv.length >= 2);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_process_argv_user_args() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.argv.slice(2).join(','));\n").unwrap();

    let output = taiyaki_bin()
        .arg("run")
        .arg(&file)
        .arg("foo")
        .arg("bar")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "foo,bar");
}

#[test]
fn test_process_env() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.env.LIBTS_TEST_VAR);\n").unwrap();

    let output = taiyaki_bin()
        .arg("run")
        .arg(&file)
        .env("LIBTS_TEST_VAR", "hello123")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello123");
}

// ── Phase 5: fetch Response enhancements ──

#[test]
fn test_base64_decode() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
var decoded = __base64_decode('AQID');
var u8 = new Uint8Array(decoded);
console.log(u8.length, u8[0], u8[1], u8[2]);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "3 1 2 3");
}

// ── Phase 8: CLI infrastructure ──

#[test]
fn test_version_flag() {
    let output = taiyaki_bin().arg("--version").output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(out.contains("taiyaki"));
}

#[test]
fn test_eval_subcommand() {
    let output = taiyaki_bin().arg("eval").arg("1 + 2").output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "3");
}

#[test]
fn test_eval_console_log() {
    let output = taiyaki_bin()
        .arg("eval")
        .arg("console.log('hello eval')")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello eval");
}

#[test]
fn test_jsx_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.jsx");
    // automatic runtime: jsx("div", { id: "test", children: "hello" })
    std::fs::write(
        &file,
        r#"const el = <div id="test">hello</div>;
console.log(el.type, el.props.id, el.props.children);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "div test hello"
    );
}

#[test]
fn test_tsx_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.tsx");
    // automatic runtime with TypeScript types
    std::fs::write(
        &file,
        r#"type Props = { name: string };
const el = <span class="a">world</span>;
console.log(el.type, el.props.children);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "span world");
}

#[test]
fn test_shebang() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "#!/usr/bin/env taiyaki run\nconsole.log('shebang');\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "shebang");
}

#[test]
fn test_package_json_module_detection() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("package.json"), r#"{"type": "module"}"#).unwrap();
    // This file has no import/export/await but should be treated as module
    // due to package.json type:module. Modules can use top-level const.
    let file = dir.path().join("test.js");
    std::fs::write(&file, "const x = 42;\nconsole.log(x);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "42");
}

// ── Phase 8: Web Platform globals ──

#[test]
fn test_performance_now() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "console.log(typeof performance.now(), performance.now() >= 0);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "number true"
    );
}

#[test]
fn test_text_encoder_decoder() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const enc = new TextEncoder();
const dec = new TextDecoder();
const encoded = enc.encode('hello');
const decoded = dec.decode(encoded);
console.log(decoded, encoded.length);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello 5");
}

#[test]
fn test_text_encoder_unicode() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const enc = new TextEncoder();
const dec = new TextDecoder();
const encoded = enc.encode('こんにちは');
console.log(dec.decode(encoded));
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "こんにちは");
}

#[test]
fn test_queue_microtask() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "queueMicrotask(() => console.log('micro'));\nconsole.log('sync');\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(out.contains("sync"));
    assert!(out.contains("micro"));
}

#[test]
fn test_structured_clone() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const orig = { a: 1, b: [2, 3], c: { d: 4 } };
const clone = structuredClone(orig);
clone.b.push(99);
clone.c.d = 999;
console.log(orig.b.length, orig.c.d, clone.b.length, clone.c.d);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "2 4 3 999");
}

// ── Phase 8: process enhancements ──

#[test]
fn test_process_cwd() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(typeof process.cwd());\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "string");
}

#[test]
fn test_process_platform() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.platform);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(
        out.trim() == "darwin" || out.trim() == "linux",
        "unexpected platform: {}",
        out.trim()
    );
}

#[test]
fn test_process_arch() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.arch);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(
        out.trim() == "arm64" || out.trim() == "x64",
        "unexpected arch: {}",
        out.trim()
    );
}

#[test]
fn test_process_pid() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.log(process.pid > 0);\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_process_hrtime() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const t = process.hrtime();
console.log(Array.isArray(t), t.length === 2, typeof t[0] === 'number');
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "true true true"
    );
}

#[test]
fn test_process_stdout_write() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "process.stdout.write('no newline'); void 0;\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout), "no newline");
}

// ── Phase 8: console enhancements ──

#[test]
fn test_console_time() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.time('t');\nconsole.timeEnd('t');\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(out.contains("t:"), "expected timer output, got: {out}");
    assert!(out.contains("ms"), "expected ms suffix, got: {out}");
}

#[test]
fn test_console_count() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "console.count('a');\nconsole.count('a');\nconsole.count('a');\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(out.contains("a: 1"));
    assert!(out.contains("a: 2"));
    assert!(out.contains("a: 3"));
}

#[test]
fn test_console_assert() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "console.assert(true, 'ok');\nconsole.assert(false, 'fail');\nconsole.log('done');\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("Assertion failed"));
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "done");
}

#[test]
fn test_console_debug_info() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "console.debug('dbg');\nconsole.info('inf');\n").unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(output.status.success());
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(out.contains("dbg"));
    assert!(out.contains("inf"));
}

// ── Phase 8: fs module ──

#[test]
fn test_fs_read_write_sync() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let data_file = dir.path().join("data.txt");
    std::fs::write(
        &file,
        format!(
            r#"import {{ readFileSync, writeFileSync }} from 'fs';
writeFileSync('{}', 'hello fs');
const content = readFileSync('{}');
console.log(content);
"#,
            data_file.display(),
            data_file.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "hello fs");
}

#[test]
fn test_fs_exists_sync() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let existing = dir.path().join("exists.txt");
    std::fs::write(&existing, "").unwrap();
    std::fs::write(
        &file,
        format!(
            r#"import {{ existsSync }} from 'fs';
console.log(existsSync('{}'), existsSync('/nonexistent_path_12345'));
"#,
            existing.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true false");
}

#[test]
fn test_fs_mkdir_readdir() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let sub = dir.path().join("sub");
    std::fs::write(
        &file,
        format!(
            r#"import {{ mkdirSync, writeFileSync, readdirSync }} from 'fs';
mkdirSync('{}');
writeFileSync('{}/a.txt', 'a');
writeFileSync('{}/b.txt', 'b');
const entries = readdirSync('{}');
console.log(entries.join(','));
"#,
            sub.display(),
            sub.display(),
            sub.display(),
            sub.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(
        out.contains("a.txt") && out.contains("b.txt"),
        "expected both files: {out}"
    );
}

#[test]
fn test_fs_stat_sync() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let data = dir.path().join("data.txt");
    std::fs::write(&data, "12345").unwrap();
    std::fs::write(
        &file,
        format!(
            r#"import {{ statSync }} from 'fs';
const s = statSync('{}');
console.log(s.isFile(), s.isDirectory(), s.size);
"#,
            data.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "true false 5"
    );
}

#[test]
fn test_fs_unlink_rename() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let a = dir.path().join("a.txt");
    let b = dir.path().join("b.txt");
    std::fs::write(&a, "content").unwrap();
    std::fs::write(
        &file,
        format!(
            r#"import {{ renameSync, existsSync, readFileSync }} from 'fs';
renameSync('{}', '{}');
console.log(existsSync('{}'), readFileSync('{}'));
"#,
            a.display(),
            b.display(),
            a.display(),
            b.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "false content"
    );
}

#[test]
fn test_fs_node_prefix() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import { existsSync } from 'node:fs';\nconsole.log(typeof existsSync);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "function");
}

#[test]
fn test_fs_promises() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    let data = dir.path().join("prom.txt");
    std::fs::write(
        &file,
        format!(
            r#"import fs from 'fs';
await fs.promises.writeFile('{}', 'async data');
const content = await fs.promises.readFile('{}');
console.log(content);
"#,
            data.display(),
            data.display()
        ),
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "async data");
}

// ── Phase 8: os module ──

#[test]
fn test_os_platform() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import os from 'os';\nconsole.log(os.platform(), os.arch());\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let out = String::from_utf8_lossy(&output.stdout);
    assert!(
        out.contains("darwin") || out.contains("linux"),
        "unexpected: {out}"
    );
}

#[test]
fn test_os_hostname_homedir() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"import os from 'os';
console.log(os.hostname().length > 0, os.homedir().length > 0);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true true");
}

#[test]
fn test_os_cpus() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import os from 'os';\nconsole.log(os.cpus().length > 0);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_os_eol() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import { EOL } from 'os';\nconsole.log(JSON.stringify(EOL));\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), r#""\n""#);
}

#[test]
fn test_os_totalmem() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import os from 'os';\nconsole.log(os.totalmem() > 0);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

// ── Phase 8: crypto module ──

#[test]
fn test_crypto_random_uuid() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const uuid = crypto.randomUUID();
const valid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(uuid);
console.log(valid);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_crypto_random_uuid_unique() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "console.log(crypto.randomUUID() !== crypto.randomUUID());\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_crypto_get_random_values() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"
const arr = new Uint8Array(16);
crypto.getRandomValues(arr);
const nonZero = arr.some(b => b !== 0);
console.log(nonZero);
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "true");
}

#[test]
fn test_crypto_module_import() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        "import { randomUUID } from 'crypto';\nconsole.log(typeof randomUUID);\n",
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "function");
}

// ── Phase 8: assert module ──

#[test]
fn test_assert_ok() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"import assert from 'assert';
assert.ok(true);
assert.strictEqual(1, 1);
assert.deepStrictEqual({a: 1}, {a: 1});
console.log('all passed');
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "all passed");
}

#[test]
fn test_assert_throws() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(
        &file,
        r#"import assert from 'assert';
assert.throws(() => { throw new Error('boom'); });
console.log('caught');
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "caught");
}

#[test]
fn test_assert_fail() {
    let output = taiyaki_bin()
        .arg("eval")
        .arg("const assert = require('assert'); assert.strictEqual(1, 2);")
        .output()
        .unwrap();
    assert!(!output.status.success());
}

// ── Phase 8: REPL ──

#[test]
fn test_repl_exit() {
    use std::io::Write;
    use std::process::Stdio;

    let mut child = Command::new(env!("CARGO_BIN_EXE_taiyaki"))
        .arg("repl")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    let stdin = child.stdin.as_mut().unwrap();
    stdin.write_all(b".exit\n").unwrap();
    drop(child.stdin.take());

    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
}

#[test]
fn test_repl_eval_expression() {
    use std::io::Write;
    use std::process::Stdio;

    let mut child = Command::new(env!("CARGO_BIN_EXE_taiyaki"))
        .arg("repl")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    let stdin = child.stdin.as_mut().unwrap();
    stdin.write_all(b"1 + 2\n.exit\n").unwrap();
    drop(child.stdin.take());

    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("3"), "expected 3 in output: {stdout}");
}
