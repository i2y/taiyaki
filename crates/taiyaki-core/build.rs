fn main() {
    let crate_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap();

    std::fs::create_dir_all("include").ok();

    cbindgen::Builder::new()
        .with_crate(&crate_dir)
        .with_config(cbindgen::Config::from_file("cbindgen.toml").unwrap())
        .generate()
        .expect("Unable to generate C bindings")
        .write_to_file("include/taiyaki.h");

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
