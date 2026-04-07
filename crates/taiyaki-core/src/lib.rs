#![allow(
    clippy::wrong_self_convention,
    clippy::needless_borrow,
    clippy::new_without_default,
    clippy::type_complexity
)]

pub mod engine;
pub mod permissions;
pub mod transpiler;

#[cfg(any(feature = "quickjs", feature = "jsc"))]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub mod ffi;

/// Re-export rquickjs for downstream crates that use `with_context`.
#[cfg(feature = "quickjs")]
pub use rquickjs;
