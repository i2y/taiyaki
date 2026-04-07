use taiyaki_core::engine::JsValue;

/// Lenient string extraction: coerces any JsValue to String, returns empty on missing.
pub fn require_str(args: &[JsValue], idx: usize) -> String {
    match args.get(idx) {
        Some(JsValue::String(s)) => s.clone(),
        Some(v) => v.coerce_string(),
        None => String::new(),
    }
}
