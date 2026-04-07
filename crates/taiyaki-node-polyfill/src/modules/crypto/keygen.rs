use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{b64_encode, crypto_err, json_str, json_u64};

/// generateKey. Args: (algorithm_json)
/// Returns JSON string with key material and metadata.
pub fn crypto_generate_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo_str = match args.first() {
        Some(JsValue::String(s)) => s.as_str(),
        _ => return Err(crypto_err("generateKey: expected algorithm JSON")),
    };
    let algo: serde_json::Value =
        serde_json::from_str(algo_str).map_err(|e| crypto_err(format!("generateKey: {e}")))?;
    let name = json_str(&algo, "name")?;

    match name {
        "AES-CBC" | "AES-CTR" | "AES-GCM" | "AES-KW" => {
            let length = json_u64(&algo, "length").ok_or_else(|| {
                crypto_err("generateKey: AES requires 'length' (128, 192, or 256)")
            })? as usize;
            if length != 128 && length != 192 && length != 256 {
                return Err(crypto_err(format!(
                    "generateKey: invalid AES key length {length}"
                )));
            }
            let mut key = vec![0u8; length / 8];
            getrandom::getrandom(&mut key).map_err(|e| crypto_err(format!("generateKey: {e}")))?;
            let result = serde_json::json!({
                "type": "secret",
                "keyData": b64_encode(&key),
                "algorithm": { "name": name, "length": length },
            });
            Ok(JsValue::String(result.to_string()))
        }
        "HMAC" => {
            let hash = algo
                .get("hash")
                .and_then(|h| {
                    h.as_str()
                        .or_else(|| h.get("name").and_then(|n| n.as_str()))
                })
                .unwrap_or("SHA-256");
            let length = json_u64(&algo, "length").unwrap_or(match hash {
                "SHA-1" => 160,
                "SHA-256" => 256,
                "SHA-384" => 384,
                "SHA-512" => 512,
                _ => 256,
            }) as usize;
            let mut key = vec![0u8; length / 8];
            getrandom::getrandom(&mut key).map_err(|e| crypto_err(format!("generateKey: {e}")))?;
            let result = serde_json::json!({
                "type": "secret",
                "keyData": b64_encode(&key),
                "algorithm": { "name": "HMAC", "hash": { "name": hash }, "length": length },
            });
            Ok(JsValue::String(result.to_string()))
        }
        "RSASSA-PKCS1-v1_5" | "RSA-PSS" | "RSA-OAEP" => {
            let modulus_length = json_u64(&algo, "modulusLength")
                .ok_or_else(|| crypto_err("generateKey: RSA requires 'modulusLength'"))?
                as u32;
            let hash = algo
                .get("hash")
                .and_then(|h| {
                    h.as_str()
                        .or_else(|| h.get("name").and_then(|n| n.as_str()))
                })
                .unwrap_or("SHA-256");

            let (priv_key, pub_key) = super::rsa_ops::rsa_generate_keypair(modulus_length)?;

            // Serialize keys using PKCS#8/SPKI DER
            use rsa::pkcs8::EncodePrivateKey;
            use rsa::pkcs8::EncodePublicKey;
            let priv_der = priv_key
                .to_pkcs8_der()
                .map_err(|e| crypto_err(format!("RSA export: {e}")))?;
            let pub_der = pub_key
                .to_public_key_der()
                .map_err(|e| crypto_err(format!("RSA export: {e}")))?;

            let result = serde_json::json!({
                "publicKey": {
                    "type": "public",
                    "keyData": b64_encode(pub_der.as_ref()),
                    "algorithm": { "name": name, "modulusLength": modulus_length, "hash": { "name": hash } },
                },
                "privateKey": {
                    "type": "private",
                    "keyData": b64_encode(priv_der.as_bytes()),
                    "algorithm": { "name": name, "modulusLength": modulus_length, "hash": { "name": hash } },
                },
            });
            Ok(JsValue::String(result.to_string()))
        }
        "ECDSA" | "ECDH" => {
            let curve = json_str(&algo, "namedCurve")?;
            let (priv_raw, pub_raw) = super::ec::ec_generate_keypair(curve)?;
            let result = serde_json::json!({
                "publicKey": {
                    "type": "public",
                    "keyData": b64_encode(&pub_raw),
                    "algorithm": { "name": name, "namedCurve": curve },
                },
                "privateKey": {
                    "type": "private",
                    "keyData": b64_encode(&priv_raw),
                    "algorithm": { "name": name, "namedCurve": curve },
                },
            });
            Ok(JsValue::String(result.to_string()))
        }
        _ => Err(crypto_err(format!(
            "generateKey: unsupported algorithm '{name}'"
        ))),
    }
}
