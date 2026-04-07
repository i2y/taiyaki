use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::rc::Rc;
use std::time::{Duration, Instant};

use rquickjs::{AsyncContext, AsyncRuntime, Module, Object, Persistent, Value};

use super::convert::{
    eval_with_catch, json_stringify, jsvalue_to_qjs, qjs_to_jsvalue_handle, register_host_fn,
};
use super::module_store::{SharedLoader, SharedResolver};
use super::{EngineError, HostCallback, JsValue, MemoryStats};

pub struct AsyncQuickJsEngine {
    runtime: AsyncRuntime,
    context: AsyncContext,
    handles: Rc<RefCell<HashMap<u64, Persistent<Value<'static>>>>>,
    next_handle: Rc<Cell<u64>>,
    module_sources: Rc<RefCell<HashMap<String, String>>>,
}

impl AsyncQuickJsEngine {
    pub async fn new() -> Result<Self, EngineError> {
        let runtime = AsyncRuntime::new().map_err(|e| EngineError::InitError(e.to_string()))?;
        let context = AsyncContext::full(&runtime)
            .await
            .map_err(|e| EngineError::InitError(e.to_string()))?;
        let module_sources = Rc::new(RefCell::new(HashMap::new()));
        runtime
            .set_loader(
                SharedResolver {
                    modules: module_sources.clone(),
                },
                SharedLoader {
                    modules: module_sources.clone(),
                },
            )
            .await;
        Ok(Self {
            runtime,
            context,
            handles: Rc::new(RefCell::new(HashMap::new())),
            next_handle: Rc::new(Cell::new(0)),
            module_sources,
        })
    }

    fn store_persistent<'js>(&self, ctx: &rquickjs::Ctx<'js>, value: Value<'js>) -> u64 {
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

    pub async fn eval(&self, code: &str) -> Result<JsValue, EngineError> {
        self.context.with(|ctx| eval_with_catch(&ctx, code)).await
    }

    /// Evaluates code and drives the event loop to resolve all pending promises.
    pub async fn eval_async(&self, code: &str) -> Result<JsValue, EngineError> {
        let result = self.eval(code).await?;
        self.idle().await;
        Ok(result)
    }

