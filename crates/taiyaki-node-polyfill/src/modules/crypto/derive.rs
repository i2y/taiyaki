use hmac::Hmac;
use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{
    algo_hash, b64_decode, b64_encode, crypto_err, json_str, json_u64, key_data_b64,
    normalize_algorithm, parse_json_arg, str_arg,
};

/// deriveBits. Args: (algorithm_json, key_json, length_str)
pub fn crypto_derive_bits(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo: serde_json::Value = parse_json_arg(args, 0, "deriveBits")?;
    let key: serde_json::Value = parse_json_arg(args, 1, "deriveBits")?;
    let length: usize = str_arg(args, 2, "deriveBits")?
        .parse()
        .map_err(|e| crypto_err(format!("deriveBits: invalid length: {e}")))?;
    let name = json_str(&algo, "name")?;

    let key_data = b64_decode(key_data_b64(&key, "deriveBits")?)?;

    match name {
        "HKDF" => {
            let hash = algo_hash(&algo);
            let salt_b64 = algo.get("salt").and_then(|v| v.as_str()).unwrap_or("");
            let info_b64 = algo.get("info").and_then(|v| v.as_str()).unwrap_or("");
            let salt = if salt_b64.is_empty() {
                vec![]
            } else {
                b64_decode(salt_b64)?
            };
            let info = if info_b64.is_empty() {
                vec![]
            } else {
                b64_decode(info_b64)?
            };
            let derived = hkdf_derive(hash, &key_data, &salt, &info, length / 8)?;
            Ok(JsValue::String(b64_encode(&derived)))
        }
        "PBKDF2" => {
            let hash = algo_hash(&algo);
            let salt_b64 = json_str(&algo, "salt")?;
            let salt = b64_decode(salt_b64)?;
            let iterations = json_u64(&algo, "iterations")
                .ok_or_else(|| crypto_err("PBKDF2: missing 'iterations'"))?
                as u32;
            let derived = pbkdf2_derive(hash, &key_data, &salt, iterations, length / 8)?;
            Ok(JsValue::String(b64_encode(&derived)))
        }
        "ECDH" => {
            let public_b64 = algo
                .get("public")
                .and_then(|p| p.get("_keyData").or_else(|| p.get("keyData")))
                .and_then(|v| v.as_str())
                .ok_or_else(|| crypto_err("ECDH deriveBits: missing public key"))?;
            let pub_key = b64_decode(public_b64)?;
            let curve = key
                .get("_algorithm")
                .or_else(|| key.get("algorithm"))
                .and_then(|a| a.get("namedCurve"))
                .and_then(|v| v.as_str())
                .ok_or_else(|| crypto_err("ECDH deriveBits: missing namedCurve"))?;
            let shared = super::ec::ecdh_derive_bits(curve, &key_data, &pub_key)?;
            // Truncate to requested length
            let byte_len = length / 8;
            if byte_len > shared.len() {
                return Err(crypto_err(format!(
                    "ECDH: requested {byte_len} bytes but shared secret is {} bytes",
                    shared.len()
                )));
            }
            Ok(JsValue::String(b64_encode(&shared[..byte_len])))
        }
        _ => Err(crypto_err(format!(
            "deriveBits: unsupported algorithm '{name}'"
        ))),
    }
}

/// deriveKey. Args: (algo_json, base_key_json, derived_algo_json, extractable, usages_json)
pub fn crypto_derive_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let algo_str = str_arg(args, 0, "deriveKey")?;
    let key_str = str_arg(args, 1, "deriveKey")?;
    let derived_algo: serde_json::Value = parse_json_arg(args, 2, "deriveKey")?;
    let extractable = str_arg(args, 3, "deriveKey")? == "true";
    let usages: Vec<String> = serde_json::from_str(str_arg(args, 4, "deriveKey")?)
        .map_err(|e| crypto_err(format!("deriveKey: {e}")))?;

    // Determine key length from derived algorithm
    let derived_name = json_str(&derived_algo, "name")?;
    let key_length_bits = match derived_name {
        "AES-CBC" | "AES-CTR" | "AES-GCM" | "AES-KW" => json_u64(&derived_algo, "length")
            .ok_or_else(|| crypto_err("deriveKey: AES requires 'length'"))?
            as usize,
        "HMAC" => json_u64(&derived_algo, "length").unwrap_or(256) as usize,
        _ => {
            return Err(crypto_err(format!(
                "deriveKey: unsupported derived algorithm '{derived_name}'"
            )));
        }
    };

    // Use deriveBits to get the key material
    let length_str = key_length_bits.to_string();
    let derive_args = vec![
        JsValue::String(algo_str.to_string()),
        JsValue::String(key_str.to_string()),
        JsValue::String(length_str),
    ];
    let bits_b64 = match crypto_derive_bits(&derive_args)? {
        JsValue::String(s) => s,
        _ => return Err(crypto_err("deriveKey: deriveBits failed")),
    };

    let result = serde_json::json!({
        "type": "secret",
        "keyData": bits_b64,
        "extractable": extractable,
        "usages": usages,
        "algorithm": derived_algo,
    });
    Ok(JsValue::String(result.to_string()))
}

