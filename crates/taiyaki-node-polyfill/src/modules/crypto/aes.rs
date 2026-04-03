use aes::cipher::{BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use aes_gcm::{Aes128Gcm, Aes256Gcm, KeyInit, Nonce, aead::Aead};
use taiyaki_core::engine::{EngineError, JsValue};

use super::util::{b64_decode, b64_encode, crypto_err, json_str, json_u64, str_arg};

/// AES encrypt. Args: (algorithm_json, key_json, data_b64)
pub fn crypto_encrypt_aes(
    algo: &serde_json::Value,
    key_data: &[u8],
    plaintext: &[u8],
) -> Result<Vec<u8>, EngineError> {
    let name = json_str(algo, "name")?;
    match name {
        "AES-GCM" => {
            let iv_b64 = json_str(algo, "iv")?;
            let iv = b64_decode(iv_b64)?;
            let tag_length = json_u64(algo, "tagLength").unwrap_or(128) as usize;
            if tag_length != 128 {
                return Err(crypto_err("AES-GCM: only 128-bit tag length supported"));
            }
            aes_gcm_encrypt(key_data, &iv, plaintext, algo)
        }
        "AES-CBC" => {
            let iv_b64 = json_str(algo, "iv")?;
            let iv = b64_decode(iv_b64)?;
            aes_cbc_encrypt(key_data, &iv, plaintext)
        }
        "AES-CTR" => {
            let counter_b64 = json_str(algo, "counter")?;
            let counter = b64_decode(counter_b64)?;
            aes_ctr_encrypt(key_data, &counter, plaintext)
        }
        _ => Err(crypto_err(format!(
            "encrypt: unsupported algorithm '{name}'"
        ))),
    }
}

/// AES decrypt. Args: (algorithm_json, key_json, data_b64)
pub fn crypto_decrypt_aes(
    algo: &serde_json::Value,
    key_data: &[u8],
    ciphertext: &[u8],
) -> Result<Vec<u8>, EngineError> {
    let name = json_str(algo, "name")?;
    match name {
        "AES-GCM" => {
            let iv_b64 = json_str(algo, "iv")?;
            let iv = b64_decode(iv_b64)?;
            aes_gcm_decrypt(key_data, &iv, ciphertext, algo)
        }
        "AES-CBC" => {
            let iv_b64 = json_str(algo, "iv")?;
            let iv = b64_decode(iv_b64)?;
            aes_cbc_decrypt(key_data, &iv, ciphertext)
        }
        "AES-CTR" => {
            let counter_b64 = json_str(algo, "counter")?;
            let counter = b64_decode(counter_b64)?;
            aes_ctr_decrypt(key_data, &counter, ciphertext)
        }
        _ => Err(crypto_err(format!(
            "decrypt: unsupported algorithm '{name}'"
        ))),
    }
}

fn aes_gcm_encrypt(
    key: &[u8],
    iv: &[u8],
    plaintext: &[u8],
    algo: &serde_json::Value,
) -> Result<Vec<u8>, EngineError> {
    let aad = algo
        .get("additionalData")
        .and_then(|v| v.as_str())
        .map(b64_decode)
        .transpose()?;

    match key.len() {
        16 => {
            let cipher =
                Aes128Gcm::new_from_slice(key).map_err(|e| crypto_err(format!("AES-GCM: {e}")))?;
            let nonce = Nonce::from_slice(iv);
            let payload = if let Some(ref aad) = aad {
                aes_gcm::aead::Payload {
                    msg: plaintext,
                    aad,
                }
            } else {
                aes_gcm::aead::Payload {
                    msg: plaintext,
                    aad: &[],
                }
            };
            cipher
                .encrypt(nonce, payload)
                .map_err(|e| crypto_err(format!("AES-GCM encrypt: {e}")))
        }
        32 => {
            let cipher =
                Aes256Gcm::new_from_slice(key).map_err(|e| crypto_err(format!("AES-GCM: {e}")))?;
            let nonce = Nonce::from_slice(iv);
            let payload = if let Some(ref aad) = aad {
                aes_gcm::aead::Payload {
                    msg: plaintext,
                    aad,
                }
            } else {
                aes_gcm::aead::Payload {
                    msg: plaintext,
                    aad: &[],
                }
            };
            cipher
                .encrypt(nonce, payload)
                .map_err(|e| crypto_err(format!("AES-GCM encrypt: {e}")))
        }
        n => Err(crypto_err(format!("AES-GCM: invalid key length {n}"))),
    }
}

fn aes_gcm_decrypt(
    key: &[u8],
    iv: &[u8],
    ciphertext: &[u8],
    algo: &serde_json::Value,
) -> Result<Vec<u8>, EngineError> {
    let aad = algo
        .get("additionalData")
        .and_then(|v| v.as_str())
        .map(b64_decode)
        .transpose()?;

    match key.len() {
        16 => {
            let cipher =
                Aes128Gcm::new_from_slice(key).map_err(|e| crypto_err(format!("AES-GCM: {e}")))?;
            let nonce = Nonce::from_slice(iv);
            let payload = if let Some(ref aad) = aad {
                aes_gcm::aead::Payload {
                    msg: ciphertext,
                    aad,
                }
            } else {
                aes_gcm::aead::Payload {
                    msg: ciphertext,
                    aad: &[],
                }
            };
            cipher
                .decrypt(nonce, payload)
                .map_err(|e| crypto_err(format!("AES-GCM decrypt: {e}")))
        }
        32 => {
            let cipher =
                Aes256Gcm::new_from_slice(key).map_err(|e| crypto_err(format!("AES-GCM: {e}")))?;
            let nonce = Nonce::from_slice(iv);
            let payload = if let Some(ref aad) = aad {
                aes_gcm::aead::Payload {
                    msg: ciphertext,
                    aad,
                }
            } else {
                aes_gcm::aead::Payload {
                    msg: ciphertext,
                    aad: &[],
                }
            };
            cipher
                .decrypt(nonce, payload)
                .map_err(|e| crypto_err(format!("AES-GCM decrypt: {e}")))
        }
        n => Err(crypto_err(format!("AES-GCM: invalid key length {n}"))),
    }
}

fn aes_cbc_encrypt(key: &[u8], iv: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EngineError> {
    use cbc::cipher::block_padding::Pkcs7;
    match key.len() {
        16 => {
            type Aes128CbcEnc = cbc::Encryptor<aes::Aes128>;
            let ct = Aes128CbcEnc::new_from_slices(key, iv)
                .map_err(|e| crypto_err(format!("AES-CBC: {e}")))?
                .encrypt_padded_vec_mut::<Pkcs7>(plaintext);
            Ok(ct)
        }
        32 => {
            type Aes256CbcEnc = cbc::Encryptor<aes::Aes256>;
            let ct = Aes256CbcEnc::new_from_slices(key, iv)
                .map_err(|e| crypto_err(format!("AES-CBC: {e}")))?
                .encrypt_padded_vec_mut::<Pkcs7>(plaintext);
            Ok(ct)
        }
        n => Err(crypto_err(format!("AES-CBC: invalid key length {n}"))),
    }
}

fn aes_cbc_decrypt(key: &[u8], iv: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EngineError> {
    use cbc::cipher::block_padding::Pkcs7;
    match key.len() {
        16 => {
            type Aes128CbcDec = cbc::Decryptor<aes::Aes128>;
            Aes128CbcDec::new_from_slices(key, iv)
                .map_err(|e| crypto_err(format!("AES-CBC: {e}")))?
                .decrypt_padded_vec_mut::<Pkcs7>(ciphertext)
                .map_err(|e| crypto_err(format!("AES-CBC decrypt: {e}")))
        }
        32 => {
            type Aes256CbcDec = cbc::Decryptor<aes::Aes256>;
            Aes256CbcDec::new_from_slices(key, iv)
                .map_err(|e| crypto_err(format!("AES-CBC: {e}")))?
                .decrypt_padded_vec_mut::<Pkcs7>(ciphertext)
                .map_err(|e| crypto_err(format!("AES-CBC decrypt: {e}")))
        }
        n => Err(crypto_err(format!("AES-CBC: invalid key length {n}"))),
    }
}

fn aes_ctr_encrypt(key: &[u8], counter: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, EngineError> {
    use ctr::cipher::StreamCipher;
    let mut buf = plaintext.to_vec();
    match key.len() {
        16 => {
            type Aes128Ctr = ctr::Ctr64BE<aes::Aes128>;
            let mut cipher = Aes128Ctr::new_from_slices(key, counter)
                .map_err(|e| crypto_err(format!("AES-CTR: {e}")))?;
            cipher.apply_keystream(&mut buf);
            Ok(buf)
        }
        32 => {
            type Aes256Ctr = ctr::Ctr64BE<aes::Aes256>;
            let mut cipher = Aes256Ctr::new_from_slices(key, counter)
                .map_err(|e| crypto_err(format!("AES-CTR: {e}")))?;
            cipher.apply_keystream(&mut buf);
            Ok(buf)
        }
        n => Err(crypto_err(format!("AES-CTR: invalid key length {n}"))),
    }
}

fn aes_ctr_decrypt(key: &[u8], counter: &[u8], ciphertext: &[u8]) -> Result<Vec<u8>, EngineError> {
    // CTR mode: encryption and decryption are the same operation
    aes_ctr_encrypt(key, counter, ciphertext)
}

/// Node createCipheriv / createDecipheriv one-shot.
/// Args: (op, algo, key_b64, iv_b64, data_b64, aad_b64?, auth_tag_b64?)
pub fn crypto_cipher(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let op = str_arg(args, 0, "cipher")?;
    let algo = str_arg(args, 1, "cipher")?;
    let key = b64_decode(str_arg(args, 2, "cipher")?)?;
    let iv = b64_decode(str_arg(args, 3, "cipher")?)?;
    let data = b64_decode(str_arg(args, 4, "cipher")?)?;
    let aad = args
        .get(5)
        .and_then(|v| match v {
            JsValue::String(s) if !s.is_empty() => Some(b64_decode(s)),
            _ => None,
        })
        .transpose()?;
    let auth_tag = args
        .get(6)
        .and_then(|v| match v {
            JsValue::String(s) if !s.is_empty() => Some(b64_decode(s)),
            _ => None,
        })
        .transpose()?;

    match (op, algo) {
        ("encrypt", "aes-128-cbc" | "aes-256-cbc") => {
            let ct = aes_cbc_encrypt(&key, &iv, &data)?;
            Ok(JsValue::String(
                serde_json::json!({"data": b64_encode(&ct)}).to_string(),
            ))
        }
        ("decrypt", "aes-128-cbc" | "aes-256-cbc") => {
            let pt = aes_cbc_decrypt(&key, &iv, &data)?;
            Ok(JsValue::String(
                serde_json::json!({"data": b64_encode(&pt)}).to_string(),
            ))
        }
        ("encrypt", "aes-128-gcm" | "aes-256-gcm") => {
            let algo_json = serde_json::json!({
                "name": "AES-GCM",
                "iv": b64_encode(&iv),
                "additionalData": aad.as_ref().map(|a| b64_encode(a)),
            });
            let ct = aes_gcm_encrypt(&key, &iv, &data, &algo_json)?;
            // GCM output = ciphertext + tag (last 16 bytes)
            let tag_start = ct.len().saturating_sub(16);
            let (ct_part, tag_part) = ct.split_at(tag_start);
            Ok(JsValue::String(
                serde_json::json!({
                    "data": b64_encode(ct_part),
                    "authTag": b64_encode(tag_part),
                })
                .to_string(),
            ))
        }
        ("decrypt", "aes-128-gcm" | "aes-256-gcm") => {
            // Append auth tag to ciphertext for aes-gcm crate
            let mut combined = data.clone();
            if let Some(tag) = auth_tag {
                combined.extend_from_slice(&tag);
            }
            let algo_json = serde_json::json!({
                "name": "AES-GCM",
                "iv": b64_encode(&iv),
                "additionalData": aad.as_ref().map(|a| b64_encode(a)),
            });
            let pt = aes_gcm_decrypt(&key, &iv, &combined, &algo_json)?;
            Ok(JsValue::String(
                serde_json::json!({"data": b64_encode(&pt)}).to_string(),
            ))
        }
        ("encrypt", "aes-128-ctr" | "aes-256-ctr") => {
            let ct = aes_ctr_encrypt(&key, &iv, &data)?;
            Ok(JsValue::String(
                serde_json::json!({"data": b64_encode(&ct)}).to_string(),
            ))
        }
        ("decrypt", "aes-128-ctr" | "aes-256-ctr") => {
            let pt = aes_ctr_decrypt(&key, &iv, &data)?;
            Ok(JsValue::String(
                serde_json::json!({"data": b64_encode(&pt)}).to_string(),
            ))
        }
        _ => Err(crypto_err(format!(
            "cipher: unsupported op='{op}' algo='{algo}'"
        ))),
    }
}
