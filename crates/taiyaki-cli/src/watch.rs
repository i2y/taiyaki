use std::io::IsTerminal;
use std::path::{Path, PathBuf};
use std::time::Instant;

use notify_debouncer_mini::{DebouncedEventKind, new_debouncer};
use tokio::sync::mpsc;

use crate::test_runner;

enum WatchEvent {
    FilesChanged(Vec<PathBuf>),
}

enum UserCommand {
    Quit,
    RunAll,
}

pub async fn run_watch(dir: &Path, filter: Option<&str>) -> Result<(), Box<dyn std::error::Error>> {
    let dir = std::fs::canonicalize(dir)?;
    let color = std::io::stdout().is_terminal();

    let files = test_runner::discover_test_files(&dir);
    let file_count = files.len();

    let (fs_tx, mut fs_rx) = mpsc::channel::<WatchEvent>(32);
    let (cmd_tx, mut cmd_rx) = mpsc::channel::<UserCommand>(8);

    // Set up file watcher
    let watch_dir = dir.clone();
    let fs_tx_clone = fs_tx.clone();
    let _watcher = setup_watcher(&watch_dir, fs_tx_clone)?;

    // Set up stdin reader
    let cmd_tx_clone = cmd_tx.clone();
    tokio::task::spawn_blocking(move || {
        stdin_reader(cmd_tx_clone);
    });

    // Print banner
    let rel_dir = dir
        .strip_prefix(std::env::current_dir().unwrap_or_default())
        .unwrap_or(&dir);
    if color {
        println!(
            "\x1b[1mWatch mode active.\x1b[0m Watching: {} ({} test files)",
            rel_dir.display(),
            file_count
        );
        println!("\x1b[2mPress: a to run all, q to quit\x1b[0m\n");
    } else {
        println!(
            "Watch mode active. Watching: {} ({} test files)",
            rel_dir.display(),
            file_count
        );
        println!("Press: a to run all, q to quit\n");
    }

    // Initial run
    run_all_tests(&dir, filter, color).await;
    print_waiting(color);

    // Main loop
    loop {
        tokio::select! {
            Some(event) = fs_rx.recv() => {
                match event {
                    WatchEvent::FilesChanged(paths) => {
                        let (test_files, has_source_change) = classify_changes(&paths, &dir);

                        if has_source_change {
                            clear_screen(color);
                            if color {
                                println!("\x1b[2mSource file changed — running all tests\x1b[0m\n");
                            } else {
                                println!("Source file changed — running all tests\n");
                            }
                            run_all_tests(&dir, filter, color).await;
                        } else if !test_files.is_empty() {
                            clear_screen(color);
                            let names: Vec<String> = test_files
                                .iter()
                                .filter_map(|p| p.file_name().and_then(|n| n.to_str()).map(String::from))
                                .collect();
                            if color {
                                println!("\x1b[2mChanged: {}\x1b[0m\n", names.join(", "));
                            } else {
                                println!("Changed: {}\n", names.join(", "));
                            }
                            run_specific_tests(&test_files, &dir, filter, color).await;
                        }

                        if has_source_change || !test_files.is_empty() {
                            print_waiting(color);
                        }
                    }
                }
            }
            Some(cmd) = cmd_rx.recv() => {
                match cmd {
                    UserCommand::Quit => {
                        if color {
                            println!("\n\x1b[2mExiting watch mode.\x1b[0m");
                        }
                        break;
                    }
                    UserCommand::RunAll => {
                        clear_screen(color);
                        run_all_tests(&dir, filter, color).await;
                        print_waiting(color);
                    }
                }
            }
        }
    }

    Ok(())
}

