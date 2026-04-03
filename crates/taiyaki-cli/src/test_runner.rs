use std::borrow::Cow;
use std::io::IsTerminal;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use taiyaki_core::permissions::Permissions;
use taiyaki_core::transpiler;

/// Discover test files matching *.test.{js,ts,jsx,tsx} or *.spec.{js,ts,jsx,tsx}
pub fn discover_test_files(dir: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    walk_dir(dir, &mut files);
    files.sort();
    files
}

fn walk_dir(dir: &Path, files: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
            if name == "node_modules" || name.starts_with('.') {
                continue;
            }
            walk_dir(&path, files);
        } else if is_test_file(&path) {
            files.push(path);
        }
    }
}

pub fn is_test_file(path: &Path) -> bool {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
    let patterns = [
        ".test.js",
        ".test.ts",
        ".test.jsx",
        ".test.tsx",
        ".spec.js",
        ".spec.ts",
        ".spec.jsx",
        ".spec.tsx",
    ];
    patterns.iter().any(|p| name.ends_with(p))
}

/// Run a single test file and return (pass_count, fail_count, results_text).
pub async fn run_test_file(
    file: &Path,
) -> Result<(usize, usize, String), Box<dyn std::error::Error>> {
    let raw_source = std::fs::read_to_string(file)?;
    let source = crate::strip_shebang(&raw_source);
    let script_dir = file.parent().unwrap_or(Path::new("."));

    let perms = Arc::new(Permissions::default());
    let engine = crate::Engine::new().await?;
    engine.enable_file_loader(script_dir).await;

    crate::builtins::register_all(&engine, file, &[], &perms).await?;
    crate::async_builtins::register_all(&engine, &perms).await?;
    crate::server::register_server(&engine).await?;
    crate::dns::register_dns(&engine, &perms).await?;
    let net_state = std::sync::Arc::new(crate::net::NetState::new());
    crate::net::register_net(&engine, &perms, &net_state).await?;
    crate::tls::register_tls(&engine, &perms, &net_state).await?;
    crate::http_node::register_http_node(&engine, &perms).await?;
    taiyaki_node_polyfill::register_all_async(&engine).await?;

    // Inject test framework.
    engine.eval(TEST_FRAMEWORK_JS).await?;

    let ext = file.extension().and_then(|e| e.to_str()).unwrap_or("");
    let code: Cow<str> = match ext {
        "tsx" | "jsx" => Cow::Owned(transpiler::transform_jsx(source, &Default::default())?),
        "ts" => Cow::Owned(transpiler::strip_types(source)?),
        _ => Cow::Borrowed(source),
    };

    // Run as module if it has import/export syntax.
    let is_module = crate::has_module_syntax(&code);
    if is_module {
        let name = file.file_stem().and_then(|s| s.to_str()).unwrap_or("test");
        engine.eval_module_async(&code, name).await?;
    } else {
        engine.eval_async(&code).await?;
    }

    // Collect results — __testResults is async, so we store resolved value in a global.
    engine
        .eval_async(
            "__testResults().then(r => { globalThis.__testResultsJSON = JSON.stringify(r); })",
        )
        .await?;
    let results_json = engine.eval("globalThis.__testResultsJSON").await?;
    let json_str = match results_json {
        taiyaki_core::engine::JsValue::String(s) => s,
        _ => "[]".to_string(),
    };

    let results: Vec<TestResult> = serde_json::from_str(&json_str).unwrap_or_default();

    let mut pass = 0;
    let mut fail = 0;
    let mut output = String::new();
    let color = std::io::stdout().is_terminal();

    for r in &results {
        if r.passed {
            pass += 1;
            if color {
                output.push_str(&format!("  \x1b[32m✓\x1b[0m {}\n", r.name));
            } else {
                output.push_str(&format!("  ✓ {}\n", r.name));
            }
        } else {
            fail += 1;
            if color {
                output.push_str(&format!("  \x1b[31m✗\x1b[0m {}\n", r.name));
                if let Some(err) = &r.error {
                    output.push_str(&format!("    \x1b[2m{err}\x1b[0m\n"));
                }
            } else {
                output.push_str(&format!("  ✗ {}\n", r.name));
                if let Some(err) = &r.error {
                    output.push_str(&format!("    {err}\n"));
                }
            }
        }
    }

    Ok((pass, fail, output))
}

