use taiyaki_core::engine::{AsyncJsEngine, EngineError};

async fn read_stdin_line() -> Option<String> {
    tokio::task::spawn_blocking(|| {
        let mut buf = String::new();
        match std::io::stdin().read_line(&mut buf) {
            Ok(0) => None,
            Ok(_) => Some(
                buf.trim_end_matches('\n')
                    .trim_end_matches('\r')
                    .to_string(),
            ),
            Err(_) => None,
        }
    })
    .await
    .unwrap_or(None)
}

pub async fn register_readline(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    engine
        .register_async_host_fn(
            "__readline_question",
            Box::new(move |args| {
                let prompt = args.first().cloned().unwrap_or_default();
                Box::pin(async move {
                    {
                        use std::io::Write;
                        print!("{prompt}");
                        let _ = std::io::stdout().flush();
                    }
                    Ok(read_stdin_line().await.unwrap_or_default())
                })
            }),
        )
        .await?;

    engine
        .register_async_host_fn(
            "__readline_read_line",
            Box::new(move |_args| {
                Box::pin(async move {
                    match read_stdin_line().await {
                        Some(l) => Ok(format!("{{\"line\":{}}}", serde_json::json!(l))),
                        None => Ok("{\"closed\":true}".into()),
                    }
                })
            }),
        )
        .await?;

    Ok(())
}
