use std::cell::RefCell;
use std::collections::VecDeque;
use std::ffi::CString;
use std::ptr;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

use super::jsc_backend::JscEngine;
use super::jsc_sys::*;
use super::{EngineError, HostCallback, JsEngine, JsValue, MemoryStats};

/// Async wrapper around `JscEngine`.
///
/// JSC operations are inherently synchronous, so this wrapper provides async
/// method signatures compatible with `AsyncQuickJsEngine`. The async layer
/// supports pending callbacks (e.g., from setTimeout, fetch) that resolve
/// JSC Promises via an ID-based callback map.
pub struct AsyncJscEngine {
    engine: JscEngine,
    /// Local pending callbacks (scheduled from the same thread).
    pending: Rc<RefCell<VecDeque<Box<dyn FnOnce(&JscEngine)>>>>,
    /// Channel for receiving callbacks from spawned tokio tasks (Send-safe).
    remote_rx: RefCell<tokio::sync::mpsc::UnboundedReceiver<Box<dyn FnOnce(&JscEngine) + Send>>>,
    remote_tx: tokio::sync::mpsc::UnboundedSender<Box<dyn FnOnce(&JscEngine) + Send>>,
    /// Number of in-flight async operations (spawned but not yet completed).
    in_flight: Arc<AtomicU32>,
    /// Waker for idle() — notified when a remote callback is sent.
    notify: Arc<tokio::sync::Notify>,
    /// Base path for file-based module resolution (set by enable_file_loader).
    file_loader_base: RefCell<Option<std::path::PathBuf>>,
}

impl AsyncJscEngine {
    pub async fn new() -> Result<Self, EngineError> {
        let (remote_tx, remote_rx) = tokio::sync::mpsc::unbounded_channel();
        let engine = JscEngine::new()?;

        // Initialize the async callback map in JS
        engine.eval("globalThis.__jsc_async_cbs = {}; globalThis.__jsc_async_next = 1;")?;

        Ok(Self {
            engine,
            pending: Rc::new(RefCell::new(VecDeque::new())),
            remote_rx: RefCell::new(remote_rx),
            remote_tx,
            in_flight: Arc::new(AtomicU32::new(0)),
            notify: Arc::new(tokio::sync::Notify::new()),
            file_loader_base: RefCell::new(None),
        })
    }

    /// Returns a reference to the underlying sync engine.
    pub fn engine(&self) -> &JscEngine {
        &self.engine
    }

    /// Schedules a callback to be executed during the next `idle()` call.
    pub fn schedule_callback(&self, cb: Box<dyn FnOnce(&JscEngine)>) {
        self.pending.borrow_mut().push_back(cb);
    }

    /// Returns the JSC context ref for raw FFI access.
    pub fn ctx(&self) -> JSContextRef {
        self.engine.ctx()
    }

    // --- Async wrappers for JsEngine trait methods ---

    pub async fn eval(&self, code: &str) -> Result<JsValue, EngineError> {
        self.engine.eval(code)
    }

    pub async fn eval_async(&self, code: &str) -> Result<JsValue, EngineError> {
        let result = self.engine.eval(code)?;
        self.idle().await;
        Ok(result)
    }

    pub async fn object_new(&self) -> Result<JsValue, EngineError> {
        self.engine.object_new()
    }

    pub async fn object_set(
        &self,
        handle: u64,
        key: &str,
        value: &JsValue,
    ) -> Result<(), EngineError> {
        self.engine.object_set(handle, key, value)
    }

    pub async fn object_get(&self, handle: u64, key: &str) -> Result<JsValue, EngineError> {
        self.engine.object_get(handle, key)
    }

    pub async fn array_new(&self) -> Result<JsValue, EngineError> {
        self.engine.array_new()
    }

    pub async fn array_push(&self, handle: u64, value: &JsValue) -> Result<(), EngineError> {
        self.engine.array_push(handle, value)
    }

    pub async fn array_get(&self, handle: u64, index: u32) -> Result<JsValue, EngineError> {
        self.engine.array_get(handle, index)
    }

