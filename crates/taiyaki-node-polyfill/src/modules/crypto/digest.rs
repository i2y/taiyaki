use digest::Digest;
use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{b64_decode, b64_encode, crypto_err, normalize_algorithm};

/// Compute hash digest. Args: (algorithm, data_b64)
pub fn crypto_digest(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo = match args.first() {
        Some(JsValue::String(s)) => s.as_str(),
        _ => return Err(crypto_err("digest: expected algorithm string")),
    };
    let data_b64 = match args.get(1) {
        Some(JsValue::String(s)) => s.as_str(),
        _ => return Err(crypto_err("digest: expected data base64 string")),
    };
    let data = b64_decode(data_b64)?;
    let result = hash_bytes(algo, &data)?;
    Ok(JsValue::String(b64_encode(&result)))
}

pub fn hash_bytes(algo: &str, data: &[u8]) -> Result<Vec<u8>, EngineError> {
    match normalize_algorithm(algo) {
        "SHA-1" => Ok(sha1::Sha1::digest(data).to_vec()),
        "SHA-256" => Ok(sha2::Sha256::digest(data).to_vec()),
        "SHA-384" => Ok(sha2::Sha384::digest(data).to_vec()),
        "SHA-512" => Ok(sha2::Sha512::digest(data).to_vec()),
        "MD5" => Ok(md5::Md5::digest(data).to_vec()),
        _ => Err(crypto_err(format!(
            "digest: unsupported algorithm '{algo}'"
        ))),
    }
}
