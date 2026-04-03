use taiyaki_core::engine::{HostCallback, JsValue};

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![(
        "__path_cwd",
        Box::new(|_args: &[JsValue]| {
            let cwd = std::env::current_dir()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_else(|_| "/".to_string());
            Ok(JsValue::String(cwd))
        }),
    )]
}