    pub async fn array_length(&self, handle: u64) -> Result<u32, EngineError> {
        self.engine.array_length(handle)
    }

    pub async fn call_function(
        &self,
        func_handle: u64,
        args: &[JsValue],
    ) -> Result<JsValue, EngineError> {
        self.engine.call_function(func_handle, args)
    }

    pub async fn to_json(&self, handle: u64) -> Result<String, EngineError> {
        self.engine.to_json(handle)
    }

    pub async fn parse_json(&self, json: &str) -> Result<JsValue, EngineError> {
        self.engine.parse_json(json)
    }

    pub async fn register_global_fn(
        &self,
        name: &str,
        callback: HostCallback,
    ) -> Result<(), EngineError> {
        self.engine.register_global_fn(name, callback)
    }

    pub fn drop_handle(&self, handle: u64) {
        self.engine.drop_handle(handle);
    }

    pub async fn set_memory_limit(&self, bytes: usize) {
        self.engine.set_memory_limit(bytes);
    }

    pub async fn set_max_stack_size(&self, bytes: usize) {
        self.engine.set_max_stack_size(bytes);
    }

    pub async fn set_execution_timeout(&self, duration: Duration) {
        self.engine.set_execution_timeout(duration);
    }

    pub async fn memory_usage(&self) -> MemoryStats {
        self.engine.memory_usage()
    }

    pub async fn run_gc(&self) {
        self.engine.run_gc();
    }

