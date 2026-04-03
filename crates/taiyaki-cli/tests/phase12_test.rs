use std::process::Command;

fn taiyaki_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_taiyaki"));
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd
}

fn run_js(code: &str) -> (String, String, bool) {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("test.js");
    std::fs::write(&file, code).unwrap();
    let output = taiyaki_bin().arg("run").arg(&file).output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    (stdout, stderr, output.status.success())
}

// --- WebCrypto: crypto.subtle.digest ---

#[test]
fn test_subtle_digest_sha256() {
    let (stdout, stderr, ok) = run_js(
        r#"
const data = new TextEncoder().encode("hello");
const hash = await crypto.subtle.digest("SHA-256", data);
const bytes = new Uint8Array(hash);
const hex = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
// Known SHA-256 of "hello"
console.log(hex);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert!(
        stdout
            .trim()
            .starts_with("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
    );
}

#[test]
fn test_subtle_digest_sha1() {
    let (stdout, stderr, ok) = run_js(
        r#"
const data = new TextEncoder().encode("hello");
const hash = await crypto.subtle.digest("SHA-1", data);
const bytes = new Uint8Array(hash);
const hex = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
console.log(hex);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d");
}

// --- WebCrypto: HMAC sign/verify ---

#[test]
fn test_subtle_hmac_sign_verify() {
    let (stdout, stderr, ok) = run_js(
        r#"
const key = await crypto.subtle.generateKey(
    { name: "HMAC", hash: "SHA-256" },
    true, ["sign", "verify"]
);
const data = new TextEncoder().encode("hello world");
const sig = await crypto.subtle.sign("HMAC", key, data);
const valid = await crypto.subtle.verify("HMAC", key, sig, data);
console.log(valid);
const tampered = new Uint8Array(sig);
tampered[0] ^= 0xff;
const invalid = await crypto.subtle.verify("HMAC", key, tampered.buffer, data);
console.log(invalid);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "true");
    assert_eq!(lines[1], "false");
}

// --- WebCrypto: AES-GCM encrypt/decrypt ---

#[test]
fn test_subtle_aes_gcm_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
);
const iv = crypto.getRandomValues(new Uint8Array(12));
const data = new TextEncoder().encode("secret message");
const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data);
const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ct);
const decoded = new TextDecoder().decode(new Uint8Array(pt));
console.log(decoded);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "secret message");
}

// --- WebCrypto: AES-CBC encrypt/decrypt ---

#[test]
fn test_subtle_aes_cbc_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
const key = await crypto.subtle.generateKey(
    { name: "AES-CBC", length: 256 }, true, ["encrypt", "decrypt"]
);
const iv = crypto.getRandomValues(new Uint8Array(16));
const data = new TextEncoder().encode("hello CBC");
const ct = await crypto.subtle.encrypt({ name: "AES-CBC", iv }, key, data);
const pt = await crypto.subtle.decrypt({ name: "AES-CBC", iv }, key, ct);
const decoded = new TextDecoder().decode(new Uint8Array(pt));
console.log(decoded);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "hello CBC");
}

// --- WebCrypto: AES-CTR encrypt/decrypt ---

#[test]
fn test_subtle_aes_ctr_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
const key = await crypto.subtle.generateKey(
    { name: "AES-CTR", length: 128 }, true, ["encrypt", "decrypt"]
);
const counter = crypto.getRandomValues(new Uint8Array(16));
const data = new TextEncoder().encode("hello CTR");
const ct = await crypto.subtle.encrypt({ name: "AES-CTR", counter, length: 64 }, key, data);
const pt = await crypto.subtle.decrypt({ name: "AES-CTR", counter, length: 64 }, key, ct);
const decoded = new TextDecoder().decode(new Uint8Array(pt));
console.log(decoded);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "hello CTR");
}

// --- WebCrypto: AES key export ---

#[test]
fn test_subtle_aes_generate_export() {
    let (stdout, stderr, ok) = run_js(
        r#"
const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
);
const raw = await crypto.subtle.exportKey("raw", key);
console.log(raw.byteLength);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "32");
}

// --- WebCrypto: importKey + HMAC ---

