use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::ffi::{CString, c_char};
use std::os::raw::c_void;
use std::panic::{self, AssertUnwindSafe};
use std::ptr;
use std::rc::Rc;
use std::time::Duration;

use super::jsc_sys::*;
use super::{EngineError, HostCallback, JsEngine, JsValue, MemoryStats};

// ---------------------------------------------------------------------------
// Helper: JSC string ↔ Rust string
// ---------------------------------------------------------------------------

/// Creates a JSStringRef from a Rust &str. Caller must call JSStringRelease.
fn rust_str_to_jsc(s: &str) -> JSStringRef {
    let cstr = CString::new(s).unwrap_or_else(|_| CString::new("").unwrap());
    unsafe { JSStringCreateWithUTF8CString(cstr.as_ptr()) }
}

/// Converts a JSStringRef to a Rust String. Does NOT release the JSStringRef.
fn jsc_str_to_rust(s: JSStringRef) -> String {
    if s.is_null() {
        return String::new();
    }
    unsafe {
        let max_size = JSStringGetMaximumUTF8CStringSize(s);
        let mut buf: Vec<u8> = vec![0; max_size];
        let actual = JSStringGetUTF8CString(s, buf.as_mut_ptr() as *mut c_char, max_size);
        if actual > 0 {
            buf.truncate(actual - 1);
        } else {
            buf.clear();
        }
        String::from_utf8(buf)
            .unwrap_or_else(|e| String::from_utf8_lossy(e.as_bytes()).into_owned())
    }
}

/// Extracts the exception message from a JSValueRef exception.
fn exception_to_string(ctx: JSContextRef, exception: JSValueRef) -> String {
    if exception.is_null() {
        return "Unknown error".to_string();
    }
    unsafe {
        let mut ex: JSValueRef = ptr::null();
        let s = JSValueToStringCopy(ctx, exception, &mut ex);
        if s.is_null() {
            return "Unknown error".to_string();
        }
        let result = jsc_str_to_rust(s);
        JSStringRelease(s);
        result
    }
}

/// Checks the exception pointer and converts to EngineError if non-null.
fn check_exception(ctx: JSContextRef, exception: JSValueRef) -> Result<(), EngineError> {
    if exception.is_null() {
        Ok(())
    } else {
        Err(EngineError::JsException {
            message: exception_to_string(ctx, exception),
        })
    }
}

// ---------------------------------------------------------------------------
// Host function trampoline data
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq)]
enum HandleKind {
    Object,
    Array,
    Function,
}

struct HostFnData {
    callback: Rc<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>,
    handles: Rc<RefCell<HashMap<u64, JSValueRef>>>,
    next_handle: Rc<Cell<u64>>,
    handle_types: Rc<RefCell<HashMap<u64, HandleKind>>>,
}

/// The C trampoline function called by JSC when a host function is invoked.
unsafe extern "C" fn host_fn_trampoline(
    ctx: JSContextRef,
    function: JSObjectRef,
    _this_object: JSObjectRef,
    argument_count: usize,
    arguments: *const JSValueRef,
    exception: *mut JSValueRef,
) -> JSValueRef {
    let result = panic::catch_unwind(AssertUnwindSafe(|| {
        let data_ptr = unsafe { JSObjectGetPrivate(function) };
        if data_ptr.is_null() {
            return unsafe { JSValueMakeUndefined(ctx) };
        }
        let data = unsafe { &*(data_ptr as *const HostFnData) };

        let mut args = Vec::with_capacity(argument_count);
        for i in 0..argument_count {
            let jsc_val = unsafe { *arguments.add(i) };
            args.push(jsc_to_jsvalue(
                ctx,
                jsc_val,
                &data.handles,
                &data.next_handle,
                &data.handle_types,
            ));
        }

        match (data.callback)(&args) {
            Ok(result) => match jsvalue_to_jsc(ctx, &result, &data.handles) {
                Ok(v) => v,
                Err(e) => {
                    set_jsc_exception(ctx, exception, &e.to_string());
                    unsafe { JSValueMakeUndefined(ctx) }
                }
            },
            Err(e) => {
                set_jsc_exception(ctx, exception, &e.to_string());
                unsafe { JSValueMakeUndefined(ctx) }
            }
        }
    }));

    match result {
        Ok(v) => v,
        Err(_) => {
            set_jsc_exception(ctx, exception, "Internal panic in host function");
            unsafe { JSValueMakeUndefined(ctx) }
        }
    }
}

/// Sets a JSC exception from a Rust string.
fn set_jsc_exception(ctx: JSContextRef, exception: *mut JSValueRef, msg: &str) {
    if !exception.is_null() {
        let s = rust_str_to_jsc(msg);
        unsafe {
            let str_val = JSValueMakeString(ctx, s);
            *exception = str_val;
            JSStringRelease(s);
        }
    }
}

// ---------------------------------------------------------------------------
// Value conversion: JSC → JsValue
// ---------------------------------------------------------------------------