    pub async fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        self.engine.eval_module(code, name)
    }

    pub async fn eval_module_async(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        let has_await = code.contains("await ");

        if has_await {
            // Async module: eval_module returns a Promise. We attach .then()
            // to store the exports in a global, then idle() to resolve it.
            self.engine.eval_module(code, name)?;
            // The async IIFE's Promise result is the return value.
            // Attach a then() to run side effects, then idle() to process.
            self.in_flight.fetch_add(1, Ordering::Release);
            let in_flight = self.in_flight.clone();
            let notify = self.notify.clone();
            let tx = self.remote_tx.clone();
            // The eval_module returned the Promise. We need to resolve it.
            // Use JS: the IIFE already ran side effects via await. Just idle.
            let _ = tx.send(Box::new(move |_engine: &JscEngine| {
                in_flight.fetch_sub(1, Ordering::Release);
                notify.notify_one();
            }));
            self.idle().await;
            Ok(JsValue::Undefined)
        } else {
            let result = self.engine.eval_module(code, name)?;
            self.idle().await;
            Ok(result)
        }
    }

    pub fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError> {
        self.engine.register_module(name, code)
    }

    /// Processes pending callbacks — both local and remote (from tokio tasks).
    /// Waits for all in-flight async operations to complete.
    pub async fn idle(&self) {
        loop {
            // Register interest in notifications BEFORE draining/checking,
            // so we don't miss notifications that arrive between drain and await.
            let notified = self.notify.notified();

            // Drain local callbacks
            while let Some(cb) = self.pending.borrow_mut().pop_front() {
                cb(&self.engine);
            }

            // Drain remote callbacks (from spawned async tasks)
            {
                let mut rx = self.remote_rx.borrow_mut();
                while let Ok(cb) = rx.try_recv() {
                    cb(&self.engine);
                }
            }

            // If no more in-flight operations, we're done
            if self.in_flight.load(Ordering::Acquire) == 0 {
                break;
            }

            // Wait for notification that a new callback has arrived
            notified.await;
        }
    }

    /// Provides access to the underlying engine for raw JSC operations.
    pub async fn with_engine<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&JscEngine) -> R,
    {
        f(&self.engine)
    }

    /// Enables file-based module resolution from the given base path.
    pub async fn enable_file_loader(&self, base_path: &std::path::Path) {
        *self.file_loader_base.borrow_mut() = Some(base_path.to_path_buf());
        self.engine.set_file_loader_base(base_path);
    }

    /// Register an async host function that returns a Promise in JS.
    /// Uses an ID-based callback map to support concurrent async operations.
    pub async fn register_async_host_fn(
        &self,
        name: &str,
        f: super::AsyncHostFn,
    ) -> Result<(), EngineError> {
        let f = Arc::new(f);
        let remote_tx = self.remote_tx.clone();
        let in_flight = self.in_flight.clone();
        let notify = self.notify.clone();
        let inner_name = format!("{name}__inner");

        // Register a sync host function. The first arg is the async callback ID,
        // followed by the user's arguments.
        self.engine.register_global_fn(
            &inner_name,
            Box::new(move |args: &[JsValue]| {
                // First arg = callback ID
                let cb_id = args.first().map(|v| v.coerce_string()).unwrap_or_default();

                // Remaining args = user arguments (coerced to strings)
                let string_args: Vec<String> = args[1..]
                    .iter()
                    .map(|v| match v {
                        JsValue::String(s) => s.clone(),
                        JsValue::Number(n) => {
                            if n.fract() == 0.0 {
                                format!("{}", *n as i64)
                            } else {
                                n.to_string()
                            }
                        }
                        JsValue::Bool(b) => b.to_string(),
                        JsValue::Null => "null".to_string(),
                        JsValue::Undefined => "undefined".to_string(),
                        JsValue::Object(s) | JsValue::Array(s) => s.clone(),
                        _ => String::new(),
                    })
                    .collect();

                let f = f.clone();
                let tx = remote_tx.clone();
                let in_flight = in_flight.clone();
                let notify = notify.clone();
                let fut = f(string_args);

                in_flight.fetch_add(1, Ordering::Release);

                tokio::spawn(async move {
                    let result = fut.await;
                    let cb_id_clone = cb_id.clone();
                    let _ = tx.send(Box::new(move |engine: &JscEngine| {
                        let ctx = engine.ctx();
                        let code = match &result {
                            Ok(val) => {
                                let escaped = val
                                    .replace('\\', "\\\\")
                                    .replace('`', "\\`")
                                    .replace('$', "\\$");
                                format!(
                                    "var __cb=globalThis.__jsc_async_cbs[{cb_id_clone}];\
                                     delete globalThis.__jsc_async_cbs[{cb_id_clone}];\
                                     if(__cb)__cb[0](`{escaped}`);"
                                )
                            }
                            Err(err) => {
                                let escaped = err
                                    .replace('\\', "\\\\")
                                    .replace('`', "\\`")
                                    .replace('$', "\\$");
                                format!(
                                    "var __cb=globalThis.__jsc_async_cbs[{cb_id_clone}];\
                                     delete globalThis.__jsc_async_cbs[{cb_id_clone}];\
                                     if(__cb)__cb[1](new Error(`{escaped}`));"
                                )
                            }
                        };
                        unsafe {
                            let cstr = CString::new(code.as_str()).unwrap();
                            let js_str = JSStringCreateWithUTF8CString(cstr.as_ptr());
                            let mut ex: JSValueRef = ptr::null();
                            JSEvaluateScript(
                                ctx,
                                js_str,
                                ptr::null_mut(),
                                ptr::null_mut(),
                                0,
                                &mut ex,
                            );
                            JSStringRelease(js_str);
                        }
                    }));
                    in_flight.fetch_sub(1, Ordering::Release);
                    notify.notify_one();
                });

                Ok(JsValue::Undefined)
            }),
        )?;

        // Register JS wrapper that creates a Promise with a unique ID.
        // JSC host functions don't have .apply(), so use spread syntax.
        let js_glue = format!(
            "globalThis.{name} = function() {{ \
                var __id = globalThis.__jsc_async_next++; \
                var __args = Array.from(arguments); \
                return new Promise(function(resolve, reject) {{ \
                    globalThis.__jsc_async_cbs[__id] = [resolve, reject]; \
                    {inner_name}(...[String(__id)].concat(__args)); \
                }}); \
            }};"
        );
        self.engine.eval(&js_glue)?;

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// AsyncJsEngine trait implementation
// ---------------------------------------------------------------------------

impl super::AsyncJsEngine for AsyncJscEngine {
    async fn eval(&self, code: &str) -> Result<JsValue, EngineError> {
        self.eval(code).await
    }

    async fn eval_async(&self, code: &str) -> Result<JsValue, EngineError> {
        self.eval_async(code).await
    }

    async fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        self.eval_module(code, name).await
    }

    async fn eval_module_async(&self, code: &str, name: &str) -> Result<JsValue, EngineError> {
        self.eval_module_async(code, name).await
    }

    fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError> {
        AsyncJscEngine::register_module(self, name, code)
    }

    async fn register_global_fn(
        &self,
        name: &str,
        callback: HostCallback,
    ) -> Result<(), EngineError> {
        self.register_global_fn(name, callback).await
    }

    async fn register_async_host_fn(
        &self,
        name: &str,
        f: super::AsyncHostFn,
    ) -> Result<(), EngineError> {
        self.register_async_host_fn(name, f).await
    }

    async fn enable_file_loader(&self, base_path: &std::path::Path) {
        self.enable_file_loader(base_path).await
    }

    async fn idle(&self) {
        self.idle().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block_on<F: std::future::Future>(f: F) -> F::Output {
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
                std::task::Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    #[test]
    fn test_async_eval_integer() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            let val = engine.eval("1 + 2").await.unwrap();
            assert_eq!(val, JsValue::Number(3.0));
        });
    }

    #[test]
    fn test_async_eval_string() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            let val = engine.eval("'hello' + ' world'").await.unwrap();
            assert_eq!(val, JsValue::String("hello world".to_string()));
        });
    }

    #[test]
    fn test_async_eval_bool() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            assert_eq!(engine.eval("true").await.unwrap(), JsValue::Bool(true));
            assert_eq!(engine.eval("false").await.unwrap(), JsValue::Bool(false));
        });
    }

    #[test]
    fn test_async_eval_null_undefined() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            assert_eq!(engine.eval("null").await.unwrap(), JsValue::Null);
            assert_eq!(engine.eval("undefined").await.unwrap(), JsValue::Undefined);
        });
    }

    #[test]
    fn test_async_eval_error() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
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
            let engine = AsyncJscEngine::new().await.unwrap();
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
            let engine = AsyncJscEngine::new().await.unwrap();
            let JsValue::ArrayHandle(h) = engine.array_new().await.unwrap() else {
                panic!("Expected ArrayHandle");
            };
            engine.array_push(h, &JsValue::Number(10.0)).await.unwrap();
            engine.array_push(h, &JsValue::Number(20.0)).await.unwrap();
            assert_eq!(engine.array_length(h).await.unwrap(), 2);
            assert_eq!(engine.array_get(h, 0).await.unwrap(), JsValue::Number(10.0));
        });
    }

    #[test]
    fn test_async_register_global_fn() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
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
            let engine = AsyncJscEngine::new().await.unwrap();
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
            let engine = AsyncJscEngine::new().await.unwrap();
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
            let engine = AsyncJscEngine::new().await.unwrap();
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
    fn test_async_json() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
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
    fn test_async_memory_usage() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            let _obj = engine.object_new().await.unwrap();
            let stats = engine.memory_usage().await;
            assert!(stats.obj_count > 0);
        });
    }

    #[test]
    fn test_async_run_gc() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();
            engine.eval("var x = {a: 1}").await.unwrap();
            engine.run_gc().await;
            let val = engine.eval("1 + 1").await.unwrap();
            assert_eq!(val, JsValue::Number(2.0));
        });
    }

    #[test]
    fn test_async_idle_with_callbacks() {
        block_on(async {
            let engine = AsyncJscEngine::new().await.unwrap();

            // Schedule a callback that sets a global variable
            engine.schedule_callback(Box::new(|eng| {
                eng.eval("globalThis.__test_val = 42").unwrap();
            }));

            // Before idle, the value shouldn't exist
            let result = engine.eval("typeof globalThis.__test_val").await.unwrap();
            assert_eq!(result, JsValue::String("undefined".to_string()));

            // After idle, the callback should have executed
            engine.idle().await;
            let val = engine.eval("globalThis.__test_val").await.unwrap();
            assert_eq!(val, JsValue::Number(42.0));
        });
    }
}