fn setup_watcher(
    dir: &Path,
    tx: mpsc::Sender<WatchEvent>,
) -> Result<notify_debouncer_mini::Debouncer<notify::RecommendedWatcher>, Box<dyn std::error::Error>>
{
    let mut debouncer = new_debouncer(
        std::time::Duration::from_millis(300),
        move |res: Result<Vec<notify_debouncer_mini::DebouncedEvent>, notify::Error>| {
            if let Err(e) = &res {
                eprintln!("Watch error: {e}");
            }
            if let Ok(events) = res {
                let paths: Vec<PathBuf> = events
                    .into_iter()
                    .filter(|e| e.kind == DebouncedEventKind::Any)
                    .map(|e| e.path)
                    .filter(|p| is_relevant_file(p))
                    .collect();
                if !paths.is_empty() {
                    let _ = tx.blocking_send(WatchEvent::FilesChanged(paths));
                }
            }
        },
    )?;

    debouncer
        .watcher()
        .watch(dir, notify::RecursiveMode::Recursive)?;

    Ok(debouncer)
}

fn stdin_reader(tx: mpsc::Sender<UserCommand>) {
    use std::io::BufRead;
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        let trimmed = line.trim().to_lowercase();
        match trimmed.as_str() {
            "q" | "quit" | "exit" => {
                let _ = tx.blocking_send(UserCommand::Quit);
                break;
            }
            "a" | "" => {
                let _ = tx.blocking_send(UserCommand::RunAll);
            }
            _ => {}
        }
    }
    // stdin closed — treat as quit
    let _ = tx.blocking_send(UserCommand::Quit);
}

fn is_relevant_file(path: &Path) -> bool {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
    matches!(ext, "js" | "ts" | "jsx" | "tsx")
        && !path.components().any(|c| {
            let s = c.as_os_str().to_str().unwrap_or("");
            s == "node_modules" || s.starts_with('.')
        })
}

fn classify_changes(paths: &[PathBuf], _dir: &Path) -> (Vec<PathBuf>, bool) {
    let mut test_files = Vec::new();
    let mut has_source_change = false;

    for path in paths {
        if test_runner::is_test_file(path) {
            test_files.push(path.clone());
        } else if is_relevant_file(path) {
            has_source_change = true;
        }
    }

    (test_files, has_source_change)
}

async fn run_all_tests(dir: &Path, filter: Option<&str>, _color: bool) {
    match test_runner::run_tests(dir, filter).await {
        Ok(_) => {}
        Err(e) => {
            eprintln!("Error running tests: {e}");
        }
    }
}

async fn run_specific_tests(files: &[PathBuf], dir: &Path, filter: Option<&str>, color: bool) {
    let start = Instant::now();
    let mut total_pass = 0;
    let mut total_fail = 0;

    let files: Vec<&PathBuf> = if let Some(f) = filter {
        files
            .iter()
            .filter(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.contains(f))
                    .unwrap_or(false)
            })
            .collect()
    } else {
        files.iter().collect()
    };

    for file in &files {
        let rel = file.strip_prefix(dir).unwrap_or(file).display().to_string();
        match test_runner::run_test_file(file).await {
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
            }
            Err(e) => {
                total_fail += 1;
                eprintln!("Error: {e}");
            }
        }
    }

    let elapsed = start.elapsed();
    println!();
    if color {
        if total_fail > 0 {
            println!(
                "\x1b[31m{total_fail} failed\x1b[0m, \x1b[32m{total_pass} passed\x1b[0m ({} files, {:.2}s)",
                files.len(),
                elapsed.as_secs_f64()
            );
        } else {
            println!(
                "\x1b[32m{total_pass} passed\x1b[0m ({} files, {:.2}s)",
                files.len(),
                elapsed.as_secs_f64()
            );
        }
    } else {
        println!(
            "{total_pass} passed, {total_fail} failed ({} files, {:.2}s)",
            files.len(),
            elapsed.as_secs_f64()
        );
    }
}

fn clear_screen(color: bool) {
    if color && std::io::stdout().is_terminal() {
        print!("\x1b[2J\x1b[H");
    }
}

fn print_waiting(color: bool) {
    println!();
    if color {
        println!("\x1b[2m--- Waiting for changes... ---\x1b[0m");
    } else {
        println!("--- Waiting for changes... ---");
    }
}