/// Run all test files and print results.
pub async fn run_tests(
    dir: &Path,
    filter: Option<&str>,
) -> Result<bool, Box<dyn std::error::Error>> {
    let start = Instant::now();
    let mut files = discover_test_files(dir);

    if let Some(f) = filter {
        files.retain(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.contains(f))
                .unwrap_or(false)
        });
    }

    if files.is_empty() {
        eprintln!("No test files found.");
        return Ok(true);
    }

    let color = std::io::stdout().is_terminal();
    let mut total_pass = 0;
    let mut total_fail = 0;
    let mut total_files = 0;
    let mut failed_files = Vec::new();

    for file in &files {
        total_files += 1;
        let rel = file.strip_prefix(dir).unwrap_or(file).display().to_string();

        match run_test_file(file).await {
            Ok((pass, fail, output)) => {
                if color {
                    if fail > 0 {
                        println!("\x1b[31m✗\x1b[0m {rel}");
                    } else {
                        println!("\x1b[32m✓\x1b[0m {rel}");
                    }
                } else {
                    println!("{} {rel}", if fail > 0 { "✗" } else { "✓" });
                }
                print!("{output}");
                total_pass += pass;
                total_fail += fail;
                if fail > 0 {
                    failed_files.push(rel);
                }
            }
            Err(e) => {
                total_fail += 1;
                if color {
                    println!("\x1b[31m✗\x1b[0m {rel}");
                    println!("  \x1b[2m{e}\x1b[0m");
                } else {
                    println!("✗ {rel}");
                    println!("  {e}");
                }
                failed_files.push(rel);
            }
        }
    }

    let elapsed = start.elapsed();
    println!();
    if color {
        if total_fail > 0 {
            println!(
                "\x1b[31m{total_fail} failed\x1b[0m, \x1b[32m{total_pass} passed\x1b[0m ({total_files} files, {:.2}s)",
                elapsed.as_secs_f64()
            );
        } else {
            println!(
                "\x1b[32m{total_pass} passed\x1b[0m ({total_files} files, {:.2}s)",
                elapsed.as_secs_f64()
            );
        }
    } else {
        println!(
            "{total_pass} passed, {total_fail} failed ({total_files} files, {:.2}s)",
            elapsed.as_secs_f64()
        );
    }

    Ok(total_fail == 0)
}

#[derive(serde::Deserialize, Default)]
struct TestResult {
    name: String,
    passed: bool,
    error: Option<String>,
}