/// Node pbkdf2Sync. Args: (password_b64, salt_b64, iterations, keylen, digest)
pub fn crypto_pbkdf2_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let pass_b64 = str_arg(args, 0, "pbkdf2Sync")?;
    let salt_b64 = str_arg(args, 1, "pbkdf2Sync")?;
    let iterations_str = str_arg(args, 2, "pbkdf2Sync")?;
    let keylen_str = str_arg(args, 3, "pbkdf2Sync")?;
    let digest_algo = str_arg(args, 4, "pbkdf2Sync")?;

    let password = b64_decode(pass_b64)?;
    let salt = b64_decode(salt_b64)?;
    let iterations: u32 = iterations_str
        .parse()
        .map_err(|e| crypto_err(format!("pbkdf2Sync: {e}")))?;
    let keylen: usize = keylen_str
        .parse()
        .map_err(|e| crypto_err(format!("pbkdf2Sync: {e}")))?;

    let derived = pbkdf2_derive(digest_algo, &password, &salt, iterations, keylen)?;
    Ok(JsValue::String(b64_encode(&derived)))
}

/// Node scryptSync. Args: (password_b64, salt_b64, keylen, options_json)
pub fn crypto_scrypt_sync(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let pass_b64 = str_arg(args, 0, "scryptSync")?;
    let salt_b64 = str_arg(args, 1, "scryptSync")?;
    let keylen_str = str_arg(args, 2, "scryptSync")?;
    let options_str = args
        .get(3)
        .and_then(|v| match v {
            JsValue::String(s) => Some(s.as_str()),
            _ => None,
        })
        .unwrap_or("{}");

    let password = b64_decode(pass_b64)?;
    let salt = b64_decode(salt_b64)?;
    let keylen: usize = keylen_str
        .parse()
        .map_err(|e| crypto_err(format!("scryptSync: {e}")))?;
    let options: serde_json::Value =
        serde_json::from_str(options_str).unwrap_or(serde_json::json!({}));

    let n = json_u64(&options, "N")
        .or_else(|| json_u64(&options, "cost"))
        .unwrap_or(16384) as u32;
    let r = json_u64(&options, "r")
        .or_else(|| json_u64(&options, "blockSize"))
        .unwrap_or(8) as u32;
    let p = json_u64(&options, "p")
        .or_else(|| json_u64(&options, "parallelization"))
        .unwrap_or(1) as u32;

    if n == 0 || (n & (n - 1)) != 0 {
        return Err(crypto_err(format!(
            "scryptSync: N must be a power of 2, got {n}"
        )));
    }
    let log_n = (n as f64).log2() as u8;
    let params = scrypt::Params::new(log_n, r, p, keylen)
        .map_err(|e| crypto_err(format!("scryptSync: {e}")))?;

    let mut output = vec![0u8; keylen];
    scrypt::scrypt(&password, &salt, &params, &mut output)
        .map_err(|e| crypto_err(format!("scryptSync: {e}")))?;

    Ok(JsValue::String(b64_encode(&output)))
}

fn hkdf_derive(
    hash: &str,
    ikm: &[u8],
    salt: &[u8],
    info: &[u8],
    length: usize,
) -> Result<Vec<u8>, EngineError> {
    let mut output = vec![0u8; length];
    match normalize_algorithm(hash) {
        "SHA-1" => {
            let hk = hkdf::Hkdf::<sha1::Sha1>::new(Some(salt), ikm);
            hk.expand(info, &mut output)
                .map_err(|e| crypto_err(format!("HKDF: {e}")))?;
        }
        "SHA-256" => {
            let hk = hkdf::Hkdf::<sha2::Sha256>::new(Some(salt), ikm);
            hk.expand(info, &mut output)
                .map_err(|e| crypto_err(format!("HKDF: {e}")))?;
        }
        "SHA-384" => {
            let hk = hkdf::Hkdf::<sha2::Sha384>::new(Some(salt), ikm);
            hk.expand(info, &mut output)
                .map_err(|e| crypto_err(format!("HKDF: {e}")))?;
        }
        "SHA-512" => {
            let hk = hkdf::Hkdf::<sha2::Sha512>::new(Some(salt), ikm);
            hk.expand(info, &mut output)
                .map_err(|e| crypto_err(format!("HKDF: {e}")))?;
        }
        _ => return Err(crypto_err(format!("HKDF: unsupported hash '{hash}'"))),
    }
    Ok(output)
}

fn pbkdf2_derive(
    hash: &str,
    password: &[u8],
    salt: &[u8],
    iterations: u32,
    length: usize,
) -> Result<Vec<u8>, EngineError> {
    let mut output = vec![0u8; length];
    match normalize_algorithm(hash) {
        "SHA-1" => {
            pbkdf2::pbkdf2::<Hmac<sha1::Sha1>>(password, salt, iterations, &mut output)
                .map_err(|e| crypto_err(format!("PBKDF2: {e}")))?;
        }
        "SHA-256" => {
            pbkdf2::pbkdf2::<Hmac<sha2::Sha256>>(password, salt, iterations, &mut output)
                .map_err(|e| crypto_err(format!("PBKDF2: {e}")))?;
        }
        "SHA-384" => {
            pbkdf2::pbkdf2::<Hmac<sha2::Sha384>>(password, salt, iterations, &mut output)
                .map_err(|e| crypto_err(format!("PBKDF2: {e}")))?;
        }
        "SHA-512" => {
            pbkdf2::pbkdf2::<Hmac<sha2::Sha512>>(password, salt, iterations, &mut output)
                .map_err(|e| crypto_err(format!("PBKDF2: {e}")))?;
        }
        _ => return Err(crypto_err(format!("PBKDF2: unsupported hash '{hash}'"))),
    }
    Ok(output)
}
