use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use rquickjs::class::Class;
use rquickjs::function::RustFunction;
use rquickjs::{Persistent, Value};

use super::{EngineError, HostCallback, JsValue, MemoryStats};

impl From<rquickjs::Error> for EngineError {
    fn from(e: rquickjs::Error) -> Self {
        EngineError::JsException {
            message: e.to_string(),
        }
    }
}

impl From<rquickjs::runtime::MemoryUsage> for MemoryStats {
    fn from(u: rquickjs::runtime::MemoryUsage) -> Self {
        Self {
            malloc_size: u.malloc_size,
            memory_used_size: u.memory_used_size,
            atom_count: u.atom_count,
            str_count: u.str_count,
            obj_count: u.obj_count,
            prop_count: u.prop_count,
            js_func_count: u.js_func_count,
            c_func_count: u.c_func_count,
            array_count: u.array_count,
        }
    }
}

/// Evaluates code and extracts exception messages on error.
pub(crate) fn eval_with_catch<'js>(
    ctx: &rquickjs::Ctx<'js>,
    code: &str,
) -> Result<JsValue, EngineError> {
    match ctx.eval::<Value<'js>, _>(code) {
        Ok(value) => convert_value(ctx, &value),
        Err(err) => {
            let message = if err.is_exception() {
                if let Some(exc) = ctx.catch().as_exception() {
                    exc.to_string()
                } else {
                    err.to_string()
                }
            } else {
                err.to_string()
            };
            Err(EngineError::JsException { message })
        }
    }
}

/// Converts primitive rquickjs values to JsValue. Returns `None` for compound types.
pub(crate) fn convert_primitive(value: &Value<'_>) -> Result<Option<JsValue>, EngineError> {
    if value.is_undefined() {
        return Ok(Some(JsValue::Undefined));
    }
    if value.is_null() {
        return Ok(Some(JsValue::Null));
    }
    if value.is_bool() {
        return Ok(Some(JsValue::Bool(value.as_bool().unwrap_or(false))));
    }
    if value.is_int() {
        return Ok(Some(JsValue::Number(value.as_int().unwrap_or(0) as f64)));
    }
    if value.is_float() {
        return Ok(Some(JsValue::Number(value.as_float().unwrap_or(0.0))));
    }
    if let Some(s) = value.as_string() {
        return Ok(Some(JsValue::String(s.to_string()?)));
    }
    Ok(None)
}

/// Converts rquickjs Value → JsValue for eval (Object/Array serialized as JSON strings).
pub(crate) fn convert_value<'js>(
    ctx: &rquickjs::Ctx<'js>,
    value: &Value<'js>,
) -> Result<JsValue, EngineError> {
    if let Some(prim) = convert_primitive(value)? {
        return Ok(prim);
    }
    if value.is_function() {
        return Ok(JsValue::Function);
    }
    if value.is_array() {
        return Ok(JsValue::Array(json_stringify(ctx, value)?));
    }
    if value.is_object() {
        return Ok(JsValue::Object(json_stringify(ctx, value)?));
    }
    Ok(JsValue::Undefined)
}

pub(crate) fn json_stringify<'js>(
    ctx: &rquickjs::Ctx<'js>,
    value: &Value<'js>,
) -> Result<String, EngineError> {
    match ctx.json_stringify(value.clone())? {
        Some(s) => Ok(s.to_string()?),
        None => Ok("null".to_string()),
    }
}

/// Converts JsValue → rquickjs Value. Handle variants are restored via the provided closure.
pub(crate) fn jsvalue_to_qjs<'js>(
    ctx: &rquickjs::Ctx<'js>,
    val: &JsValue,
    restore_handle: impl Fn(u64) -> Result<Value<'js>, EngineError>,
) -> Result<Value<'js>, EngineError> {
    match val {
        JsValue::Undefined => Ok(Value::new_undefined(ctx.clone())),
        JsValue::Null => Ok(Value::new_null(ctx.clone())),
        JsValue::Bool(b) => Ok(Value::new_bool(ctx.clone(), *b)),
        JsValue::Number(n) => Ok(Value::new_float(ctx.clone(), *n)),
        JsValue::String(s) => {
            let js_str = rquickjs::String::from_str(ctx.clone(), s)?;
            Ok(js_str.into_value())
        }
        JsValue::Object(json) | JsValue::Array(json) => Ok(ctx.json_parse(json.as_str())?),
        JsValue::ObjectHandle(id) | JsValue::ArrayHandle(id) | JsValue::FunctionHandle(id) => {
            restore_handle(*id)
        }
        JsValue::Function => Err(EngineError::TypeError(
            "Cannot convert opaque Function marker to a JS value".to_string(),
        )),
    }
}

