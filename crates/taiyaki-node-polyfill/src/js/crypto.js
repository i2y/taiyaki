export function randomUUID() {
    return __crypto_random_uuid();
}

export function getRandomValues(typedArray) {
    const b64 = __crypto_get_random_values(typedArray.length);
    const bytes = __buffer_b64_to_bytes(b64);
    const src = new Uint8Array(bytes);
    typedArray.set(src.subarray(0, typedArray.length));
    return typedArray;
}

export const subtle = globalThis.crypto.subtle;

// --- Node.js crypto API ---

function _toB64(data) {
    if (typeof data === 'string') {
        // Encode string as UTF-8 bytes then base64
        const enc = new TextEncoder();
        const bytes = enc.encode(data);
        return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
    }
    let bytes;
    if (data instanceof ArrayBuffer) bytes = new Uint8Array(data);
    else if (ArrayBuffer.isView(data)) bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    else bytes = new Uint8Array(data);
    return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
}

function _fromB64(b64) {
    return new Uint8Array(__buffer_b64_to_bytes(b64));
}

function _hexEncode(bytes) {
    return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

function _hexDecode(hex) {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < hex.length; i += 2) {
        bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
    }
    return bytes;
}

function _mergeChunksB64(chunks) {
    if (chunks.length === 1) return chunks[0];
    const arrays = chunks.map(c => _fromB64(c));
    const total = arrays.reduce((s, a) => s + a.length, 0);
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const a of arrays) { merged.set(a, offset); offset += a.length; }
    return _toB64(merged);
}

export function createHash(algorithm) {
    const chunks = [];
    return {
        update(data) {
            // Always convert to base64 immediately
            chunks.push(_toB64(data));
            return this;
        },
        digest(encoding) {
            const combinedB64 = _mergeChunksB64(chunks);
            const resultB64 = __crypto_create_hash(algorithm, combinedB64);
            const bytes = _fromB64(resultB64);
            if (encoding === 'hex') return _hexEncode(bytes);
            if (encoding === 'base64') return resultB64;
            return bytes;
        },
    };
}

export function createHmac(algorithm, key) {
    const keyB64 = _toB64(key);
    const chunks = [];
    return {
        update(data) {
            chunks.push(_toB64(data));
            return this;
        },
        digest(encoding) {
            const combinedB64 = _mergeChunksB64(chunks);
            const resultB64 = __crypto_create_hmac(algorithm, keyB64, combinedB64);
            const bytes = _fromB64(resultB64);
            if (encoding === 'hex') return _hexEncode(bytes);
            if (encoding === 'base64') return resultB64;
            return bytes;
        },
    };
}

export function pbkdf2Sync(password, salt, iterations, keylen, digest) {
    const passB64 = _toB64(password);
    const saltB64 = _toB64(salt);
    const resultB64 = __crypto_pbkdf2_sync(passB64, saltB64, String(iterations), String(keylen), digest);
    return _fromB64(resultB64);
}

export function pbkdf2(password, salt, iterations, keylen, digest, callback) {
    try {
        const result = pbkdf2Sync(password, salt, iterations, keylen, digest);
        if (typeof callback === 'function') {
            Promise.resolve().then(() => callback(null, result));
        }
    } catch (err) {
        if (typeof callback === 'function') {
            Promise.resolve().then(() => callback(err));
        }
    }
}

export function scryptSync(password, salt, keylen, options) {
    const passB64 = _toB64(password);
    const saltB64 = _toB64(salt);
    const optStr = options ? JSON.stringify(options) : '{}';
    const resultB64 = __crypto_scrypt_sync(passB64, saltB64, String(keylen), optStr);
    return _fromB64(resultB64);
}

export function createCipheriv(algorithm, key, iv) {
    const keyB64 = _toB64(key);
    const ivB64 = _toB64(iv);
    const chunks = [];
    let _aad = '';
    return {
        setAAD(aad) { _aad = _toB64(aad); return this; },
        update(data, inputEncoding, outputEncoding) {
            chunks.push({ data, inputEncoding, outputEncoding });
            return '';
        },
        final(outputEncoding) {
            // Concatenate all input data
            let allData = '';
            for (const c of chunks) {
                if (typeof c.data === 'string') {
                    if (c.inputEncoding === 'hex') {
                        allData += c.data; // will be hex-decoded below
                    } else {
                        allData += c.data;
                    }
                }
            }
            let dataB64;
            if (chunks.length > 0 && chunks[0].inputEncoding === 'hex') {
                dataB64 = _toB64(_hexDecode(allData));
            } else {
                dataB64 = _toB64(allData);
            }
            const resultStr = __crypto_cipher('encrypt', algorithm, keyB64, ivB64, dataB64, _aad, '');
            const result = JSON.parse(resultStr);
            const bytes = _fromB64(result.data);
            this._authTag = result.authTag ? _fromB64(result.authTag) : null;
            const enc = outputEncoding || (chunks[0] && chunks[0].outputEncoding);
            if (enc === 'hex') return _hexEncode(bytes);
            if (enc === 'base64') return result.data;
            return bytes;
        },
        getAuthTag() { return this._authTag; },
    };
}

export function createDecipheriv(algorithm, key, iv) {
    const keyB64 = _toB64(key);
    const ivB64 = _toB64(iv);
    const chunks = [];
    let _aad = '';
    let _authTagB64 = '';
    return {
        setAAD(aad) { _aad = _toB64(aad); return this; },
        setAuthTag(tag) { _authTagB64 = _toB64(tag); return this; },
        update(data, inputEncoding, outputEncoding) {
            chunks.push({ data, inputEncoding, outputEncoding });
            return '';
        },
        final(outputEncoding) {
            let allData = '';
            for (const c of chunks) {
                allData += typeof c.data === 'string' ? c.data : '';
            }
            let dataB64;
            if (chunks.length > 0 && chunks[0].inputEncoding === 'hex') {
                dataB64 = _toB64(_hexDecode(allData));
            } else {
                dataB64 = _toB64(allData);
            }
            const resultStr = __crypto_cipher('decrypt', algorithm, keyB64, ivB64, dataB64, _aad, _authTagB64);
            const result = JSON.parse(resultStr);
            const bytes = _fromB64(result.data);
            const enc = outputEncoding || (chunks[0] && chunks[0].outputEncoding);
            if (enc === 'utf8' || enc === 'utf-8') return new TextDecoder().decode(bytes);
            if (enc === 'hex') return _hexEncode(bytes);
            if (enc === 'base64') return result.data;
            return bytes;
        },
    };
}

export default {
    randomUUID, getRandomValues, subtle,
    createHash, createHmac,
    pbkdf2, pbkdf2Sync, scryptSync,
    createCipheriv, createDecipheriv,
};