    pub async fn object_new(&self) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let obj = Object::new(ctx.clone())?;
                let id = self.store_persistent(&ctx, obj.into_value());
                Ok(JsValue::ObjectHandle(id))
            })
            .await
    }

    pub async fn object_set(
        &self,
        handle: u64,
        key: &str,
        value: &JsValue,
    ) -> Result<(), EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                let obj = val
                    .into_object()
                    .ok_or_else(|| EngineError::TypeError("Value is not an object".to_string()))?;
                let js_val = self.to_qjs(&ctx, value)?;
                obj.set(key, js_val)?;
                Ok(())
            })
            .await
    }

    pub async fn object_get(&self, handle: u64, key: &str) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                let obj = val
                    .into_object()
                    .ok_or_else(|| EngineError::TypeError("Value is not an object".to_string()))?;
                let result: Value<'_> = obj.get(key)?;
                self.qjs_to_jsvalue(&ctx, result)
            })
            .await
    }

    pub async fn array_new(&self) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let arr = rquickjs::Array::new(ctx.clone())?;
                let id = self.store_persistent(&ctx, arr.into_value());
                Ok(JsValue::ArrayHandle(id))
            })
            .await
    }

    pub async fn array_push(&self, handle: u64, value: &JsValue) -> Result<(), EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                let arr = val
                    .into_array()
                    .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
                let js_val = self.to_qjs(&ctx, value)?;
                let len = arr.len();
                arr.set(len, js_val)?;
                Ok(())
            })
            .await
    }

    pub async fn array_get(&self, handle: u64, index: u32) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                let arr = val
                    .into_array()
                    .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
                let result: Value<'_> = arr.get(index as usize)?;
                self.qjs_to_jsvalue(&ctx, result)
            })
            .await
    }

    pub async fn array_length(&self, handle: u64) -> Result<u32, EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                let arr = val
                    .into_array()
                    .ok_or_else(|| EngineError::TypeError("Value is not an array".to_string()))?;
                Ok(arr.len() as u32)
            })
            .await
    }

    pub async fn call_function(
        &self,
        func_handle: u64,
        args: &[JsValue],
    ) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
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
            .await
    }

    pub async fn to_json(&self, handle: u64) -> Result<String, EngineError> {
        self.context
            .with(|ctx| {
                let val = self.restore_handle(&ctx, handle)?;
                json_stringify(&ctx, &val)
            })
            .await
    }

    pub async fn parse_json(&self, json: &str) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let val: Value<'_> = ctx.json_parse(json)?;
                self.qjs_to_jsvalue(&ctx, val)
            })
            .await
    }

    pub async fn register_global_fn(
        &self,
        name: &str,
        callback: HostCallback,
    ) -> Result<(), EngineError> {
        let cb = Rc::new(callback);
        let handles = self.handles.clone();
        let name = name.to_string();

        self.context
            .with(|ctx| register_host_fn(&ctx, &name, cb, handles))
            .await
    }

    pub fn drop_handle(&self, handle: u64) {
        self.handles.borrow_mut().remove(&handle);
    }

    pub async fn set_memory_limit(&self, bytes: usize) {
        self.runtime.set_memory_limit(bytes).await;
    }

    pub async fn set_max_stack_size(&self, bytes: usize) {
        self.runtime.set_max_stack_size(bytes).await;
    }

    pub async fn set_execution_timeout(&self, duration: Duration) {
        let deadline = Instant::now() + duration;
        self.runtime
            .set_interrupt_handler(Some(Box::new(move || Instant::now() >= deadline)))
            .await;
    }

    pub async fn memory_usage(&self) -> MemoryStats {
        self.runtime.memory_usage().await.into()
    }

    pub async fn run_gc(&self) {
        self.runtime.run_gc().await;
    }

    pub async fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        self.context
            .with(|ctx| {
                let module = Module::declare(ctx.clone(), name, code)?;
                let (module, promise) = module.eval()?;
                promise.finish::<()>()?;
                let ns = module.namespace()?;
                let id = self.store_persistent(&ctx, ns.into_value());
                Ok(JsValue::ObjectHandle(id))
            })
            .await
    }

    /// Evaluates a module and drives the event loop to resolve all pending promises.
    /// Unlike `eval_module`, this does not block on the module promise, allowing
    /// top-level await with async operations (fetch, setTimeout, etc.).
    pub async fn eval_module_async(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        let ns_handle = self
            .context
            .with(|ctx| {
                let module = Module::declare(ctx.clone(), name, code)?;
                let (module, _promise) = module.eval()?;
                // Don't block on promise.finish() — let idle() drive async ops
                let ns = module.namespace()?;
                let id = self.store_persistent(&ctx, ns.into_value());
                Ok::<_, EngineError>(JsValue::ObjectHandle(id))
            })
            .await?;
        self.idle().await;
        Ok(ns_handle)
    }

    pub fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError> {
        self.module_sources
            .borrow_mut()
            .insert(name.to_string(), code.to_string());
        Ok(())
    }

    /// Gets a global property by name.
    pub async fn get_global(&self, name: &str) -> Result<JsValue, EngineError> {
        let name = name.to_string();
        self.context
            .with(|ctx| {
                let globals = ctx.globals();
                let val: Value<'_> = globals
                    .get(&*name)
                    .map_err(|e| EngineError::JsException {
                        message: e.to_string(),
                    })?;
                qjs_to_jsvalue_handle(val, |v| self.store_persistent(&ctx, v))
            })
            .await
    }

    /// Drives all pending jobs and spawned futures to completion.
    pub async fn idle(&self) {
        self.runtime.idle().await;
    }

    /// Provides raw access to the async context for registering
    /// Promise-returning functions (fetch, setTimeout, etc.).
    pub async fn with_context<F, R>(&self, f: F) -> R
    where
        F: for<'js> FnOnce(rquickjs::Ctx<'js>) -> R,
        R: 'static,
    {
        self.context.with(f).await
    }

    /// Enables file-based module resolution from the given base path.
    pub async fn enable_file_loader(&self, base_path: &std::path::Path) {
        use rquickjs::loader::{FileResolver, ScriptLoader};
        let modules = self.module_sources.clone();
        let base = base_path.to_str().unwrap_or(".").to_string();
        self.runtime
            .set_loader(
                (
                    SharedResolver {
                        modules: modules.clone(),
                    },
                    FileResolver::default().with_path(&base),
                ),
                (SharedLoader { modules }, ScriptLoader::default()),
            )
            .await;
    }
}

// ---------------------------------------------------------------------------
// AsyncJsEngine trait implementation
// ---------------------------------------------------------------------------

impl super::AsyncJsEngine for AsyncQuickJsEngine {
    async fn eval(&self, code: &str) -> Result<super::JsValue, super::EngineError> {
        self.eval(code).await
    }

    async fn eval_async(&self, code: &str) -> Result<super::JsValue, super::EngineError> {
        self.eval_async(code).await
    }

