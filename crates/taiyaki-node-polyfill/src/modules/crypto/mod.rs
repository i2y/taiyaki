pub mod aes;
pub mod derive;
pub mod digest;
pub mod ec;
pub mod hmac_ops;
pub mod import_export;
pub mod keygen;
pub mod rsa_ops;
pub mod util;
pub mod wrap;

use taiyaki_core::engine::{EngineError, HostCallback, JsEngine, JsValue};
use util::{b64_decode, b64_encode, crypto_err};

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__crypto_random_uuid", Box::new(crypto_random_uuid)),
        (
            "__crypto_get_random_values",
            Box::new(crypto_get_random_values),
        ),
        ("__crypto_digest", Box::new(digest::crypto_digest)),
        (
            "__crypto_generate_key",
            Box::new(keygen::crypto_generate_key),
        ),
        (
            "__crypto_import_key",
            Box::new(import_export::crypto_import_key),
        ),
        (
            "__crypto_export_key",
            Box::new(import_export::crypto_export_key),
        ),
        ("__crypto_sign", Box::new(crypto_sign)),
        ("__crypto_verify", Box::new(crypto_verify)),
        ("__crypto_encrypt", Box::new(crypto_encrypt)),
        ("__crypto_decrypt", Box::new(crypto_decrypt)),
        ("__crypto_derive_bits", Box::new(derive::crypto_derive_bits)),
        ("__crypto_derive_key", Box::new(derive::crypto_derive_key)),
        ("__crypto_wrap_key", Box::new(wrap::crypto_wrap_key)),
        ("__crypto_unwrap_key", Box::new(wrap::crypto_unwrap_key)),
        ("__crypto_create_hash", Box::new(crypto_create_hash)),
        (
            "__crypto_create_hmac",
            Box::new(hmac_ops::crypto_create_hmac),
        ),
        ("__crypto_pbkdf2_sync", Box::new(derive::crypto_pbkdf2_sync)),
        ("__crypto_scrypt_sync", Box::new(derive::crypto_scrypt_sync)),
        ("__crypto_cipher", Box::new(aes::crypto_cipher)),
    ]
}

const CRYPTO_GLOBAL_JS: &str = include_str!("../../js/crypto_global.js");

pub fn register_globals(engine: &dyn JsEngine) -> Result<(), EngineError> {
    engine.eval(CRYPTO_GLOBAL_JS)?;
    Ok(())
}

pub async fn register_globals_async(
    engine: &impl taiyaki_core::engine::AsyncJsEngine,
) -> Result<(), EngineError> {
    engine.eval(CRYPTO_GLOBAL_JS).await?;
    Ok(())
}

// --- Existing functions ---

fn crypto_random_uuid(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let mut bytes = [0u8; 16];
    getrandom::getrandom(&mut bytes).map_err(|e| EngineError::JsException {
        message: format!("crypto.randomUUID: {e}"),
    })?;
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let uuid = format!(
        "{:02x}{:02x}{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        bytes[0],
        bytes[1],
        bytes[2],
        bytes[3],
        bytes[4],
        bytes[5],
        bytes[6],
        bytes[7],
        bytes[8],
        bytes[9],
        bytes[10],
        bytes[11],
        bytes[12],
        bytes[13],
        bytes[14],
        bytes[15],
    );
    Ok(JsValue::String(uuid))
}

fn crypto_get_random_values(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let len = match args.first() {
        Some(JsValue::Number(n)) => *n as usize,
        _ => {
            return Err(EngineError::TypeError(
                "getRandomValues: expected number".into(),
            ));
        }
    };
    let mut bytes = vec![0u8; len];
    getrandom::getrandom(&mut bytes).map_err(|e| EngineError::JsException {
        message: format!("crypto.getRandomValues: {e}"),
    })?;
    Ok(JsValue::String(b64_encode(&bytes)))
}

// --- Dispatch functions for sign/verify/encrypt/decrypt ---

fn crypto_sign(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = util::parse_json_arg(args, 0, "sign")?;
    let name = algo.get("name").and_then(|v| v.as_str()).unwrap_or("");

    // HMAC handles its own arg parsing
    if name == "HMAC" {
        return hmac_ops::crypto_sign_hmac(args);
    }

    let key: serde_json::Value = util::parse_json_arg(args, 1, "sign")?;
    let data = b64_decode(util::str_arg(args, 2, "sign")?)?;
    let hash = util::algo_hash(&algo);
    let key_data = b64_decode(util::key_data_b64(&key, "sign")?)?;

    match name {
        "RSASSA-PKCS1-v1_5" => {
            use rsa::pkcs8::DecodePrivateKey;
            let priv_key = rsa::RsaPrivateKey::from_pkcs8_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA sign: {e}")))?;
            let sig = rsa_ops::rsa_pkcs1v15_sign(&priv_key, hash, &data)?;
            Ok(JsValue::String(b64_encode(&sig)))
        }
        "RSA-PSS" => {
            use rsa::pkcs8::DecodePrivateKey;
            let priv_key = rsa::RsaPrivateKey::from_pkcs8_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA-PSS sign: {e}")))?;
            let sig = rsa_ops::rsa_pss_sign(&priv_key, hash, &data)?;
            Ok(JsValue::String(b64_encode(&sig)))
        }
        "ECDSA" => {
            let curve = key
                .get("_algorithm")
                .or_else(|| key.get("algorithm"))
                .and_then(|a| a.get("namedCurve"))
                .and_then(|v| v.as_str())
                .ok_or_else(|| crypto_err("ECDSA sign: missing namedCurve"))?;
            let sig = ec::ecdsa_sign(curve, hash, &key_data, &data)?;
            Ok(JsValue::String(b64_encode(&sig)))
        }
        _ => Err(crypto_err(format!("sign: unsupported algorithm '{name}'"))),
    }
}

