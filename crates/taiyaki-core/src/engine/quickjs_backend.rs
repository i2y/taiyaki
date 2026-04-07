use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::rc::Rc;
use std::time::{Duration, Instant};

use rquickjs::{Context, Module, Object, Persistent, Runtime, Value};

use super::convert::{
    eval_with_catch, json_stringify, jsvalue_to_qjs, qjs_to_jsvalue_handle, register_host_fn,
};
use super::module_store::NodeModuleResolver;
use super::module_store::{SharedLoader, SharedResolver};
use super::{EngineError, HostCallback, JsEngine, JsValue, MemoryStats};

pub struct QuickJsEngine {
    runtime: Runtime,
    context: Context,
    handles: Rc<RefCell<HashMap<u64, Persistent<Value<'static>>>>>,
    next_handle: Rc<Cell<u64>>,
    module_sources: Rc<RefCell<HashMap<String, String>>>,
}

impl Drop for QuickJsEngine {
    fn drop(&mut self) {
        // Persistent handles must be dropped before the Runtime,
        // otherwise QuickJS will abort on cleanup.
        self.handles.borrow_mut().clear();
    }
}

impl QuickJsEngine {
    pub fn new() -> Result<Self, EngineError> {
        let runtime = Runtime::new().map_err(|e| EngineError::InitError(e.to_string()))?;
        let context = Context::full(&runtime).map_err(|e| EngineError::InitError(e.to_string()))?;
        let module_sources = Rc::new(RefCell::new(HashMap::new()));
        runtime.set_loader(
            SharedResolver {
                modules: module_sources.clone(),
            },
            SharedLoader {
                modules: module_sources.clone(),
            },
        );
        Ok(Self {
            runtime,
            context,
            handles: Rc::new(RefCell::new(HashMap::new())),
            next_handle: Rc::new(Cell::new(0)),
            module_sources,
        })
    }

    pub(crate) fn store_persistent<'js>(&self, ctx: &rquickjs::Ctx<'js>, value: Value<'js>) -> u64 {
        let id = self.next_handle.get();
        self.next_handle.set(id + 1);
        let persistent = Persistent::save(ctx, value);
        self.handles.borrow_mut().insert(id, persistent);
        id
    }

    fn to_qjs<'js>(
        &self,
        ctx: &rquickjs::Ctx<'js>,
        val: &JsValue,
    ) -> Result<Value<'js>, EngineError> {
        let handles = &self.handles;
        jsvalue_to_qjs(ctx, val, |id| {
            let store = handles.borrow();
            let persistent = store.get(&id).ok_or(EngineError::InvalidHandle(id))?;
            Ok(persistent.clone().restore(ctx)?)
        })
    }

    fn qjs_to_jsvalue<'js>(
        &self,
        ctx: &rquickjs::Ctx<'js>,
        value: Value<'js>,
    ) -> Result<JsValue, EngineError> {
        let handles = &self.handles;
        let next_handle = &self.next_handle;
        qjs_to_jsvalue_handle(value, |v| {
            let id = next_handle.get();
            next_handle.set(id + 1);
            handles.borrow_mut().insert(id, Persistent::save(ctx, v));
            id
        })
    }

    fn restore_handle<'js>(
        &self,
        ctx: &rquickjs::Ctx<'js>,
        handle: u64,
    ) -> Result<Value<'js>, EngineError> {
        let handles = self.handles.borrow();
        let persistent = handles
            .get(&handle)
            .ok_or(EngineError::InvalidHandle(handle))?;
        Ok(persistent.clone().restore(ctx)?)
    }
}

