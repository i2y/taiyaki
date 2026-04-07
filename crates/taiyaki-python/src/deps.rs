//! npm dependency installer — fetch packages from the registry, extract,
//! bundle into a single IIFE script, and cache the result.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use flate2::read::GzDecoder;
use serde::Deserialize;
use sha2::{Digest, Sha256};

const REGISTRY: &str = "https://registry.npmjs.org";

// ── npm registry types ─────────────────────────────────────

#[derive(Deserialize)]
struct NpmMeta {
    #[serde(rename = "dist-tags")]
    dist_tags: Option<HashMap<String, String>>,
    versions: Option<HashMap<String, NpmVersion>>,
}

#[derive(Deserialize)]
struct NpmVersion {
    #[allow(dead_code)]
    version: String,
    dist: Option<NpmDist>,
    #[serde(default)]
    dependencies: HashMap<String, String>,
}

#[derive(Deserialize)]
struct NpmDist {
    tarball: String,
}

// ── Public API ─────────────────────────────────────────────

/// Install npm packages and return a JS bundle string that assigns each
/// package to `globalThis.<sanitized_name>`.
///
/// Results are cached under `~/.cache/taiyaki/deps/<hash>/bundle.js`.
pub async fn install_and_bundle(
    pkgs: &[String],
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    if pkgs.is_empty() {
        return Ok(String::new());
    }

    let hash = hash_pkgs(pkgs);
    let cache_dir = cache_dir(&hash);
    let bundle_path = cache_dir.join("bundle.js");

    // Cache hit
    if let Ok(data) = std::fs::read_to_string(&bundle_path) {
        return Ok(data);
    }

    // Cache miss — install + bundle
    let work_dir = cache_dir.join("work");
    std::fs::create_dir_all(&work_dir)?;
    let node_modules = work_dir.join("node_modules");
    std::fs::create_dir_all(&node_modules)?;

    let client = reqwest::Client::new();

    // Resolve base packages (strip subpaths, dedup)
    let mut seen = std::collections::HashSet::new();
    let mut base_pkgs = Vec::new();
    for spec in pkgs {
        let (full_name, version) = parse_spec(spec);
        let base = strip_subpath(&full_name);
        if seen.insert(base.clone()) {
            base_pkgs.push((base, version));
        }
    }

    // Install each package
    for (name, version) in &base_pkgs {
        install_package(&client, name, version, &node_modules).await?;
    }

    // Generate bundle: import each package and assign to globalThis
    let bundle = generate_bundle(pkgs, &node_modules)?;

    // Write cache
    std::fs::create_dir_all(&cache_dir)?;
    std::fs::write(&bundle_path, &bundle)?;

    // Remove work dir, keep only bundle.js
    let _ = std::fs::remove_dir_all(&work_dir);

    Ok(bundle)
}

/// Remove all cached dependency bundles.
pub fn clear_cache() -> Result<(), std::io::Error> {
    let base = cache_base_dir();
    if base.exists() {
        std::fs::remove_dir_all(&base)?;
    }
    Ok(())
}

// ── Bundle generation ──────────────────────────────────────

fn generate_bundle(
    pkgs: &[String],
    node_modules: &Path,
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    // For each package, read its main entry and wrap as a module.
    // We produce a self-contained IIFE that assigns each package to globalThis.
    let mut bundle = String::from("(function() {\n");

    for spec in pkgs {
        let (name, _) = parse_spec(spec);
        let safe_name = sanitize_var_name(&name);
        let entry_code = read_package_entry(node_modules, &name)?;

        // Wrap each package in a closure to avoid variable collisions
        bundle.push_str(&format!(
            "// --- {name} ---\n\
             globalThis.{safe_name} = (function() {{\n\
             var module = {{exports: {{}}}};\n\
             var exports = module.exports;\n\
             {entry_code}\n\
             return module.exports.default ?? module.exports;\n\
             }})();\n\n"
        ));
    }

    bundle.push_str("})();\n");
    Ok(bundle)
}

