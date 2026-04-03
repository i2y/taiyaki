// CryptoKey class
class CryptoKey {
    constructor(type, extractable, algorithm, usages, keyData) {
        this._type = type;
        this._extractable = extractable;
        this._algorithm = algorithm;
        this._usages = usages;
        this._keyData = keyData;
    }
    get type() { return this._type; }
    get extractable() { return this._extractable; }
    get algorithm() { return Object.freeze({...this._algorithm}); }
    get usages() { return [...this._usages]; }
}

// Helper: convert ArrayBuffer/TypedArray/DataView to base64
function __toB64(data) {
    if (typeof data === 'string') return data;
    let bytes;
    if (data instanceof ArrayBuffer) {
        bytes = new Uint8Array(data);
    } else if (ArrayBuffer.isView(data)) {
        bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    } else {
        throw new TypeError('Expected BufferSource');
    }
    return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
}

// Helper: base64 to ArrayBuffer
function __fromB64(b64) {
    const bytes = new Uint8Array(__buffer_b64_to_bytes(b64));
    return bytes.buffer;
}

// Helper: normalize algorithm parameter
function __normalizeAlgo(algo) {
    if (typeof algo === 'string') return { name: algo };
    return algo;
}

// Helper: serialize algo for Rust, encoding binary fields as base64
function __serializeAlgo(algo) {
    const obj = {...algo};
    if (obj.iv) obj.iv = __toB64(obj.iv);
    if (obj.counter) obj.counter = __toB64(obj.counter);
    if (obj.salt) obj.salt = __toB64(obj.salt);
    if (obj.info) obj.info = __toB64(obj.info);
    if (obj.additionalData) obj.additionalData = __toB64(obj.additionalData);
    if (obj.label) obj.label = __toB64(obj.label);
    if (obj.hash && typeof obj.hash === 'object') obj.hash = obj.hash.name || obj.hash;
    // Serialize public key for ECDH
    if (obj.public && obj.public instanceof CryptoKey) {
        obj.public = { _keyData: obj.public._keyData, _algorithm: obj.public._algorithm };
    }
    return JSON.stringify(obj);
}

// Helper: serialize CryptoKey for Rust
function __serializeKey(key) {
    return JSON.stringify({
        _type: key._type,
        _keyData: key._keyData,
        _algorithm: key._algorithm,
        _extractable: key._extractable,
        _usages: key._usages,
    });
}

// Helper: build CryptoKey from Rust result JSON
function __buildKey(json, extractable, usages) {
    const data = typeof json === 'string' ? JSON.parse(json) : json;
    return new CryptoKey(
        data.type,
        extractable !== undefined ? extractable : (data.extractable || false),
        data.algorithm,
        usages !== undefined ? usages : (data.usages || []),
        data.keyData,
    );
}

// SubtleCrypto class
class SubtleCrypto {
    async digest(algorithm, data) {
        const algo = __normalizeAlgo(algorithm);
        const b64 = __crypto_digest(algo.name, __toB64(data));
        return __fromB64(b64);
    }

    async generateKey(algorithm, extractable, keyUsages) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_generate_key(__serializeAlgo(algo));
        const parsed = JSON.parse(result);
        if (parsed.publicKey && parsed.privateKey) {
            return {
                publicKey: __buildKey(parsed.publicKey, extractable, keyUsages.filter(u => ['verify', 'encrypt', 'wrapKey'].includes(u))),
                privateKey: __buildKey(parsed.privateKey, extractable, keyUsages.filter(u => ['sign', 'decrypt', 'unwrapKey'].includes(u))),
            };
        }
        return __buildKey(parsed, extractable, keyUsages);
    }

    async importKey(format, keyData, algorithm, extractable, keyUsages) {
        const algo = __normalizeAlgo(algorithm);
        const keyB64 = (format === 'jwk') ? JSON.stringify(keyData) : __toB64(keyData);
        const result = __crypto_import_key(
            format, keyB64, __serializeAlgo(algo),
            String(extractable), JSON.stringify(keyUsages),
        );
        return __buildKey(result, extractable, keyUsages);
    }

    async exportKey(format, key) {
        const result = __crypto_export_key(format, __serializeKey(key));
        if (format === 'jwk') {
            return JSON.parse(result);
        }
        return __fromB64(result);
    }

    async sign(algorithm, key, data) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_sign(
            __serializeAlgo(algo), __serializeKey(key), __toB64(data),
        );
        return __fromB64(result);
    }

    async verify(algorithm, key, signature, data) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_verify(
            __serializeAlgo(algo), __serializeKey(key),
            __toB64(signature), __toB64(data),
        );
        return result === true || result === 'true';
    }

    async encrypt(algorithm, key, data) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_encrypt(
            __serializeAlgo(algo), __serializeKey(key), __toB64(data),
        );
        return __fromB64(result);
    }

    async decrypt(algorithm, key, data) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_decrypt(
            __serializeAlgo(algo), __serializeKey(key), __toB64(data),
        );
        return __fromB64(result);
    }

    async deriveBits(algorithm, baseKey, length) {
        const algo = __normalizeAlgo(algorithm);
        const result = __crypto_derive_bits(
            __serializeAlgo(algo), __serializeKey(baseKey), String(length),
        );
        return __fromB64(result);
    }

    async deriveKey(algorithm, baseKey, derivedKeyAlgorithm, extractable, keyUsages) {
        const algo = __normalizeAlgo(algorithm);
        const derivedAlgo = __normalizeAlgo(derivedKeyAlgorithm);
        const result = __crypto_derive_key(
            __serializeAlgo(algo), __serializeKey(baseKey),
            JSON.stringify(derivedAlgo), String(extractable), JSON.stringify(keyUsages),
        );
        return __buildKey(result, extractable, keyUsages);
    }

    async wrapKey(format, key, wrappingKey, wrapAlgorithm) {
        const algo = __normalizeAlgo(wrapAlgorithm);
        const result = __crypto_wrap_key(
            format, __serializeKey(key), __serializeKey(wrappingKey), __serializeAlgo(algo),
        );
        return __fromB64(result);
    }

    async unwrapKey(format, wrappedKey, unwrappingKey, unwrapAlgorithm, unwrappedKeyAlgorithm, extractable, keyUsages) {
        const unwrapAlgo = __normalizeAlgo(unwrapAlgorithm);
        const unwrappedAlgo = __normalizeAlgo(unwrappedKeyAlgorithm);
        const result = __crypto_unwrap_key(
            format, __toB64(wrappedKey), __serializeKey(unwrappingKey),
            __serializeAlgo(unwrapAlgo), JSON.stringify(unwrappedAlgo),
            String(extractable), JSON.stringify(keyUsages),
        );
        return __buildKey(result, extractable, keyUsages);
    }
}

// Set up globalThis.crypto
globalThis.crypto = globalThis.crypto || {};
globalThis.crypto.randomUUID = () => __crypto_random_uuid();
globalThis.crypto.getRandomValues = (arr) => {
    const b64 = __crypto_get_random_values(arr.length);
    const bytes = __buffer_b64_to_bytes(b64);
    const src = new Uint8Array(bytes);
    arr.set(src.subarray(0, arr.length));
    return arr;
};
globalThis.crypto.subtle = new SubtleCrypto();
globalThis.CryptoKey = CryptoKey;
