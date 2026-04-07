use std::sync::Arc;

use taiyaki_core::engine::{AsyncJsEngine, EngineError};
use taiyaki_core::permissions::Permissions;

pub async fn register_async_fs(
    engine: &impl AsyncJsEngine,
    perms: &Arc<Permissions>,
) -> Result<(), EngineError> {
    // __fs_read_file_async(path, encoding) -> string
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_read_file_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let encoding = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&path).map_err(|e| e.to_string())?;
                        match encoding.as_str() {
                            "utf8" | "utf-8" => {
                                let content = tokio::fs::read_to_string(&path)
                                    .await
                                    .map_err(|e| format!("readFile: {e}"))?;
                                Ok(content)
                            }
                            _ => {
                                use base64::Engine as _;
                                let bytes = tokio::fs::read(&path)
                                    .await
                                    .map_err(|e| format!("readFile: {e}"))?;
                                Ok(base64::engine::general_purpose::STANDARD.encode(&bytes))
                            }
                        }
                    })
                }),
            )
            .await?;
    }

    // __fs_write_file_async(path, data) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_write_file_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let data = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        tokio::fs::write(&path, data.as_bytes())
                            .await
                            .map_err(|e| format!("writeFile: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_stat_async(path) -> JSON
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_stat_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&path).map_err(|e| e.to_string())?;
                        let meta = tokio::fs::metadata(&path)
                            .await
                            .map_err(|e| format!("stat: {e}"))?;
                        Ok(taiyaki_node_polyfill::stat_to_json(&meta))
                    })
                }),
            )
            .await?;
    }

    // __fs_lstat_async(path) -> JSON
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_lstat_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&path).map_err(|e| e.to_string())?;
                        let meta = tokio::fs::symlink_metadata(&path)
                            .await
                            .map_err(|e| format!("lstat: {e}"))?;
                        Ok(taiyaki_node_polyfill::stat_to_json(&meta))
                    })
                }),
            )
            .await?;
    }

    // __fs_readdir_async(path) -> JSON array
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_readdir_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&path).map_err(|e| e.to_string())?;
                        let mut entries = Vec::new();
                        let mut dir = tokio::fs::read_dir(&path)
                            .await
                            .map_err(|e| format!("readdir: {e}"))?;
                        while let Some(entry) = dir
                            .next_entry()
                            .await
                            .map_err(|e| format!("readdir: {e}"))?
                        {
                            if let Some(name) = entry.file_name().to_str() {
                                entries.push(name.to_string());
                            }
                        }
                        Ok(serde_json::to_string(&entries).unwrap_or_else(|_| "[]".into()))
                    })
                }),
            )
            .await?;
    }

    // __fs_mkdir_async(path, recursive) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_mkdir_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let recursive = args.get(1).map(|s| s == "true").unwrap_or(false);
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        if recursive {
                            tokio::fs::create_dir_all(&path)
                                .await
                                .map_err(|e| format!("mkdir: {e}"))?;
                        } else {
                            tokio::fs::create_dir(&path)
                                .await
                                .map_err(|e| format!("mkdir: {e}"))?;
                        }
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_unlink_async(path) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_unlink_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        tokio::fs::remove_file(&path)
                            .await
                            .map_err(|e| format!("unlink: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_rename_async(old, new) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_rename_async",
                Box::new(move |args| {
                    let old = args.first().cloned().unwrap_or_default();
                    let new_path = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&old).map_err(|e| e.to_string())?;
                        perms.check_write(&new_path).map_err(|e| e.to_string())?;
                        tokio::fs::rename(&old, &new_path)
                            .await
                            .map_err(|e| format!("rename: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_rm_async(path, recursive, force) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_rm_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let recursive = args.get(1).map(|s| s == "true").unwrap_or(false);
                    let force = args.get(2).map(|s| s == "true").unwrap_or(false);
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        match tokio::fs::remove_file(&path).await {
                            Ok(()) => {}
                            Err(e) if e.kind() == std::io::ErrorKind::NotFound && force => {}
                            Err(e)
                                if e.raw_os_error() == Some(libc::EISDIR)
                                    || e.raw_os_error() == Some(libc::EPERM) =>
                            {
                                if recursive {
                                    tokio::fs::remove_dir_all(&path)
                                        .await
                                        .map_err(|e| format!("rm: {e}"))?;
                                } else {
                                    tokio::fs::remove_dir(&path)
                                        .await
                                        .map_err(|e| format!("rm: {e}"))?;
                                }
                            }
                            Err(e) => return Err(format!("rm: {e}")),
                        }
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_copy_file_async(src, dest) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_copy_file_async",
                Box::new(move |args| {
                    let src = args.first().cloned().unwrap_or_default();
                    let dest = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&src).map_err(|e| e.to_string())?;
                        perms.check_write(&dest).map_err(|e| e.to_string())?;
                        tokio::fs::copy(&src, &dest)
                            .await
                            .map_err(|e| format!("copyFile: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_realpath_async(path) -> resolved path string
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_realpath_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_read(&path).map_err(|e| e.to_string())?;
                        let real = tokio::fs::canonicalize(&path)
                            .await
                            .map_err(|e| format!("realpath: {e}"))?;
                        Ok(real.to_string_lossy().into_owned())
                    })
                }),
            )
            .await?;
    }

    // __fs_chmod_async(path, mode) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_chmod_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let mode: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        use std::os::unix::fs::PermissionsExt;
                        tokio::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode))
                            .await
                            .map_err(|e| format!("chmod: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    // __fs_append_file_async(path, data) -> ""
    {
        let perms = perms.clone();
        engine
            .register_async_host_fn(
                "__fs_append_file_async",
                Box::new(move |args| {
                    let path = args.first().cloned().unwrap_or_default();
                    let data = args.get(1).cloned().unwrap_or_default();
                    let perms = perms.clone();
                    Box::pin(async move {
                        perms.check_write(&path).map_err(|e| e.to_string())?;
                        use tokio::io::AsyncWriteExt;
                        let mut file = tokio::fs::OpenOptions::new()
                            .create(true)
                            .append(true)
                            .open(&path)
                            .await
                            .map_err(|e| format!("appendFile: {e}"))?;
                        file.write_all(data.as_bytes())
                            .await
                            .map_err(|e| format!("appendFile: {e}"))?;
                        Ok(String::new())
                    })
                }),
            )
            .await?;
    }

    Ok(())
}