/// Read the main entry point of a package from node_modules.
fn read_package_entry(
    node_modules: &Path,
    name: &str,
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    let pkg_dir = node_modules.join(strip_subpath(name));
    let pkg_json_path = pkg_dir.join("package.json");

    if !pkg_json_path.exists() {
        return Err(format!("Package '{name}' not found in node_modules").into());
    }

    let pkg_json: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&pkg_json_path)?)?;

    // Determine entry file: exports > main > index.js
    let entry_rel = if let Some(exports) = pkg_json.get("exports") {
        resolve_exports(exports)
    } else {
        None
    }
    .or_else(|| {
        pkg_json
            .get("main")
            .and_then(|m| m.as_str())
            .map(String::from)
    })
    .unwrap_or_else(|| "index.js".to_string());

    // If the name has a subpath (e.g., "react-dom/server"), resolve from subpath
    let entry_path = if name.contains('/') && !name.starts_with('@')
        || name.starts_with('@') && name.matches('/').count() > 1
    {
        let subpath = if name.starts_with('@') {
            name.splitn(3, '/').nth(2).unwrap_or("")
        } else {
            name.splitn(2, '/').nth(1).unwrap_or("")
        };
        let sub_path = pkg_dir.join(subpath);
        if sub_path.is_file() {
            sub_path
        } else if sub_path.join("index.js").is_file() {
            sub_path.join("index.js")
        } else {
            sub_path.with_extension("js")
        }
    } else {
        let p = pkg_dir.join(&entry_rel);
        if p.is_file() {
            p
        } else if p.is_dir() {
            p.join("index.js")
        } else {
            p.with_extension("js")
        }
    };

    if !entry_path.exists() {
        return Err(format!(
            "Entry point not found for '{name}': {}",
            entry_path.display()
        )
        .into());
    }

    std::fs::read_to_string(&entry_path)
        .map_err(|e| format!("Failed to read {}: {e}", entry_path.display()).into())
}

/// Resolve the "exports" field of package.json to an entry path.
fn resolve_exports(exports: &serde_json::Value) -> Option<String> {
    match exports {
        serde_json::Value::String(s) => Some(s.clone()),
        serde_json::Value::Object(map) => {
            // Try "." > "default" > "require" > "import"
            for key in [".", "default", "require", "import"] {
                if let Some(val) = map.get(key) {
                    if let Some(s) = val.as_str() {
                        return Some(s.to_string());
                    }
                    if let Some(resolved) = resolve_exports(val) {
                        return Some(resolved);
                    }
                }
            }
            None
        }
        _ => None,
    }
}

// ── npm install ────────────────────────────────────────────

async fn install_package(
    client: &reqwest::Client,
    name: &str,
    version_range: &str,
    node_modules: &Path,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let pkg_dir = node_modules.join(name);
    if pkg_dir.exists() {
        return Ok(());
    }

    let encoded = name.replace('/', "%2f");
    let url = format!("{REGISTRY}/{encoded}");
    let resp = client
        .get(&url)
        .header("Accept", "application/vnd.npm.install-v1+json")
        .send()
        .await?;
    if !resp.status().is_success() {
        return Err(format!("Package '{name}' not found ({}).", resp.status()).into());
    }

    let meta: NpmMeta = resp.json().await?;
    let resolved = resolve_version(&meta, version_range)?;

    let version_meta = meta
        .versions
        .as_ref()
        .and_then(|v| v.get(&resolved))
        .ok_or_else(|| format!("Version {resolved} not found for {name}"))?;

    let dist = version_meta
        .dist
        .as_ref()
        .ok_or("No dist info in package")?;

    let tarball_bytes = client.get(&dist.tarball).send().await?.bytes().await?;
    extract_tarball(&tarball_bytes, &pkg_dir)?;

    // Install sub-dependencies (one level)
    for (dep_name, dep_range) in &version_meta.dependencies {
        let dep_dir = node_modules.join(dep_name);
        if !dep_dir.exists() {
            if let Err(e) =
                Box::pin(install_package(client, dep_name, dep_range, node_modules)).await
            {
                eprintln!("Warning: failed to install {dep_name}: {e}");
            }
        }
    }

    Ok(())
}

// ── Version resolution ─────────────────────────────────────

fn resolve_version(
    meta: &NpmMeta,
    range: &str,
) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
    let range = if range.is_empty() { "latest" } else { range };

    if range == "latest" {
        if let Some(tags) = &meta.dist_tags {
            if let Some(latest) = tags.get("latest") {
                return Ok(latest.clone());
            }
        }
    }

    if let Some(versions) = &meta.versions {
        if versions.contains_key(range) {
            return Ok(range.to_string());
        }

        let mut all: Vec<&str> = versions.keys().map(|s| s.as_str()).collect();
        all.sort_by(|a, b| semver_cmp(b, a));

        let req = parse_range(range);
        for v in &all {
            if !v.contains('-') && satisfies(v, &req) {
                return Ok(v.to_string());
            }
        }
    }

    Err(format!("Could not resolve version '{range}'").into())
}

struct VersionReq {
    op: &'static str,
    major: u64,
    minor: u64,
    patch: u64,
}

