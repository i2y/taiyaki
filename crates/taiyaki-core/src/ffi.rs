use std::cell::RefCell;
use std::ffi::{CString, c_char, c_void};
use std::panic::{self, AssertUnwindSafe};
use std::ptr;

use crate::engine::{EngineError, JsEngine, JsValue, MemoryStats};
use crate::transpiler::Transpiler;

#[cfg(feature = "quickjs")]
use crate::engine::quickjs_backend::QuickJsEngine;

#[cfg(feature = "jsc")]
use crate::engine::jsc_backend::JscEngine;

thread_local! {
    static LAST_ERROR: RefCell<Option<CString>> = const { RefCell::new(None) };
}

fn set_last_error(msg: &str) {
    LAST_ERROR.with(|e| {
        *e.borrow_mut() = CString::new(msg).ok();
    });
}

fn clear_last_error() {
    LAST_ERROR.with(|e| {
        *e.borrow_mut() = None;
    });
}

macro_rules! ffi_guard {
    ($null_val:expr, $body:expr) => {{
        clear_last_error();
        match panic::catch_unwind(AssertUnwindSafe(|| $body)) {
            Ok(result) => result,
            Err(_) => {
                set_last_error("Internal panic in taiyaki");
                $null_val
            }
        }
    }};
}

#[cfg(feature = "quickjs")]
type EngineImpl = QuickJsEngine;

#[cfg(feature = "jsc")]
type EngineImpl = JscEngine;

pub struct LibtsRuntime {
    engine: EngineImpl,
    transpiler: Transpiler,
}

pub struct LibtsValue {
    inner: JsValue,
    cached_string: Option<CString>,
    engine: Option<*const EngineImpl>,
}

#[repr(C)]
pub enum LibtsType {
    Undefined = 0,
    Null = 1,
    Bool = 2,
    Number = 3,
    String = 4,
    Object = 5,
    Array = 6,
    Function = 7,
}

/// C callback type for host functions.
pub type LibtsHostFn = unsafe extern "C" fn(
    args: *const *const LibtsValue,
    argc: usize,
    user_data: *mut c_void,
) -> *mut LibtsValue;

/// Wraps a JsValue into a heap-allocated LibtsValue (no engine handle).
fn wrap_value(val: JsValue) -> *mut LibtsValue {
    Box::into_raw(Box::new(LibtsValue {
        inner: val,
        cached_string: None,
        engine: None,
    }))
}

/// Wraps a JsValue into a heap-allocated LibtsValue, storing engine pointer for handle variants.
fn wrap_handle_value(val: JsValue, engine: &EngineImpl) -> *mut LibtsValue {
    let needs_engine = matches!(
        val,
        JsValue::ObjectHandle(_) | JsValue::ArrayHandle(_) | JsValue::FunctionHandle(_)
    );
    Box::into_raw(Box::new(LibtsValue {
        inner: val,
        cached_string: None,
        engine: if needs_engine {
            Some(engine as *const EngineImpl)
        } else {
            None
        },
    }))
}

fn extract_handle(val: &LibtsValue) -> Option<u64> {
    val.inner.handle_id()
}

/// Returns the last error message, or NULL if no error.
/// The returned pointer is valid until the next taiyaki call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_get_last_error() -> *const c_char {
    LAST_ERROR.with(|e| match e.borrow().as_ref() {
        Some(msg) => msg.as_ptr(),
        None => ptr::null(),
    })
}