    async fn eval_module(
        &self,
        code: &str,
        name: &str,
    ) -> Result<super::JsValue, super::EngineError> {
        self.eval_module(code, name).await
    }

    async fn eval_module_async(
        &self,
        code: &str,
        name: &str,
    ) -> Result<super::JsValue, super::EngineError> {
        self.eval_module_async(code, name).await
    }

    fn register_module(&self, name: &str, code: &str) -> Result<(), super::EngineError> {
        AsyncQuickJsEngine::register_module(self, name, code)
    }

    async fn register_global_fn(
        &self,
        name: &str,
        callback: super::HostCallback,
    ) -> Result<(), super::EngineError> {
        self.register_global_fn(name, callback).await
    }

    async fn register_async_host_fn(
        &self,
        name: &str,
        f: super::AsyncHostFn,
    ) -> Result<(), super::EngineError> {
        use std::sync::Arc;
        let f = Arc::new(f);
        let name = name.to_string();

        self.context
            .with(move |ctx| -> Result<(), super::EngineError> {
                use rquickjs::Function;
                use rquickjs::function::Async;

                let func = Function::new(
                    ctx.clone(),
                    Async(
                        move |args: rquickjs::function::Rest<rquickjs::Coerced<String>>| {
                            let args_vec: Vec<String> = args.0.into_iter().map(|c| c.0).collect();
                            let f = f.clone();
                            async move {
                                f(args_vec).await.map_err(|e| {
                                    rquickjs::Error::new_from_js_message("async", "Error", e)
                                })
                            }
                        },
                    ),
                )
                .map_err(|e| super::EngineError::JsException {
                    message: e.to_string(),
                })?;
                ctx.globals().set(name.as_str(), func)?;
                Ok(())
            })
            .await
    }

    async fn enable_file_loader(&self, base_path: &std::path::Path) {
        self.enable_file_loader(base_path).await
    }

    async fn get_global(&self, name: &str) -> Result<super::JsValue, super::EngineError> {
        self.get_global(name).await
    }

    async fn idle(&self) {
        self.idle().await
    }
}

