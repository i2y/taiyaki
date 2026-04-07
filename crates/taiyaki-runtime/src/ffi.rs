//! C ABI for AOT-compiled binaries.
//!
//! Provides a full runtime (tokio + async engine + all builtins) callable from C.

use std::ffi::{c_char, c_void};
use std::path::Path;
use std::sync::Arc;

use taiyaki_core::engine::JsValue;
use taiyaki_core::permissions::Permissions;

use crate::Engine;

/// Opaque handle to the full runtime (tokio + async engine + builtins).
pub struct TaiyakiFullRuntime {
    tokio_rt: tokio::runtime::Runtime,
    engine: Engine,
}

/// C callback type for fast f64 native functions.
pub type TaiyakiAotFnF64 = unsafe extern "C" fn(
    args: *const f64,
    argc: usize,
    user_data: *mut c_void,
) -> f64;

/// Creates a full runtime with all builtins registered.
/// Returns NULL on failure.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_new(
    argc: i32,
    argv: *const *const c_char,
) -> *mut TaiyakiFullRuntime {
    // Collect argv for process.argv
    let user_args: Vec<String> = if !argv.is_null() && argc > 0 {
        (0..argc as usize)
            .filter_map(|i| {
                let ptr = unsafe { *argv.add(i) };
                if ptr.is_null() {
                    None
                } else {
                    let cstr = unsafe { std::ffi::CStr::from_ptr(ptr) };
                    cstr.to_str().ok().map(|s| s.to_string())
                }
            })
            .collect()
    } else {
        vec![]
    };

    let tokio_rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(_) => return std::ptr::null_mut(),
    };

    let engine = match tokio_rt.block_on(Engine::new()) {
        Ok(e) => e,
        Err(_) => return std::ptr::null_mut(),
    };

    let perms = Arc::new(Permissions::default());
    let script_path = Path::new("<aot>");

    // Enable file loader for ESM node_modules resolution
    tokio_rt.block_on(engine.enable_file_loader(Path::new(".")));

    if let Err(e) = tokio_rt.block_on(crate::bootstrap_engine(
        &engine,
        script_path,
        &user_args,
        &perms,
    )) {
        eprintln!("taiyaki runtime bootstrap failed: {e}");
        return std::ptr::null_mut();
    }

    Box::into_raw(Box::new(TaiyakiFullRuntime { tokio_rt, engine }))
}