/// Creates a new runtime. Returns NULL on failure.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_runtime_new() -> *mut LibtsRuntime {
    ffi_guard!(ptr::null_mut(), {
        match EngineImpl::new() {
            Ok(engine) => Box::into_raw(Box::new(LibtsRuntime {
                engine,
                transpiler: Transpiler::new(),
            })),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Frees a runtime. NULL-safe.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_runtime_free(rt: *mut LibtsRuntime) {
    if !rt.is_null() {
        let _ = panic::catch_unwind(AssertUnwindSafe(|| unsafe {
            drop(Box::from_raw(rt));
        }));
    }
}

/// # Safety
/// `code` must point to at least `len` bytes of valid memory.
/// The returned `&str` lifetime depends on caller guarantees.
unsafe fn extract_str<'a>(code: *const c_char, len: usize) -> Result<&'a str, ()> {
    let bytes = unsafe { std::slice::from_raw_parts(code as *const u8, len) };
    std::str::from_utf8(bytes).map_err(|_| ())
}

/// Shared eval implementation.
fn eval_inner(rt: &LibtsRuntime, code: &str) -> Result<JsValue, String> {
    rt.engine.eval(code).map_err(|e| e.to_string())
}

/// Evaluates JavaScript code.
/// `code` is a UTF-8 string of length `len` (no NUL terminator required).
/// Returns a pointer to LibtsValue on success (caller frees with taiyaki_value_free).
/// Returns NULL on failure.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_eval(
    rt: *mut LibtsRuntime,
    code: *const c_char,
    len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || code.is_null() {
            set_last_error("Null argument passed to taiyaki_eval");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let code_str = match unsafe { extract_str(code, len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in code");
                return ptr::null_mut();
            }
        };
        match eval_inner(rt, code_str) {
            Ok(val) => wrap_value(val),
            Err(msg) => {
                set_last_error(&msg);
                ptr::null_mut()
            }
        }
    })
}

/// Evaluates TypeScript code (strips type annotations before execution).
/// `code` is a UTF-8 string of length `len`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_eval_ts(
    rt: *mut LibtsRuntime,
    code: *const c_char,
    len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || code.is_null() {
            set_last_error("Null argument passed to taiyaki_eval_ts");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let ts_code = match unsafe { extract_str(code, len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in code");
                return ptr::null_mut();
            }
        };
        let js_code = match rt.transpiler.strip_types(ts_code) {
            Ok(js) => js,
            Err(e) => {
                set_last_error(&e.to_string());
                return ptr::null_mut();
            }
        };
        match eval_inner(rt, &js_code) {
            Ok(val) => wrap_value(val),
            Err(msg) => {
                set_last_error(&msg);
                ptr::null_mut()
            }
        }
    })
}

/// Returns the type of a value.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_type(val: *const LibtsValue) -> LibtsType {
    if val.is_null() {
        return LibtsType::Undefined;
    }
    let val = unsafe { &*val };
    match &val.inner {
        JsValue::Undefined => LibtsType::Undefined,
        JsValue::Null => LibtsType::Null,
        JsValue::Bool(_) => LibtsType::Bool,
        JsValue::Number(_) => LibtsType::Number,
        JsValue::String(_) => LibtsType::String,
        JsValue::Object(_) | JsValue::ObjectHandle(_) => LibtsType::Object,
        JsValue::Array(_) | JsValue::ArrayHandle(_) => LibtsType::Array,
        JsValue::Function | JsValue::FunctionHandle(_) => LibtsType::Function,
    }
}

/// Returns the value as a number. Returns 0.0 if not a number.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_as_number(val: *const LibtsValue) -> f64 {
    if val.is_null() {
        return 0.0;
    }
    let val = unsafe { &*val };
    match &val.inner {
        JsValue::Number(n) => *n,
        _ => 0.0,
    }
}

/// Returns the value as a boolean (1 or 0). Returns 0 if not a boolean.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_as_bool(val: *const LibtsValue) -> i32 {
    if val.is_null() {
        return 0;
    }
    let val = unsafe { &*val };
    match &val.inner {
        JsValue::Bool(b) => *b as i32,
        _ => 0,
    }
}

/// Returns the value as a string.
/// The returned pointer is valid until the next taiyaki_value_as_string call
/// on the same value, or until taiyaki_value_free.
/// If `out_len` is non-NULL, writes the string length.
/// Returns NULL if not a string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_as_string(
    val: *mut LibtsValue,
    out_len: *mut usize,
) -> *const c_char {
    if val.is_null() {
        return ptr::null();
    }
    let val = unsafe { &mut *val };

    if val.cached_string.is_none() {
        let s = match &val.inner {
            JsValue::String(s) => s.as_str(),
            JsValue::Object(s) | JsValue::Array(s) => s.as_str(),
            _ => return ptr::null(),
        };
        let cstr = match CString::new(s) {
            Ok(cs) => cs,
            Err(_) => return ptr::null(),
        };
        val.cached_string = Some(cstr);
    }

    let cached = val.cached_string.as_ref().unwrap();
    if !out_len.is_null() {
        unsafe {
            *out_len = cached.as_bytes().len();
        }
    }
    cached.as_ptr()
}

