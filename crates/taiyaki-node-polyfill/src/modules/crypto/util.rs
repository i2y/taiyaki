use base64::Engine as _;
use taiyaki_core::engine::{EngineError, JsValue};

pub fn b64_decode(s: &str) -> Result<Vec<u8>, EngineError> {
    base64::engine::general_purpose::STANDARD
        .decode(s)
        .map_err(|e| EngineError::TypeError(format!("base64 decode: {e}")))
}

pub fn b64_encode(bytes: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(bytes)
}

pub fn crypto_err(msg: impl Into<String>) -> EngineError {
    EngineError::JsException {
        message: msg.into(),
    }
}

/// Normalize algorithm name to canonical form.
pub fn normalize_algorithm(name: &str) -> &str {
    match name.to_uppercase().as_str() {
        "SHA-1" | "SHA1" => "SHA-1",
        "SHA-256" | "SHA256" => "SHA-256",
        "SHA-384" | "SHA384" => "SHA-384",
        "SHA-512" | "SHA512" => "SHA-512",
        "MD5" => "MD5",
        _ => name,
    }
}

/// Extract a required string from JSON value.
pub fn json_str<'a>(val: &'a serde_json::Value, key: &str) -> Result<&'a str, EngineError> {
    val.get(key)
        .and_then(|v| v.as_str())
        .ok_or_else(|| crypto_err(format!("missing or invalid '{key}'")))
}

/// Extract an optional u64 from JSON value.
pub fn json_u64(val: &serde_json::Value, key: &str) -> Option<u64> {
    val.get(key).and_then(|v| v.as_u64())
}

/// Extract a string argument from JsValue args.
pub fn str_arg<'a>(
    args: &'a [JsValue],
    index: usize,
    fn_name: &str,
) -> Result<&'a str, EngineError> {
    match args.get(index) {
        Some(JsValue::String(s)) => Ok(s.as_str()),
        _ => Err(crypto_err(format!(
            "{fn_name}: expected string at arg {index}"
        ))),
    }
}

/// Parse a JSON string argument from JsValue args.
pub fn parse_json_arg(
    args: &[JsValue],
    index: usize,
    fn_name: &str,
) -> Result<serde_json::Value, EngineError> {
    let s = str_arg(args, index, fn_name)?;
    serde_json::from_str(s).map_err(|e| crypto_err(format!("{fn_name}: invalid JSON: {e}")))
}

/// Extract key data (base64) from a serialized key JSON, checking both `_keyData` and `keyData`.
pub fn key_data_b64<'a>(key: &'a serde_json::Value, fn_name: &str) -> Result<&'a str, EngineError> {
    key.get("_keyData")
        .or_else(|| key.get("keyData"))
        .and_then(|v| v.as_str())
        .ok_or_else(|| crypto_err(format!("{fn_name}: missing key data")))
}

/// Extract the hash algorithm name from an algorithm JSON object.
pub fn algo_hash<'a>(algo: &'a serde_json::Value) -> &'a str {
    algo.get("hash")
        .and_then(|h| {
            h.as_str()
                .or_else(|| h.get("name").and_then(|n| n.as_str()))
        })
        .unwrap_or("SHA-256")
}