/// Converts a JSC primitive (non-object) value, returning None for object types.
unsafe fn convert_jsc_primitive(ctx: JSContextRef, value: JSValueRef) -> Option<JsValue> {
    unsafe {
        let ty = JSValueGetType(ctx, value);
        if ty == kJSTypeUndefined {
            Some(JsValue::Undefined)
        } else if ty == kJSTypeNull {
            Some(JsValue::Null)
        } else if ty == kJSTypeBoolean {
            Some(JsValue::Bool(JSValueToBoolean(ctx, value)))
        } else if ty == kJSTypeNumber {
            let mut ex: JSValueRef = ptr::null();
            Some(JsValue::Number(JSValueToNumber(ctx, value, &mut ex)))
        } else if ty == kJSTypeString {
            let mut ex: JSValueRef = ptr::null();
            let s = JSValueToStringCopy(ctx, value, &mut ex);
            if s.is_null() {
                return Some(JsValue::String(String::new()));
            }
            let result = jsc_str_to_rust(s);
            JSStringRelease(s);
            Some(JsValue::String(result))
        } else {
            None
        }
    }
}

/// Converts a JSC value to a JsValue. Objects/arrays/functions get stored as handles.
fn jsc_to_jsvalue(
    ctx: JSContextRef,
    value: JSValueRef,
    handles: &Rc<RefCell<HashMap<u64, JSValueRef>>>,
    next_handle: &Rc<Cell<u64>>,
    handle_types: &Rc<RefCell<HashMap<u64, HandleKind>>>,
) -> JsValue {
    if value.is_null() {
        return JsValue::Undefined;
    }
    unsafe {
        if let Some(prim) = convert_jsc_primitive(ctx, value) {
            return prim;
        }
        let ty = JSValueGetType(ctx, value);
        let (kind, jsval_fn): (HandleKind, fn(u64) -> JsValue) = if ty == kJSTypeObject {
            if JSObjectIsFunction(ctx, value as JSObjectRef) {
                (HandleKind::Function, JsValue::FunctionHandle)
            } else if JSValueIsArray(ctx, value) {
                (HandleKind::Array, JsValue::ArrayHandle)
            } else {
                (HandleKind::Object, JsValue::ObjectHandle)
            }
        } else {
            (HandleKind::Object, JsValue::ObjectHandle)
        };
        let id = store_value(ctx, value, handles, next_handle);
        handle_types.borrow_mut().insert(id, kind);
        jsval_fn(id)
    }
}

/// Like jsc_to_jsvalue but for eval results: objects/arrays serialize to JSON, functions return marker.
fn jsc_to_jsvalue_eval(ctx: JSContextRef, value: JSValueRef) -> JsValue {
    if value.is_null() {
        return JsValue::Undefined;
    }
    unsafe {
        if let Some(prim) = convert_jsc_primitive(ctx, value) {
            return prim;
        }
        let ty = JSValueGetType(ctx, value);
        if ty == kJSTypeObject && JSObjectIsFunction(ctx, value as JSObjectRef) {
            return JsValue::Function;
        }
        // Check array before JSON serialization
        let is_array = ty == kJSTypeObject && JSValueIsArray(ctx, value);
        let mut ex: JSValueRef = ptr::null();
        let json_str = JSValueCreateJSONString(ctx, value, 0, &mut ex);
        if json_str.is_null() {
            return JsValue::Object("{}".to_string());
        }
        let json = jsc_str_to_rust(json_str);
        JSStringRelease(json_str);
        if is_array {
            JsValue::Array(json)
        } else {
            JsValue::Object(json)
        }
    }
}

/// Protects a JSValueRef and stores it in the handle map, returning its handle ID.
fn store_value(
    ctx: JSContextRef,
    value: JSValueRef,
    handles: &Rc<RefCell<HashMap<u64, JSValueRef>>>,
    next_handle: &Rc<Cell<u64>>,
) -> u64 {
    unsafe { JSValueProtect(ctx, value) };
    let id = next_handle.get();
    next_handle.set(id + 1);
    handles.borrow_mut().insert(id, value);
    id
}

// ---------------------------------------------------------------------------
// Value conversion: JsValue → JSC
// ---------------------------------------------------------------------------

