use taiyaki_core::engine::{EngineError, HostCallback, JsEngine, JsValue};

use super::require_string_arg;

const BUFFER_GLOBAL_JS: &str = include_str!("../js/buffer_global.js");

pub fn register_globals(engine: &dyn JsEngine) -> Result<(), EngineError> {
    engine.eval(BUFFER_GLOBAL_JS)?;
    Ok(())
}

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__buffer_from_string", Box::new(buffer_from_string)),
        ("__buffer_to_string", Box::new(buffer_to_string)),
        ("__buffer_b64_to_bytes", Box::new(buffer_b64_to_bytes)),
        ("__buffer_bytes_to_b64", Box::new(buffer_bytes_to_b64)),
    ]
}

pub async fn register_globals_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    engine.eval(BUFFER_GLOBAL_JS).await?;
    Ok(())
}

fn buffer_from_string(args: &[JsValue]) -> Result<JsValue, EngineError> {
    use base64::Engine as _;

    let input = require_string_arg(args, 0, "__buffer_from_string")?;
    let encoding = match args.get(1) {
        Some(JsValue::String(s)) => s.as_str(),
        _ => "utf-8",
    };

    let bytes = match encoding {
        "utf-8" | "utf8" => input.as_bytes().to_vec(),
        "ascii" | "latin1" | "binary" => input.bytes().collect(),
        "hex" => hex_decode(input).map_err(|e| EngineError::JsException {
            message: format!("Invalid hex string: {e}"),
        })?,
        "base64" => base64::engine::general_purpose::STANDARD
            .decode(input)
            .map_err(|e| EngineError::JsException {
                message: format!("Invalid base64: {e}"),
            })?,
        _ => {
            return Err(EngineError::TypeError(format!(
                "Unknown encoding: {encoding}"
            )));
        }
    };

    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(JsValue::String(b64))
}

fn buffer_to_string(args: &[JsValue]) -> Result<JsValue, EngineError> {
    use base64::Engine as _;

    let b64 = require_string_arg(args, 0, "__buffer_to_string")?;
    let encoding = match args.get(1) {
        Some(JsValue::String(s)) => s.as_str(),
        _ => "utf-8",
    };

    let bytes = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| EngineError::JsException {
            message: format!("Invalid base64 data: {e}"),
        })?;

    let result = match encoding {
        "utf-8" | "utf8" => String::from_utf8_lossy(&bytes).into_owned(),
        "ascii" | "latin1" | "binary" => bytes.iter().map(|&b| b as char).collect(),
        "hex" => hex_encode(&bytes),
        "base64" => base64::engine::general_purpose::STANDARD.encode(&bytes),
        _ => {
            return Err(EngineError::TypeError(format!(
                "Unknown encoding: {encoding}"
            )));
        }
    };

    Ok(JsValue::String(result))
}

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    if !s.len().is_multiple_of(2) {
        return Err("Hex string must have even length".to_string());
    }
    let mut bytes = Vec::with_capacity(s.len() / 2);
    let chars: Vec<u8> = s.bytes().collect();
    for i in (0..chars.len()).step_by(2) {
        let high = hex_nibble(chars[i])?;
        let low = hex_nibble(chars[i + 1])?;
        bytes.push((high << 4) | low);
    }
    Ok(bytes)
}

fn hex_nibble(c: u8) -> Result<u8, String> {
    match c {
        b'0'..=b'9' => Ok(c - b'0'),
        b'a'..=b'f' => Ok(c - b'a' + 10),
        b'A'..=b'F' => Ok(c - b'A' + 10),
        _ => Err(format!("Invalid hex character: {}", c as char)),
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0x0f) as usize] as char);
    }
    s
}

fn buffer_b64_to_bytes(args: &[JsValue]) -> Result<JsValue, EngineError> {
    use base64::Engine as _;

    let b64 = require_string_arg(args, 0, "__buffer_b64_to_bytes")?;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .map_err(|e| EngineError::JsException {
            message: format!("Invalid base64: {e}"),
        })?;
    let json = serde_json::to_string(&bytes).expect("byte array serialization");
    Ok(JsValue::Array(json))
}

fn buffer_bytes_to_b64(args: &[JsValue]) -> Result<JsValue, EngineError> {
    use base64::Engine as _;

    let json = require_string_arg(args, 0, "__buffer_bytes_to_b64")?;
    let bytes: Vec<u8> = serde_json::from_str(json).map_err(|e| EngineError::JsException {
        message: format!("Invalid byte array JSON: {e}"),
    })?;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(JsValue::String(b64))
}
