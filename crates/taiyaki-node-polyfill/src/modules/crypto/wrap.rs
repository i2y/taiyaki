use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{
    b64_decode, b64_encode, crypto_err, json_str, key_data_b64, parse_json_arg, str_arg,
};

/// wrapKey. Args: (format, key_json, wrapping_key_json, wrap_algo_json)
pub fn crypto_wrap_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let format = str_arg(args, 0, "wrapKey")?;
    let key: serde_json::Value = parse_json_arg(args, 1, "wrapKey")?;
    let wrapping_key: serde_json::Value = parse_json_arg(args, 2, "wrapKey")?;
    let wrap_algo: serde_json::Value = parse_json_arg(args, 3, "wrapKey")?;

    let key_material = match format {
        "raw" => b64_decode(key_data_b64(&key, "wrapKey")?)?,
        _ => {
            return Err(crypto_err(format!(
                "wrapKey: unsupported format '{format}'"
            )));
        }
    };

    let wrapping_key_data = b64_decode(key_data_b64(&wrapping_key, "wrapKey")?)?;

    let wrap_name = json_str(&wrap_algo, "name")?;
    match wrap_name {
        "AES-KW" => {
            let wrapped = aes_kw_wrap(&wrapping_key_data, &key_material)?;
            Ok(JsValue::String(b64_encode(&wrapped)))
        }
        "AES-GCM" => {
            let ct = super::aes::crypto_encrypt_aes(&wrap_algo, &wrapping_key_data, &key_material)?;
            Ok(JsValue::String(b64_encode(&ct)))
        }
        _ => Err(crypto_err(format!(
            "wrapKey: unsupported algorithm '{wrap_name}'"
        ))),
    }
}

/// unwrapKey. Args: (format, wrapped_b64, unwrapping_key_json, unwrap_algo_json, unwrapped_algo_json, extractable, usages_json)
pub fn crypto_unwrap_key(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let format = str_arg(args, 0, "unwrapKey")?;
    if format != "raw" {
        return Err(crypto_err(format!(
            "unwrapKey: unsupported format '{format}'"
        )));
    }
    let wrapped_b64 = str_arg(args, 1, "unwrapKey")?;
    let unwrapping_key: serde_json::Value = parse_json_arg(args, 2, "unwrapKey")?;
    let unwrap_algo: serde_json::Value = parse_json_arg(args, 3, "unwrapKey")?;
    let unwrapped_algo: serde_json::Value = parse_json_arg(args, 4, "unwrapKey")?;
    let extractable = str_arg(args, 5, "unwrapKey")? == "true";
    let usages: Vec<String> = serde_json::from_str(str_arg(args, 6, "unwrapKey")?)
        .map_err(|e| crypto_err(format!("unwrapKey: {e}")))?;

    let wrapped = b64_decode(wrapped_b64)?;
    let unwrapping_key_data = b64_decode(key_data_b64(&unwrapping_key, "unwrapKey")?)?;

    let unwrap_name = json_str(&unwrap_algo, "name")?;
    let key_material = match unwrap_name {
        "AES-KW" => aes_kw_unwrap(&unwrapping_key_data, &wrapped)?,
        "AES-GCM" => super::aes::crypto_decrypt_aes(&unwrap_algo, &unwrapping_key_data, &wrapped)?,
        _ => {
            return Err(crypto_err(format!(
                "unwrapKey: unsupported algorithm '{unwrap_name}'"
            )));
        }
    };

    let unwrapped_name = json_str(&unwrapped_algo, "name")?;
    let length = key_material.len() * 8;
    let result = serde_json::json!({
        "type": "secret",
        "keyData": b64_encode(&key_material),
        "extractable": extractable,
        "usages": usages,
        "algorithm": {
            "name": unwrapped_name,
            "length": length,
        },
    });
    Ok(JsValue::String(result.to_string()))
}

fn aes_kw_wrap(wrapping_key: &[u8], data: &[u8]) -> Result<Vec<u8>, EngineError> {
    use aes_kw::Kek;
    let mut out = vec![0u8; data.len() + 8];
    match wrapping_key.len() {
        16 => {
            let kek = Kek::<aes::Aes128>::new(wrapping_key.into());
            kek.wrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW wrap: {e}")))?;
        }
        24 => {
            let kek = Kek::<aes::Aes192>::new(wrapping_key.into());
            kek.wrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW wrap: {e}")))?;
        }
        32 => {
            let kek = Kek::<aes::Aes256>::new(wrapping_key.into());
            kek.wrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW wrap: {e}")))?;
        }
        n => return Err(crypto_err(format!("AES-KW: invalid key length {n}"))),
    }
    Ok(out)
}

fn aes_kw_unwrap(wrapping_key: &[u8], data: &[u8]) -> Result<Vec<u8>, EngineError> {
    use aes_kw::Kek;
    if data.len() < 8 {
        return Err(crypto_err("AES-KW: wrapped data too short"));
    }
    let mut out = vec![0u8; data.len() - 8];
    match wrapping_key.len() {
        16 => {
            let kek = Kek::<aes::Aes128>::new(wrapping_key.into());
            kek.unwrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW unwrap: {e}")))?;
        }
        24 => {
            let kek = Kek::<aes::Aes192>::new(wrapping_key.into());
            kek.unwrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW unwrap: {e}")))?;
        }
        32 => {
            let kek = Kek::<aes::Aes256>::new(wrapping_key.into());
            kek.unwrap(data, &mut out)
                .map_err(|e| crypto_err(format!("AES-KW unwrap: {e}")))?;
        }
        n => return Err(crypto_err(format!("AES-KW: invalid key length {n}"))),
    }
    Ok(out)
}
