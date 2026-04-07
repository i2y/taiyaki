use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use rusqlite::{Connection, params_from_iter, types::Value};
use taiyaki_core::engine::{AsyncJsEngine, EngineError, JsValue};

use crate::util::require_str;

struct SqliteState {
    connections: std::sync::Mutex<HashMap<u64, Connection>>,
    next_id: AtomicU64,
}

fn parse_params(json: &str) -> Vec<Value> {
    let parsed: serde_json::Value = serde_json::from_str(json).unwrap_or(serde_json::Value::Null);
    match parsed {
        serde_json::Value::Array(arr) => arr.into_iter().map(json_to_sqlite_value).collect(),
        serde_json::Value::Null => vec![],
        _ => vec![],
    }
}

fn json_to_sqlite_value(v: serde_json::Value) -> Value {
    match v {
        serde_json::Value::Null => Value::Null,
        serde_json::Value::Bool(b) => Value::Integer(if b { 1 } else { 0 }),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::Integer(i)
            } else {
                Value::Real(n.as_f64().unwrap_or(0.0))
            }
        }
        serde_json::Value::String(s) => Value::Text(s),
        _ => Value::Text(v.to_string()),
    }
}

fn sqlite_value_to_json(val: Value) -> serde_json::Value {
    use base64::Engine as _;
    match val {
        Value::Null => serde_json::Value::Null,
        Value::Integer(n) => serde_json::json!(n),
        Value::Real(f) => serde_json::json!(f),
        Value::Text(s) => serde_json::Value::String(s),
        Value::Blob(b) => {
            serde_json::Value::String(base64::engine::general_purpose::STANDARD.encode(&b))
        }
    }
}

fn row_to_json(
    row: &rusqlite::Row,
    columns: &[String],
) -> Result<serde_json::Value, rusqlite::Error> {
    let mut map = serde_json::Map::new();
    for (i, col) in columns.iter().enumerate() {
        map.insert(col.clone(), sqlite_value_to_json(row.get(i)?));
    }
    Ok(serde_json::Value::Object(map))
}

fn row_to_array(
    row: &rusqlite::Row,
    col_count: usize,
) -> Result<serde_json::Value, rusqlite::Error> {
    let mut arr = Vec::with_capacity(col_count);
    for i in 0..col_count {
        arr.push(sqlite_value_to_json(row.get(i)?));
    }
    Ok(serde_json::Value::Array(arr))
}

