use std::collections::HashMap;
use std::process::{Command, Stdio};

use taiyaki_core::engine::{EngineError, HostCallback, JsValue};

use super::require_string_arg;

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__cp_spawn_sync", Box::new(cp_spawn_sync)),
        ("__cp_exec_sync", Box::new(cp_exec_sync)),
        ("__cp_exec_file_sync", Box::new(cp_exec_file_sync)),
    ]
}

fn cp_err(op: &str, msg: impl std::fmt::Display) -> EngineError {
    EngineError::JsException {
        message: format!("{op}: {msg}"),
    }
}

/// Parse common options from JSON string.
struct SpawnOpts {
    cwd: Option<String>,
    env: Option<HashMap<String, String>>,
    shell: bool,
    stdio: String, // "pipe" | "inherit" | "ignore"
}

fn parse_opts(json: &str) -> SpawnOpts {
    let obj: serde_json::Value = serde_json::from_str(json).unwrap_or(serde_json::Value::Null);
    let cwd = obj.get("cwd").and_then(|v| v.as_str()).map(String::from);
    let env = obj.get("env").and_then(|v| {
        v.as_object().map(|m| {
            m.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .collect()
        })
    });
    let shell = obj.get("shell").and_then(|v| v.as_bool()).unwrap_or(false);
    let stdio = obj
        .get("stdio")
        .and_then(|v| v.as_str())
        .unwrap_or("pipe")
        .to_string();
    SpawnOpts {
        cwd,
        env,
        shell,
        stdio,
    }
}

fn configure_cmd(cmd: &mut Command, opts: &SpawnOpts) {
    if let Some(ref cwd) = opts.cwd {
        cmd.current_dir(cwd);
    }
    if let Some(ref env) = opts.env {
        cmd.env_clear();
        for (k, v) in env {
            cmd.env(k, v);
        }
    }
    match opts.stdio.as_str() {
        "inherit" => {
            cmd.stdin(Stdio::inherit())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit());
        }
        "ignore" => {
            cmd.stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
        }
        _ => {
            // pipe (default)
            cmd.stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
        }
    }
}

/// `__cp_spawn_sync(command, args_json, opts_json)` → JSON result
fn cp_spawn_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let command = require_string_arg(args, 0, "spawnSync")?;
    let args_json = require_string_arg(args, 1, "spawnSync")?;
    let opts_json = args
        .get(2)
        .and_then(|v| match v {
            JsValue::String(s) => Some(s.as_str()),
            _ => None,
        })
        .unwrap_or("{}");

    let child_args: Vec<String> =
        serde_json::from_str(args_json).map_err(|e| cp_err("spawnSync", e))?;
    let opts = parse_opts(opts_json);

    let mut cmd = if opts.shell {
        let mut full = command.to_string();
        for a in &child_args {
            full.push(' ');
            full.push_str(a);
        }
        let mut c = Command::new("sh");
        c.args(["-c", &full]);
        c
    } else {
        let mut c = Command::new(command);
        c.args(&child_args);
        c
    };
    configure_cmd(&mut cmd, &opts);

    match cmd.output() {
        Ok(output) => {
            let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
            let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
            let status = output.status.code().unwrap_or(-1);
            let signal = if output.status.code().is_none() {
                // Process was killed by a signal
                #[cfg(unix)]
                {
                    use std::os::unix::process::ExitStatusExt;
                    output.status.signal().map(|s| signal_name(s))
                }
                #[cfg(not(unix))]
                {
                    None::<String>
                }
            } else {
                None
            };
            let result = serde_json::json!({
                "status": status,
                "stdout": stdout,
                "stderr": stderr,
                "signal": signal,
                "error": null,
            });
            Ok(JsValue::String(result.to_string()))
        }
        Err(e) => {
            let result = serde_json::json!({
                "status": null,
                "stdout": "",
                "stderr": "",
                "signal": null,
                "error": e.to_string(),
            });
            Ok(JsValue::String(result.to_string()))
        }
    }
}

/// `__cp_exec_sync(command, opts_json)` → stdout string
/// Runs via shell, throws on non-zero exit.
fn cp_exec_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let command = require_string_arg(args, 0, "execSync")?;
    let opts_json = args
        .get(1)
        .and_then(|v| match v {
            JsValue::String(s) => Some(s.as_str()),
            _ => None,
        })
        .unwrap_or("{}");
    let opts = parse_opts(opts_json);

    let mut cmd = Command::new("sh");
    cmd.args(["-c", command]);
    configure_cmd(&mut cmd, &opts);
    // Always pipe for exec (we need to capture output)
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let output = cmd.output().map_err(|e| cp_err("execSync", e))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let code = output.status.code().unwrap_or(-1);
        return Err(cp_err(
            "execSync",
            format!("Command failed with exit code {code}: {stderr}"),
        ));
    }
    Ok(JsValue::String(
        String::from_utf8_lossy(&output.stdout).into_owned(),
    ))
}

/// `__cp_exec_file_sync(file, args_json, opts_json)` → stdout string
/// Direct exec (no shell), throws on non-zero exit.
fn cp_exec_file_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let file = require_string_arg(args, 0, "execFileSync")?;
    let args_json = require_string_arg(args, 1, "execFileSync")?;
    let opts_json = args
        .get(2)
        .and_then(|v| match v {
            JsValue::String(s) => Some(s.as_str()),
            _ => None,
        })
        .unwrap_or("{}");

    let child_args: Vec<String> =
        serde_json::from_str(args_json).map_err(|e| cp_err("execFileSync", e))?;
    let opts = parse_opts(opts_json);

    let mut cmd = Command::new(file);
    cmd.args(&child_args);
    configure_cmd(&mut cmd, &opts);
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let output = cmd.output().map_err(|e| cp_err("execFileSync", e))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let code = output.status.code().unwrap_or(-1);
        return Err(cp_err(
            "execFileSync",
            format!("Command failed with exit code {code}: {stderr}"),
        ));
    }
    Ok(JsValue::String(
        String::from_utf8_lossy(&output.stdout).into_owned(),
    ))
}

#[cfg(unix)]
fn signal_name(sig: i32) -> String {
    match sig {
        1 => "SIGHUP".into(),
        2 => "SIGINT".into(),
        3 => "SIGQUIT".into(),
        6 => "SIGABRT".into(),
        9 => "SIGKILL".into(),
        11 => "SIGSEGV".into(),
        13 => "SIGPIPE".into(),
        14 => "SIGALRM".into(),
        15 => "SIGTERM".into(),
        _ => format!("SIG{sig}"),
    }
}
