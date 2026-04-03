#[cfg(all(feature = "quickjs", feature = "jsc"))]
compile_error!("Features `quickjs` and `jsc` are mutually exclusive. Choose one.");

#[cfg(feature = "quickjs")]
pub mod quickjs_backend;

#[cfg(feature = "futures")]
pub mod async_quickjs_backend;

#[cfg(feature = "quickjs")]
pub(crate) mod convert;

#[cfg(feature = "quickjs")]
pub(crate) mod module_store;

#[cfg(feature = "jsc")]
pub(crate) mod jsc_sys;

#[cfg(feature = "jsc")]
pub mod jsc_backend;

#[cfg(feature = "jsc")]
pub mod async_jsc_backend;

/// Represents a JS value.
///
/// Object/Array are kept as JSON strings (backward-compatible eval() return).
/// Handle variants are live handles into the engine's Persistent store.
#[derive(Debug, Clone, PartialEq)]
pub enum JsValue {
    Undefined,
    Null,
    Bool(bool),
    Number(f64),
    String(String),
    /// JSON-serialized object (from eval)
    Object(String),
    /// JSON-serialized array (from eval)
    Array(String),
    /// Opaque marker (from eval, not callable)
    Function,
    ObjectHandle(u64),
    ArrayHandle(u64),
    FunctionHandle(u64),
}

impl JsValue {
    /// Returns the handle ID, or `None` if this is not a handle variant.
    pub fn handle_id(&self) -> Option<u64> {
        match self {
            Self::ObjectHandle(id) | Self::ArrayHandle(id) | Self::FunctionHandle(id) => Some(*id),
            _ => None,
        }
    }

    /// Coerce to u64 (Number cast or String parse).
    pub fn coerce_u64(&self) -> u64 {
        match self {
            Self::Number(n) => *n as u64,
            Self::String(s) => s.parse().unwrap_or(0),
            _ => 0,
        }
    }

    /// Coerce to i32 (Number cast or String parse).
    pub fn coerce_i32(&self) -> i32 {
        match self {
            Self::Number(n) => *n as i32,
            Self::String(s) => s.parse().unwrap_or(0),
            _ => 0,
        }
    }

    /// Coerce to u16 (Number cast or String parse).
    pub fn coerce_u16(&self) -> u16 {
        match self {
            Self::Number(n) => *n as u16,
            Self::String(s) => s.parse().unwrap_or(0),
            _ => 0,
        }
    }

    /// Extract as owned String, or empty string for non-string values.
    pub fn coerce_string(&self) -> String {
        match self {
            Self::String(s) => s.clone(),
            _ => String::new(),
        }
    }

    /// Coerce to bool (Bool value, or false for other types).
    pub fn coerce_bool(&self) -> bool {
        match self {
            Self::Bool(b) => *b,
            _ => false,
        }
    }
}

/// Host function callback type.
pub type HostCallback = Box<dyn Fn(&[JsValue]) -> Result<JsValue, EngineError>>;

/// Memory usage statistics.
#[derive(Debug, Clone)]
#[repr(C)]
pub struct MemoryStats {
    pub malloc_size: i64,
    pub memory_used_size: i64,
    pub atom_count: i64,
    pub str_count: i64,
    pub obj_count: i64,
    pub prop_count: i64,
    pub js_func_count: i64,
    pub c_func_count: i64,
    pub array_count: i64,
}

/// Common interface for JS engines.
pub trait JsEngine {
    fn eval(&self, code: &str) -> Result<JsValue, EngineError>;

    fn object_new(&self) -> Result<JsValue, EngineError>;
    fn object_set(&self, handle: u64, key: &str, value: &JsValue) -> Result<(), EngineError>;
    fn object_get(&self, handle: u64, key: &str) -> Result<JsValue, EngineError>;

    fn array_new(&self) -> Result<JsValue, EngineError>;
    fn array_push(&self, handle: u64, value: &JsValue) -> Result<(), EngineError>;
    fn array_get(&self, handle: u64, index: u32) -> Result<JsValue, EngineError>;
    fn array_length(&self, handle: u64) -> Result<u32, EngineError>;

    fn call_function(&self, func_handle: u64, args: &[JsValue]) -> Result<JsValue, EngineError>;

    fn to_json(&self, handle: u64) -> Result<String, EngineError>;
    fn parse_json(&self, json: &str) -> Result<JsValue, EngineError>;

    fn register_global_fn(&self, name: &str, callback: HostCallback) -> Result<(), EngineError>;

    fn drop_handle(&self, handle: u64);

    fn set_memory_limit(&self, bytes: usize);
    fn set_max_stack_size(&self, bytes: usize);
    fn set_execution_timeout(&self, duration: std::time::Duration);
    fn memory_usage(&self) -> MemoryStats;
    fn run_gc(&self);

    fn eval_module(&self, code: &str, name: &str) -> Result<JsValue, EngineError>;
    fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError>;
}

// ---------------------------------------------------------------------------
// Async engine trait + async host function type
// ---------------------------------------------------------------------------

/// An async host function: receives string args, returns string result asynchronously.
/// The outer closure is `Send + Sync` (shared across registrations).
/// The inner Future is `Send` (runs on tokio).
pub type AsyncHostFn = Box<
    dyn Fn(
            Vec<String>,
        )
            -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<String, String>> + Send>>
        + Send
        + Sync,
>;

/// Common async interface for JS engines (QuickJS, JSC).
///
/// Both `AsyncQuickJsEngine` and `AsyncJscEngine` implement this trait,
/// allowing the CLI and polyfill to be backend-agnostic.
pub trait AsyncJsEngine {
    fn eval(&self, code: &str) -> impl std::future::Future<Output = Result<JsValue, EngineError>>;

    fn eval_async(
        &self,
        code: &str,
    ) -> impl std::future::Future<Output = Result<JsValue, EngineError>>;

    fn eval_module(
        &self,
        code: &str,
        name: &str,
    ) -> impl std::future::Future<Output = Result<JsValue, EngineError>>;

    fn eval_module_async(
        &self,
        code: &str,
        name: &str,
    ) -> impl std::future::Future<Output = Result<JsValue, EngineError>>;

    fn register_module(&self, name: &str, code: &str) -> Result<(), EngineError>;

    fn register_global_fn(
        &self,
        name: &str,
        callback: HostCallback,
    ) -> impl std::future::Future<Output = Result<(), EngineError>>;

    /// Register an async host function that returns a Promise in JS.
    /// The function receives all arguments as strings and returns a string result.
    fn register_async_host_fn(
        &self,
        name: &str,
        f: AsyncHostFn,
    ) -> impl std::future::Future<Output = Result<(), EngineError>>;

    fn enable_file_loader(
        &self,
        base_path: &std::path::Path,
    ) -> impl std::future::Future<Output = ()>;

    /// Process pending async callbacks (resolve promises, drain queues).
    fn idle(&self) -> impl std::future::Future<Output = ()>;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum EngineError {
    JsException { message: String },
    InitError(String),
    InvalidHandle(u64),
    TypeError(String),
}

impl std::fmt::Display for EngineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EngineError::JsException { message } => write!(f, "JavaScript error: {message}"),
            EngineError::InitError(msg) => write!(f, "Engine initialization failed: {msg}"),
            EngineError::InvalidHandle(id) => write!(f, "Invalid handle: {id}"),
            EngineError::TypeError(msg) => write!(f, "Type error: {msg}"),
        }
    }
}

impl std::error::Error for EngineError {}
