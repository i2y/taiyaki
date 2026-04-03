use std::io::IsTerminal;
use std::path::Path;
use std::sync::Arc;

use rustyline::DefaultEditor;
use rustyline::error::ReadlineError;
use taiyaki_core::engine::JsValue;
use taiyaki_core::permissions::Permissions;

const LOGO_LINE1: &str = "  ╺┳╸┏━┓╻╻ ╻┏━┓╻┏╸╻";
const LOGO_LINE2: &str = "   ┃ ┣━┫┃┗┳┛┣━┫┣┻┓┃";
const LOGO_LINE3: &str = "   ╹ ╹ ╹╹ ╹ ╹ ╹╹ ╹╹";

pub async fn start_repl() -> Result<(), Box<dyn std::error::Error>> {
    let is_tty = std::io::stdout().is_terminal();
    let perms = Arc::new(Permissions::default());
    let engine = crate::Engine::new().await?;
    crate::builtins::register_all(&engine, Path::new("<repl>"), &[], &perms).await?;
    crate::async_builtins::register_all(&engine, &perms).await?;
    taiyaki_node_polyfill::register_all_async(&engine).await?;

    let mut rl = DefaultEditor::new()?;
    let history_path = std::env::var("HOME")
        .ok()
        .map(|h| std::path::PathBuf::from(h).join(".taiyaki_history"));
    if let Some(ref path) = history_path {
        let _ = rl.load_history(path);
    }

    // Welcome
    if is_tty {
        println!();
        println!("\x1b[35m{LOGO_LINE1}\x1b[0m");
        println!("\x1b[35m{LOGO_LINE2}\x1b[0m");
        println!("\x1b[35m{LOGO_LINE3}\x1b[0m");
        println!(
            "  \x1b[2m{} · JS/TS runtime\x1b[0m",
            env!("CARGO_PKG_VERSION")
        );
        println!();
    } else {
        println!(
            "taiyaki v{} — Type .help for help, .exit to quit",
            env!("CARGO_PKG_VERSION")
        );
    }

    let prompt = if is_tty {
        "\x1b[1;35mtaiyaki\x1b[0m\x1b[2m>\x1b[0m "
    } else {
        "> "
    };
    let cont_prompt = if is_tty {
        "\x1b[2m   ...\x1b[0m "
    } else {
        "... "
    };

    loop {
        match rl.readline(prompt) {
            Ok(first_line) => {
                let first_line = first_line.trim_end().to_string();
                if first_line.trim().is_empty() {
                    continue;
                }

                // Collect multi-line input
                let line = collect_multiline(&mut rl, &first_line, cont_prompt);

                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }

                // Dot commands
                if trimmed.starts_with('.') {
                    if handle_dot_command(trimmed, &engine, is_tty).await {
                        let _ = rl.add_history_entry(trimmed);
                        continue;
                    }
                }

                let _ = rl.add_history_entry(&line);
                eval_and_print(&engine, trimmed, is_tty).await;
            }
            Err(ReadlineError::Interrupted) => continue,
            Err(ReadlineError::Eof) => break,
            Err(e) => {
                print_error(&format!("{e}"), is_tty);
                break;
            }
        }
    }

    if let Some(ref path) = history_path {
        let _ = rl.save_history(path);
    }
    Ok(())
}

// ── Multi-line input ──

fn needs_continuation(input: &str) -> bool {
    // Check bracket balance
    let mut braces = 0i32;
    let mut parens = 0i32;
    let mut brackets = 0i32;
    let mut in_string = false;
    let mut string_char = ' ';
    let mut prev = ' ';

    for ch in input.chars() {
        if in_string {
            if ch == string_char && prev != '\\' {
                in_string = false;
            }
        } else {
            match ch {
                '"' | '\'' | '`' => {
                    in_string = true;
                    string_char = ch;
                }
                '{' => braces += 1,
                '}' => braces -= 1,
                '(' => parens += 1,
                ')' => parens -= 1,
                '[' => brackets += 1,
                ']' => brackets -= 1,
                _ => {}
            }
        }
        prev = ch;
    }

    if braces > 0 || parens > 0 || brackets > 0 {
        return true;
    }

    // Trailing continuation tokens
    let trimmed = input.trim_end();
    let ends_with_continuation = [",", "=>", "||", "&&", "?", "+", "-", "\\"]
        .iter()
        .any(|tok| trimmed.ends_with(tok));
    ends_with_continuation
}

fn collect_multiline(rl: &mut DefaultEditor, first_line: &str, cont_prompt: &str) -> String {
    let mut buf = first_line.to_string();
    while needs_continuation(&buf) {
        match rl.readline(cont_prompt) {
            Ok(next) => {
                let next = next.trim_end();
                if next.is_empty() {
                    break; // empty line forces execution
                }
                buf.push('\n');
                buf.push_str(next);
            }
            Err(_) => break,
        }
    }
    buf
}

// ── Dot commands ──

