use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

// --- Test Runner ---

#[test]
fn test_runner_passing() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("math.test.js");
    std::fs::write(
        &file,
        r#"
test("addition", () => {
    expect(1 + 2).toBe(3);
});
test("subtraction", () => {
    expect(5 - 3).toBe(2);
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(dir.path()).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("2 passed"));
}

#[test]
fn test_runner_failing() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("fail.test.js");
    std::fs::write(
        &file,
        r#"
test("should fail", () => {
    expect(1).toBe(2);
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(dir.path()).output().unwrap();
    assert!(!output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("1 failed"));
}

#[test]
fn test_runner_describe() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("nested.test.js");
    std::fs::write(
        &file,
        r#"
describe("outer", () => {
    describe("inner", () => {
        test("deep test", () => {
            expect(true).toBeTruthy();
        });
    });
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("outer > inner > deep test"));
}

#[test]
fn test_runner_expect_matchers() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("matchers.test.js");
    std::fs::write(
        &file,
        r#"
test("toBeTruthy/toBeFalsy", () => {
    expect(1).toBeTruthy();
    expect(0).toBeFalsy();
});
test("toBeNull/toBeUndefined/toBeDefined", () => {
    expect(null).toBeNull();
    expect(undefined).toBeUndefined();
    expect(42).toBeDefined();
});
test("toEqual", () => {
    expect({ a: 1 }).toEqual({ a: 1 });
    expect([1, 2]).toEqual([1, 2]);
});
test("toContain", () => {
    expect([1, 2, 3]).toContain(2);
    expect("hello world").toContain("world");
});
test("toHaveLength", () => {
    expect([1, 2, 3]).toHaveLength(3);
    expect("abc").toHaveLength(3);
});
test("comparison", () => {
    expect(10).toBeGreaterThan(5);
    expect(3).toBeLessThan(7);
});
test("toThrow", () => {
    expect(() => { throw new Error("oops"); }).toThrow("oops");
    expect(() => {}).not.toThrow();
});
test("toMatch", () => {
    expect("hello").toMatch(/^hel/);
    expect("world").toMatch("orl");
});
test("not matchers", () => {
    expect(1).not.toBe(2);
    expect({ a: 1 }).not.toEqual({ a: 2 });
    expect(42).not.toBeNull();
    expect(42).not.toBeUndefined();
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("9 passed"));
}

#[test]
fn test_runner_async_tests() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("async.test.js");
    std::fs::write(
        &file,
        r#"
test("async test", async () => {
    const result = await Promise.resolve(42);
    expect(result).toBe(42);
});

test("async with setTimeout", async () => {
    const val = await new Promise(resolve => setTimeout(() => resolve("done"), 10));
    expect(val).toBe("done");
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("2 passed"));
}

#[test]
fn test_runner_before_after() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("hooks.test.js");
    std::fs::write(
        &file,
        r#"
let value = 0;

beforeAll(() => { value = 10; });
beforeEach(() => { value += 1; });
afterEach(() => { value -= 1; });

test("first", () => {
    expect(value).toBe(11);
});
test("second", () => {
    expect(value).toBe(11);
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("2 passed"));
}

#[test]
fn test_runner_filter() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("alpha.test.js"),
        r#"test("a", () => { expect(1).toBe(1); });"#,
    )
    .unwrap();
    std::fs::write(
        dir.path().join("beta.test.js"),
        r#"test("b", () => { expect(1).toBe(1); });"#,
    )
    .unwrap();

    let output = taiyaki_bin()
        .arg("test")
        .arg(dir.path())
        .args(["--filter", "alpha"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("1 passed"));
    assert!(stdout.contains("1 files"));
}

#[test]
fn test_runner_ts_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("typed.test.ts");
    std::fs::write(
        &file,
        r#"
const x: number = 42;
test("ts types work", () => {
    expect(x).toBe(42);
});
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("1 passed"));
}

#[test]
fn test_runner_skip_and_todo() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("skip.test.js");
    std::fs::write(
        &file,
        r#"
test("normal", () => { expect(1).toBe(1); });
test.skip("skipped", () => { throw new Error("should not run"); });
test.todo("not implemented yet");
"#,
    )
    .unwrap();

    let output = taiyaki_bin().arg("test").arg(file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("3 passed"));
    assert!(stdout.contains("skipped"));
    assert!(stdout.contains("todo"));
}

#[test]
fn test_runner_no_test_files() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("not_a_test.js"), "console.log('hi');").unwrap();

    let output = taiyaki_bin().arg("test").arg(dir.path()).output().unwrap();
    assert!(output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("No test files found"));
}

// --- .env file ---

#[test]
fn test_env_file() {
    let dir = tempfile::tempdir().unwrap();
    let env_file = dir.path().join(".env");
    std::fs::write(
        &env_file,
        r#"
TEST_VAR=hello
QUOTED_VAR="world"
# comment
SINGLE_QUOTED='value'
"#,
    )
    .unwrap();

    let script = dir.path().join("test.js");
    std::fs::write(
        &script,
        "console.log(process.env.TEST_VAR, process.env.QUOTED_VAR, process.env.SINGLE_QUOTED);",
    )
    .unwrap();

    let output = taiyaki_bin()
        .arg("run")
        .arg("--env-file")
        .arg(&env_file)
        .arg(&script)
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&output.stdout).trim(),
        "hello world value"
    );
}

