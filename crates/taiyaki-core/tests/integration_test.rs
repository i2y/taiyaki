use std::ffi::c_void;

#[cfg(feature = "quickjs")]
use taiyaki_core::engine::quickjs_backend::QuickJsEngine;
#[cfg(feature = "quickjs")]
use taiyaki_core::engine::{JsEngine, JsValue};
use taiyaki_core::ffi;
#[cfg(feature = "quickjs")]
use taiyaki_core::transpiler;

// ---------- Rust API テスト (QuickJS) ----------

#[cfg(feature = "quickjs")]
#[test]
fn test_eval_number() {
    let engine = QuickJsEngine::new().unwrap();
    let val = engine.eval("1 + 2").unwrap();
    assert_eq!(val, JsValue::Number(3.0));
}

#[cfg(feature = "quickjs")]
#[test]
fn test_eval_string_concat() {
    let engine = QuickJsEngine::new().unwrap();
    let val = engine.eval("'foo' + 'bar'").unwrap();
    assert_eq!(val, JsValue::String("foobar".to_string()));
}

#[cfg(feature = "quickjs")]
#[test]
fn test_eval_ts_basic() {
    let ts_code = "const x: number = 42; x";
    let js_code = transpiler::strip_types(ts_code).unwrap();
    let engine = QuickJsEngine::new().unwrap();
    let val = engine.eval(&js_code).unwrap();
    assert_eq!(val, JsValue::Number(42.0));
}

#[cfg(feature = "quickjs")]
#[test]
fn test_eval_ts_interface() {
    let ts_code = r#"
        interface User { name: string; age: number }
        const user: User = { name: "Alice", age: 30 };
        user.name
    "#;
    let js_code = transpiler::strip_types(ts_code).unwrap();
    let engine = QuickJsEngine::new().unwrap();
    let val = engine.eval(&js_code).unwrap();
    assert_eq!(val, JsValue::String("Alice".to_string()));
}

#[cfg(feature = "quickjs")]
#[test]
fn test_eval_ts_generics() {
    let ts_code = r#"
        function identity<T>(x: T): T { return x; }
        identity(42)
    "#;
    let js_code = transpiler::strip_types(ts_code).unwrap();
    let engine = QuickJsEngine::new().unwrap();
    let val = engine.eval(&js_code).unwrap();
    assert_eq!(val, JsValue::Number(42.0));
}

// ---------- FFI テスト ----------