fn crypto_verify(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = util::parse_json_arg(args, 0, "verify")?;
    let name = algo.get("name").and_then(|v| v.as_str()).unwrap_or("");

    if name == "HMAC" {
        return hmac_ops::crypto_verify_hmac(args);
    }

    let key: serde_json::Value = util::parse_json_arg(args, 1, "verify")?;
    let sig = b64_decode(util::str_arg(args, 2, "verify")?)?;
    let data = b64_decode(util::str_arg(args, 3, "verify")?)?;
    let hash = util::algo_hash(&algo);
    let key_data = b64_decode(util::key_data_b64(&key, "verify")?)?;

    match name {
        "RSASSA-PKCS1-v1_5" => {
            use rsa::pkcs8::DecodePublicKey;
            let pub_key = rsa::RsaPublicKey::from_public_key_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA verify: {e}")))?;
            let valid = rsa_ops::rsa_pkcs1v15_verify(&pub_key, hash, &sig, &data)?;
            Ok(JsValue::Bool(valid))
        }
        "RSA-PSS" => {
            use rsa::pkcs8::DecodePublicKey;
            let pub_key = rsa::RsaPublicKey::from_public_key_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA-PSS verify: {e}")))?;
            let valid = rsa_ops::rsa_pss_verify(&pub_key, hash, &sig, &data)?;
            Ok(JsValue::Bool(valid))
        }
        "ECDSA" => {
            let curve = key
                .get("_algorithm")
                .or_else(|| key.get("algorithm"))
                .and_then(|a| a.get("namedCurve"))
                .and_then(|v| v.as_str())
                .ok_or_else(|| crypto_err("ECDSA verify: missing namedCurve"))?;
            let valid = ec::ecdsa_verify(curve, hash, &key_data, &sig, &data)?;
            Ok(JsValue::Bool(valid))
        }
        _ => Err(crypto_err(format!(
            "verify: unsupported algorithm '{name}'"
        ))),
    }
}

fn crypto_encrypt(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = util::parse_json_arg(args, 0, "encrypt")?;
    let key: serde_json::Value = util::parse_json_arg(args, 1, "encrypt")?;
    let data = b64_decode(util::str_arg(args, 2, "encrypt")?)?;
    let name = algo.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let key_data = b64_decode(util::key_data_b64(&key, "encrypt")?)?;

    match name {
        "AES-GCM" | "AES-CBC" | "AES-CTR" => {
            let ct = aes::crypto_encrypt_aes(&algo, &key_data, &data)?;
            Ok(JsValue::String(b64_encode(&ct)))
        }
        "RSA-OAEP" => {
            use rsa::pkcs8::DecodePublicKey;
            let hash = util::algo_hash(&algo);
            let pub_key = rsa::RsaPublicKey::from_public_key_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA-OAEP: {e}")))?;
            let ct = rsa_ops::rsa_oaep_encrypt(&pub_key, hash, &data)?;
            Ok(JsValue::String(b64_encode(&ct)))
        }
        _ => Err(crypto_err(format!(
            "encrypt: unsupported algorithm '{name}'"
        ))),
    }
}

fn crypto_decrypt(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = util::parse_json_arg(args, 0, "decrypt")?;
    let key: serde_json::Value = util::parse_json_arg(args, 1, "decrypt")?;
    let data = b64_decode(util::str_arg(args, 2, "decrypt")?)?;
    let name = algo.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let key_data = b64_decode(util::key_data_b64(&key, "decrypt")?)?;

    match name {
        "AES-GCM" | "AES-CBC" | "AES-CTR" => {
            let pt = aes::crypto_decrypt_aes(&algo, &key_data, &data)?;
            Ok(JsValue::String(b64_encode(&pt)))
        }
        "RSA-OAEP" => {
            use rsa::pkcs8::DecodePrivateKey;
            let hash = util::algo_hash(&algo);
            let priv_key = rsa::RsaPrivateKey::from_pkcs8_der(&key_data)
                .map_err(|e| crypto_err(format!("RSA-OAEP: {e}")))?;
            let pt = rsa_ops::rsa_oaep_decrypt(&priv_key, hash, &data)?;
            Ok(JsValue::String(b64_encode(&pt)))
        }
        _ => Err(crypto_err(format!(
            "decrypt: unsupported algorithm '{name}'"
        ))),
    }
}

/// Node createHash one-shot. Args: (algorithm, data_b64)
fn crypto_create_hash(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo = match args.first() {
        Some(JsValue::String(s)) => s.as_str(),
        _ => return Err(crypto_err("createHash: expected algorithm string")),
    };
    let data_b64 = match args.get(1) {
        Some(JsValue::String(s)) => s.as_str(),
        _ => return Err(crypto_err("createHash: expected data base64")),
    };
    let data = b64_decode(data_b64)?;
    let result = digest::hash_bytes(algo, &data)?;
    Ok(JsValue::String(b64_encode(&result)))
}
