use hmac::{Hmac, Mac};
use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{
    algo_hash, b64_decode, b64_encode, crypto_err, key_data_b64, normalize_algorithm,
    parse_json_arg,
};

/// HMAC sign. Args: (algorithm_json, key_json, data_b64)
pub fn crypto_sign_hmac(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = parse_json_arg(args, 0, "sign")?;
    let key: serde_json::Value = parse_json_arg(args, 1, "sign")?;
    let data_b64 = super::util::str_arg(args, 2, "sign")?;

    let hash = algo_hash(&algo);
    let key_data = b64_decode(key_data_b64(&key, "sign")?)?;
    let data = b64_decode(data_b64)?;

    let sig = hmac_compute(hash, &key_data, &data)?;
    Ok(JsValue::String(b64_encode(&sig)))
}

/// HMAC verify. Args: (algorithm_json, key_json, signature_b64, data_b64)
pub fn crypto_verify_hmac(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = parse_json_arg(args, 0, "verify")?;
    let key: serde_json::Value = parse_json_arg(args, 1, "verify")?;
    let sig_b64 = super::util::str_arg(args, 2, "verify")?;
    let data_b64 = super::util::str_arg(args, 3, "verify")?;

    let hash = algo_hash(&algo);
    let key_data = b64_decode(key_data_b64(&key, "verify")?)?;
    let sig = b64_decode(sig_b64)?;
    let data = b64_decode(data_b64)?;

    let expected = hmac_compute(hash, &key_data, &data)?;
    Ok(JsValue::Bool(sig == expected))
}

/// Node createHmac one-shot. Args: (algorithm, key_b64, data_b64)
pub fn crypto_create_hmac(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo = super::util::str_arg(args, 0, "createHmac")?;
    let key_b64 = super::util::str_arg(args, 1, "createHmac")?;
    let data_b64 = super::util::str_arg(args, 2, "createHmac")?;

    let key = b64_decode(key_b64)?;
    let data = b64_decode(data_b64)?;
    let result = hmac_compute(algo, &key, &data)?;
    Ok(JsValue::String(b64_encode(&result)))
}

pub fn hmac_compute(algo: &str, key: &[u8], data: &[u8]) -> Result<Vec<u8>, EngineError> {
    macro_rules! hmac_with {
        ($hash:ty) => {{
            let mut mac =
                Hmac::<$hash>::new_from_slice(key).map_err(|e| crypto_err(format!("hmac: {e}")))?;
            mac.update(data);
            Ok(mac.finalize().into_bytes().to_vec())
        }};
    }
    match normalize_algorithm(algo) {
        "SHA-1" => hmac_with!(sha1::Sha1),
        "SHA-256" => hmac_with!(sha2::Sha256),
        "SHA-384" => hmac_with!(sha2::Sha384),
        "SHA-512" => hmac_with!(sha2::Sha512),
        _ => Err(crypto_err(format!("hmac: unsupported hash '{algo}'"))),
    }
}