/// Frees a LibtsValue. NULL-safe.
/// For handle values, also releases the engine-side handle.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_free(val: *mut LibtsValue) {
    if !val.is_null() {
        let _ = panic::catch_unwind(AssertUnwindSafe(|| {
            let val = unsafe { Box::from_raw(val) };
            if let (Some(engine_ptr), Some(id)) = (val.engine, extract_handle(&val)) {
                let engine = unsafe { &*engine_ptr };
                engine.drop_handle(id);
            }
        }));
    }
}

// --- Value creation ---

/// Creates an f64 value.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_number(n: f64) -> *mut LibtsValue {
    wrap_value(JsValue::Number(n))
}

/// Creates a string value. `s` is a UTF-8 string of length `len`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_string(s: *const c_char, len: usize) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if s.is_null() {
            set_last_error("Null argument passed to taiyaki_value_string");
            return ptr::null_mut();
        }
        let str_val = match unsafe { extract_str(s, len) } {
            Ok(v) => v,
            Err(()) => {
                set_last_error("Invalid UTF-8 in string");
                return ptr::null_mut();
            }
        };
        wrap_value(JsValue::String(str_val.to_string()))
    })
}

/// Creates a boolean value. 0 maps to false, anything else to true.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_bool(b: i32) -> *mut LibtsValue {
    wrap_value(JsValue::Bool(b != 0))
}

/// Creates a null value.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_null() -> *mut LibtsValue {
    wrap_value(JsValue::Null)
}

/// Creates an undefined value.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_value_undefined() -> *mut LibtsValue {
    wrap_value(JsValue::Undefined)
}

// --- Object operations ---

