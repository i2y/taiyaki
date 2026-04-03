use ecdsa::signature::{Signer, Verifier};
use elliptic_curve::sec1::ToEncodedPoint;
use rand::rngs::OsRng;
use taiyaki_core::engine::EngineError;

use super::util::crypto_err;

/// Generate ECDSA/ECDH key pair. Returns (private_key_raw, public_key_uncompressed).
pub fn ec_generate_keypair(curve: &str) -> Result<(Vec<u8>, Vec<u8>), EngineError> {
    match curve {
        "P-256" => {
            let secret = p256::SecretKey::random(&mut OsRng);
            let priv_bytes = secret.to_bytes().to_vec();
            let pub_point = secret.public_key().to_encoded_point(false);
            Ok((priv_bytes, pub_point.as_bytes().to_vec()))
        }
        "P-384" => {
            let secret = p384::SecretKey::random(&mut OsRng);
            let priv_bytes = secret.to_bytes().to_vec();
            let pub_point = secret.public_key().to_encoded_point(false);
            Ok((priv_bytes, pub_point.as_bytes().to_vec()))
        }
        _ => Err(crypto_err(format!("EC: unsupported curve '{curve}'"))),
    }
}

/// ECDSA sign. Returns DER-encoded signature.
pub fn ecdsa_sign(
    curve: &str,
    _hash: &str,
    priv_key_raw: &[u8],
    data: &[u8],
) -> Result<Vec<u8>, EngineError> {
    match curve {
        "P-256" => {
            let secret = p256::SecretKey::from_bytes(priv_key_raw.into())
                .map_err(|e| crypto_err(format!("ECDSA P-256: {e}")))?;
            let signing_key = p256::ecdsa::SigningKey::from(secret);
            let sig: p256::ecdsa::DerSignature = signing_key.sign(data);
            Ok(sig.to_bytes().to_vec())
        }
        "P-384" => {
            let secret = p384::SecretKey::from_bytes(priv_key_raw.into())
                .map_err(|e| crypto_err(format!("ECDSA P-384: {e}")))?;
            let signing_key = p384::ecdsa::SigningKey::from(secret);
            let sig: p384::ecdsa::DerSignature = signing_key.sign(data);
            Ok(sig.to_bytes().to_vec())
        }
        _ => Err(crypto_err(format!("ECDSA: unsupported curve '{curve}'"))),
    }
}

/// ECDSA verify.
pub fn ecdsa_verify(
    curve: &str,
    _hash: &str,
    pub_key_raw: &[u8],
    signature: &[u8],
    data: &[u8],
) -> Result<bool, EngineError> {
    match curve {
        "P-256" => {
            let vk = p256::ecdsa::VerifyingKey::from_sec1_bytes(pub_key_raw)
                .map_err(|e| crypto_err(format!("ECDSA P-256: {e}")))?;
            let sig = p256::ecdsa::DerSignature::from_bytes(signature)
                .map_err(|e| crypto_err(format!("ECDSA P-256: {e}")))?;
            Ok(vk.verify(data, &sig).is_ok())
        }
        "P-384" => {
            let vk = p384::ecdsa::VerifyingKey::from_sec1_bytes(pub_key_raw)
                .map_err(|e| crypto_err(format!("ECDSA P-384: {e}")))?;
            let sig = p384::ecdsa::DerSignature::from_bytes(signature)
                .map_err(|e| crypto_err(format!("ECDSA P-384: {e}")))?;
            Ok(vk.verify(data, &sig).is_ok())
        }
        _ => Err(crypto_err(format!("ECDSA: unsupported curve '{curve}'"))),
    }
}

/// ECDH deriveBits. Returns shared secret raw bytes.
pub fn ecdh_derive_bits(
    curve: &str,
    priv_key_raw: &[u8],
    pub_key_raw: &[u8],
) -> Result<Vec<u8>, EngineError> {
    match curve {
        "P-256" => {
            let secret = p256::SecretKey::from_bytes(priv_key_raw.into())
                .map_err(|e| crypto_err(format!("ECDH P-256: {e}")))?;
            let pub_key = p256::PublicKey::from_sec1_bytes(pub_key_raw)
                .map_err(|e| crypto_err(format!("ECDH P-256: {e}")))?;
            let shared =
                p256::ecdh::diffie_hellman(secret.to_nonzero_scalar(), pub_key.as_affine());
            Ok(shared.raw_secret_bytes().to_vec())
        }
        "P-384" => {
            let secret = p384::SecretKey::from_bytes(priv_key_raw.into())
                .map_err(|e| crypto_err(format!("ECDH P-384: {e}")))?;
            let pub_key = p384::PublicKey::from_sec1_bytes(pub_key_raw)
                .map_err(|e| crypto_err(format!("ECDH P-384: {e}")))?;
            let shared =
                p384::ecdh::diffie_hellman(secret.to_nonzero_scalar(), pub_key.as_affine());
            Ok(shared.raw_secret_bytes().to_vec())
        }
        _ => Err(crypto_err(format!("ECDH: unsupported curve '{curve}'"))),
    }
}