async fn handle_dot_command(line: &str, engine: &crate::Engine, is_tty: bool) -> bool {
    let parts: Vec<&str> = line.splitn(2, ' ').collect();
    let cmd = parts[0];
    let arg = parts.get(1).map(|s| s.trim()).unwrap_or("");

    match cmd {
        ".exit" | ".quit" => std::process::exit(0),
        ".help" => {
            print_help(is_tty);
            true
        }
        ".clear" => {
            if is_tty {
                print!("\x1b[2J\x1b[H");
            }
            true
        }
        ".type" => {
            if arg.is_empty() {
                print_error("Usage: .type <expression>", is_tty);
            } else {
                let code = format!("typeof ({arg})");
                match engine.eval_async(&code).await {
                    Ok(JsValue::String(s)) => {
                        if is_tty {
                            println!("\x1b[36m{s}\x1b[0m");
                        } else {
                            println!("{s}");
                        }
                    }
                    Ok(v) => print_value(&v, is_tty),
                    Err(e) => print_error(&e.to_string(), is_tty),
                }
            }
            true
        }
        ".load" => {
            if arg.is_empty() {
                print_error("Usage: .load <file>", is_tty);
            } else {
                match std::fs::read_to_string(arg) {
                    Ok(source) => {
                        if is_tty {
                            println!("\x1b[2mLoading {arg}...\x1b[0m");
                        }
                        eval_and_print(engine, &source, is_tty).await;
                    }
                    Err(e) => print_error(&format!("Cannot read '{arg}': {e}"), is_tty),
                }
            }
            true
        }
        _ => false,
    }
}

fn print_help(is_tty: bool) {
    if is_tty {
        println!();
        println!("  \x1b[1;35mCommands\x1b[0m");
        println!("  \x1b[33m.help\x1b[0m       Show this help");
        println!("  \x1b[33m.exit\x1b[0m       Exit the REPL");
        println!("  \x1b[33m.clear\x1b[0m      Clear the screen");
        println!("  \x1b[33m.type\x1b[0m \x1b[2m<expr>\x1b[0m  Show the type of an expression");
        println!("  \x1b[33m.load\x1b[0m \x1b[2m<file>\x1b[0m  Load and execute a file");
        println!();
        println!("  \x1b[2mMulti-line: unclosed brackets auto-continue.\x1b[0m");
        println!("  \x1b[2mEmpty line in multi-line mode forces execution.\x1b[0m");
        println!();
    } else {
        println!(".help       Show this help");
        println!(".exit       Exit the REPL");
        println!(".clear      Clear the screen");
        println!(".type <expr>  Show type of expression");
        println!(".load <file>  Load and execute a file");
    }
}

// ── Eval & print ──

async fn eval_and_print(engine: &crate::Engine, code: &str, is_tty: bool) {
    // Try as expression first (captures the return value)
    let wrapped = format!("globalThis.__repl_last = (function(){{ return ({code}); }})()");
    match engine.eval_async(&wrapped).await {
        Ok(val) => {
            // If the input is a declaration, also eval directly so it
            // registers in the global scope (the wrapper only captures
            // the value without creating a global binding).
            let trimmed = code.trim();
            if trimmed.starts_with("function ")
                || trimmed.starts_with("async function ")
                || trimmed.starts_with("function*(")
                || trimmed.starts_with("class ")
            {
                let _ = engine.eval_async(code).await;
            }

            match &val {
                JsValue::Undefined => {}
                _ => match engine.eval("__inspect(__repl_last)").await {
                    Ok(JsValue::String(s)) => println!("{s}"),
                    _ => print_value(&val, is_tty),
                },
            }
        }
        Err(_) => {
            // Expression failed — run as statement (let/const/if/for/etc.)
            match engine.eval_async(code).await {
                Ok(val) => match &val {
                    JsValue::Undefined => {}
                    _ => print_value(&val, is_tty),
                },
                Err(e) => print_error(&e.to_string(), is_tty),
            }
        }
    }
}

// ── Value display ──

fn print_value(val: &JsValue, is_tty: bool) {
    if !is_tty {
        match val {
            JsValue::Undefined => {}
            JsValue::Null => println!("null"),
            JsValue::Bool(b) => println!("{b}"),
            JsValue::Number(n) => {
                if n.fract() == 0.0 {
                    println!("{}", *n as i64);
                } else {
                    println!("{n}");
                }
            }
            JsValue::String(s) => println!("'{s}'"),
            _ => println!("{val:?}"),
        }
        return;
    }

    match val {
        JsValue::Undefined => {}
        JsValue::Null => println!("\x1b[2mnull\x1b[0m"),
        JsValue::Bool(b) => println!("\x1b[36m{b}\x1b[0m"),
        JsValue::Number(n) => {
            if n.fract() == 0.0 {
                println!("\x1b[33m{}\x1b[0m", *n as i64);
            } else {
                println!("\x1b[33m{n}\x1b[0m");
            }
        }
        JsValue::String(s) => println!("\x1b[32m'{s}'\x1b[0m"),
        _ => println!("{val:?}"),
    }
}

fn print_error(msg: &str, is_tty: bool) {
    if is_tty {
        let mut lines = msg.lines();
        if let Some(first) = lines.next() {
            eprintln!("\x1b[31m{first}\x1b[0m");
        }
        for line in lines {
            eprintln!("\x1b[2m{line}\x1b[0m");
        }
    } else {
        eprintln!("{msg}");
    }
}