/// Creates an empty JS object.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_object_new(rt: *mut LibtsRuntime) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() {
            set_last_error("Null runtime");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        match rt.engine.object_new() {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Sets a property on an object. Returns 0 on success, -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_object_set(
    rt: *mut LibtsRuntime,
    obj: *const LibtsValue,
    key: *const c_char,
    key_len: usize,
    val: *const LibtsValue,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || obj.is_null() || key.is_null() || val.is_null() {
            set_last_error("Null argument passed to taiyaki_object_set");
            return -1;
        }
        let rt = unsafe { &*rt };
        let obj = unsafe { &*obj };
        let val = unsafe { &*val };
        let key_str = match unsafe { extract_str(key, key_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in key");
                return -1;
            }
        };
        let handle = match extract_handle(obj) {
            Some(h) => h,
            None => {
                set_last_error("Value is not an object handle");
                return -1;
            }
        };
        match rt.engine.object_set(handle, key_str, &val.inner) {
            Ok(()) => 0,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}

/// Gets a property from an object.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_object_get(
    rt: *mut LibtsRuntime,
    obj: *const LibtsValue,
    key: *const c_char,
    key_len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || obj.is_null() || key.is_null() {
            set_last_error("Null argument passed to taiyaki_object_get");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let obj = unsafe { &*obj };
        let key_str = match unsafe { extract_str(key, key_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in key");
                return ptr::null_mut();
            }
        };
        let handle = match extract_handle(obj) {
            Some(h) => h,
            None => {
                set_last_error("Value is not an object handle");
                return ptr::null_mut();
            }
        };
        match rt.engine.object_get(handle, key_str) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

// --- Array operations ---

/// Creates an empty JS array.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_array_new(rt: *mut LibtsRuntime) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() {
            set_last_error("Null runtime");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        match rt.engine.array_new() {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Pushes an element onto an array. Returns 0 on success, -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_array_push(
    rt: *mut LibtsRuntime,
    arr: *const LibtsValue,
    val: *const LibtsValue,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || arr.is_null() || val.is_null() {
            set_last_error("Null argument passed to taiyaki_array_push");
            return -1;
        }
        let rt = unsafe { &*rt };
        let arr = unsafe { &*arr };
        let val = unsafe { &*val };
        let handle = match extract_handle(arr) {
            Some(h) => h,
            None => {
                set_last_error("Value is not an array handle");
                return -1;
            }
        };
        match rt.engine.array_push(handle, &val.inner) {
            Ok(()) => 0,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}

/// Gets an element from an array by index.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_array_get(
    rt: *mut LibtsRuntime,
    arr: *const LibtsValue,
    index: u32,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || arr.is_null() {
            set_last_error("Null argument passed to taiyaki_array_get");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let arr = unsafe { &*arr };
        let handle = match extract_handle(arr) {
            Some(h) => h,
            None => {
                set_last_error("Value is not an array handle");
                return ptr::null_mut();
            }
        };
        match rt.engine.array_get(handle, index) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Returns the length of an array. Returns -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_array_length(
    rt: *mut LibtsRuntime,
    arr: *const LibtsValue,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || arr.is_null() {
            set_last_error("Null argument passed to taiyaki_array_length");
            return -1;
        }
        let rt = unsafe { &*rt };
        let arr = unsafe { &*arr };
        let handle = match extract_handle(arr) {
            Some(h) => h,
            None => {
                set_last_error("Value is not an array handle");
                return -1;
            }
        };
        match rt.engine.array_length(handle) {
            Ok(len) => len as i32,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}

// --- Function calling ---

/// Calls a JS function. `func` must be a FunctionHandle.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_call(
    rt: *mut LibtsRuntime,
    func: *const LibtsValue,
    args: *const *const LibtsValue,
    argc: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || func.is_null() {
            set_last_error("Null argument passed to taiyaki_call");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let func = unsafe { &*func };
        let func_handle = match extract_handle(func) {
            Some(h) => h,
            None => {
                set_last_error("Value is not a function handle");
                return ptr::null_mut();
            }
        };

        let mut js_args = Vec::with_capacity(argc);
        if argc > 0 && !args.is_null() {
            for i in 0..argc {
                let arg_ptr = unsafe { *args.add(i) };
                if arg_ptr.is_null() {
                    js_args.push(JsValue::Undefined);
                } else {
                    let arg = unsafe { &*arg_ptr };
                    js_args.push(arg.inner.clone());
                }
            }
        }

        match rt.engine.call_function(func_handle, &js_args) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

// --- JSON bridge ---

/// Serializes a handle value to a JSON string.
/// Returns a String-typed LibtsValue.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_to_json(
    rt: *mut LibtsRuntime,
    val: *const LibtsValue,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || val.is_null() {
            set_last_error("Null argument passed to taiyaki_to_json");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let val = unsafe { &*val };
        let handle = match extract_handle(val) {
            Some(h) => h,
            None => {
                set_last_error("Value is not a handle");
                return ptr::null_mut();
            }
        };
        match rt.engine.to_json(handle) {
            Ok(json) => wrap_value(JsValue::String(json)),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Parses a JSON string and returns a handle value.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_from_json(
    rt: *mut LibtsRuntime,
    json: *const c_char,
    len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || json.is_null() {
            set_last_error("Null argument passed to taiyaki_from_json");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let json_str = match unsafe { extract_str(json, len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in JSON");
                return ptr::null_mut();
            }
        };
        match rt.engine.parse_json(json_str) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

// --- Host function registration ---

/// Registers a host function as a JS global. Returns 0 on success, -1 on error.
/// `name` is a UTF-8 string of length `name_len`.
/// `callback` is a C function pointer; `user_data` is passed through to the callback.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_register_fn(
    rt: *mut LibtsRuntime,
    name: *const c_char,
    name_len: usize,
    callback: LibtsHostFn,
    user_data: *mut c_void,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_register_fn");
            return -1;
        }
        let rt = unsafe { &mut *rt };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return -1;
            }
        };

        let user_data_ptr = user_data as usize;

        type HostFn = Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>;
        let rust_callback: HostFn = Box::new(move |args: &[JsValue]| {
            let c_args: Vec<*mut LibtsValue> = args.iter().map(|a| wrap_value(a.clone())).collect();
            let c_arg_ptrs: Vec<*const LibtsValue> =
                c_args.iter().map(|p| *p as *const LibtsValue).collect();

            let result_ptr = unsafe {
                callback(
                    c_arg_ptrs.as_ptr(),
                    c_arg_ptrs.len(),
                    user_data_ptr as *mut c_void,
                )
            };

            // Free temporary LibtsValues (not handle values, so no engine needed)
            for ptr in c_args {
                unsafe {
                    drop(Box::from_raw(ptr));
                }
            }

            if result_ptr.is_null() {
                Ok(JsValue::Undefined)
            } else {
                let result_box = unsafe { Box::from_raw(result_ptr) };
                Ok(result_box.inner)
            }
        });

        match rt.engine.register_global_fn(name_str, rust_callback) {
            Ok(()) => 0,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}

// --- Resource limits ---

/// Sets the memory limit in bytes. 0 means unlimited.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_set_memory_limit(rt: *mut LibtsRuntime, bytes: usize) {
    ffi_guard!((), {
        if rt.is_null() {
            return;
        }
        let rt = unsafe { &*rt };
        rt.engine.set_memory_limit(bytes);
    })
}

/// Sets the maximum stack size in bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_set_max_stack_size(rt: *mut LibtsRuntime, bytes: usize) {
    ffi_guard!((), {
        if rt.is_null() {
            return;
        }
        let rt = unsafe { &*rt };
        rt.engine.set_max_stack_size(bytes);
    })
}

/// Sets an execution timeout in milliseconds. Uses the interrupt handler.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_set_execution_timeout(rt: *mut LibtsRuntime, milliseconds: u64) {
    ffi_guard!((), {
        if rt.is_null() {
            return;
        }
        let rt = unsafe { &*rt };
        rt.engine
            .set_execution_timeout(std::time::Duration::from_millis(milliseconds));
    })
}

/// Returns memory usage statistics. Returns 0 on success, -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_memory_usage(rt: *mut LibtsRuntime, out: *mut MemoryStats) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || out.is_null() {
            set_last_error("Null argument passed to taiyaki_memory_usage");
            return -1;
        }
        let rt = unsafe { &*rt };
        unsafe {
            *out = rt.engine.memory_usage();
        }
        0
    })
}

/// Triggers garbage collection.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_run_gc(rt: *mut LibtsRuntime) {
    ffi_guard!((), {
        if rt.is_null() {
            return;
        }
        let rt = unsafe { &*rt };
        rt.engine.run_gc();
    })
}

// --- ES Module support ---

/// Evaluates JavaScript code as an ES module.
/// Returns an ObjectHandle to the module namespace (exports).
/// `code` is a UTF-8 string of length `code_len`.
/// `name` is a UTF-8 module name of length `name_len`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_eval_module(
    rt: *mut LibtsRuntime,
    code: *const c_char,
    code_len: usize,
    name: *const c_char,
    name_len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || code.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_eval_module");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let code_str = match unsafe { extract_str(code, code_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in code");
                return ptr::null_mut();
            }
        };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return ptr::null_mut();
            }
        };
        match rt.engine.eval_module(code_str, name_str) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Evaluates TypeScript code as an ES module (strips types first).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_eval_module_ts(
    rt: *mut LibtsRuntime,
    code: *const c_char,
    code_len: usize,
    name: *const c_char,
    name_len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || code.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_eval_module_ts");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let ts_code = match unsafe { extract_str(code, code_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in code");
                return ptr::null_mut();
            }
        };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return ptr::null_mut();
            }
        };
        let js_code = match rt.transpiler.strip_types(ts_code) {
            Ok(js) => js,
            Err(e) => {
                set_last_error(&e.to_string());
                return ptr::null_mut();
            }
        };
        match rt.engine.eval_module(&js_code, name_str) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Registers a module source for later import. Returns 0 on success, -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_register_module(
    rt: *mut LibtsRuntime,
    name: *const c_char,
    name_len: usize,
    code: *const c_char,
    code_len: usize,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || name.is_null() || code.is_null() {
            set_last_error("Null argument passed to taiyaki_register_module");
            return -1;
        }
        let rt = unsafe { &*rt };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return -1;
            }
        };
        let code_str = match unsafe { extract_str(code, code_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in code");
                return -1;
            }
        };
        match rt.engine.register_module(name_str, code_str) {
            Ok(()) => 0,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}

