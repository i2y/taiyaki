fn main() {
    let crate_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();

    std::fs::create_dir_all("include").ok();

    cbindgen::Builder::new()
        .with_crate(&crate_dir)
        .with_config(cbindgen::Config::from_file("cbindgen.toml").unwrap())
        .generate()
        .expect("Unable to generate C bindings")
        .write_to_file("include/taiyaki_raw.h");

    // Post-process: remove JSC-specific lines from the header.
    // cbindgen doesn't respect #[cfg(feature)] so JSC types leak into the header.
    let raw = std::fs::read_to_string("include/taiyaki_raw.h").unwrap();
    let mut filtered = String::new();
    let mut skip = false;
    for line in raw.lines() {
        // Skip JSC type definitions and extern function declarations
        if line.contains("JSContextRef")
            || line.contains("JSValueRef")
            || line.contains("JSObjectRef")
            || line.contains("JSStringRef")
            || line.contains("JSGlobalContextRef")
            || line.contains("JSContextGroupRef")
            || line.contains("JSClassRef")
            || line.contains("JSPropertyAttributes")
            || line.contains("JSClassAttributes")
            || line.contains("JSClassDefinition")
            || line.contains("JSObjectCallAsFunction")
            || line.contains("Option_JSObject")
            || line.contains("Option_JSShould")
            || line.contains("JSType ")
            || line.contains("JscEngine")
        {
            skip = true;
            continue;
        }
        // Skip multi-line continuations of skipped items
        if skip {
            if line.trim().is_empty()
                || line.starts_with("extern")
                || line.starts_with("typedef")
                || line.starts_with("#")
                || line.starts_with("/**")
                || line.starts_with(" *")
            {
                skip = false;
            } else {
                continue;
            }
        }
        filtered.push_str(line);
        filtered.push('\n');
    }
    std::fs::write("include/taiyaki.h", filtered).unwrap();
    let _ = std::fs::remove_file("include/taiyaki_raw.h");

    #[cfg(feature = "jsc")]
    link_jsc();
}

#[cfg(feature = "jsc")]
fn link_jsc() {
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();

    match target_os.as_str() {
        "macos" | "ios" => {
            println!("cargo:rustc-link-lib=framework=JavaScriptCore");
        }
        "linux" => {
            // Try JavaScriptCore GTK versions in order of preference
            let candidates = [
                "javascriptcoregtk-6.0",
                "javascriptcoregtk-4.1",
                "javascriptcoregtk-4.0",
            ];
            for lib in &candidates {
                if pkg_config::probe_library(lib).is_ok() {
                    return;
                }
            }
            panic!(
                "JSC backend on Linux requires libjavascriptcoregtk. \
                 Install one of: libjavascriptcoregtk-6.0-dev, \
                 libjavascriptcoregtk-4.1-dev, libjavascriptcoregtk-4.0-dev"
            );
        }
        other => {
            panic!("JSC backend does not support target OS: {other}");
        }
    }
}