#[test]
fn test_subtle_import_hmac_key() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyData = crypto.getRandomValues(new Uint8Array(32));
const key = await crypto.subtle.importKey(
    "raw", keyData, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
);
console.log(key.type);
console.log(key.algorithm.name);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "secret");
    assert_eq!(lines[1], "HMAC");
}

// --- WebCrypto: HKDF deriveBits ---

#[test]
fn test_subtle_hkdf_derive_bits() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode("secret"), { name: "HKDF" }, false, ["deriveBits"]
);
const derived = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: new Uint8Array(16), info: new Uint8Array(0) },
    keyMaterial, 256
);
console.log(derived.byteLength);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "32");
}

// --- WebCrypto: PBKDF2 deriveKey ---

#[test]
fn test_subtle_pbkdf2_derive_key() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode("password"), { name: "PBKDF2" }, false, ["deriveKey"]
);
const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: new TextEncoder().encode("salt"), iterations: 100000 },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    true, ["encrypt", "decrypt"]
);
const raw = await crypto.subtle.exportKey("raw", key);
console.log(raw.byteLength);
console.log(key.algorithm.name);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "32");
    assert_eq!(lines[1], "AES-GCM");
}

// --- WebCrypto: RSA-OAEP encrypt/decrypt ---

#[test]
fn test_subtle_rsa_oaep_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyPair = await crypto.subtle.generateKey(
    { name: "RSA-OAEP", modulusLength: 2048, hash: "SHA-256", publicExponent: new Uint8Array([1, 0, 1]) },
    true, ["encrypt", "decrypt"]
);
const data = new TextEncoder().encode("RSA test");
const ct = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, keyPair.publicKey, data);
const pt = await crypto.subtle.decrypt({ name: "RSA-OAEP" }, keyPair.privateKey, ct);
console.log(new TextDecoder().decode(new Uint8Array(pt)));
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "RSA test");
}

// --- WebCrypto: RSASSA-PKCS1-v1_5 sign/verify ---

#[test]
fn test_subtle_rsa_pkcs1_sign_verify() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyPair = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, hash: "SHA-256", publicExponent: new Uint8Array([1, 0, 1]) },
    true, ["sign", "verify"]
);
const data = new TextEncoder().encode("sign me");
const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", keyPair.privateKey, data);
const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", keyPair.publicKey, sig, data);
console.log(valid);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "true");
}

// --- WebCrypto: ECDSA sign/verify ---

#[test]
fn test_subtle_ecdsa_sign_verify() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyPair = await crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    true, ["sign", "verify"]
);
const data = new TextEncoder().encode("EC test");
const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" }, keyPair.privateKey, data
);
const valid = await crypto.subtle.verify(
    { name: "ECDSA", hash: "SHA-256" }, keyPair.publicKey, sig, data
);
console.log(valid);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "true");
}

// --- WebCrypto: ECDH deriveBits ---

#[test]
fn test_subtle_ecdh_derive_bits() {
    let (stdout, stderr, ok) = run_js(
        r#"
const alice = await crypto.subtle.generateKey(
    { name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]
);
const bob = await crypto.subtle.generateKey(
    { name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]
);
const shared1 = await crypto.subtle.deriveBits(
    { name: "ECDH", public: bob.publicKey }, alice.privateKey, 256
);
const shared2 = await crypto.subtle.deriveBits(
    { name: "ECDH", public: alice.publicKey }, bob.privateKey, 256
);
// Both should produce the same shared secret
const hex1 = Array.from(new Uint8Array(shared1)).map(b => b.toString(16).padStart(2, '0')).join('');
const hex2 = Array.from(new Uint8Array(shared2)).map(b => b.toString(16).padStart(2, '0')).join('');
console.log(hex1 === hex2);
console.log(shared1.byteLength);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    let lines: Vec<&str> = stdout.trim().lines().collect();
    assert_eq!(lines[0], "true");
    assert_eq!(lines[1], "32");
}

// --- WebCrypto: wrapKey/unwrapKey ---

#[test]
fn test_subtle_wrap_unwrap_aes_kw() {
    let (stdout, stderr, ok) = run_js(
        r#"
const wrappingKey = await crypto.subtle.generateKey(
    { name: "AES-KW", length: 256 }, true, ["wrapKey", "unwrapKey"]
);
const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
);
const wrapped = await crypto.subtle.wrapKey("raw", key, wrappingKey, "AES-KW");
const unwrapped = await crypto.subtle.unwrapKey(
    "raw", wrapped, wrappingKey, "AES-KW",
    { name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]
);
// Exported keys should match
const orig = await crypto.subtle.exportKey("raw", key);
const restored = await crypto.subtle.exportKey("raw", unwrapped);
const origHex = Array.from(new Uint8Array(orig)).map(b => b.toString(16).padStart(2, '0')).join('');
const restoredHex = Array.from(new Uint8Array(restored)).map(b => b.toString(16).padStart(2, '0')).join('');
console.log(origHex === restoredHex);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "true");
}