// --- Watch Mode (Phase 10.2) ---

#[test]
fn test_watch_flag_accepted() {
    // Verify --watch flag is accepted by the CLI parser
    let output = taiyaki_bin()
        .arg("test")
        .arg("--watch")
        .arg("--help")
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("watch") || stdout.contains("Watch"));
}

#[test]
fn test_watch_rejects_file_path() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("single.test.js");
    std::fs::write(&file, "test('a', () => {});").unwrap();

    let output = taiyaki_bin()
        .arg("test")
        .arg("--watch")
        .arg(&file)
        .output()
        .unwrap();
    assert!(!output.status.success());
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("directory"));
}

#[test]
fn test_watch_initial_run_and_quit() {
    use std::io::Write;
    use std::process::Stdio;
    use std::time::Duration;

    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("hello.test.js"),
        r#"test("hello", () => { expect(1 + 1).toBe(2); });"#,
    )
    .unwrap();

    let mut child = taiyaki_bin()
        .arg("test")
        .arg("--watch")
        .arg(dir.path())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    // Wait for initial run
    std::thread::sleep(Duration::from_secs(3));

    // Send quit command
    if let Some(ref mut stdin) = child.stdin {
        let _ = stdin.write_all(b"q\n");
        let _ = stdin.flush();
    }

    // Wait with timeout
    let output = child.wait_with_output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    // Should have run the initial test
    assert!(
        stdout.contains("passed") || stdout.contains("hello"),
        "stdout: {stdout}"
    );
}

#[test]
fn test_watch_run_all_command() {
    use std::io::Write;
    use std::process::Stdio;
    use std::time::Duration;

    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("math.test.js"),
        r#"test("add", () => { expect(2 + 2).toBe(4); });"#,
    )
    .unwrap();

    let mut child = taiyaki_bin()
        .arg("test")
        .arg("--watch")
        .arg(dir.path())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();

    // Wait for initial run
    std::thread::sleep(Duration::from_secs(3));

    // Send 'a' to run all, then quit
    if let Some(ref mut stdin) = child.stdin {
        let _ = stdin.write_all(b"a\n");
        let _ = stdin.flush();
    }
    std::thread::sleep(Duration::from_secs(2));

    if let Some(ref mut stdin) = child.stdin {
        let _ = stdin.write_all(b"q\n");
        let _ = stdin.flush();
    }

    let output = child.wait_with_output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    // Should show results twice (initial + re-run from 'a')
    let pass_count = stdout.matches("passed").count();
    assert!(
        pass_count >= 2,
        "Expected at least 2 'passed' occurrences, got {pass_count}. stdout: {stdout}"
    );
}