/// Converts rquickjs Value → JsValue, storing compound types as persistent handles
/// via the provided closure.
pub(crate) fn qjs_to_jsvalue_handle<'js>(
    value: Value<'js>,
    store_persistent: impl Fn(Value<'js>) -> u64,
) -> Result<JsValue, EngineError> {
    if let Some(prim) = convert_primitive(&value)? {
        return Ok(prim);
    }
    if value.is_function() {
        let id = store_persistent(value);
        return Ok(JsValue::FunctionHandle(id));
    }
    if value.is_array() {
        let id = store_persistent(value);
        return Ok(JsValue::ArrayHandle(id));
    }
    if value.is_object() {
        let id = store_persistent(value);
        return Ok(JsValue::ObjectHandle(id));
    }
    Ok(JsValue::Undefined)
}

/// Creates a host function closure that bridges Rust HostCallback into rquickjs.
pub(crate) fn make_host_fn<'js>(
    cb: Rc<HostCallback>,
    handles: Rc<RefCell<HashMap<u64, Persistent<Value<'static>>>>>,
) -> impl for<'a> Fn(rquickjs::function::Params<'a, 'js>) -> rquickjs::Result<Value<'js>> + 'js {
    move |params| {
        let ctx = params.ctx();

        let mut js_args = Vec::with_capacity(params.len());
        for i in 0..params.len() {
            if let Some(v) = params.arg(i) {
                js_args.push(
                    convert_value(ctx, &v)
                        .map_err(|_| rquickjs::Error::new_from_js("value", "JsValue"))?,
                );
            }
        }

        let result = (cb)(&js_args).map_err(|e| {
            let _ = ctx.throw(
                rquickjs::String::from_str(ctx.clone(), &e.to_string())
                    .unwrap()
                    .into_value(),
            );
            rquickjs::Error::Exception
        })?;

        result_to_qjs(ctx, result, &handles)
    }
}

/// Converts a JsValue result from a host callback back to a rquickjs Value.
/// Used by make_host_fn where we can't call engine methods due to lifetime constraints.
pub(crate) fn result_to_qjs<'js>(
    ctx: &rquickjs::Ctx<'js>,
    result: JsValue,
    handles: &RefCell<HashMap<u64, Persistent<Value<'static>>>>,
) -> rquickjs::Result<Value<'js>> {
    match result {
        JsValue::Undefined => Ok(Value::new_undefined(ctx.clone())),
        JsValue::Null => Ok(Value::new_null(ctx.clone())),
        JsValue::Bool(b) => Ok(Value::new_bool(ctx.clone(), b)),
        JsValue::Number(n) => Ok(Value::new_float(ctx.clone(), n)),
        JsValue::String(s) => Ok(rquickjs::String::from_str(ctx.clone(), &s)?.into_value()),
        JsValue::Object(json) | JsValue::Array(json) => ctx.json_parse(json.as_str()),
        JsValue::ObjectHandle(id) | JsValue::ArrayHandle(id) | JsValue::FunctionHandle(id) => {
            let store = handles.borrow();
            let persistent = store
                .get(&id)
                .ok_or_else(|| rquickjs::Error::new_from_js("handle", "Value"))?;
            persistent.clone().restore(ctx)
        }
        JsValue::Function => Err(rquickjs::Error::new_from_js("Function", "Value")),
    }
}

/// Registers a host function as a global in the given context.
pub(crate) fn register_host_fn<'js>(
    ctx: &rquickjs::Ctx<'js>,
    name: &str,
    cb: Rc<HostCallback>,
    handles: Rc<RefCell<HashMap<u64, Persistent<Value<'static>>>>>,
) -> Result<(), EngineError> {
    let host_fn = make_host_fn(cb, handles);
    let rust_fn = RustFunction(Box::new(host_fn));
    let func = Class::instance(ctx.clone(), rust_fn)?;
    debug_assert!(func.is_function());
    ctx.globals().set(name, func)?;
    Ok(())
}