impl JsEngine for QuickJsEngine {
    fn eval(&self, code: &str) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| eval_with_catch(&ctx, code))
    }

    fn object_new(&self) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let obj = Object::new(ctx.clone())?;
            let id = self.store_persistent(&ctx, obj.into_value());
            Ok(JsValue::ObjectHandle(id))
        })
    }

    fn object_set(&self, handle: u64, key: &str, value: &JsValue) -> Result<(), EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            let obj = val
                .into_object()
                .ok_or_else(|| EngineError::TypeError("Value is not an object".to_string()))?;
            let js_val = self.to_qjs(&ctx, value)?;
            obj.set(key, js_val)?;
            Ok(())
        })
    }

    fn object_get(&self, handle: u64, key: &str) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            let obj = val
                .into_object()
                .ok_or_else(|| EngineError::TypeError("Value is not an object".to_string()))?;
            let result: Value<'_> = obj.get(key)?;
            self.qjs_to_jsvalue(&ctx, result)
        })
    }

    fn array_new(&self) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let arr = rquickjs::Array::new(ctx.clone())?;
            let id = self.store_persistent(&ctx, arr.into_value());
            Ok(JsValue::ArrayHandle(id))
        })
    }

    fn array_push(&self, handle: u64, value: &JsValue) -> Result<(), EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            let arr = val
                .into_array()
                .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
            let js_val = self.to_qjs(&ctx, value)?;
            let len = arr.len();
            arr.set(len, js_val)?;
            Ok(())
        })
    }

    fn array_get(&self, handle: u64, index: u32) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            let arr = val
                .into_array()
                .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
            let result: Value<'_> = arr.get(index as usize)?;
            self.qjs_to_jsvalue(&ctx, result)
        })
    }

    fn array_length(&self, handle: u64) -> Result<u32, EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            let arr = val
                .into_array()
                .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
            Ok(arr.len() as u32)
        })
    }

    fn call_function(&self, func_handle: u64, args: &[JsValue]) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, func_handle)?;
            let func = val
                .into_function()
                .ok_or_else(|| EngineError::TypeError("Value is not a function".to_string()))?;
            let js_args: Vec<Value<'_>> = args
                .iter()
                .map(|a| self.to_qjs(&ctx, a))
                .collect::<Result<_, _>>()?;
            let result: Value<'_> = func.call((rquickjs::function::Rest(js_args),))?;
            self.qjs_to_jsvalue(&ctx, result)
        })
    }

    fn to_json(&self, handle: u64) -> Result<String, EngineError> {
        self.context.with(|ctx| {
            let val = self.restore_handle(&ctx, handle)?;
            json_stringify(&ctx, &val)
        })
    }

    fn parse_json(&self, json: &str) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let val: Value<'_> = ctx.json_parse(json)?;
            self.qjs_to_jsvalue(&ctx, val)
        })
    }

    fn register_global_fn(&self, name: &str, callback: HostCallback) -> Result<(), EngineError> {
        let cb = Rc::new(callback);
        let handles = self.handles.clone();

        self.context
            .with(|ctx| register_host_fn(&ctx, name, cb, handles))
    }

    fn drop_handle(&self, handle: u64) {
        self.handles.borrow_mut().remove(&handle);
    }

    fn set_memory_limit(&self, bytes: usize) {
        self.runtime.set_memory_limit(bytes);
    }

    fn set_max_stack_size(&self, bytes: usize) {
        self.runtime.set_max_stack_size(bytes);
    }

    fn set_execution_timeout(&self, duration: Duration) {
        let deadline = Instant::now() + duration;
        self.runtime
            .set_interrupt_handler(Some(Box::new(move || Instant::now() >= deadline)));
    }

    fn memory_usage(&self) -> MemoryStats {
        self.runtime.memory_usage().into()
    }

    fn run_gc(&self) {
        self.runtime.run_gc();
    }

    fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| {
            let module = Module::declare(ctx.clone(), name, code)?;
            let (module, promise) = module.eval()?;
            promise.finish::<()>()?;
            let ns = module.namespace()?;
            let id = self.store_persistent(&ctx, ns.into_value());
            Ok(JsValue::ObjectHandle(id))
        })
    }

    fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError> {
        self.module_sources
            .borrow_mut()
            .insert(name.to_string(), code.to_string());
        Ok(())
    }

    fn get_global(&self, name: &str) -> Result<JsValue, EngineError> {
        let name = name.to_string();
        self.context.with(|ctx| {
            let globals = ctx.globals();
            let val: Value<'_> = globals.get(&*name).map_err(|e| EngineError::JsException {
                message: e.to_string(),
            })?;
            qjs_to_jsvalue_handle(val, |v| self.store_persistent(&ctx, v))
        })
    }
}