// --- Node crypto: createHash ---

#[test]
fn test_node_create_hash_sha256() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { createHash } from 'crypto';
const hash = createHash('sha256').update('hello').digest('hex');
console.log(hash);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(
        stdout.trim(),
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    );
}

// --- Node crypto: createHmac ---

#[test]
fn test_node_create_hmac() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { createHmac } from 'crypto';
const hmac = createHmac('sha256', 'key').update('hello').digest('hex');
console.log(hmac);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    // Known HMAC-SHA256 of "hello" with key "key"
    assert_eq!(
        stdout.trim(),
        "9307b3b915efb5171ff14d8cb55fbcc798c6c0ef1456d66ded1a6aa723a58b7b"
    );
}

// --- Node crypto: pbkdf2Sync ---

#[test]
fn test_node_pbkdf2_sync() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { pbkdf2Sync } from 'crypto';
const derived = pbkdf2Sync('password', 'salt', 1, 20, 'sha1');
const hex = Array.from(derived).map(b => b.toString(16).padStart(2, '0')).join('');
// RFC 6070 test vector: PBKDF2-HMAC-SHA1, 1 iteration
console.log(hex);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "0c60c80f961f0e71f3a9b524af6012062fe037a6");
}

// --- Node crypto: scryptSync ---

#[test]
fn test_node_scrypt_sync() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { scryptSync } from 'crypto';
const derived = scryptSync('password', 'salt', 32, { N: 1024, r: 8, p: 1 });
console.log(derived.length);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "32");
}

// --- Node crypto: createCipheriv/createDecipheriv ---

#[test]
fn test_node_aes_cbc_cipher_roundtrip() {
    let (stdout, stderr, ok) = run_js(
        r#"
import { createCipheriv, createDecipheriv } from 'crypto';
const key = crypto.getRandomValues(new Uint8Array(32));
const iv = crypto.getRandomValues(new Uint8Array(16));
const cipher = createCipheriv('aes-256-cbc', key, iv);
cipher.update('hello world', 'utf8', 'hex');
const encrypted = cipher.final('hex');
const decipher = createDecipheriv('aes-256-cbc', key, iv);
decipher.update(encrypted, 'hex', 'utf8');
const decrypted = decipher.final('utf8');
console.log(decrypted);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "hello world");
}

// --- Node crypto: RSA-PSS sign/verify ---

#[test]
fn test_subtle_rsa_pss_sign_verify() {
    let (stdout, stderr, ok) = run_js(
        r#"
const keyPair = await crypto.subtle.generateKey(
    { name: "RSA-PSS", modulusLength: 2048, hash: "SHA-256", publicExponent: new Uint8Array([1, 0, 1]) },
    true, ["sign", "verify"]
);
const data = new TextEncoder().encode("RSA-PSS test");
const sig = await crypto.subtle.sign(
    { name: "RSA-PSS", saltLength: 32 }, keyPair.privateKey, data
);
const valid = await crypto.subtle.verify(
    { name: "RSA-PSS", saltLength: 32 }, keyPair.publicKey, sig, data
);
console.log(valid);
"#,
    );
    assert!(ok, "stderr: {stderr}");
    assert_eq!(stdout.trim(), "true");
}