/// Converts a JsValue to a JSC value. Handle variants are restored from the handle map.
fn jsvalue_to_jsc(
    ctx: JSContextRef,
    val: &JsValue,
    handles: &Rc<RefCell<HashMap<u64, JSValueRef>>>,
) -> Result<JSValueRef, EngineError> {
    unsafe {
        match val {
            JsValue::Undefined => Ok(JSValueMakeUndefined(ctx)),
            JsValue::Null => Ok(JSValueMakeNull(ctx)),
            JsValue::Bool(b) => Ok(JSValueMakeBoolean(ctx, *b)),
            JsValue::Number(n) => Ok(JSValueMakeNumber(ctx, *n)),
            JsValue::String(s) => {
                let jsc_str = rust_str_to_jsc(s);
                let val = JSValueMakeString(ctx, jsc_str);
                JSStringRelease(jsc_str);
                Ok(val)
            }
            JsValue::Object(json) | JsValue::Array(json) => {
                let jsc_str = rust_str_to_jsc(json);
                let val = JSValueMakeFromJSONString(ctx, jsc_str);
                JSStringRelease(jsc_str);
                if val.is_null() {
                    Err(EngineError::TypeError("Invalid JSON".to_string()))
                } else {
                    Ok(val)
                }
            }
            JsValue::Function => Err(EngineError::TypeError(
                "Cannot convert opaque Function marker to JSC value".to_string(),
            )),
            JsValue::ObjectHandle(id) | JsValue::ArrayHandle(id) | JsValue::FunctionHandle(id) => {
                let store = handles.borrow();
                let val = store.get(id).ok_or(EngineError::InvalidHandle(*id))?;
                Ok(*val)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// JscEngine
// ---------------------------------------------------------------------------

pub struct JscEngine {
    ctx: JSGlobalContextRef,
    handles: Rc<RefCell<HashMap<u64, JSValueRef>>>,
    handle_types: Rc<RefCell<HashMap<u64, HandleKind>>>,
    next_handle: Rc<Cell<u64>>,
    module_sources: Rc<RefCell<HashMap<String, String>>>,
    host_fn_data: RefCell<Vec<*mut HostFnData>>,
    host_fn_class: JSClassRef,
    file_loader_base: RefCell<Option<std::path::PathBuf>>,
}

impl Drop for JscEngine {
    fn drop(&mut self) {
        // Clear execution time limit before releasing context
        unsafe {
            let group = JSContextGetGroup(self.ctx as JSContextRef);
            JSContextGroupClearExecutionTimeLimit(group);
        }

        let handles = self.handles.borrow();
        for &val in handles.values() {
            unsafe { JSValueUnprotect(self.ctx as JSContextRef, val) };
        }
        drop(handles);

        for ptr in self.host_fn_data.borrow().iter() {
            let _ = unsafe { Box::from_raw(*ptr) };
        }

        unsafe {
            JSClassRelease(self.host_fn_class);
            JSGlobalContextRelease(self.ctx);
        }
    }
}

impl JscEngine {
    pub fn new() -> Result<Self, EngineError> {
        unsafe {
            let mut class_def = JSClassDefinition::empty();
            let class_name = CString::new("HostFunction").unwrap();
            class_def.class_name = class_name.as_ptr();
            class_def.call_as_function = Some(host_fn_trampoline);

            let host_fn_class = JSClassCreate(&class_def);

            let ctx = JSGlobalContextCreate(ptr::null_mut());
            if ctx.is_null() {
                JSClassRelease(host_fn_class);
                return Err(EngineError::InitError(
                    "Failed to create JSC global context".to_string(),
                ));
            }

            Ok(Self {
                ctx,
                handles: Rc::new(RefCell::new(HashMap::new())),
                handle_types: Rc::new(RefCell::new(HashMap::new())),
                next_handle: Rc::new(Cell::new(0)),
                module_sources: Rc::new(RefCell::new(HashMap::new())),
                host_fn_data: RefCell::new(Vec::new()),
                host_fn_class,
                file_loader_base: RefCell::new(None),
            })
        }
    }

    pub(crate) fn ctx(&self) -> JSContextRef {
        self.ctx as JSContextRef
    }

    /// Set the base path for file-based module resolution.
    pub fn set_file_loader_base(&self, base_path: &std::path::Path) {
        *self.file_loader_base.borrow_mut() = Some(base_path.to_path_buf());
    }

    fn store_handle(&self, value: JSValueRef) -> u64 {
        store_value(self.ctx(), value, &self.handles, &self.next_handle)
    }

    fn store_handle_typed(&self, value: JSValueRef, kind: HandleKind) -> u64 {
        let id = self.store_handle(value);
        self.handle_types.borrow_mut().insert(id, kind);
        id
    }

    fn restore_handle(&self, handle: u64) -> Result<JSValueRef, EngineError> {
        self.handles
            .borrow()
            .get(&handle)
            .copied()
            .ok_or(EngineError::InvalidHandle(handle))
    }

    fn to_jsc(&self, val: &JsValue) -> Result<JSValueRef, EngineError> {
        jsvalue_to_jsc(self.ctx(), val, &self.handles)
    }

    fn from_jsc_handle(&self, value: JSValueRef) -> JsValue {
        jsc_to_jsvalue(
            self.ctx(),
            value,
            &self.handles,
            &self.next_handle,
            &self.handle_types,
        )
    }
}

impl JsEngine for JscEngine {
    fn eval(&self, code: &str) -> Result<JsValue, EngineError> {
        unsafe {
            let script = rust_str_to_jsc(code);
            let mut exception: JSValueRef = ptr::null();
            let result = JSEvaluateScript(
                self.ctx(),
                script,
                ptr::null_mut(),
                ptr::null_mut(),
                1,
                &mut exception,
            );
            JSStringRelease(script);

            if !exception.is_null() {
                return Err(EngineError::JsException {
                    message: exception_to_string(self.ctx(), exception),
                });
            }
            Ok(jsc_to_jsvalue_eval(self.ctx(), result))
        }
    }

    fn object_new(&self) -> Result<JsValue, EngineError> {
        unsafe {
            let obj = JSObjectMake(self.ctx(), ptr::null_mut(), ptr::null_mut());
            let id = self.store_handle_typed(obj as JSValueRef, HandleKind::Object);
            Ok(JsValue::ObjectHandle(id))
        }
    }

    fn object_set(&self, handle: u64, key: &str, value: &JsValue) -> Result<(), EngineError> {
        let obj_ref = self.restore_handle(handle)?;
        let jsc_val = self.to_jsc(value)?;
        unsafe {
            let prop_name = rust_str_to_jsc(key);
            let mut exception: JSValueRef = ptr::null();
            JSObjectSetProperty(
                self.ctx(),
                obj_ref as JSObjectRef,
                prop_name,
                jsc_val,
                kJSPropertyAttributeNone,
                &mut exception,
            );
            JSStringRelease(prop_name);
            check_exception(self.ctx(), exception)
        }
    }

    fn object_get(&self, handle: u64, key: &str) -> Result<JsValue, EngineError> {
        let obj_ref = self.restore_handle(handle)?;
        unsafe {
            let prop_name = rust_str_to_jsc(key);
            let mut exception: JSValueRef = ptr::null();
            let result = JSObjectGetProperty(
                self.ctx(),
                obj_ref as JSObjectRef,
                prop_name,
                &mut exception,
            );
            JSStringRelease(prop_name);
            check_exception(self.ctx(), exception)?;
            Ok(self.from_jsc_handle(result))
        }
    }

    fn array_new(&self) -> Result<JsValue, EngineError> {
        unsafe {
            let mut exception: JSValueRef = ptr::null();
            let arr = JSObjectMakeArray(self.ctx(), 0, ptr::null(), &mut exception);
            check_exception(self.ctx(), exception)?;
            let id = self.store_handle_typed(arr as JSValueRef, HandleKind::Array);
            Ok(JsValue::ArrayHandle(id))
        }
    }

    fn array_push(&self, handle: u64, value: &JsValue) -> Result<(), EngineError> {
        let arr_ref = self.restore_handle(handle)?;
        let jsc_val = self.to_jsc(value)?;
        unsafe {
            let length_name = rust_str_to_jsc("length");
            let mut exception: JSValueRef = ptr::null();
            let length_val = JSObjectGetProperty(
                self.ctx(),
                arr_ref as JSObjectRef,
                length_name,
                &mut exception,
            );
            JSStringRelease(length_name);
            check_exception(self.ctx(), exception)?;

            let mut ex2: JSValueRef = ptr::null();
            let length = JSValueToNumber(self.ctx(), length_val, &mut ex2) as u32;
            check_exception(self.ctx(), ex2)?;

            let mut ex3: JSValueRef = ptr::null();
            JSObjectSetPropertyAtIndex(
                self.ctx(),
                arr_ref as JSObjectRef,
                length,
                jsc_val,
                &mut ex3,
            );
            check_exception(self.ctx(), ex3)
        }
    }

    fn array_get(&self, handle: u64, index: u32) -> Result<JsValue, EngineError> {
        let arr_ref = self.restore_handle(handle)?;
        unsafe {
            let mut exception: JSValueRef = ptr::null();
            let result = JSObjectGetPropertyAtIndex(
                self.ctx(),
                arr_ref as JSObjectRef,
                index,
                &mut exception,
            );
            check_exception(self.ctx(), exception)?;
            Ok(self.from_jsc_handle(result))
        }
    }

    fn array_length(&self, handle: u64) -> Result<u32, EngineError> {
        let arr_ref = self.restore_handle(handle)?;
        unsafe {
            let length_name = rust_str_to_jsc("length");
            let mut exception: JSValueRef = ptr::null();
            let length_val = JSObjectGetProperty(
                self.ctx(),
                arr_ref as JSObjectRef,
                length_name,
                &mut exception,
            );
            JSStringRelease(length_name);
            check_exception(self.ctx(), exception)?;

            let mut ex2: JSValueRef = ptr::null();
            let length = JSValueToNumber(self.ctx(), length_val, &mut ex2);
            check_exception(self.ctx(), ex2)?;
            Ok(length as u32)
        }
    }

    fn call_function(&self, func_handle: u64, args: &[JsValue]) -> Result<JsValue, EngineError> {
        let func_ref = self.restore_handle(func_handle)?;
        unsafe {
            if !JSObjectIsFunction(self.ctx(), func_ref as JSObjectRef) {
                return Err(EngineError::TypeError(
                    "Value is not a function".to_string(),
                ));
            }

            let mut jsc_args: Vec<JSValueRef> = Vec::with_capacity(args.len());
            for a in args {
                jsc_args.push(self.to_jsc(a)?);
            }

            let mut exception: JSValueRef = ptr::null();
            let result = JSObjectCallAsFunction(
                self.ctx(),
                func_ref as JSObjectRef,
                ptr::null_mut(),
                jsc_args.len(),
                if jsc_args.is_empty() {
                    ptr::null()
                } else {
                    jsc_args.as_ptr()
                },
                &mut exception,
            );

            if !exception.is_null() {
                return Err(EngineError::JsException {
                    message: exception_to_string(self.ctx(), exception),
                });
            }

            Ok(self.from_jsc_handle(result))
        }
    }

    fn to_json(&self, handle: u64) -> Result<String, EngineError> {
        let val = self.restore_handle(handle)?;
        unsafe {
            let mut exception: JSValueRef = ptr::null();
            let json_str = JSValueCreateJSONString(self.ctx(), val, 0, &mut exception);
            check_exception(self.ctx(), exception)?;
            if json_str.is_null() {
                return Err(EngineError::TypeError(
                    "Value is not JSON-serializable".to_string(),
                ));
            }
            let result = jsc_str_to_rust(json_str);
            JSStringRelease(json_str);
            Ok(result)
        }
    }

    fn parse_json(&self, json: &str) -> Result<JsValue, EngineError> {
        unsafe {
            let jsc_str = rust_str_to_jsc(json);
            let val = JSValueMakeFromJSONString(self.ctx(), jsc_str);
            JSStringRelease(jsc_str);
            if val.is_null() {
                return Err(EngineError::JsException {
                    message: "Invalid JSON".to_string(),
                });
            }
            Ok(self.from_jsc_handle(val))
        }
    }

    fn register_global_fn(&self, name: &str, callback: HostCallback) -> Result<(), EngineError> {
        unsafe {
            let data = Box::new(HostFnData {
                callback: Rc::from(callback),
                handles: self.handles.clone(),
                next_handle: self.next_handle.clone(),
                handle_types: self.handle_types.clone(),
            });
            let data_ptr = Box::into_raw(data);
            self.host_fn_data.borrow_mut().push(data_ptr);

            let func_obj = JSObjectMake(self.ctx(), self.host_fn_class, data_ptr as *mut c_void);

            let prop_name = rust_str_to_jsc(name);
            let global = JSContextGetGlobalObject(self.ctx());
            let mut exception: JSValueRef = ptr::null();
            JSObjectSetProperty(
                self.ctx(),
                global,
                prop_name,
                func_obj as JSValueRef,
                kJSPropertyAttributeNone,
                &mut exception,
            );
            JSStringRelease(prop_name);
            check_exception(self.ctx(), exception)
        }
    }

    fn drop_handle(&self, handle: u64) {
        if let Some(val) = self.handles.borrow_mut().remove(&handle) {
            unsafe { JSValueUnprotect(self.ctx(), val) };
        }
        self.handle_types.borrow_mut().remove(&handle);
    }

    fn set_memory_limit(&self, _bytes: usize) {
        // JSC does not expose a public memory limit API.
    }

    fn set_max_stack_size(&self, _bytes: usize) {
        // JSC does not expose a public stack size limit API.
    }

    fn set_execution_timeout(&self, duration: Duration) {
        unsafe {
            let group = JSContextGetGroup(self.ctx());
            let seconds = duration.as_secs_f64();
            JSContextGroupSetExecutionTimeLimit(group, seconds, None, ptr::null_mut());
        }
    }

    fn memory_usage(&self) -> MemoryStats {
        let types = self.handle_types.borrow();
        let obj_count = types.values().filter(|&&k| k == HandleKind::Object).count() as i64;
        let array_count = types.values().filter(|&&k| k == HandleKind::Array).count() as i64;
        let func_count = types
            .values()
            .filter(|&&k| k == HandleKind::Function)
            .count() as i64;
        let total = obj_count + array_count + func_count;
        MemoryStats {
            malloc_size: 0,
            memory_used_size: total * std::mem::size_of::<*const ()>() as i64,
            atom_count: 0,
            str_count: 0,
            obj_count,
            prop_count: 0,
            js_func_count: func_count,
            c_func_count: self.host_fn_data.borrow().len() as i64,
            array_count,
        }
    }

    fn run_gc(&self) {
        unsafe { JSGarbageCollect(self.ctx()) };
    }

    fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        // Pre-register any file-based imports into module_sources
        if let Some(base) = self.file_loader_base.borrow().as_ref() {
            let mut sources = self.module_sources.borrow_mut();
            load_file_imports(code, base, &mut sources);
        }

        // Transform ESM → CJS using swc (handles all export patterns properly)
        let cjs = crate::transpiler::transform_esm_to_cjs(code).map_err(|e| {
            EngineError::JsException {
                message: e.to_string(),
            }
        })?;

        // Also register this module's CJS source so require() can find it
        self.module_sources
            .borrow_mut()
            .insert(name.to_string(), cjs.clone());

        // Sync all Rust-side module_sources into JS-side __builtin_sources
        // so that require() inside eval_module can resolve them.
        {
            let sources = self.module_sources.borrow();
            for (mod_name, mod_code) in sources.iter() {
                let escaped = mod_code
                    .replace('\\', "\\\\")
                    .replace('`', "\\`")
                    .replace('$', "\\$");
                let _ = self.eval(&format!(
                    "globalThis.__builtin_sources=globalThis.__builtin_sources||{{}};\
                     globalThis.__builtin_sources['{mod_name}']=`{escaped}`;"
                ));
            }
        }

        // Wrap CJS code in an IIFE that provides require/exports/module.
        // For async modules (top-level await), use async IIFE that returns a Promise.
        let has_await = code.contains("await ");
        let fn_kw = if has_await {
            "async function"
        } else {
            "function"
        };

        let wrapper = format!(
            r#"({fn_kw}() {{
var module = {{ exports: {{}} }};
var exports = module.exports;
var require = function(name) {{
  var s = (globalThis.__builtin_sources || {{}})[name];
  if (s) {{
    var m = {{ exports: {{}} }};
    var fn = new Function("module", "exports", "require", s);
    fn(m, m.exports, require);
    return m.exports;
  }}
  if (globalThis.require) return globalThis.require(name);
  throw new Error("Cannot find module '" + name + "'");
}};
{cjs}
return module.exports;
}})()"#,
        );

        unsafe {
            let script = rust_str_to_jsc(&wrapper);
            let source_url = rust_str_to_jsc(name);
            let mut exception: JSValueRef = ptr::null();
            let result = JSEvaluateScript(
                self.ctx(),
                script,
                ptr::null_mut(),
                source_url,
                1,
                &mut exception,
            );
            JSStringRelease(script);
            JSStringRelease(source_url);

            if !exception.is_null() {
                return Err(EngineError::JsException {
                    message: exception_to_string(self.ctx(), exception),
                });
            }

            if result.is_null() || JSValueIsUndefined(self.ctx(), result) {
                return Ok(JsValue::Undefined);
            }

            let id = self.store_handle_typed(result, HandleKind::Object);
            Ok(JsValue::ObjectHandle(id))
        }
    }

    fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError> {
        // For node: aliases (e.g. "node:path"), reuse already-transformed CJS from base name
        let cjs = if let Some(base) = name.strip_prefix("node:") {
            if let Some(existing) = self.module_sources.borrow().get(base).cloned() {
                existing
            } else {
                crate::transpiler::transform_esm_to_cjs(code).map_err(|e| {
                    EngineError::JsException {
                        message: e.to_string(),
                    }
                })?
            }
        } else {
            crate::transpiler::transform_esm_to_cjs(code).map_err(|e| EngineError::JsException {
                message: e.to_string(),
            })?
        };

        // Store CJS source in JS global so require() can find built-in modules
        let escaped = cjs
            .replace('\\', "\\\\")
            .replace('`', "\\`")
            .replace('$', "\\$");
        self.eval(&format!(
            "globalThis.__builtin_sources=globalThis.__builtin_sources||{{}};\
             globalThis.__builtin_sources['{name}']=`{escaped}`;"
        ))?;
        self.module_sources
            .borrow_mut()
            .insert(name.to_string(), cjs);
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Module helpers (standalone, no engine dependency)
// ---------------------------------------------------------------------------

/// Extracts the module name from `import ... from 'module'` or `import ... from "module"`.
fn extract_module_name(line: &str) -> Option<&str> {
    let from_idx = line.find(" from ")?;
    let after_from = &line[from_idx + 6..];
    let trimmed = after_from.trim().trim_end_matches(';');
    if (trimmed.starts_with('\'') && trimmed.ends_with('\''))
        || (trimmed.starts_with('"') && trimmed.ends_with('"'))
    {
        Some(&trimmed[1..trimmed.len() - 1])
    } else {
        None
    }
}

/// Scan code for import statements and load any relative imports from disk.
fn load_file_imports(code: &str, base: &std::path::Path, sources: &mut HashMap<String, String>) {
    for line in code.lines() {
        let trimmed = line.trim();
        if !trimmed.starts_with("import ") {
            continue;
        }
        let Some(mod_name) = extract_module_name(trimmed) else {
            continue;
        };
        if sources.contains_key(mod_name) {
            continue;
        }
        // Only load relative/absolute paths
        if !mod_name.starts_with('.') && !mod_name.starts_with('/') {
            continue;
        }
        let path = base.join(mod_name);
        // Try with extensions
        let candidates = [
            path.clone(),
            path.with_extension("js"),
            path.with_extension("ts"),
            path.with_extension("jsx"),
            path.with_extension("tsx"),
        ];
        for candidate in &candidates {
            if let Ok(content) = std::fs::read_to_string(candidate) {
                let mut source = content;
                // Transpile TS/TSX/JSX if needed
                let ext = candidate.extension().and_then(|e| e.to_str()).unwrap_or("");
                if ext == "tsx" || ext == "jsx" {
                    if let Ok(transformed) =
                        crate::transpiler::transform_jsx(&source, &Default::default())
                    {
                        source = transformed;
                    }
                } else if ext == "ts" {
                    if let Ok(stripped) = crate::transpiler::strip_types(&source) {
                        source = stripped;
                    }
                }
                sources.insert(mod_name.to_string(), source);
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_eval_integer() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("1 + 2").unwrap();
        assert_eq!(val, JsValue::Number(3.0));
    }

    #[test]
    fn test_eval_float() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("1.5 + 2.5").unwrap();
        assert_eq!(val, JsValue::Number(4.0));
    }

    #[test]
    fn test_eval_string() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("'hello' + ' world'").unwrap();
        assert_eq!(val, JsValue::String("hello world".to_string()));
    }

    #[test]
    fn test_eval_bool_true() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("true").unwrap();
        assert_eq!(val, JsValue::Bool(true));
    }

    #[test]
    fn test_eval_bool_false() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("false").unwrap();
        assert_eq!(val, JsValue::Bool(false));
    }

    #[test]
    fn test_eval_null() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("null").unwrap();
        assert_eq!(val, JsValue::Null);
    }

    #[test]
    fn test_eval_undefined() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("undefined").unwrap();
        assert_eq!(val, JsValue::Undefined);
    }

    #[test]
    fn test_eval_object() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("({a: 1, b: 2})").unwrap();
        match val {
            JsValue::Object(json) => {
                assert!(json.contains("\"a\""));
                assert!(json.contains("\"b\""));
            }
            other => panic!("Expected Object, got {:?}", other),
        }
    }

    #[test]
    fn test_eval_array() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("[1, 2, 3]").unwrap();
        match val {
            JsValue::Array(json) => {
                assert_eq!(json, "[1,2,3]");
            }
            other => panic!("Expected Array, got {:?}", other),
        }
    }

    #[test]
    fn test_eval_function() {
        let engine = JscEngine::new().unwrap();
        let val = engine.eval("(function() {})").unwrap();
        assert_eq!(val, JsValue::Function);
    }

    #[test]
    fn test_eval_throw_error() {
        let engine = JscEngine::new().unwrap();
        let result = engine.eval("throw new Error('boom')");
        assert!(result.is_err());
        let err = result.unwrap_err();
        match err {
            EngineError::JsException { message } => {
                assert!(message.contains("boom"), "Error message: {message}");
            }
            other => panic!("Expected JsException, got {:?}", other),
        }
    }

    #[test]
    fn test_eval_syntax_error() {
        let engine = JscEngine::new().unwrap();
        let result = engine.eval("if (");
        assert!(result.is_err());
    }

    #[test]
    fn test_eval_reference_error() {
        let engine = JscEngine::new().unwrap();
        let result = engine.eval("undeclaredVariable");
        assert!(result.is_err());
    }

    #[test]
    fn test_eval_multiline() {
        let engine = JscEngine::new().unwrap();
        let val = engine
            .eval(
                r#"
            let x = 10;
            let y = 20;
            x + y
        "#,
            )
            .unwrap();
        assert_eq!(val, JsValue::Number(30.0));
    }

    #[test]
    fn test_object_new_set_get() {
        let engine = JscEngine::new().unwrap();
        let obj = engine.object_new().unwrap();
        let handle = match obj {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        engine
            .object_set(handle, "x", &JsValue::Number(42.0))
            .unwrap();
        let val = engine.object_get(handle, "x").unwrap();
        assert_eq!(val, JsValue::Number(42.0));
    }

    #[test]
    fn test_object_set_string() {
        let engine = JscEngine::new().unwrap();
        let JsValue::ObjectHandle(h) = engine.object_new().unwrap() else {
            panic!()
        };
        engine
            .object_set(h, "name", &JsValue::String("Alice".into()))
            .unwrap();
        let val = engine.object_get(h, "name").unwrap();
        assert_eq!(val, JsValue::String("Alice".into()));
    }

    #[test]
    fn test_array_new_push_get_length() {
        let engine = JscEngine::new().unwrap();
        let JsValue::ArrayHandle(h) = engine.array_new().unwrap() else {
            panic!()
        };
        engine.array_push(h, &JsValue::Number(10.0)).unwrap();
        engine.array_push(h, &JsValue::Number(20.0)).unwrap();
        engine.array_push(h, &JsValue::Number(30.0)).unwrap();

        assert_eq!(engine.array_length(h).unwrap(), 3);
        assert_eq!(engine.array_get(h, 0).unwrap(), JsValue::Number(10.0));
        assert_eq!(engine.array_get(h, 2).unwrap(), JsValue::Number(30.0));
    }

    #[test]
    fn test_call_function() {
        let engine = JscEngine::new().unwrap();
        let ns = engine
            .eval_module("export function add(a, b) { return a + b; }", "test_call")
            .unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let add_val = engine.object_get(h, "add").unwrap();
        let func_h = match add_val {
            JsValue::FunctionHandle(id) => id,
            other => panic!("Expected FunctionHandle, got {:?}", other),
        };
        let result = engine
            .call_function(func_h, &[JsValue::Number(3.0), JsValue::Number(4.0)])
            .unwrap();
        assert_eq!(result, JsValue::Number(7.0));
    }

    #[test]
    fn test_to_json() {
        let engine = JscEngine::new().unwrap();
        let JsValue::ObjectHandle(h) = engine.object_new().unwrap() else {
            panic!()
        };
        engine.object_set(h, "a", &JsValue::Number(1.0)).unwrap();
        engine
            .object_set(h, "b", &JsValue::String("hello".into()))
            .unwrap();
        let json = engine.to_json(h).unwrap();
        assert!(json.contains("\"a\""));
        assert!(json.contains("\"hello\""));
    }

    #[test]
    fn test_from_json() {
        let engine = JscEngine::new().unwrap();
        let val = engine.parse_json(r#"{"x": 42, "y": [1,2,3]}"#).unwrap();
        let h = match val {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let x = engine.object_get(h, "x").unwrap();
        assert_eq!(x, JsValue::Number(42.0));

        let y = engine.object_get(h, "y").unwrap();
        let yh = match y {
            JsValue::ArrayHandle(id) => id,
            other => panic!("Expected ArrayHandle, got {:?}", other),
        };
        assert_eq!(engine.array_length(yh).unwrap(), 3);
        assert_eq!(engine.array_get(yh, 0).unwrap(), JsValue::Number(1.0));
    }

    #[test]
    fn test_register_global_fn() {
        let engine = JscEngine::new().unwrap();
        engine
            .register_global_fn(
                "hostAdd",
                Box::new(|args| {
                    let a = match &args[0] {
                        JsValue::Number(n) => *n,
                        _ => 0.0,
                    };
                    let b = match &args[1] {
                        JsValue::Number(n) => *n,
                        _ => 0.0,
                    };
                    Ok(JsValue::Number(a + b))
                }),
            )
            .unwrap();
        let result = engine.eval("hostAdd(10, 20)").unwrap();
        assert_eq!(result, JsValue::Number(30.0));
    }

    #[test]
    fn test_register_global_fn_string() {
        let engine = JscEngine::new().unwrap();
        engine
            .register_global_fn(
                "greet",
                Box::new(|args| {
                    let name = match &args[0] {
                        JsValue::String(s) => s.clone(),
                        _ => "world".to_string(),
                    };
                    Ok(JsValue::String(format!("Hello, {name}!")))
                }),
            )
            .unwrap();
        let result = engine.eval("greet('Rust')").unwrap();
        assert_eq!(result, JsValue::String("Hello, Rust!".into()));
    }

    #[test]
    fn test_drop_handle() {
        let engine = JscEngine::new().unwrap();
        let JsValue::ObjectHandle(h) = engine.object_new().unwrap() else {
            panic!()
        };
        engine.drop_handle(h);
        let result = engine.object_get(h, "x");
        assert!(result.is_err());
        match result.unwrap_err() {
            EngineError::InvalidHandle(id) => assert_eq!(id, h),
            other => panic!("Expected InvalidHandle, got {:?}", other),
        }
    }

    #[test]
    fn test_invalid_handle() {
        let engine = JscEngine::new().unwrap();
        let result = engine.object_get(9999, "x");
        assert!(matches!(
            result.unwrap_err(),
            EngineError::InvalidHandle(9999)
        ));
    }

    #[test]
    fn test_execution_timeout() {
        let engine = JscEngine::new().unwrap();
        engine.set_execution_timeout(std::time::Duration::from_millis(100));
        let result = engine.eval("while(true){}");
        assert!(result.is_err());
    }

    #[test]
    fn test_memory_usage() {
        let engine = JscEngine::new().unwrap();
        let _obj = engine.object_new().unwrap();
        let _arr = engine.array_new().unwrap();
        let stats = engine.memory_usage();
        assert_eq!(stats.obj_count, 1);
        assert_eq!(stats.array_count, 1);
        assert!(stats.memory_used_size > 0);
    }

    #[test]
    fn test_run_gc() {
        let engine = JscEngine::new().unwrap();
        engine.eval("var x = {a: 1}").unwrap();
        engine.run_gc();
        let val = engine.eval("1 + 1").unwrap();
        assert_eq!(val, JsValue::Number(2.0));
    }

    #[test]
    fn test_eval_module_basic() {
        let engine = JscEngine::new().unwrap();
        let ns = engine.eval_module("export const x = 42;", "test").unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let x = engine.object_get(h, "x").unwrap();
        assert_eq!(x, JsValue::Number(42.0));
    }

    #[test]
    fn test_register_module_and_import() {
        let engine = JscEngine::new().unwrap();
        engine
            .register_module("helper", "export const PI = 3.14;")
            .unwrap();
        let ns = engine
            .eval_module(
                "import { PI } from 'helper'; export const tau = PI * 2;",
                "main",
            )
            .unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let tau = engine.object_get(h, "tau").unwrap();
        assert_eq!(tau, JsValue::Number(6.28));
    }

    #[test]
    fn test_eval_module_export_function() {
        let engine = JscEngine::new().unwrap();
        let ns = engine
            .eval_module("export function add(a, b) { return a + b; }", "math")
            .unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let add_val = engine.object_get(h, "add").unwrap();
        let func_h = match add_val {
            JsValue::FunctionHandle(id) => id,
            other => panic!("Expected FunctionHandle, got {:?}", other),
        };
        let result = engine
            .call_function(func_h, &[JsValue::Number(3.0), JsValue::Number(4.0)])
            .unwrap();
        assert_eq!(result, JsValue::Number(7.0));
    }

    #[test]
    fn test_eval_module_multiline_function() {
        let engine = JscEngine::new().unwrap();
        let ns = engine
            .eval_module(
                r#"
export function greet(name) {
    const prefix = "Hello";
    return prefix + ", " + name + "!";
}
"#,
                "multiline",
            )
            .unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let greet = engine.object_get(h, "greet").unwrap();
        let func_h = match greet {
            JsValue::FunctionHandle(id) => id,
            other => panic!("Expected FunctionHandle, got {:?}", other),
        };
        let result = engine
            .call_function(func_h, &[JsValue::String("World".into())])
            .unwrap();
        assert_eq!(result, JsValue::String("Hello, World!".into()));
    }

    #[test]
    fn test_eval_module_string_with_semicolons() {
        let engine = JscEngine::new().unwrap();
        let ns = engine
            .eval_module(r#"export const msg = "hello; world; foo";"#, "semicolons")
            .unwrap();
        let h = match ns {
            JsValue::ObjectHandle(id) => id,
            other => panic!("Expected ObjectHandle, got {:?}", other),
        };
        let msg = engine.object_get(h, "msg").unwrap();
        assert_eq!(msg, JsValue::String("hello; world; foo".into()));
    }
}
