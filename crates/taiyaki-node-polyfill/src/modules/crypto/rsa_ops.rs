use rand::rngs::OsRng;
use rsa::{Oaep, Pkcs1v15Sign, RsaPrivateKey, RsaPublicKey};
use taiyaki_core::engine::EngineError;

use super::util::{crypto_err, normalize_algorithm};

pub fn rsa_generate_keypair(
    modulus_length: u32,
) -> Result<(RsaPrivateKey, RsaPublicKey), EngineError> {
    let bits = modulus_length as usize;
    let priv_key =
        RsaPrivateKey::new(&mut OsRng, bits).map_err(|e| crypto_err(format!("RSA keygen: {e}")))?;
    let pub_key = priv_key.to_public_key();
    Ok((priv_key, pub_key))
}

pub fn rsa_oaep_encrypt(
    pub_key: &RsaPublicKey,
    hash: &str,
    plaintext: &[u8],
) -> Result<Vec<u8>, EngineError> {
    let padding = oaep_padding(hash)?;
    pub_key
        .encrypt(&mut OsRng, padding, plaintext)
        .map_err(|e| crypto_err(format!("RSA-OAEP encrypt: {e}")))
}

pub fn rsa_oaep_decrypt(
    priv_key: &RsaPrivateKey,
    hash: &str,
    ciphertext: &[u8],
) -> Result<Vec<u8>, EngineError> {
    let padding = oaep_padding(hash)?;
    priv_key
        .decrypt(padding, ciphertext)
        .map_err(|e| crypto_err(format!("RSA-OAEP decrypt: {e}")))
}

pub fn rsa_pkcs1v15_sign(
    priv_key: &RsaPrivateKey,
    hash: &str,
    data: &[u8],
) -> Result<Vec<u8>, EngineError> {
    use digest::Digest;
    match normalize_algorithm(hash) {
        "SHA-256" => {
            let hashed = sha2::Sha256::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha256>();
            priv_key
                .sign(scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSASSA-PKCS1-v1_5 sign: {e}")))
        }
        "SHA-384" => {
            let hashed = sha2::Sha384::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha384>();
            priv_key
                .sign(scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSASSA-PKCS1-v1_5 sign: {e}")))
        }
        "SHA-512" => {
            let hashed = sha2::Sha512::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha512>();
            priv_key
                .sign(scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSASSA-PKCS1-v1_5 sign: {e}")))
        }
        "SHA-1" => {
            let hashed = sha1::Sha1::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha1::Sha1>();
            priv_key
                .sign(scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSASSA-PKCS1-v1_5 sign: {e}")))
        }
        _ => Err(crypto_err(format!(
            "RSASSA-PKCS1-v1_5: unsupported hash '{hash}'"
        ))),
    }
}

pub fn rsa_pkcs1v15_verify(
    pub_key: &RsaPublicKey,
    hash: &str,
    signature: &[u8],
    data: &[u8],
) -> Result<bool, EngineError> {
    use digest::Digest;
    match normalize_algorithm(hash) {
        "SHA-256" => {
            let hashed = sha2::Sha256::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha256>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        "SHA-384" => {
            let hashed = sha2::Sha384::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha384>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        "SHA-512" => {
            let hashed = sha2::Sha512::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha2::Sha512>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        "SHA-1" => {
            let hashed = sha1::Sha1::digest(data);
            let scheme = Pkcs1v15Sign::new::<sha1::Sha1>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        _ => Err(crypto_err(format!(
            "RSASSA-PKCS1-v1_5: unsupported hash '{hash}'"
        ))),
    }
}

pub fn rsa_pss_sign(
    priv_key: &RsaPrivateKey,
    hash: &str,
    data: &[u8],
) -> Result<Vec<u8>, EngineError> {
    use digest::Digest;
    use rsa::pss::Pss;
    match normalize_algorithm(hash) {
        "SHA-256" => {
            let hashed = sha2::Sha256::digest(data);
            let scheme = Pss::new::<sha2::Sha256>();
            priv_key
                .sign_with_rng(&mut OsRng, scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSA-PSS sign: {e}")))
        }
        "SHA-384" => {
            let hashed = sha2::Sha384::digest(data);
            let scheme = Pss::new::<sha2::Sha384>();
            priv_key
                .sign_with_rng(&mut OsRng, scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSA-PSS sign: {e}")))
        }
        "SHA-512" => {
            let hashed = sha2::Sha512::digest(data);
            let scheme = Pss::new::<sha2::Sha512>();
            priv_key
                .sign_with_rng(&mut OsRng, scheme, &hashed)
                .map_err(|e| crypto_err(format!("RSA-PSS sign: {e}")))
        }
        _ => Err(crypto_err(format!("RSA-PSS: unsupported hash '{hash}'"))),
    }
}

pub fn rsa_pss_verify(
    pub_key: &RsaPublicKey,
    hash: &str,
    signature: &[u8],
    data: &[u8],
) -> Result<bool, EngineError> {
    use digest::Digest;
    use rsa::pss::Pss;
    match normalize_algorithm(hash) {
        "SHA-256" => {
            let hashed = sha2::Sha256::digest(data);
            let scheme = Pss::new::<sha2::Sha256>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        "SHA-384" => {
            let hashed = sha2::Sha384::digest(data);
            let scheme = Pss::new::<sha2::Sha384>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        "SHA-512" => {
            let hashed = sha2::Sha512::digest(data);
            let scheme = Pss::new::<sha2::Sha512>();
            Ok(pub_key.verify(scheme, &hashed, signature).is_ok())
        }
        _ => Err(crypto_err(format!("RSA-PSS: unsupported hash '{hash}'"))),
    }
}

fn oaep_padding(hash: &str) -> Result<Oaep, EngineError> {
    match normalize_algorithm(hash) {
        "SHA-1" => Ok(Oaep::new::<sha1::Sha1>()),
        "SHA-256" => Ok(Oaep::new::<sha2::Sha256>()),
        "SHA-384" => Ok(Oaep::new::<sha2::Sha384>()),
        "SHA-512" => Ok(Oaep::new::<sha2::Sha512>()),
        _ => Err(crypto_err(format!("RSA-OAEP: unsupported hash '{hash}'"))),
    }
}
