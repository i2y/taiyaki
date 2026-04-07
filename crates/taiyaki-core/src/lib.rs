pub mod engine;
pub mod permissions;
pub mod transpiler;

/// C ABI bindings. All functions accept raw pointers from the C caller.
/// The caller must ensure pointers are valid and non-null.
#[cfg(any(feature = "quickjs", feature = "jsc"))]
#[allow(clippy::missing_safety_doc)]
pub mod ffi;

/// Re-export rquickjs for downstream crates that use `with_context`.
#[cfg(feature = "quickjs")]
pub use rquickjs;