impl Drop for AsyncQuickJsEngine {
    fn drop(&mut self) {
        // Persistent handles must be dropped before the Runtime.
        self.handles.borrow_mut().clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block_on<F: std::future::Future>(f: F) -> F::Output {
        // Minimal single-threaded executor for tests.
        // Uses rquickjs's async-lock internally, no tokio needed.
        struct Waker;
        impl std::task::Wake for Waker {
            fn wake(self: std::sync::Arc<Self>) {}
        }
        let waker = std::task::Waker::from(std::sync::Arc::new(Waker));
        let mut cx = std::task::Context::from_waker(&waker);
        let mut f = std::pin::pin!(f);
        loop {
            match f.as_mut().poll(&mut cx) {
                std::task::Poll::Ready(v) => return v,
                std::task::Poll::Pending => {
                    // Busy-loop for tests; fine for unit tests.
                    std::thread::yield_now();
                }
            }
        }
    }

    #[test]
    fn test_async_eval_integer() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let val = engine.eval("1 + 2").await.unwrap();
            assert_eq!(val, JsValue::Number(3.0));
        });
    }

    #[test]
    fn test_async_eval_string() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let val = engine.eval("'hello' + ' world'").await.unwrap();
            assert_eq!(val, JsValue::String("hello world".to_string()));
        });
    }

    #[test]
    fn test_async_eval_bool() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            assert_eq!(engine.eval("true").await.unwrap(), JsValue::Bool(true));
            assert_eq!(engine.eval("false").await.unwrap(), JsValue::Bool(false));
        });
    }

    #[test]
    fn test_async_eval_null_undefined() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            assert_eq!(engine.eval("null").await.unwrap(), JsValue::Null);
            assert_eq!(engine.eval("undefined").await.unwrap(), JsValue::Undefined);
        });
    }

    #[test]
    fn test_async_eval_error() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let result = engine.eval("throw new Error('boom')").await;
            assert!(result.is_err());
            match result.unwrap_err() {
                EngineError::JsException { message } => {
                    assert!(message.contains("boom"));
                }
                other => panic!("Expected JsException, got {:?}", other),
            }
        });
    }

    #[test]
    fn test_async_object_ops() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let JsValue::ObjectHandle(h) = engine.object_new().await.unwrap() else {
                panic!("Expected ObjectHandle");
            };
            engine
                .object_set(h, "x", &JsValue::Number(42.0))
                .await
                .unwrap();
            let val = engine.object_get(h, "x").await.unwrap();
            assert_eq!(val, JsValue::Number(42.0));
        });
    }

    #[test]
    fn test_async_array_ops() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let JsValue::ArrayHandle(h) = engine.array_new().await.unwrap() else {
                panic!("Expected ArrayHandle");
            };
            engine.array_push(h, &JsValue::Number(10.0)).await.unwrap();
            engine.array_push(h, &JsValue::Number(20.0)).await.unwrap();
            assert_eq!(engine.array_length(h).await.unwrap(), 2);
            assert_eq!(engine.array_get(h, 0).await.unwrap(), JsValue::Number(10.0));
            assert_eq!(engine.array_get(h, 1).await.unwrap(), JsValue::Number(20.0));
        });
    }

    #[test]
    fn test_async_call_function() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            engine
                .eval("function add(a, b) { return a + b; }")
                .await
                .unwrap();
            let func_handle = engine
                .with_context(|ctx| {
                    let func: Value<'_> = ctx.globals().get("add").unwrap();
                    engine.store_persistent(&ctx, func)
                })
                .await;
            let result = engine
                .call_function(func_handle, &[JsValue::Number(3.0), JsValue::Number(4.0)])
                .await
                .unwrap();
            assert_eq!(result, JsValue::Number(7.0));
        });
    }

    #[test]
    fn test_async_json() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let JsValue::ObjectHandle(h) = engine.object_new().await.unwrap() else {
                panic!();
            };
            engine
                .object_set(h, "a", &JsValue::Number(1.0))
                .await
                .unwrap();
            let json = engine.to_json(h).await.unwrap();
            assert!(json.contains("\"a\""));

            let val = engine.parse_json(r#"{"x": 42}"#).await.unwrap();
            let h2 = match val {
                JsValue::ObjectHandle(id) => id,
                other => panic!("Expected ObjectHandle, got {:?}", other),
            };
            let x = engine.object_get(h2, "x").await.unwrap();
            assert_eq!(x, JsValue::Number(42.0));
        });
    }

    #[test]
    fn test_async_register_global_fn() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
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
                .await
                .unwrap();
            let result = engine.eval("hostAdd(10, 20)").await.unwrap();
            assert_eq!(result, JsValue::Number(30.0));
        });
    }

    #[test]
    fn test_async_drop_handle() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let JsValue::ObjectHandle(h) = engine.object_new().await.unwrap() else {
                panic!();
            };
            engine.drop_handle(h);
            let result = engine.object_get(h, "x").await;
            assert!(matches!(result.unwrap_err(), EngineError::InvalidHandle(_)));
        });
    }

    #[test]
    fn test_async_eval_module() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            let ns = engine
                .eval_module("export const x = 42;", "test")
                .await
                .unwrap();
            let h = match ns {
                JsValue::ObjectHandle(id) => id,
                other => panic!("Expected ObjectHandle, got {:?}", other),
            };
            let x = engine.object_get(h, "x").await.unwrap();
            assert_eq!(x, JsValue::Number(42.0));
        });
    }

    #[test]
    fn test_async_register_module_and_import() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            engine
                .register_module("helper", "export const PI = 3.14;")
                .unwrap();
            let ns = engine
                .eval_module(
                    "import { PI } from 'helper'; export const tau = PI * 2;",
                    "main",
                )
                .await
                .unwrap();
            let h = match ns {
                JsValue::ObjectHandle(id) => id,
                other => panic!("Expected ObjectHandle, got {:?}", other),
            };
            let tau = engine.object_get(h, "tau").await.unwrap();
            assert_eq!(tau, JsValue::Number(6.28));
        });
    }

    #[test]
    fn test_async_memory_usage() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            engine.eval("var x = [1,2,3]").await.unwrap();
            let stats = engine.memory_usage().await;
            assert!(stats.memory_used_size > 0);
        });
    }

    #[test]
    fn test_async_run_gc() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            engine.eval("var x = {a: 1}").await.unwrap();
            engine.run_gc().await;
            let val = engine.eval("1 + 1").await.unwrap();
            assert_eq!(val, JsValue::Number(2.0));
        });
    }

    #[test]
    fn test_async_promise_resolution() {
        block_on(async {
            let engine = AsyncQuickJsEngine::new().await.unwrap();
            // eval_async resolves promises
            let val = engine.eval_async("Promise.resolve(42)").await.unwrap();
            // Note: eval returns the Promise object itself (not resolved value)
            // because convert_value sees it as an Object.
            // The resolved value is available after idle() in the JS runtime.
            // For eval_async, the promise runs but eval's return is still the Promise.
            // Actual async value extraction requires calling .then() or using modules.
            assert!(matches!(val, JsValue::Object(_)));
        });
    }
}