/// Registers an AOT-compiled f64 function as a JS global.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_register_fn_f64(
    rt: *mut TaiyakiFullRuntime,
    name: *const c_char,
    name_len: usize,
    callback: TaiyakiAotFnF64,
    declared_argc: usize,
    user_data: *mut c_void,
) -> i32 {
    if rt.is_null() || name.is_null() {
        return -1;
    }
    let rt = unsafe { &*rt };
    let name_str = match unsafe { extract_str(name, name_len) } {
        Some(s) => s,
        None => return -1,
    };

    let user_data_ptr = user_data as usize;
    let _ = declared_argc;

    let rust_callback: taiyaki_core::engine::HostCallback =
        Box::new(move |args: &[JsValue]| {
            let f64_args: Vec<f64> = args
                .iter()
                .map(|a| match a {
                    JsValue::Number(n) => *n,
                    JsValue::Bool(b) => if *b { 1.0 } else { 0.0 },
                    _ => 0.0,
                })
                .collect();
            let result = unsafe {
                callback(f64_args.as_ptr(), f64_args.len(), user_data_ptr as *mut c_void)
            };
            Ok(JsValue::Number(result))
        });

    match rt
        .tokio_rt
        .block_on(rt.engine.register_global_fn(name_str, rust_callback))
    {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Argument type tags for generic host functions.
#[repr(C)]
pub enum TaiyakiArgType {
    Number = 0,
    String = 1,
    Bool = 2,
    Null = 3,
}

/// Typed argument for generic host functions.
#[repr(C)]
pub struct TaiyakiArg {
    pub arg_type: TaiyakiArgType,
    pub number: f64,
    pub string: *const c_char,
    pub string_len: usize,
}

/// C callback type for generic host functions (supports string args).
pub type TaiyakiHostFnGeneric = unsafe extern "C" fn(
    args: *const TaiyakiArg,
    argc: usize,
    user_data: *mut c_void,
) -> f64;

/// Registers a generic host function that receives typed args (number/string/bool).
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_register_fn(
    rt: *mut TaiyakiFullRuntime,
    name: *const c_char,
    name_len: usize,
    callback: TaiyakiHostFnGeneric,
    declared_argc: usize,
    user_data: *mut c_void,
) -> i32 {
    if rt.is_null() || name.is_null() {
        return -1;
    }
    let rt = unsafe { &*rt };
    let name_str = match unsafe { extract_str(name, name_len) } {
        Some(s) => s,
        None => return -1,
    };

    let user_data_ptr = user_data as usize;
    let _ = declared_argc;

    let rust_callback: taiyaki_core::engine::HostCallback =
        Box::new(move |args: &[JsValue]| {
            // Convert JsValue args to TaiyakiArg, keeping CStrings alive
            let mut c_strings: Vec<std::ffi::CString> = Vec::new();
            let c_args: Vec<TaiyakiArg> = args
                .iter()
                .map(|a| match a {
                    JsValue::Number(n) => TaiyakiArg {
                        arg_type: TaiyakiArgType::Number,
                        number: *n,
                        string: std::ptr::null(),
                        string_len: 0,
                    },
                    JsValue::String(s) => {
                        let cs = std::ffi::CString::new(s.as_str()).unwrap_or_default();
                        let ptr = cs.as_ptr();
                        let len = s.len();
                        c_strings.push(cs);
                        TaiyakiArg {
                            arg_type: TaiyakiArgType::String,
                            number: 0.0,
                            string: ptr,
                            string_len: len,
                        }
                    }
                    JsValue::Bool(b) => TaiyakiArg {
                        arg_type: TaiyakiArgType::Bool,
                        number: if *b { 1.0 } else { 0.0 },
                        string: std::ptr::null(),
                        string_len: 0,
                    },
                    _ => TaiyakiArg {
                        arg_type: TaiyakiArgType::Null,
                        number: 0.0,
                        string: std::ptr::null(),
                        string_len: 0,
                    },
                })
                .collect();
            let result = unsafe {
                callback(c_args.as_ptr(), c_args.len(), user_data_ptr as *mut c_void)
            };
            // c_strings dropped here, after callback returns
            Ok(JsValue::Number(result))
        });

    match rt
        .tokio_rt
        .block_on(rt.engine.register_global_fn(name_str, rust_callback))
    {
        Ok(()) => 0,
        Err(_) => -1,
    }
}

/// Evaluates JS code. Returns 0 on success, -1 on error.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_eval(
    rt: *mut TaiyakiFullRuntime,
    code: *const c_char,
    code_len: usize,
) -> i32 {
    if rt.is_null() || code.is_null() {
        return -1;
    }
    let rt = unsafe { &*rt };
    let code_str = match unsafe { extract_str(code, code_len) } {
        Some(s) => s,
        None => return -1,
    };
    match rt.tokio_rt.block_on(rt.engine.eval_async(code_str)) {
        Ok(_) => 0,
        Err(e) => {
            eprintln!("taiyaki eval error: {e}");
            -1
        }
    }
}

/// Evaluates JS code as an ES module and runs the event loop.
/// This is the main entry point for AOT binaries with async code (servers, etc.).
/// Blocks until the event loop has no more work.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_eval_module_and_run(
    rt: *mut TaiyakiFullRuntime,
    code: *const c_char,
    code_len: usize,
    name: *const c_char,
    name_len: usize,
) -> i32 {
    if rt.is_null() || code.is_null() || name.is_null() {
        return -1;
    }
    let rt = unsafe { &*rt };
    let code_str = match unsafe { extract_str(code, code_len) } {
        Some(s) => s,
        None => return -1,
    };
    let name_str = match unsafe { extract_str(name, name_len) } {
        Some(s) => s,
        None => return -1,
    };
    match rt
        .tokio_rt
        .block_on(rt.engine.eval_module_async(code_str, name_str))
    {
        Ok(_) => 0,
        Err(e) => {
            eprintln!("taiyaki module error: {e}");
            -1
        }
    }
}

/// Frees the runtime. NULL-safe.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_free(rt: *mut TaiyakiFullRuntime) {
    if !rt.is_null() {
        let _ = unsafe { Box::from_raw(rt) };
    }
}

/// Gets a global property by name.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn taiyaki_full_runtime_get_global(
    rt: *mut TaiyakiFullRuntime,
    name: *const c_char,
    name_len: usize,
) -> f64 {
    if rt.is_null() || name.is_null() {
        return f64::NAN;
    }
    let rt = unsafe { &*rt };
    let name_str = match unsafe { extract_str(name, name_len) } {
        Some(s) => s,
        None => return f64::NAN,
    };
    match rt.tokio_rt.block_on(rt.engine.get_global(name_str)) {
        Ok(JsValue::Number(n)) => n,
        _ => f64::NAN,
    }
}

unsafe fn extract_str<'a>(ptr: *const c_char, len: usize) -> Option<&'a str> {
    let bytes = unsafe { std::slice::from_raw_parts(ptr as *const u8, len) };
    std::str::from_utf8(bytes).ok()
}
