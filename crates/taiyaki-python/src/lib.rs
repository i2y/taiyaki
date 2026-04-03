use pyo3::IntoPyObject;
use pyo3::prelude::*;

// Compile-time backend selection
#[cfg(all(feature = "quickjs", feature = "jsc"))]
compile_error!("Cannot enable both `quickjs` and `jsc` features for taiyaki-python");
#[cfg(not(any(feature = "quickjs", feature = "jsc")))]
compile_error!("Enable either `quickjs` or `jsc` feature for taiyaki-python");

#[cfg(feature = "jsc")]
use taiyaki_core::engine::jsc_backend::JscEngine as SyncEngine;
#[cfg(feature = "quickjs")]
use taiyaki_core::engine::quickjs_backend::QuickJsEngine as SyncEngine;

use taiyaki_core::engine::{EngineError, JsEngine, JsValue};
use taiyaki_core::transpiler;

fn engine_err(e: EngineError) -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
}

fn transpile_err(e: transpiler::TranspileError) -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
}

#[pyclass]
#[derive(Clone)]
struct JsHandle {
    value: JsValue,
}

// ── Sync Runtime ──

#[pyclass(unsendable)]
struct Runtime {
    engine: SyncEngine,
}

#[pymethods]
impl Runtime {
    #[new]
    fn new() -> PyResult<Self> {
        let engine = SyncEngine::new().map_err(engine_err)?;
        Ok(Self { engine })
    }

