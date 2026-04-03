use std::io::{Read, Write};

use taiyaki_core::engine::{EngineError, HostCallback, JsValue};

use super::crypto::util::{b64_decode, b64_encode};
use super::require_string_arg;

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__zlib_deflate_raw", Box::new(zlib_deflate_raw)),
        ("__zlib_inflate_raw", Box::new(zlib_inflate_raw)),
        ("__zlib_deflate", Box::new(zlib_deflate)),
        ("__zlib_inflate", Box::new(zlib_inflate)),
        ("__zlib_gzip", Box::new(zlib_gzip)),
        ("__zlib_gunzip", Box::new(zlib_gunzip)),
        ("__zlib_brotli_compress", Box::new(zlib_brotli_compress)),
        ("__zlib_brotli_decompress", Box::new(zlib_brotli_decompress)),
    ]
}

fn zlib_err(msg: impl Into<String>) -> EngineError {
    EngineError::JsException {
        message: msg.into(),
    }
}

fn parse_level(args: &[JsValue]) -> u32 {
    match args.get(1) {
        Some(JsValue::String(s)) => {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(s) {
                v.get("level")
                    .and_then(|l| l.as_i64())
                    .map(|l| if l < 0 { 6 } else { l as u32 })
                    .unwrap_or(6)
            } else {
                6
            }
        }
        _ => 6,
    }
}

// --- Deflate raw (no header) ---

fn zlib_deflate_raw(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_deflate_raw")?;
    let data = b64_decode(data_b64)?;
    let level = parse_level(args);

    let mut encoder =
        flate2::write::DeflateEncoder::new(Vec::new(), flate2::Compression::new(level));
    encoder
        .write_all(&data)
        .map_err(|e| zlib_err(format!("deflateRaw: {e}")))?;
    let compressed = encoder
        .finish()
        .map_err(|e| zlib_err(format!("deflateRaw finish: {e}")))?;
    Ok(JsValue::String(b64_encode(&compressed)))
}

fn zlib_inflate_raw(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_inflate_raw")?;
    let data = b64_decode(data_b64)?;

    let mut decoder = flate2::read::DeflateDecoder::new(&data[..]);
    let mut output = Vec::new();
    decoder
        .read_to_end(&mut output)
        .map_err(|e| zlib_err(format!("inflateRaw: {e}")))?;
    Ok(JsValue::String(b64_encode(&output)))
}

// --- Deflate (zlib format, with zlib header) ---

fn zlib_deflate(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_deflate")?;
    let data = b64_decode(data_b64)?;
    let level = parse_level(args);

    let mut encoder = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::new(level));
    encoder
        .write_all(&data)
        .map_err(|e| zlib_err(format!("deflate: {e}")))?;
    let compressed = encoder
        .finish()
        .map_err(|e| zlib_err(format!("deflate finish: {e}")))?;
    Ok(JsValue::String(b64_encode(&compressed)))
}

fn zlib_inflate(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_inflate")?;
    let data = b64_decode(data_b64)?;

    let mut decoder = flate2::read::ZlibDecoder::new(&data[..]);
    let mut output = Vec::new();
    decoder
        .read_to_end(&mut output)
        .map_err(|e| zlib_err(format!("inflate: {e}")))?;
    Ok(JsValue::String(b64_encode(&output)))
}

// --- Gzip ---

fn zlib_gzip(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_gzip")?;
    let data = b64_decode(data_b64)?;
    let level = parse_level(args);

    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::new(level));
    encoder
        .write_all(&data)
        .map_err(|e| zlib_err(format!("gzip: {e}")))?;
    let compressed = encoder
        .finish()
        .map_err(|e| zlib_err(format!("gzip finish: {e}")))?;
    Ok(JsValue::String(b64_encode(&compressed)))
}

fn zlib_gunzip(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_gunzip")?;
    let data = b64_decode(data_b64)?;

    let mut decoder = flate2::read::GzDecoder::new(&data[..]);
    let mut output = Vec::new();
    decoder
        .read_to_end(&mut output)
        .map_err(|e| zlib_err(format!("gunzip: {e}")))?;
    Ok(JsValue::String(b64_encode(&output)))
}

// --- Brotli ---

fn zlib_brotli_compress(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_brotli_compress")?;
    let data = b64_decode(data_b64)?;

    let mut output = Vec::new();
    {
        let mut writer = brotli::CompressorWriter::new(&mut output, 4096, 6, 22);
        writer
            .write_all(&data)
            .map_err(|e| zlib_err(format!("brotli compress: {e}")))?;
    }
    Ok(JsValue::String(b64_encode(&output)))
}

fn zlib_brotli_decompress(args: &[JsValue]) -> Result<JsValue, EngineError> {
    let data_b64 = require_string_arg(args, 0, "__zlib_brotli_decompress")?;
    let data = b64_decode(data_b64)?;

    let mut decoder = brotli::Decompressor::new(&data[..], 4096);
    let mut output = Vec::new();
    decoder
        .read_to_end(&mut output)
        .map_err(|e| zlib_err(format!("brotli decompress: {e}")))?;
    Ok(JsValue::String(b64_encode(&output)))
}