impl QuickJsEngine {
    /// Enables file-based module resolution from the given base path.
    /// Composes with the existing builtin resolver/loader.
    pub fn enable_file_loader(&self, base_path: &std::path::Path) {
        use rquickjs::loader::{FileResolver, ScriptLoader};
        self.runtime.set_loader(
            (
                SharedResolver {
                    modules: self.module_sources.clone(),
                },
                NodeModuleResolver::new(),
                FileResolver::default().with_path(base_path.to_str().unwrap_or(".")),
            ),
            (
                SharedLoader {
                    modules: self.module_sources.clone(),
                },
                ScriptLoader::default(),
            ),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_eval_integer() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("1 + 2").unwrap();
        assert_eq!(val, JsValue::Number(3.0));
    }

    #[test]
    fn test_eval_float() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("1.5 + 2.5").unwrap();
        assert_eq!(val, JsValue::Number(4.0));
    }

    #[test]
    fn test_eval_string() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("'hello' + ' world'").unwrap();
        assert_eq!(val, JsValue::String("hello world".to_string()));
    }

    #[test]
    fn test_eval_bool_true() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("true").unwrap();
        assert_eq!(val, JsValue::Bool(true));
    }

    #[test]
    fn test_eval_bool_false() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("false").unwrap();
        assert_eq!(val, JsValue::Bool(false));
    }

    #[test]
    fn test_eval_null() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("null").unwrap();
        assert_eq!(val, JsValue::Null);
    }

    #[test]
    fn test_eval_undefined() {
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("undefined").unwrap();
        assert_eq!(val, JsValue::Undefined);
    }

    #[test]
    fn test_eval_object() {
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
        let val = engine.eval("(function() {})").unwrap();
        assert_eq!(val, JsValue::Function);
    }

    #[test]
    fn test_eval_throw_error() {
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
        let result = engine.eval("if (");
        assert!(result.is_err());
    }

    #[test]
    fn test_eval_reference_error() {
        let engine = QuickJsEngine::new().unwrap();
        let result = engine.eval("undeclaredVariable");
        assert!(result.is_err());
    }

    #[test]
    fn test_eval_multiline() {
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
        engine.eval("function add(a, b) { return a + b; }").unwrap();
        assert_eq!(engine.eval("add").unwrap(), JsValue::Function);

        let func_handle = engine.context.with(|ctx| {
            let func: Value<'_> = ctx.globals().get("add").unwrap();
            engine.store_persistent(&ctx, func)
        });

        let result = engine
            .call_function(func_handle, &[JsValue::Number(3.0), JsValue::Number(4.0)])
            .unwrap();
        assert_eq!(result, JsValue::Number(7.0));
    }

    #[test]
    fn test_to_json() {
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
        let result = engine.object_get(9999, "x");
        assert!(matches!(
            result.unwrap_err(),
            EngineError::InvalidHandle(9999)
        ));
    }

    #[test]
    fn test_execution_timeout() {
        let engine = QuickJsEngine::new().unwrap();
        engine.set_execution_timeout(std::time::Duration::from_millis(100));
        let result = engine.eval("while(true){}");
        assert!(result.is_err());
    }

    #[test]
    fn test_memory_usage() {
        let engine = QuickJsEngine::new().unwrap();
        engine.eval("var x = [1,2,3]").unwrap();
        let stats = engine.memory_usage();
        assert!(stats.memory_used_size > 0);
        assert!(stats.obj_count > 0);
    }

    #[test]
    fn test_run_gc() {
        let engine = QuickJsEngine::new().unwrap();
        engine.eval("var x = {a: 1}").unwrap();
        engine.run_gc();
        // Should not crash; engine still usable
        let val = engine.eval("1 + 1").unwrap();
        assert_eq!(val, JsValue::Number(2.0));
    }

    #[test]
    fn test_set_memory_limit() {
        let engine = QuickJsEngine::new().unwrap();
        engine.set_memory_limit(1024 * 64); // 64KB
        let result = engine.eval(
            "var a = []; for(var i = 0; i < 100000; i++) a.push({x: i, y: 'hello'.repeat(100)})",
        );
        assert!(result.is_err());
    }

    #[test]
    fn test_eval_module_basic() {
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
        let engine = QuickJsEngine::new().unwrap();
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
}