/// JavaScript test framework injected before each test file.
const TEST_FRAMEWORK_JS: &str = r#"
(function() {
    const __tests = [];
    const __beforeEachFns = [];
    const __afterEachFns = [];
    const __beforeAllFns = [];
    const __afterAllFns = [];
    let __currentDescribe = '';

    globalThis.describe = function(name, fn) {
        const prev = __currentDescribe;
        __currentDescribe = prev ? prev + ' > ' + name : name;
        fn();
        __currentDescribe = prev;
    };

    globalThis.it = globalThis.test = function(name, fn) {
        const fullName = __currentDescribe ? __currentDescribe + ' > ' + name : name;
        __tests.push({ name: fullName, fn: fn });
    };

    globalThis.test.skip = globalThis.it.skip = function(name, fn) {
        const fullName = __currentDescribe ? __currentDescribe + ' > ' + name : name;
        __tests.push({ name: fullName + ' (skipped)', fn: null, skip: true });
    };

    globalThis.test.todo = globalThis.it.todo = function(name) {
        const fullName = __currentDescribe ? __currentDescribe + ' > ' + name : name;
        __tests.push({ name: fullName + ' (todo)', fn: null, skip: true });
    };

    globalThis.beforeEach = function(fn) { __beforeEachFns.push(fn); };
    globalThis.afterEach = function(fn) { __afterEachFns.push(fn); };
    globalThis.beforeAll = function(fn) { __beforeAllFns.push(fn); };
    globalThis.afterAll = function(fn) { __afterAllFns.push(fn); };

    globalThis.expect = function(actual) {
        return {
            toBe: function(expected) {
                if (actual !== expected) throw new Error('Expected ' + __inspect(actual) + ' to be ' + __inspect(expected));
            },
            toEqual: function(expected) {
                if (JSON.stringify(actual) !== JSON.stringify(expected))
                    throw new Error('Expected ' + __inspect(actual) + ' to equal ' + __inspect(expected));
            },
            toStrictEqual: function(expected) {
                if (JSON.stringify(actual) !== JSON.stringify(expected))
                    throw new Error('Expected ' + __inspect(actual) + ' to strict equal ' + __inspect(expected));
            },
            toBeTruthy: function() {
                if (!actual) throw new Error('Expected ' + __inspect(actual) + ' to be truthy');
            },
            toBeFalsy: function() {
                if (actual) throw new Error('Expected ' + __inspect(actual) + ' to be falsy');
            },
            toBeNull: function() {
                if (actual !== null) throw new Error('Expected ' + __inspect(actual) + ' to be null');
            },
            toBeUndefined: function() {
                if (actual !== undefined) throw new Error('Expected ' + __inspect(actual) + ' to be undefined');
            },
            toBeDefined: function() {
                if (actual === undefined) throw new Error('Expected value to be defined');
            },
            toBeGreaterThan: function(n) {
                if (!(actual > n)) throw new Error('Expected ' + actual + ' > ' + n);
            },
            toBeGreaterThanOrEqual: function(n) {
                if (!(actual >= n)) throw new Error('Expected ' + actual + ' >= ' + n);
            },
            toBeLessThan: function(n) {
                if (!(actual < n)) throw new Error('Expected ' + actual + ' < ' + n);
            },
            toBeLessThanOrEqual: function(n) {
                if (!(actual <= n)) throw new Error('Expected ' + actual + ' <= ' + n);
            },
            toContain: function(item) {
                if (typeof actual === 'string') {
                    if (!actual.includes(item)) throw new Error('Expected string to contain ' + __inspect(item));
                } else if (Array.isArray(actual)) {
                    if (!actual.includes(item)) throw new Error('Expected array to contain ' + __inspect(item));
                } else {
                    throw new Error('toContain requires string or array');
                }
            },
            toHaveLength: function(len) {
                if (actual.length !== len) throw new Error('Expected length ' + actual.length + ' to be ' + len);
            },
            toThrow: function(expected) {
                let threw = false, err;
                try { actual(); } catch(e) { threw = true; err = e; }
                if (!threw) throw new Error('Expected function to throw');
                if (expected !== undefined) {
                    const msg = err && (err.message || String(err));
                    if (typeof expected === 'string' && msg !== expected) throw new Error('Expected throw message ' + __inspect(msg) + ' to be ' + __inspect(expected));
                    if (expected instanceof RegExp && !expected.test(msg)) throw new Error('Expected throw message to match ' + expected);
                }
            },
            toMatch: function(pattern) {
                if (typeof pattern === 'string') {
                    if (!actual.includes(pattern)) throw new Error('Expected ' + __inspect(actual) + ' to match ' + __inspect(pattern));
                } else if (pattern instanceof RegExp) {
                    if (!pattern.test(actual)) throw new Error('Expected ' + __inspect(actual) + ' to match ' + pattern);
                }
            },
            toBeInstanceOf: function(cls) {
                if (!(actual instanceof cls)) throw new Error('Expected instance of ' + (cls.name || cls));
            },
            not: {
                toBe: function(expected) {
                    if (actual === expected) throw new Error('Expected ' + __inspect(actual) + ' not to be ' + __inspect(expected));
                },
                toEqual: function(expected) {
                    if (JSON.stringify(actual) === JSON.stringify(expected))
                        throw new Error('Expected ' + __inspect(actual) + ' not to equal ' + __inspect(expected));
                },
                toBeNull: function() {
                    if (actual === null) throw new Error('Expected value not to be null');
                },
                toBeUndefined: function() {
                    if (actual === undefined) throw new Error('Expected value not to be undefined');
                },
                toBeTruthy: function() {
                    if (actual) throw new Error('Expected ' + __inspect(actual) + ' not to be truthy');
                },
                toBeFalsy: function() {
                    if (!actual) throw new Error('Expected value not to be falsy');
                },
                toContain: function(item) {
                    if (typeof actual === 'string' && actual.includes(item)) throw new Error('Expected string not to contain ' + __inspect(item));
                    if (Array.isArray(actual) && actual.includes(item)) throw new Error('Expected array not to contain ' + __inspect(item));
                },
                toThrow: function() {
                    let threw = false;
                    try { actual(); } catch(e) { threw = true; }
                    if (threw) throw new Error('Expected function not to throw');
                },
            }
        };
    };

    // Run all tests and return results.
    globalThis.__testResults = async function() {
        const results = [];
        for (const fn of __beforeAllFns) { try { await fn(); } catch(e) {} }
        for (const t of __tests) {
            if (t.skip) {
                results.push({ name: t.name, passed: true, error: null });
                continue;
            }
            for (const fn of __beforeEachFns) { try { await fn(); } catch(e) {} }
            try {
                await t.fn();
                results.push({ name: t.name, passed: true, error: null });
            } catch(e) {
                results.push({ name: t.name, passed: false, error: e.message || String(e) });
            }
            for (const fn of __afterEachFns) { try { await fn(); } catch(e) {} }
        }
        for (const fn of __afterAllFns) { try { await fn(); } catch(e) {} }
        return results;
    };
})();
"#;