pub async fn register_sqlite(engine: &impl AsyncJsEngine) -> Result<(), EngineError> {
    let state = Arc::new(SqliteState {
        connections: std::sync::Mutex::new(HashMap::new()),
        next_id: AtomicU64::new(1),
    });

    // __sqlite_open(path) -> JSON {id}
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_open",
                Box::new(move |args: &[JsValue]| {
                    let path = require_str(args, 0);
                    let conn = if path == ":memory:" || path.is_empty() {
                        Connection::open_in_memory()
                    } else {
                        Connection::open(&path)
                    }
                    .map_err(|e| EngineError::JsException {
                        message: format!("SQLite open failed: {e}"),
                    })?;
                    // Enable WAL mode for file-based databases
                    if !path.is_empty() && path != ":memory:" {
                        let _ = conn.execute_batch("PRAGMA journal_mode=WAL;");
                    }
                    let id = state.next_id.fetch_add(1, Ordering::Relaxed);
                    state.connections.lock().unwrap().insert(id, conn);
                    Ok(JsValue::String(serde_json::json!({"id": id}).to_string()))
                }),
            )
            .await?;
    }

    // __sqlite_close(conn_id)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_close",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    state.connections.lock().unwrap().remove(&id);
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __sqlite_exec(conn_id, sql)
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_exec",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let sql = require_str(args, 1);
                    let conns = state.connections.lock().unwrap();
                    let conn = conns.get(&id).ok_or_else(|| EngineError::JsException {
                        message: "Database is closed".into(),
                    })?;
                    conn.execute_batch(&sql)
                        .map_err(|e| EngineError::JsException {
                            message: format!("SQLite exec: {e}"),
                        })?;
                    Ok(JsValue::Undefined)
                }),
            )
            .await?;
    }

    // __sqlite_run(conn_id, sql, params_json) -> JSON {changes, lastInsertRowid}
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_run",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let sql = require_str(args, 1);
                    let params_json = require_str(args, 2);
                    let params = parse_params(&params_json);
                    let conns = state.connections.lock().unwrap();
                    let conn = conns.get(&id).ok_or_else(|| EngineError::JsException {
                        message: "Database is closed".into(),
                    })?;
                    let mut stmt =
                        conn.prepare_cached(&sql)
                            .map_err(|e| EngineError::JsException {
                                message: format!("SQLite prepare: {e}"),
                            })?;
                    let changes = stmt.execute(params_from_iter(params.iter())).map_err(|e| {
                        EngineError::JsException {
                            message: format!("SQLite run: {e}"),
                        }
                    })?;
                    let last_id = conn.last_insert_rowid();
                    Ok(JsValue::String(
                        serde_json::json!({"changes": changes, "lastInsertRowid": last_id})
                            .to_string(),
                    ))
                }),
            )
            .await?;
    }

    // __sqlite_all(conn_id, sql, params_json) -> JSON array of row objects
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_all",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let sql = require_str(args, 1);
                    let params_json = require_str(args, 2);
                    let params = parse_params(&params_json);
                    let conns = state.connections.lock().unwrap();
                    let conn = conns.get(&id).ok_or_else(|| EngineError::JsException {
                        message: "Database is closed".into(),
                    })?;
                    let mut stmt =
                        conn.prepare_cached(&sql)
                            .map_err(|e| EngineError::JsException {
                                message: format!("SQLite prepare: {e}"),
                            })?;
                    let columns: Vec<String> =
                        stmt.column_names().iter().map(|s| s.to_string()).collect();
                    let rows = stmt
                        .query_map(params_from_iter(params.iter()), |row| {
                            row_to_json(row, &columns)
                        })
                        .map_err(|e| EngineError::JsException {
                            message: format!("SQLite query: {e}"),
                        })?;
                    let mut result = Vec::new();
                    for row in rows {
                        result.push(row.map_err(|e| EngineError::JsException {
                            message: format!("SQLite row: {e}"),
                        })?);
                    }
                    Ok(JsValue::String(
                        serde_json::Value::Array(result).to_string(),
                    ))
                }),
            )
            .await?;
    }

    // __sqlite_get(conn_id, sql, params_json) -> JSON object or "null"
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_get",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let sql = require_str(args, 1);
                    let params_json = require_str(args, 2);
                    let params = parse_params(&params_json);
                    let conns = state.connections.lock().unwrap();
                    let conn = conns.get(&id).ok_or_else(|| EngineError::JsException {
                        message: "Database is closed".into(),
                    })?;
                    let mut stmt =
                        conn.prepare_cached(&sql)
                            .map_err(|e| EngineError::JsException {
                                message: format!("SQLite prepare: {e}"),
                            })?;
                    let columns: Vec<String> =
                        stmt.column_names().iter().map(|s| s.to_string()).collect();
                    let mut rows = stmt
                        .query_map(params_from_iter(params.iter()), |row| {
                            row_to_json(row, &columns)
                        })
                        .map_err(|e| EngineError::JsException {
                            message: format!("SQLite query: {e}"),
                        })?;
                    match rows.next() {
                        Some(Ok(val)) => Ok(JsValue::String(val.to_string())),
                        Some(Err(e)) => Err(EngineError::JsException {
                            message: format!("SQLite row: {e}"),
                        }),
                        None => Ok(JsValue::String("null".into())),
                    }
                }),
            )
            .await?;
    }

    // __sqlite_values(conn_id, sql, params_json) -> JSON array of arrays
    {
        let state = state.clone();
        engine
            .register_global_fn(
                "__sqlite_values",
                Box::new(move |args: &[JsValue]| {
                    let id: u64 = require_str(args, 0).parse().unwrap_or(0);
                    let sql = require_str(args, 1);
                    let params_json = require_str(args, 2);
                    let params = parse_params(&params_json);
                    let conns = state.connections.lock().unwrap();
                    let conn = conns.get(&id).ok_or_else(|| EngineError::JsException {
                        message: "Database is closed".into(),
                    })?;
                    let mut stmt =
                        conn.prepare_cached(&sql)
                            .map_err(|e| EngineError::JsException {
                                message: format!("SQLite prepare: {e}"),
                            })?;
                    let col_count = stmt.column_count();
                    let rows = stmt
                        .query_map(params_from_iter(params.iter()), |row| {
                            row_to_array(row, col_count)
                        })
                        .map_err(|e| EngineError::JsException {
                            message: format!("SQLite query: {e}"),
                        })?;
                    let mut result = Vec::new();
                    for row in rows {
                        result.push(row.map_err(|e| EngineError::JsException {
                            message: format!("SQLite row: {e}"),
                        })?);
                    }
                    Ok(JsValue::String(
                        serde_json::Value::Array(result).to_string(),
                    ))
                }),
            )
            .await?;
    }

    Ok(())
}