fn parse_range(range: &str) -> VersionReq {
    let range = range.trim();
    let (op, ver) = if let Some(r) = range.strip_prefix('^') {
        ("^", r)
    } else if let Some(r) = range.strip_prefix('~') {
        ("~", r)
    } else if let Some(r) = range.strip_prefix(">=") {
        (">=", r)
    } else if range == "*" {
        return VersionReq {
            op: "*",
            major: 0,
            minor: 0,
            patch: 0,
        };
    } else {
        ("^", range)
    };
    let parts: Vec<&str> = ver.trim().split('.').collect();
    VersionReq {
        op,
        major: parts.first().and_then(|s| s.parse().ok()).unwrap_or(0),
        minor: parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0),
        patch: parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(0),
    }
}

fn satisfies(version: &str, req: &VersionReq) -> bool {
    let parts: Vec<&str> = version.split('.').collect();
    let major: u64 = parts.first().and_then(|s| s.parse().ok()).unwrap_or(0);
    let minor: u64 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let patch: u64 = parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(0);

    match req.op {
        "*" => true,
        ">=" => (major, minor, patch) >= (req.major, req.minor, req.patch),
        "^" => {
            if req.major > 0 {
                major == req.major && (minor, patch) >= (req.minor, req.patch)
            } else if req.minor > 0 {
                major == 0 && minor == req.minor && patch >= req.patch
            } else {
                major == 0 && minor == 0 && patch == req.patch
            }
        }
        "~" => major == req.major && minor == req.minor && patch >= req.patch,
        _ => (major, minor, patch) == (req.major, req.minor, req.patch),
    }
}

fn semver_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    let pa: Vec<u64> = a
        .split('.')
        .filter_map(|s| s.split('-').next()?.parse().ok())
        .collect();
    let pb: Vec<u64> = b
        .split('.')
        .filter_map(|s| s.split('-').next()?.parse().ok())
        .collect();
    pa.cmp(&pb)
}

// ── Tarball extraction ─────────────────────────────────────

fn extract_tarball(
    data: &[u8],
    dest: &Path,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let gz = GzDecoder::new(data);
    let mut archive = tar::Archive::new(gz);

    if dest.exists() {
        std::fs::remove_dir_all(dest)?;
    }
    std::fs::create_dir_all(dest)?;

    for entry in archive.entries()? {
        let mut entry = entry?;
        let path = entry.path()?;
        let path_str = path.to_string_lossy();

        let relative = if let Some(stripped) = path_str.strip_prefix("package/") {
            PathBuf::from(stripped)
        } else {
            continue;
        };

        let target = dest.join(&relative);
        if entry.header().entry_type().is_dir() {
            std::fs::create_dir_all(&target)?;
        } else {
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let mut file = std::fs::File::create(&target)?;
            std::io::copy(&mut entry, &mut file)?;
        }
    }

    Ok(())
}

// ── Helpers ────────────────────────────────────────────────

fn parse_spec(spec: &str) -> (String, String) {
    if spec.starts_with('@') {
        if let Some(pos) = spec[1..].find('@') {
            let pos = pos + 1;
            return (spec[..pos].to_string(), spec[pos + 1..].to_string());
        }
        return (spec.to_string(), String::new());
    }
    if let Some(pos) = spec.find('@') {
        (spec[..pos].to_string(), spec[pos + 1..].to_string())
    } else {
        (spec.to_string(), String::new())
    }
}

fn strip_subpath(name: &str) -> String {
    if name.starts_with('@') {
        let parts: Vec<&str> = name.splitn(3, '/').collect();
        if parts.len() >= 2 {
            return format!("{}/{}", parts[0], parts[1]);
        }
        return name.to_string();
    }
    name.split('/').next().unwrap_or(name).to_string()
}

fn sanitize_var_name(name: &str) -> String {
    let s = name.strip_prefix('@').unwrap_or(name);
    s.replace('/', "_").replace('-', "_")
}

fn hash_pkgs(pkgs: &[String]) -> String {
    let mut sorted: Vec<&str> = pkgs.iter().map(|s| s.as_str()).collect();
    sorted.sort();
    let mut hasher = Sha256::new();
    for p in &sorted {
        hasher.update(p.as_bytes());
        hasher.update(b"\n");
    }
    let result = hasher.finalize();
    hex::encode(&result[..8])
}

fn cache_base_dir() -> PathBuf {
    if let Ok(d) = std::env::var("XDG_CACHE_HOME") {
        PathBuf::from(d).join("taiyaki").join("deps")
    } else if let Some(home) = dirs_home() {
        home.join(".cache").join("taiyaki").join("deps")
    } else {
        PathBuf::from("/tmp/taiyaki/deps")
    }
}

fn cache_dir(hash: &str) -> PathBuf {
    cache_base_dir().join(hash)
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var("HOME").ok().map(PathBuf::from)
}

// hex helper (inline to avoid adding a dep)
mod hex {
    pub fn encode(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }
}