// --- Global property access (for AOT bridge) ---

/// Gets a global property by name. Returns NULL on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_get_global(
    rt: *mut LibtsRuntime,
    name: *const c_char,
    name_len: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_get_global");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return ptr::null_mut();
            }
        };
        match rt.engine.get_global(name_str) {
            Ok(val) => wrap_handle_value(val, &rt.engine),
            Err(e) => {
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

/// Calls a global function by name. Convenience for get_global + call.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_call_global(
    rt: *mut LibtsRuntime,
    name: *const c_char,
    name_len: usize,
    args: *const *const LibtsValue,
    argc: usize,
) -> *mut LibtsValue {
    ffi_guard!(ptr::null_mut(), {
        if rt.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_call_global");
            return ptr::null_mut();
        }
        let rt = unsafe { &*rt };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return ptr::null_mut();
            }
        };
        let func_val = match rt.engine.get_global(name_str) {
            Ok(val) => val,
            Err(e) => {
                set_last_error(&e.to_string());
                return ptr::null_mut();
            }
        };
        let func_handle = match func_val.handle_id() {
            Some(h) => h,
            None => {
                set_last_error("Global is not a function handle");
                return ptr::null_mut();
            }
        };
        let mut js_args = Vec::with_capacity(argc);
        if argc > 0 && !args.is_null() {
            for i in 0..argc {
                let arg_ptr = unsafe { *args.add(i) };
                if arg_ptr.is_null() {
                    js_args.push(JsValue::Undefined);
                } else {
                    let arg = unsafe { &*arg_ptr };
                    js_args.push(arg.inner.clone());
                }
            }
        }
        match rt.engine.call_function(func_handle, &js_args) {
            Ok(val) => {
                rt.engine.drop_handle(func_handle);
                wrap_handle_value(val, &rt.engine)
            }
            Err(e) => {
                rt.engine.drop_handle(func_handle);
                set_last_error(&e.to_string());
                ptr::null_mut()
            }
        }
    })
}

