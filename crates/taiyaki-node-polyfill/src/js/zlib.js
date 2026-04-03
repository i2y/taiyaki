import { Transform } from 'stream';

// --- base64 helpers (reuse Buffer host functions) ---

function _toB64(data) {
    if (typeof data === 'string') {
        var enc = new TextEncoder();
        var bytes = enc.encode(data);
        return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
    }
    var bytes;
    if (data instanceof ArrayBuffer) bytes = new Uint8Array(data);
    else if (ArrayBuffer.isView(data)) bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    else if (data && data._data) bytes = new Uint8Array(data._data); // Buffer
    else bytes = new Uint8Array(data);
    return __buffer_bytes_to_b64(JSON.stringify(Array.from(bytes)));
}

function _fromB64(b64) {
    return new Uint8Array(__buffer_b64_to_bytes(b64));
}

// --- One-shot functions ---

function _oneShot(rustFn, data, opts, cb) {
    if (typeof opts === 'function') { cb = opts; opts = undefined; }
    try {
        var b64In = _toB64(data);
        var optsJson = opts ? JSON.stringify(opts) : '{}';
        var b64Out = rustFn(b64In, optsJson);
        var result = _fromB64(b64Out);
        if (cb) { queueMicrotask(function() { cb(null, result); }); return; }
        return Promise.resolve(result);
    } catch (e) {
        var err = e instanceof Error ? e : new Error(String(e));
        if (cb) { queueMicrotask(function() { cb(err); }); return; }
        return Promise.reject(err);
    }
}

function _oneShotSync(rustFn, data, opts) {
    var b64In = _toB64(data);
    var optsJson = opts ? JSON.stringify(opts) : '{}';
    var b64Out = rustFn(b64In, optsJson);
    return _fromB64(b64Out);
}

// --- Async / callback API ---

export function gzip(data, opts, cb) { return _oneShot(__zlib_gzip, data, opts, cb); }
export function gunzip(data, opts, cb) { return _oneShot(__zlib_gunzip, data, opts, cb); }
export function deflate(data, opts, cb) { return _oneShot(__zlib_deflate, data, opts, cb); }
export function inflate(data, opts, cb) { return _oneShot(__zlib_inflate, data, opts, cb); }
export function deflateRaw(data, opts, cb) { return _oneShot(__zlib_deflate_raw, data, opts, cb); }
export function inflateRaw(data, opts, cb) { return _oneShot(__zlib_inflate_raw, data, opts, cb); }
export function brotliCompress(data, opts, cb) { return _oneShot(__zlib_brotli_compress, data, opts, cb); }
export function brotliDecompress(data, opts, cb) { return _oneShot(__zlib_brotli_decompress, data, opts, cb); }

// --- Sync API ---

export function gzipSync(data, opts) { return _oneShotSync(__zlib_gzip, data, opts); }
export function gunzipSync(data, opts) { return _oneShotSync(__zlib_gunzip, data, opts); }
export function deflateSync(data, opts) { return _oneShotSync(__zlib_deflate, data, opts); }
export function inflateSync(data, opts) { return _oneShotSync(__zlib_inflate, data, opts); }
export function deflateRawSync(data, opts) { return _oneShotSync(__zlib_deflate_raw, data, opts); }
export function inflateRawSync(data, opts) { return _oneShotSync(__zlib_inflate_raw, data, opts); }
export function brotliCompressSync(data, opts) { return _oneShotSync(__zlib_brotli_compress, data, opts); }
export function brotliDecompressSync(data, opts) { return _oneShotSync(__zlib_brotli_decompress, data, opts); }

// --- Transform stream factories ---

function _createTransform(rustFn, opts) {
    var optsJson = opts ? JSON.stringify(opts) : '{}';
    return new Transform({
        transform: function(chunk, _enc, cb) {
            try {
                var b64In = _toB64(chunk);
                var b64Out = rustFn(b64In, optsJson);
                cb(null, _fromB64(b64Out));
            } catch (e) { cb(e instanceof Error ? e : new Error(String(e))); }
        }
    });
}

export function createGzip(opts) { return _createTransform(__zlib_gzip, opts); }
export function createGunzip(opts) { return _createTransform(__zlib_gunzip, opts); }
export function createDeflate(opts) { return _createTransform(__zlib_deflate, opts); }
export function createInflate(opts) { return _createTransform(__zlib_inflate, opts); }
export function createDeflateRaw(opts) { return _createTransform(__zlib_deflate_raw, opts); }
export function createInflateRaw(opts) { return _createTransform(__zlib_inflate_raw, opts); }
export function createBrotliCompress(opts) { return _createTransform(__zlib_brotli_compress, opts); }
export function createBrotliDecompress(opts) { return _createTransform(__zlib_brotli_decompress, opts); }

// --- Constants ---

export var constants = {
    Z_NO_COMPRESSION: 0,
    Z_BEST_SPEED: 1,
    Z_BEST_COMPRESSION: 9,
    Z_DEFAULT_COMPRESSION: -1,
    Z_FILTERED: 1,
    Z_HUFFMAN_ONLY: 2,
    Z_RLE: 3,
    Z_FIXED: 4,
    Z_DEFAULT_STRATEGY: 0,
    Z_NO_FLUSH: 0,
    Z_PARTIAL_FLUSH: 1,
    Z_SYNC_FLUSH: 2,
    Z_FULL_FLUSH: 3,
    Z_FINISH: 4,
    Z_BLOCK: 5,
    Z_TREES: 6,
    Z_OK: 0,
    Z_STREAM_END: 1,
    Z_NEED_DICT: 2,
    Z_ERRNO: -1,
    Z_STREAM_ERROR: -2,
    Z_DATA_ERROR: -3,
    Z_MEM_ERROR: -4,
    Z_BUF_ERROR: -5,
    Z_VERSION_ERROR: -6,
    BROTLI_OPERATION_PROCESS: 0,
    BROTLI_OPERATION_FLUSH: 1,
    BROTLI_OPERATION_FINISH: 2,
};

export default {
    gzip, gunzip, deflate, inflate, deflateRaw, inflateRaw,
    brotliCompress, brotliDecompress,
    gzipSync, gunzipSync, deflateSync, inflateSync,
    deflateRawSync, inflateRawSync, brotliCompressSync, brotliDecompressSync,
    createGzip, createGunzip, createDeflate, createInflate,
    createDeflateRaw, createInflateRaw, createBrotliCompress, createBrotliDecompress,
    constants,
};