    fn eval(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let val = self.engine.eval(code).map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn eval_ts(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let js_code = transpiler::strip_types(code).map_err(transpile_err)?;
        let val = self.engine.eval(&js_code).map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn eval_jsx(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let js_code = transpile_jsx(code, None)?;
        self.eval(py, &js_code)
    }

    fn object_new(&self) -> PyResult<JsHandle> {
        let val = self.engine.object_new().map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn object_set(&self, obj: &JsHandle, key: &str, val: &Bound<'_, PyAny>) -> PyResult<()> {
        let handle = require_handle(&obj.value, "object")?;
        let js_val = py_to_jsvalue(val)?;
        self.engine
            .object_set(handle, key, &js_val)
            .map_err(engine_err)?;
        Ok(())
    }

    fn object_get(&self, py: Python<'_>, obj: &JsHandle, key: &str) -> PyResult<PyObject> {
        let handle = require_handle(&obj.value, "object")?;
        let val = self.engine.object_get(handle, key).map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn array_new(&self) -> PyResult<JsHandle> {
        let val = self.engine.array_new().map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn array_push(&self, arr: &JsHandle, val: &Bound<'_, PyAny>) -> PyResult<()> {
        let handle = require_handle(&arr.value, "array")?;
        let js_val = py_to_jsvalue(val)?;
        self.engine
            .array_push(handle, &js_val)
            .map_err(engine_err)?;
        Ok(())
    }

    fn array_get(&self, py: Python<'_>, arr: &JsHandle, index: u32) -> PyResult<PyObject> {
        let handle = require_handle(&arr.value, "array")?;
        let val = self.engine.array_get(handle, index).map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn array_length(&self, arr: &JsHandle) -> PyResult<u32> {
        let handle = require_handle(&arr.value, "array")?;
        Ok(self.engine.array_length(handle).map_err(engine_err)?)
    }

    #[pyo3(signature = (func, *args))]
    fn call(
        &self,
        py: Python<'_>,
        func: &JsHandle,
        args: &Bound<'_, pyo3::types::PyTuple>,
    ) -> PyResult<PyObject> {
        let handle = require_handle(&func.value, "function")?;
        let mut js_args = Vec::with_capacity(args.len());
        for item in args.iter() {
            js_args.push(py_to_jsvalue(&item)?);
        }
        let val = self
            .engine
            .call_function(handle, &js_args)
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn to_json(&self, handle: &JsHandle) -> PyResult<String> {
        let id = require_handle(&handle.value, "handle")?;
        Ok(self.engine.to_json(id).map_err(engine_err)?)
    }

    fn from_json(&self, json: &str) -> PyResult<JsHandle> {
        let val = self.engine.parse_json(json).map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn register_fn(&self, name: &str, callback: PyObject) -> PyResult<()> {
        self.engine
            .register_global_fn(name, make_py_callback(callback))
            .map_err(engine_err)?;
        Ok(())
    }

    /// Enable Node.js compatibility APIs (path, events, util, url, Buffer, require).
    fn enable_node_polyfills(&self) -> PyResult<()> {
        taiyaki_node_polyfill::register_all(&self.engine).map_err(engine_err)?;
        Ok(())
    }
}

// ── Shared callback builder ──

#[cfg(feature = "jsc")]
use taiyaki_core::engine::async_jsc_backend::AsyncJscEngine as AsyncEngine;
#[cfg(feature = "quickjs")]
use taiyaki_core::engine::async_quickjs_backend::AsyncQuickJsEngine as AsyncEngine;

fn py_to_engine_err(e: impl std::fmt::Display) -> EngineError {
    EngineError::JsException {
        message: e.to_string(),
    }
}

fn shutdown_err() -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err("engine shutdown")
}

fn make_py_callback(
    callback: PyObject,
) -> Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError> + Send> {
    Box::new(move |args: &[JsValue]| {
        Python::with_gil(|py| {
            let py_args: Vec<PyObject> = args
                .iter()
                .map(|a| js_value_to_py(py, a))
                .collect::<PyResult<_>>()
                .map_err(py_to_engine_err)?;
            let tuple = pyo3::types::PyTuple::new(py, &py_args).map_err(py_to_engine_err)?;
            let result = callback.call(py, tuple, None).map_err(py_to_engine_err)?;
            py_to_jsvalue(&result.bind(py)).map_err(py_to_engine_err)
        })
    })
}

// ── Async Runtime (background engine thread) ──

type EngineCommand = Box<dyn FnOnce(&AsyncEngine, &tokio::runtime::Runtime) + Send>;

fn engine_worker(
    cmd_rx: std::sync::mpsc::Receiver<EngineCommand>,
    init_tx: std::sync::mpsc::SyncSender<Result<(), EngineError>>,
) {
    let tokio_rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            let _ = init_tx.send(Err(EngineError::InitError(e.to_string())));
            return;
        }
    };
    match tokio_rt.block_on(AsyncEngine::new()) {
        Ok(engine) => {
            let _ = init_tx.send(Ok(()));
            while let Ok(cmd) = cmd_rx.recv() {
                cmd(&engine, &tokio_rt);
            }
        }
        Err(e) => {
            let _ = init_tx.send(Err(e));
        }
    }
}

#[pyclass(unsendable)]
struct AsyncRuntime {
    cmd_tx: std::sync::mpsc::Sender<EngineCommand>,
    _worker: Option<std::thread::JoinHandle<()>>,
}

impl AsyncRuntime {
    /// Send a command to the engine thread and block (releasing GIL) until the result is ready.
    fn send_sync<T: Send + 'static>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&AsyncEngine, &tokio::runtime::Runtime) -> T + Send + 'static,
    ) -> PyResult<T> {
        let (tx, rx) = std::sync::mpsc::sync_channel::<T>(1);
        self.cmd_tx
            .send(Box::new(move |engine, rt| {
                let _ = tx.send(f(engine, rt));
            }))
            .map_err(|_| shutdown_err())?;
        py.allow_threads(move || rx.recv())
            .map_err(|_| shutdown_err())
    }

    /// Send a command that resolves an asyncio.Future via call_soon_threadsafe.
    fn send_async<'py>(
        &self,
        py: Python<'py>,
        f: impl FnOnce(&AsyncEngine, &tokio::runtime::Runtime) -> Result<JsValue, EngineError>
        + Send
        + 'static,
    ) -> PyResult<Bound<'py, PyAny>> {
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("get_running_loop")?;
        let future = event_loop.call_method0("create_future")?;

        let future_ref = future.clone().unbind();
        let loop_ref = event_loop.clone().unbind();

        self.cmd_tx
            .send(Box::new(move |engine, tokio_rt| {
                let result = f(engine, tokio_rt);
                Python::with_gil(|py| {
                    resolve_future(py, &loop_ref, &future_ref, result);
                });
            }))
            .map_err(|_| shutdown_err())?;

        Ok(future)
    }
}

/// Resolve an asyncio.Future from the engine thread via call_soon_threadsafe.
fn resolve_future(
    py: Python<'_>,
    loop_ref: &PyObject,
    future_ref: &PyObject,
    result: Result<JsValue, EngineError>,
) {
    let loop_ = loop_ref.bind(py);
    let future = future_ref.bind(py);

    let schedule = |method: &str, value: PyObject| match future.getattr(method) {
        Ok(cb) => {
            if let Err(e) = loop_.call_method1("call_soon_threadsafe", (cb, value)) {
                eprintln!("taiyaki: call_soon_threadsafe failed: {e}");
            }
        }
        Err(e) => eprintln!("taiyaki: future.{method} unavailable: {e}"),
    };

    match result {
        Ok(val) => match js_value_to_py(py, &val) {
            Ok(py_val) => schedule("set_result", py_val),
            Err(e) => schedule("set_exception", e.value(py).clone().unbind().into()),
        },
        Err(e) => schedule(
            "set_exception",
            engine_err(e).value(py).clone().unbind().into(),
        ),
    }
}

impl Drop for AsyncRuntime {
    fn drop(&mut self) {
        // Drop sender to close the channel, signaling the worker to exit.
        // Field drop order (cmd_tx before _worker) ensures this, but we
        // take the handle to join explicitly for deterministic shutdown.
        if let Some(handle) = self._worker.take() {
            drop(std::mem::replace(
                &mut self.cmd_tx,
                std::sync::mpsc::channel().0,
            ));
            let _ = handle.join();
        }
    }
}

#[pymethods]
impl AsyncRuntime {
    #[new]
    fn new() -> PyResult<Self> {
        let (cmd_tx, cmd_rx) = std::sync::mpsc::channel();
        let (init_tx, init_rx) = std::sync::mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || engine_worker(cmd_rx, init_tx));
        init_rx
            .recv()
            .map_err(|_| {
                pyo3::exceptions::PyRuntimeError::new_err("engine worker failed to start")
            })?
            .map_err(engine_err)?;
        Ok(Self {
            cmd_tx,
            _worker: Some(worker),
        })
    }

    fn eval(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let code = code.to_string();
        let val = self
            .send_sync(py, move |engine, rt| rt.block_on(engine.eval(&code)))?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    /// Evaluates code and drives the event loop to resolve all promises.
    fn eval_async(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let code = code.to_string();
        let val = self
            .send_sync(py, move |engine, rt| rt.block_on(engine.eval_async(&code)))?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    /// Evaluates code and drives the event loop. Returns a true non-blocking Python awaitable.
    fn eval_await<'py>(&self, py: Python<'py>, code: &str) -> PyResult<Bound<'py, PyAny>> {
        let code = code.to_string();
        self.send_async(py, move |engine, tokio_rt| {
            tokio_rt.block_on(engine.eval_async(&code))
        })
    }

    fn eval_ts(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let js_code = transpiler::strip_types(code).map_err(transpile_err)?;
        let val = self
            .send_sync(py, move |engine, rt| rt.block_on(engine.eval(&js_code)))?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn eval_jsx(&self, py: Python<'_>, code: &str) -> PyResult<PyObject> {
        let js_code = transpile_jsx(code, None)?;
        self.eval(py, &js_code)
    }

    fn eval_module_jsx(&self, py: Python<'_>, code: &str, name: &str) -> PyResult<PyObject> {
        let js_code = transpile_jsx(code, None)?;
        self.eval_module(py, &js_code, name)
    }

    fn eval_module_jsx_await<'py>(
        &self,
        py: Python<'py>,
        code: &str,
        name: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let js_code = transpile_jsx(code, None)?;
        self.eval_module_await(py, &js_code, name)
    }

    fn eval_module(&self, py: Python<'_>, code: &str, name: &str) -> PyResult<PyObject> {
        let code = code.to_string();
        let name = name.to_string();
        let val = self
            .send_sync(py, move |engine, rt| {
                rt.block_on(engine.eval_module(&code, &name))
            })?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    /// Evaluates a module and drives the event loop to resolve all promises.
    fn eval_module_async(&self, py: Python<'_>, code: &str, name: &str) -> PyResult<PyObject> {
        let code = code.to_string();
        let name = name.to_string();
        let val = self
            .send_sync(py, move |engine, rt| {
                rt.block_on(engine.eval_module_async(&code, &name))
            })?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    /// Evaluates a module and drives the event loop. Returns a true non-blocking Python awaitable.
    fn eval_module_await<'py>(
        &self,
        py: Python<'py>,
        code: &str,
        name: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let code = code.to_string();
        let name = name.to_string();
        self.send_async(py, move |engine, tokio_rt| {
            tokio_rt.block_on(engine.eval_module_async(&code, &name))
        })
    }

    fn register_module(&self, py: Python<'_>, name: &str, code: &str) -> PyResult<()> {
        let name = name.to_string();
        let code = code.to_string();
        self.send_sync(py, move |engine, _rt| engine.register_module(&name, &code))?
            .map_err(engine_err)
    }

    fn object_new(&self, py: Python<'_>) -> PyResult<JsHandle> {
        let val = self
            .send_sync(py, |engine, rt| rt.block_on(engine.object_new()))?
            .map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn object_set(
        &self,
        py: Python<'_>,
        obj: &JsHandle,
        key: &str,
        val: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let handle = require_handle(&obj.value, "object")?;
        let js_val = py_to_jsvalue(val)?;
        let key = key.to_string();
        self.send_sync(py, move |engine, rt| {
            rt.block_on(engine.object_set(handle, &key, &js_val))
        })?
        .map_err(engine_err)
    }

    fn object_get(&self, py: Python<'_>, obj: &JsHandle, key: &str) -> PyResult<PyObject> {
        let handle = require_handle(&obj.value, "object")?;
        let key = key.to_string();
        let val = self
            .send_sync(py, move |engine, rt| {
                rt.block_on(engine.object_get(handle, &key))
            })?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn array_new(&self, py: Python<'_>) -> PyResult<JsHandle> {
        let val = self
            .send_sync(py, |engine, rt| rt.block_on(engine.array_new()))?
            .map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn array_push(&self, py: Python<'_>, arr: &JsHandle, val: &Bound<'_, PyAny>) -> PyResult<()> {
        let handle = require_handle(&arr.value, "array")?;
        let js_val = py_to_jsvalue(val)?;
        self.send_sync(py, move |engine, rt| {
            rt.block_on(engine.array_push(handle, &js_val))
        })?
        .map_err(engine_err)
    }

    fn array_get(&self, py: Python<'_>, arr: &JsHandle, index: u32) -> PyResult<PyObject> {
        let handle = require_handle(&arr.value, "array")?;
        let val = self
            .send_sync(py, move |engine, rt| {
                rt.block_on(engine.array_get(handle, index))
            })?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn array_length(&self, py: Python<'_>, arr: &JsHandle) -> PyResult<u32> {
        let handle = require_handle(&arr.value, "array")?;
        self.send_sync(py, move |engine, rt| {
            rt.block_on(engine.array_length(handle))
        })?
        .map_err(engine_err)
    }

    #[pyo3(signature = (func, *args))]
    fn call(
        &self,
        py: Python<'_>,
        func: &JsHandle,
        args: &Bound<'_, pyo3::types::PyTuple>,
    ) -> PyResult<PyObject> {
        let handle = require_handle(&func.value, "function")?;
        let mut js_args = Vec::with_capacity(args.len());
        for item in args.iter() {
            js_args.push(py_to_jsvalue(&item)?);
        }
        let val = self
            .send_sync(py, move |engine, rt| {
                rt.block_on(engine.call_function(handle, &js_args))
            })?
            .map_err(engine_err)?;
        js_value_to_py(py, &val)
    }

    fn to_json(&self, py: Python<'_>, handle: &JsHandle) -> PyResult<String> {
        let id = require_handle(&handle.value, "handle")?;
        self.send_sync(py, move |engine, rt| rt.block_on(engine.to_json(id)))?
            .map_err(engine_err)
    }

    fn from_json(&self, py: Python<'_>, json: &str) -> PyResult<JsHandle> {
        let json = json.to_string();
        let val = self
            .send_sync(py, move |engine, rt| rt.block_on(engine.parse_json(&json)))?
            .map_err(engine_err)?;
        Ok(JsHandle { value: val })
    }

    fn register_fn(&self, py: Python<'_>, name: &str, callback: PyObject) -> PyResult<()> {
        let name = name.to_string();
        let cb = make_py_callback(callback);
        self.send_sync(py, move |engine, rt| {
            rt.block_on(engine.register_global_fn(&name, cb))
        })?
        .map_err(engine_err)
    }

    /// Drives the event loop to resolve all pending promises.
    fn idle(&self, py: Python<'_>) -> PyResult<()> {
        self.send_sync(py, |engine, rt| rt.block_on(engine.idle()))
    }

    /// Enable Node.js compatibility APIs (path, events, util, url, Buffer, require).
    fn enable_node_polyfills(&self, py: Python<'_>) -> PyResult<()> {
        self.send_sync(py, |engine, rt| {
            rt.block_on(taiyaki_node_polyfill::register_all_async(engine))
        })?
        .map_err(engine_err)
    }
}

// ── Shared helpers ──

fn require_handle(value: &JsValue, expected: &str) -> PyResult<u64> {
    value.handle_id().ok_or_else(|| {
        pyo3::exceptions::PyTypeError::new_err(format!("Expected a JS {expected} handle"))
    })
}

fn py_to_jsvalue(obj: &Bound<'_, PyAny>) -> PyResult<JsValue> {
    if let Ok(handle) = obj.extract::<JsHandle>() {
        return Ok(handle.value);
    }
    if obj.is_none() {
        return Ok(JsValue::Null);
    }
    // Check bool before int (Python bool is a subclass of int)
    if let Ok(b) = obj.extract::<bool>() {
        return Ok(JsValue::Bool(b));
    }
    if let Ok(n) = obj.extract::<f64>() {
        return Ok(JsValue::Number(n));
    }
    if let Ok(s) = obj.extract::<String>() {
        return Ok(JsValue::String(s));
    }
    let py = obj.py();
    let json_mod = py.import("json")?;
    let json_str: String = json_mod.call_method1("dumps", (obj,))?.extract()?;
    Ok(JsValue::Object(json_str))
}

fn js_value_to_py(py: Python<'_>, val: &JsValue) -> PyResult<PyObject> {
    match val {
        JsValue::Undefined | JsValue::Null => Ok(py.None()),
        JsValue::Bool(b) => Ok(b.into_pyobject(py)?.to_owned().into_any().unbind()),
        JsValue::Number(n) => {
            if n.fract() == 0.0 && *n >= -(2.0_f64.powi(63)) && *n < 2.0_f64.powi(63) {
                Ok((*n as i64).into_pyobject(py)?.into_any().unbind())
            } else {
                Ok(n.into_pyobject(py)?.to_owned().into_any().unbind())
            }
        }
        JsValue::String(s) => Ok(s.into_pyobject(py)?.into_any().unbind()),
        JsValue::Object(json) | JsValue::Array(json) => {
            let json_mod = py.import("json")?;
            let result = json_mod.call_method1("loads", (json.as_str(),))?;
            Ok(result.unbind())
        }
        JsValue::Function => Ok(py.None()),
        JsValue::ObjectHandle(_) | JsValue::ArrayHandle(_) | JsValue::FunctionHandle(_) => {
            let handle = JsHandle { value: val.clone() };
            Ok(handle.into_pyobject(py)?.into_any().unbind())
        }
    }
}

fn transpile_jsx(code: &str, import_source: Option<&str>) -> PyResult<String> {
    let opts = match import_source {
        Some(src) => transpiler::JsxOptions {
            import_source: src.into(),
        },
        None => transpiler::JsxOptions::default(),
    };
    transpiler::transform_jsx(code, &opts).map_err(transpile_err)
}

/// Transform JSX/TSX code to JavaScript (standalone function).
#[pyfunction]
#[pyo3(signature = (code, import_source=None))]
fn transform_jsx(code: &str, import_source: Option<&str>) -> PyResult<String> {
    transpile_jsx(code, import_source)
}

#[pymodule]
fn taiyaki(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Runtime>()?;
    m.add_class::<AsyncRuntime>()?;
    m.add_class::<JsHandle>()?;
    m.add_function(wrap_pyfunction!(transform_jsx, m)?)?;
    Ok(())
}
