use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{
    b64_decode, b64_encode, crypto_err, json_str, key_data_b64, parse_json_arg, str_arg,
};

/// importKey. Args: (format, kd, algorithm_json, extractable, usages_json)
pub fn crypto_import_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let format = str_arg(args, 0, "importKey")?;
    let kd = str_arg(args, 1, "importKey")?;
    let algo: serde_json::Value = parse_json_arg(args, 2, "importKey")?;
    let extractable = str_arg(args, 3, "importKey")? == "true";
    let usages: Vec<String> = serde_json::from_str(str_arg(args, 4, "importKey")?)
        .map_err(|e| crypto_err(format!("importKey: {e}")))?;
    let name = json_str(&algo, "name")?;

    match (format, name) {
        ("raw", "AES-CBC" | "AES-CTR" | "AES-GCM" | "AES-KW") => {
            let key_data = b64_decode(kd)?;
            let length = key_data.len() * 8;
            let result = serde_json::json!({
                "type": "secret",
                "keyData": b64_encode(&key_data),
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "length": length },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("raw", "HMAC") => {
            let key_data = b64_decode(kd)?;
            let hash = algo
                .get("hash")
                .and_then(|h| {
                    h.as_str()
                        .or_else(|| h.get("name").and_then(|n| n.as_str()))
                })
                .unwrap_or("SHA-256");
            let length = key_data.len() * 8;
            let result = serde_json::json!({
                "type": "secret",
                "keyData": b64_encode(&key_data),
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": "HMAC", "hash": { "name": hash }, "length": length },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("raw", "ECDSA" | "ECDH") => {
            // Raw public key (uncompressed point)
            let key_data = b64_decode(kd)?;
            let curve = json_str(&algo, "namedCurve")?;
            let result = serde_json::json!({
                "type": "public",
                "keyData": b64_encode(&key_data),
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "namedCurve": curve },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("pkcs8", "RSASSA-PKCS1-v1_5" | "RSA-PSS" | "RSA-OAEP") => {
            // PKCS#8 DER private key — store as-is
            let hash = algo
                .get("hash")
                .and_then(|h| {
                    h.as_str()
                        .or_else(|| h.get("name").and_then(|n| n.as_str()))
                })
                .unwrap_or("SHA-256");
            let result = serde_json::json!({
                "type": "private",
                "keyData": kd,
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "hash": { "name": hash } },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("spki", "RSASSA-PKCS1-v1_5" | "RSA-PSS" | "RSA-OAEP") => {
            let hash = algo
                .get("hash")
                .and_then(|h| {
                    h.as_str()
                        .or_else(|| h.get("name").and_then(|n| n.as_str()))
                })
                .unwrap_or("SHA-256");
            let result = serde_json::json!({
                "type": "public",
                "keyData": kd,
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "hash": { "name": hash } },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("pkcs8", "ECDSA" | "ECDH") => {
            let curve = json_str(&algo, "namedCurve")?;
            // Extract raw private key from PKCS#8 DER
            let der_bytes = b64_decode(kd)?;
            let raw_key = ec_private_key_from_pkcs8(&der_bytes, curve)?;
            let result = serde_json::json!({
                "type": "private",
                "keyData": b64_encode(&raw_key),
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "namedCurve": curve },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("spki", "ECDSA" | "ECDH") => {
            let curve = json_str(&algo, "namedCurve")?;
            // SPKI is the uncompressed public key point — store as-is
            let result = serde_json::json!({
                "type": "public",
                "keyData": kd,
                "extractable": extractable,
                "usages": usages,
                "algorithm": { "name": name, "namedCurve": curve },
            });
            Ok(JsValue::String(result.to_string()))
        }
        ("raw", "HKDF" | "PBKDF2") => {
            let key_data = b64_decode(kd)?;
            let result = serde_json::json!({
                "type": "secret",
                "keyData": b64_encode(&key_data),
                "extractable": false,
                "usages": usages,
                "algorithm": { "name": name },
            });
            Ok(JsValue::String(result.to_string()))
        }
        _ => Err(crypto_err(format!(
            "importKey: unsupported format/algorithm '{format}/{name}'"
        ))),
    }
}

/// exportKey. Args: (format, key_json)
pub fn crypto_export_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let format = str_arg(args, 0, "exportKey")?;
    let key: serde_json::Value = parse_json_arg(args, 1, "exportKey")?;

    let extractable = key.get("_extractable").and_then(|v| v.as_bool()).unwrap_or(
        key.get("extractable")
            .and_then(|v| v.as_bool())
            .unwrap_or(true),
    );
    if !extractable {
        return Err(crypto_err("exportKey: key is not extractable"));
    }

    let kd = key_data_b64(&key, "exportKey")?;

    match format {
        "raw" => {
            // Return the raw key data as base64
            Ok(JsValue::String(kd.to_string()))
        }
        "pkcs8" | "spki" => {
            // Return the DER key data as base64 (already stored in this format for RSA)
            Ok(JsValue::String(kd.to_string()))
        }
        _ => Err(crypto_err(format!(
            "exportKey: unsupported format '{format}'"
        ))),
    }
}

fn ec_private_key_from_pkcs8(der: &[u8], curve: &str) -> Result<Vec<u8>, EngineError> {
    match curve {
        "P-256" => {
            use p256::pkcs8::DecodePrivateKey;
            let secret = p256::SecretKey::from_pkcs8_der(der)
                .map_err(|e| crypto_err(format!("EC P-256 PKCS#8: {e}")))?;
            Ok(secret.to_bytes().to_vec())
        }
        "P-384" => {
            use p384::pkcs8::DecodePrivateKey;
            let secret = p384::SecretKey::from_pkcs8_der(der)
                .map_err(|e| crypto_err(format!("EC P-384 PKCS#8: {e}")))?;
            Ok(secret.to_bytes().to_vec())
        }
        _ => Err(crypto_err(format!(
            "EC PKCS#8: unsupported curve '{curve}'"
        ))),
    }
}