// --- Fast-path calls for AOT bridge (avoid LibtsValue heap allocation) ---

/// Calls a function handle with f64 args, returns f64 result.
/// Avoids heap-allocating LibtsValue for each argument.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_call_fast_f64(
    rt: *mut LibtsRuntime,
    func: *const LibtsValue,
    args: *const f64,
    argc: usize,
) -> f64 {
    if rt.is_null() || func.is_null() {
        return f64::NAN;
    }
    let rt = unsafe { &*rt };
    let func = unsafe { &*func };
    let func_handle = match extract_handle(func) {
        Some(h) => h,
        None => return f64::NAN,
    };
    let mut js_args = Vec::with_capacity(argc);
    for i in 0..argc {
        js_args.push(JsValue::Number(unsafe { *args.add(i) }));
    }
    match rt.engine.call_function(func_handle, &js_args) {
        Ok(JsValue::Number(n)) => n,
        Ok(JsValue::Bool(b)) => {
            if b {
                1.0
            } else {
                0.0
            }
        }
        _ => f64::NAN,
    }
}

/// C callback type for fast f64 native functions (used by AOT wrappers).
pub type TaiyakiFastFnF64 = unsafe extern "C" fn(
    args: *const f64,
    argc: usize,
    user_data: *mut c_void,
) -> f64;

/// Registers a native function that takes f64 args and returns f64.
/// Avoids LibtsValue boxing overhead for numeric functions.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_register_fast_fn_f64(
    rt: *mut LibtsRuntime,
    name: *const c_char,
    name_len: usize,
    callback: TaiyakiFastFnF64,
    declared_argc: usize,
    user_data: *mut c_void,
) -> i32 {
    ffi_guard!(-1, {
        if rt.is_null() || name.is_null() {
            set_last_error("Null argument passed to taiyaki_register_fast_fn_f64");
            return -1;
        }
        let rt = unsafe { &mut *rt };
        let name_str = match unsafe { extract_str(name, name_len) } {
            Ok(s) => s,
            Err(()) => {
                set_last_error("Invalid UTF-8 in name");
                return -1;
            }
        };
        let user_data_ptr = user_data as usize;
        let _ = declared_argc; // Used by callee, not needed here

        type HostFn = Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>;
        let rust_callback: HostFn = Box::new(move |args: &[JsValue]| {
            let mut f64_args: Vec<f64> = args
                .iter()
                .map(|a| match a {
                    JsValue::Number(n) => *n,
                    JsValue::Bool(b) => {
                        if *b {
                            1.0
                        } else {
                            0.0
                        }
                    }
                    _ => 0.0,
                })
                .collect();
            let result = unsafe {
                callback(
                    f64_args.as_mut_ptr(),
                    f64_args.len(),
                    user_data_ptr as *mut c_void,
                )
            };
            Ok(JsValue::Number(result))
        });

        match rt.engine.register_global_fn(name_str, rust_callback) {
            Ok(()) => 0,
            Err(e) => {
                set_last_error(&e.to_string());
                -1
            }
        }
    })
}