#[test]
fn test_ffi_runtime_lifecycle() {
    let rt = ffi::taiyaki_runtime_new();
    assert!(!rt.is_null());
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_runtime_free_null() {
    // NULL に対して安全に呼べることを確認
    ffi::taiyaki_runtime_free(std::ptr::null_mut());
}

#[test]
fn test_ffi_eval_number() {
    let rt = ffi::taiyaki_runtime_new();
    assert!(!rt.is_null());

    let code = b"1 + 2";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(!val.is_null());

    let num = ffi::taiyaki_value_as_number(val);
    assert!((num - 3.0).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(val);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_eval_string() {
    let rt = ffi::taiyaki_runtime_new();

    let code = b"'hello world'";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(!val.is_null());

    let mut len: usize = 0;
    let ptr = ffi::taiyaki_value_as_string(val, &mut len);
    assert!(!ptr.is_null());
    let s = unsafe { std::ffi::CStr::from_ptr(ptr) }.to_str().unwrap();
    assert_eq!(s, "hello world");
    assert_eq!(len, 11);

    ffi::taiyaki_value_free(val);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_eval_ts() {
    let rt = ffi::taiyaki_runtime_new();

    let code = b"const x: number = 99; x";
    let val = ffi::taiyaki_eval_ts(rt, code.as_ptr() as *const _, code.len());
    assert!(!val.is_null());

    let num = ffi::taiyaki_value_as_number(val);
    assert!((num - 99.0).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(val);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_eval_error() {
    let rt = ffi::taiyaki_runtime_new();

    let code = b"throw new Error('oops')";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(val.is_null());

    let err = ffi::taiyaki_get_last_error();
    assert!(!err.is_null());
    let msg = unsafe { std::ffi::CStr::from_ptr(err) }.to_str().unwrap();
    assert!(msg.contains("oops"), "Error: {msg}");

    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_value_type() {
    let rt = ffi::taiyaki_runtime_new();

    // Number
    let code = b"42";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(matches!(
        ffi::taiyaki_value_type(val),
        ffi::LibtsType::Number
    ));
    ffi::taiyaki_value_free(val);

    // String
    let code = b"'hi'";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(matches!(
        ffi::taiyaki_value_type(val),
        ffi::LibtsType::String
    ));
    ffi::taiyaki_value_free(val);

    // Bool
    let code = b"true";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(matches!(ffi::taiyaki_value_type(val), ffi::LibtsType::Bool));
    ffi::taiyaki_value_free(val);

    // Null
    let code = b"null";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(matches!(ffi::taiyaki_value_type(val), ffi::LibtsType::Null));
    ffi::taiyaki_value_free(val);

    ffi::taiyaki_runtime_free(rt);
}

// ---------- Phase 2 FFI テスト ----------

// 値の生成

#[test]
fn test_ffi_value_number() {
    let val = ffi::taiyaki_value_number(42.5);
    assert!(!val.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(val),
        ffi::LibtsType::Number
    ));
    assert!((ffi::taiyaki_value_as_number(val) - 42.5).abs() < f64::EPSILON);
    ffi::taiyaki_value_free(val);
}

#[test]
fn test_ffi_value_string_create() {
    let s = b"hello";
    let val = ffi::taiyaki_value_string(s.as_ptr() as *const _, s.len());
    assert!(!val.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(val),
        ffi::LibtsType::String
    ));
    let mut len: usize = 0;
    let ptr = ffi::taiyaki_value_as_string(val, &mut len);
    assert!(!ptr.is_null());
    let result = unsafe { std::ffi::CStr::from_ptr(ptr) }.to_str().unwrap();
    assert_eq!(result, "hello");
    assert_eq!(len, 5);
    ffi::taiyaki_value_free(val);
}

#[test]
fn test_ffi_value_bool_create() {
    let val_true = ffi::taiyaki_value_bool(1);
    assert!(matches!(
        ffi::taiyaki_value_type(val_true),
        ffi::LibtsType::Bool
    ));
    assert_eq!(ffi::taiyaki_value_as_bool(val_true), 1);
    ffi::taiyaki_value_free(val_true);

    let val_false = ffi::taiyaki_value_bool(0);
    assert_eq!(ffi::taiyaki_value_as_bool(val_false), 0);
    ffi::taiyaki_value_free(val_false);
}

#[test]
fn test_ffi_value_null_undefined() {
    let null_val = ffi::taiyaki_value_null();
    assert!(matches!(
        ffi::taiyaki_value_type(null_val),
        ffi::LibtsType::Null
    ));
    ffi::taiyaki_value_free(null_val);

    let undef_val = ffi::taiyaki_value_undefined();
    assert!(matches!(
        ffi::taiyaki_value_type(undef_val),
        ffi::LibtsType::Undefined
    ));
    ffi::taiyaki_value_free(undef_val);
}

// オブジェクト操作

#[test]
fn test_ffi_object_new_set_get() {
    let rt = ffi::taiyaki_runtime_new();
    let obj = ffi::taiyaki_object_new(rt);
    assert!(!obj.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(obj),
        ffi::LibtsType::Object
    ));

    let key = b"x";
    let val = ffi::taiyaki_value_number(42.0);
    let ret = ffi::taiyaki_object_set(rt, obj, key.as_ptr() as *const _, key.len(), val);
    assert_eq!(ret, 0);
    ffi::taiyaki_value_free(val);

    let got = ffi::taiyaki_object_get(rt, obj, key.as_ptr() as *const _, key.len());
    assert!(!got.is_null());
    assert!((ffi::taiyaki_value_as_number(got) - 42.0).abs() < f64::EPSILON);
    ffi::taiyaki_value_free(got);

    ffi::taiyaki_value_free(obj);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_object_to_json() {
    let rt = ffi::taiyaki_runtime_new();
    let obj = ffi::taiyaki_object_new(rt);

    let key = b"name";
    let val = ffi::taiyaki_value_string(b"Alice".as_ptr() as *const _, 5);
    ffi::taiyaki_object_set(rt, obj, key.as_ptr() as *const _, key.len(), val);
    ffi::taiyaki_value_free(val);

    let json = ffi::taiyaki_to_json(rt, obj);
    assert!(!json.is_null());
    let mut len: usize = 0;
    let ptr = ffi::taiyaki_value_as_string(json, &mut len);
    let json_str = unsafe { std::ffi::CStr::from_ptr(ptr) }.to_str().unwrap();
    assert!(json_str.contains("\"name\""));
    assert!(json_str.contains("\"Alice\""));

    ffi::taiyaki_value_free(json);
    ffi::taiyaki_value_free(obj);
    ffi::taiyaki_runtime_free(rt);
}

// 配列操作

#[test]
fn test_ffi_array_new_push_get_length() {
    let rt = ffi::taiyaki_runtime_new();
    let arr = ffi::taiyaki_array_new(rt);
    assert!(!arr.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(arr),
        ffi::LibtsType::Array
    ));

    for i in 0..3 {
        let val = ffi::taiyaki_value_number((i + 1) as f64 * 10.0);
        let ret = ffi::taiyaki_array_push(rt, arr, val);
        assert_eq!(ret, 0);
        ffi::taiyaki_value_free(val);
    }

    assert_eq!(ffi::taiyaki_array_length(rt, arr), 3);

    let elem = ffi::taiyaki_array_get(rt, arr, 1);
    assert!(!elem.is_null());
    assert!((ffi::taiyaki_value_as_number(elem) - 20.0).abs() < f64::EPSILON);
    ffi::taiyaki_value_free(elem);

    ffi::taiyaki_value_free(arr);
    ffi::taiyaki_runtime_free(rt);
}

// JSON ブリッジ

#[test]
fn test_ffi_from_json() {
    let rt = ffi::taiyaki_runtime_new();
    let json = br#"{"a": 1, "b": [10, 20]}"#;
    let val = ffi::taiyaki_from_json(rt, json.as_ptr() as *const _, json.len());
    assert!(!val.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(val),
        ffi::LibtsType::Object
    ));

    let key = b"a";
    let a = ffi::taiyaki_object_get(rt, val, key.as_ptr() as *const _, key.len());
    assert!((ffi::taiyaki_value_as_number(a) - 1.0).abs() < f64::EPSILON);
    ffi::taiyaki_value_free(a);

    let key = b"b";
    let b = ffi::taiyaki_object_get(rt, val, key.as_ptr() as *const _, key.len());
    assert!(matches!(ffi::taiyaki_value_type(b), ffi::LibtsType::Array));
    assert_eq!(ffi::taiyaki_array_length(rt, b), 2);
    ffi::taiyaki_value_free(b);

    ffi::taiyaki_value_free(val);
    ffi::taiyaki_runtime_free(rt);
}

// ホスト関数登録

#[test]
fn test_ffi_register_fn() {
    let rt = ffi::taiyaki_runtime_new();

    unsafe extern "C" fn add_fn(
        args: *const *const ffi::LibtsValue,
        argc: usize,
        _user_data: *mut c_void,
    ) -> *mut ffi::LibtsValue {
        if argc < 2 {
            return ffi::taiyaki_value_number(0.0);
        }
        unsafe {
            let a = ffi::taiyaki_value_as_number(*args.add(0));
            let b = ffi::taiyaki_value_as_number(*args.add(1));
            ffi::taiyaki_value_number(a + b)
        }
    }

    let name = b"hostAdd";
    let ret = ffi::taiyaki_register_fn(
        rt,
        name.as_ptr() as *const _,
        name.len(),
        add_fn,
        std::ptr::null_mut(),
    );
    assert_eq!(ret, 0);

    let code = b"hostAdd(3, 4)";
    let result = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(!result.is_null());
    assert!((ffi::taiyaki_value_as_number(result) - 7.0).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(result);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_register_fn_string_args() {
    let rt = ffi::taiyaki_runtime_new();

    unsafe extern "C" fn greet_fn(
        args: *const *const ffi::LibtsValue,
        argc: usize,
        _user_data: *mut c_void,
    ) -> *mut ffi::LibtsValue {
        unsafe {
            if argc < 1 {
                return ffi::taiyaki_value_string(b"Hello!".as_ptr() as *const _, 6);
            }
            let mut len: usize = 0;
            let ptr = ffi::taiyaki_value_as_string(*args.add(0) as *mut _, &mut len);
            if ptr.is_null() {
                return ffi::taiyaki_value_string(b"Hello!".as_ptr() as *const _, 6);
            }
            let name = std::ffi::CStr::from_ptr(ptr).to_str().unwrap();
            let greeting = format!("Hello, {name}!");
            ffi::taiyaki_value_string(greeting.as_ptr() as *const _, greeting.len())
        }
    }

    let name = b"greet";
    ffi::taiyaki_register_fn(
        rt,
        name.as_ptr() as *const _,
        name.len(),
        greet_fn,
        std::ptr::null_mut(),
    );

    let code = b"greet('World')";
    let result = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(!result.is_null());
    let mut len: usize = 0;
    let ptr = ffi::taiyaki_value_as_string(result, &mut len);
    let s = unsafe { std::ffi::CStr::from_ptr(ptr) }.to_str().unwrap();
    assert_eq!(s, "Hello, World!");

    ffi::taiyaki_value_free(result);
    ffi::taiyaki_runtime_free(rt);
}

// ---------- Phase 3 Resource Limits FFI テスト ----------

#[cfg(feature = "quickjs")]
#[test]
fn test_ffi_execution_timeout() {
    let rt = ffi::taiyaki_runtime_new();
    ffi::taiyaki_set_execution_timeout(rt, 100); // 100ms
    let code = b"while(true){}";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(val.is_null());
    ffi::taiyaki_runtime_free(rt);
}

#[cfg(feature = "quickjs")]
#[test]
fn test_ffi_memory_usage() {
    let rt = ffi::taiyaki_runtime_new();
    let code = b"var x = [1,2,3]";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    ffi::taiyaki_value_free(val);

    let mut stats: taiyaki_core::engine::MemoryStats = unsafe { std::mem::zeroed() };
    let ret = ffi::taiyaki_memory_usage(rt, &mut stats);
    assert_eq!(ret, 0);
    assert!(stats.memory_used_size > 0);

    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_run_gc() {
    let rt = ffi::taiyaki_runtime_new();
    let code = b"var x = {a: 1}";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    ffi::taiyaki_value_free(val);
    ffi::taiyaki_run_gc(rt);
    // Engine still usable after GC
    let code2 = b"1 + 1";
    let val2 = ffi::taiyaki_eval(rt, code2.as_ptr() as *const _, code2.len());
    assert!(!val2.is_null());
    assert!((ffi::taiyaki_value_as_number(val2) - 2.0).abs() < f64::EPSILON);
    ffi::taiyaki_value_free(val2);
    ffi::taiyaki_runtime_free(rt);
}

#[cfg(feature = "quickjs")]
#[test]
fn test_ffi_set_memory_limit() {
    let rt = ffi::taiyaki_runtime_new();
    ffi::taiyaki_set_memory_limit(rt, 1024 * 64); // 64KB
    let code =
        b"var a = []; for(var i = 0; i < 100000; i++) a.push({x: i, y: 'hello'.repeat(100)})";
    let val = ffi::taiyaki_eval(rt, code.as_ptr() as *const _, code.len());
    assert!(val.is_null()); // Should fail with OOM
    ffi::taiyaki_runtime_free(rt);
}

// ---------- Phase 3 ES Module FFI テスト ----------

#[test]
fn test_ffi_eval_module() {
    let rt = ffi::taiyaki_runtime_new();
    let code = b"export const x = 42;";
    let name = b"test";
    let ns = ffi::taiyaki_eval_module(
        rt,
        code.as_ptr() as *const _,
        code.len(),
        name.as_ptr() as *const _,
        name.len(),
    );
    assert!(!ns.is_null());
    assert!(matches!(
        ffi::taiyaki_value_type(ns),
        ffi::LibtsType::Object
    ));

    let key = b"x";
    let x = ffi::taiyaki_object_get(rt, ns, key.as_ptr() as *const _, key.len());
    assert!(!x.is_null());
    assert!((ffi::taiyaki_value_as_number(x) - 42.0).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(x);
    ffi::taiyaki_value_free(ns);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_register_module_and_import() {
    let rt = ffi::taiyaki_runtime_new();

    let mod_name = b"helper";
    let mod_code = b"export const PI = 3.14;";
    let ret = ffi::taiyaki_register_module(
        rt,
        mod_name.as_ptr() as *const _,
        mod_name.len(),
        mod_code.as_ptr() as *const _,
        mod_code.len(),
    );
    assert_eq!(ret, 0);

    let code = b"import { PI } from 'helper'; export const tau = PI * 2;";
    let name = b"main";
    let ns = ffi::taiyaki_eval_module(
        rt,
        code.as_ptr() as *const _,
        code.len(),
        name.as_ptr() as *const _,
        name.len(),
    );
    assert!(!ns.is_null());

    let key = b"tau";
    let tau = ffi::taiyaki_object_get(rt, ns, key.as_ptr() as *const _, key.len());
    assert!(!tau.is_null());
    assert!((ffi::taiyaki_value_as_number(tau) - 6.28).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(tau);
    ffi::taiyaki_value_free(ns);
    ffi::taiyaki_runtime_free(rt);
}

#[test]
fn test_ffi_eval_module_ts() {
    let rt = ffi::taiyaki_runtime_new();
    let code = b"export const x: number = 99;";
    let name = b"ts_mod";
    let ns = ffi::taiyaki_eval_module_ts(
        rt,
        code.as_ptr() as *const _,
        code.len(),
        name.as_ptr() as *const _,
        name.len(),
    );
    assert!(!ns.is_null());

    let key = b"x";
    let x = ffi::taiyaki_object_get(rt, ns, key.as_ptr() as *const _, key.len());
    assert!((ffi::taiyaki_value_as_number(x) - 99.0).abs() < f64::EPSILON);

    ffi::taiyaki_value_free(x);
    ffi::taiyaki_value_free(ns);
    ffi::taiyaki_runtime_free(rt);
}
