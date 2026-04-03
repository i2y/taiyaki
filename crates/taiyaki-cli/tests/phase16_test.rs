use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

// ============================================================
// init
// ============================================================

#[test]
fn test_init_creates_package_json() {
    let dir = tempfile::tempdir().unwrap();
    let output = taiyaki_bin()
        .arg("init")
        .current_dir(dir.path())
        .output()
        .unwrap();
    assert!(output.status.success());
    let pkg = std::fs::read_to_string(dir.path().join("package.json")).unwrap();
    assert!(pkg.contains("\"version\""));
    assert!(pkg.contains("\"module\""));
}

#[test]
fn test_init_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    taiyaki_bin()
        .arg("init")
        .current_dir(dir.path())
        .output()
        .unwrap();
    let output = taiyaki_bin()
        .arg("init")
        .current_dir(dir.path())
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("already exists"));
}

// ============================================================
// check
// ============================================================

#[test]
fn test_check_valid_ts() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("test.ts"),
        "const x: number = 42;\nconsole.log(x);\n",
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("check")
        .arg(dir.path().join("test.ts"))
        .output()
        .unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("no errors"));
}

#[test]
fn test_check_invalid_syntax() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("bad.js"), "const = ;;\n").unwrap();
    let output = taiyaki_bin()
        .arg("check")
        .arg(dir.path().join("bad.js"))
        .output()
        .unwrap();
    assert!(!output.status.success());
}

// ============================================================
// fmt
// ============================================================

#[test]
fn test_fmt_formats_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "const x=1;console.log(x)").unwrap();
    let output = taiyaki_bin().arg("fmt").arg(&file).output().unwrap();
    assert!(output.status.success());
    let content = std::fs::read_to_string(&file).unwrap();
    // SWC adds whitespace during formatting
    assert!(content.contains("const x"));
}

#[test]
fn test_fmt_check_mode() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "const   x  =  1 ;\n").unwrap();
    let output = taiyaki_bin()
        .arg("fmt")
        .arg("--check")
        .arg(&file)
        .output()
        .unwrap();
    // Should fail because file needs formatting
    assert!(!output.status.success());
}

// ============================================================
// lint
// ============================================================

#[test]
fn test_lint_detects_issues() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "var x = 1;\ndebugger;\n").unwrap();
    let output = taiyaki_bin().arg("lint").arg(&file).output().unwrap();
    assert!(!output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("no-var"));
    assert!(stdout.contains("no-debugger"));
}

#[test]
fn test_lint_clean_file() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "const x = 1;\nconsole.log(x);\n").unwrap();
    let output = taiyaki_bin().arg("lint").arg(&file).output().unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("no warnings"));
}

#[test]
fn test_lint_eqeqeq() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, "if (1 == 2) {}\n").unwrap();
    let output = taiyaki_bin().arg("lint").arg(&file).output().unwrap();
    assert!(!output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("eqeqeq"));
}

// ============================================================
// build
// ============================================================

#[test]
fn test_build_basic_bundle() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("util.js"),
        "export function greet(n) { return 'hi ' + n; }\n",
    )
    .unwrap();
    std::fs::write(
        dir.path().join("main.js"),
        "import { greet } from './util.js';\nconsole.log(greet('world'));\n",
    )
    .unwrap();
    let outfile = dir.path().join("out.js");
    let output = taiyaki_bin()
        .arg("build")
        .arg(dir.path().join("main.js"))
        .arg("-o")
        .arg(&outfile)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(outfile.exists());
    let bundle = std::fs::read_to_string(&outfile).unwrap();
    assert!(bundle.contains("__require"));
    assert!(bundle.contains("greet"));
}

#[test]
fn test_build_ts_entry() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("main.ts"),
        "const x: number = 42;\nconsole.log(x);\n",
    )
    .unwrap();
    let outfile = dir.path().join("out.js");
    let output = taiyaki_bin()
        .arg("build")
        .arg(dir.path().join("main.ts"))
        .arg("-o")
        .arg(&outfile)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let bundle = std::fs::read_to_string(&outfile).unwrap();
    assert!(!bundle.contains(": number"));
}

// ============================================================
// compile
// ============================================================

#[test]
fn test_compile_and_run() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("hello.js"),
        "console.log('compiled-output');\n",
    )
    .unwrap();
    let binary = dir.path().join("hello_bin");
    let output = taiyaki_bin()
        .arg("compile")
        .arg(dir.path().join("hello.js"))
        .arg("-o")
        .arg(&binary)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(binary.exists());

    // Run the compiled binary
    let run_output = Command::new(&binary).output().unwrap();
    let stdout = String::from_utf8_lossy(&run_output.stdout);
    assert!(stdout.contains("compiled-output"), "stdout: {stdout}");
}

// ============================================================
// package manager (install/add/remove)
// ============================================================

#[test]
fn test_install_empty_deps() {
    let dir = tempfile::tempdir().unwrap();
    // Create package.json with no deps
    std::fs::write(
        dir.path().join("package.json"),
        r#"{"name":"test","version":"1.0.0"}"#,
    )
    .unwrap();
    let output = taiyaki_bin()
        .arg("install")
        .current_dir(dir.path())
        .output()
        .unwrap();
    assert!(output.status.success());
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(stdout.contains("No dependencies"));
}

#[test]
fn test_remove_package() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(
        dir.path().join("package.json"),
        r#"{"name":"test","version":"1.0.0","dependencies":{"foo":"^1.0.0"}}"#,
    )
    .unwrap();
    // Create fake node_modules/foo
    let foo_dir = dir.path().join("node_modules").join("foo");
    std::fs::create_dir_all(&foo_dir).unwrap();
    std::fs::write(foo_dir.join("index.js"), "").unwrap();

    let output = taiyaki_bin()
        .arg("remove")
        .arg("foo")
        .current_dir(dir.path())
        .output()
        .unwrap();
    assert!(output.status.success());

    // Check foo removed from package.json
    let pkg = std::fs::read_to_string(dir.path().join("package.json")).unwrap();
    assert!(!pkg.contains("foo"));
    // Check directory removed
    assert!(!foo_dir.exists());
}
