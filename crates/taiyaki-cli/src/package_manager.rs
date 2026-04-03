use std::collections::HashMap;
use std::path::{Path, PathBuf};

use flate2::read::GzDecoder;
use serde::{Deserialize, Serialize};

const REGISTRY: &str = "https://registry.npmjs.org";

#[derive(Serialize, Deserialize, Debug, Default)]
pub struct PackageJson {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub main: Option<String>,
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    pub module_type: Option<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub scripts: HashMap<String, String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub dependencies: HashMap<String, String>,
    #[serde(
        rename = "devDependencies",
        default,
        skip_serializing_if = "HashMap::is_empty"
    )]
    pub dev_dependencies: HashMap<String, String>,
}

#[derive(Deserialize, Debug)]
struct NpmPackageMeta {
    #[serde(rename = "dist-tags")]
    dist_tags: Option<HashMap<String, String>>,
    versions: Option<HashMap<String, NpmVersionMeta>>,
}

#[derive(Deserialize, Debug)]
struct NpmVersionMeta {
    #[allow(dead_code)]
    version: String,
    dist: Option<NpmDist>,
    #[serde(default)]
    dependencies: HashMap<String, String>,
}

#[derive(Deserialize, Debug)]
struct NpmDist {
    tarball: String,
    #[allow(dead_code)]
    shasum: Option<String>,
}

fn read_package_json() -> Result<PackageJson, Box<dyn std::error::Error>> {
    let path = Path::new("package.json");
    if !path.exists() {
        return Err("package.json not found. Run 'taiyaki init' first.".into());
    }
    let content = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&content)?)
}

fn write_package_json(pkg: &PackageJson) -> Result<(), Box<dyn std::error::Error>> {
    let json = serde_json::to_string_pretty(pkg)?;
    std::fs::write("package.json", format!("{json}\n"))?;
    Ok(())
}

pub async fn init() -> Result<(), Box<dyn std::error::Error>> {
    if Path::new("package.json").exists() {
        println!("package.json already exists.");
        return Ok(());
    }

    let dir_name = std::env::current_dir()?
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("my-project")
        .to_string();

    let pkg = PackageJson {
        name: Some(dir_name),
        version: Some("1.0.0".into()),
        description: Some(String::new()),
        main: Some("index.js".into()),
        module_type: Some("module".into()),
        scripts: HashMap::from([("test".into(), "taiyaki test".into())]),
        dependencies: HashMap::new(),
        dev_dependencies: HashMap::new(),
    };

    write_package_json(&pkg)?;
    println!("Created package.json");
    Ok(())
}

pub async fn install() -> Result<(), Box<dyn std::error::Error>> {
    let pkg = read_package_json()?;
    let all_deps: Vec<(String, String)> = pkg
        .dependencies
        .iter()
        .chain(pkg.dev_dependencies.iter())
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();

    if all_deps.is_empty() {
        println!("No dependencies to install.");
        return Ok(());
    }

    std::fs::create_dir_all("node_modules")?;

    let client = reqwest::Client::new();
    let mut installed = 0;

    for (name, version_range) in &all_deps {
        match install_package(&client, name, version_range, Path::new("node_modules")).await {
            Ok(ver) => {
                installed += 1;
                println!("  + {name}@{ver}");
            }
            Err(e) => {
                eprintln!("  ✗ {name}: {e}");
            }
        }
    }

    println!("\n{installed} package(s) installed.");
    Ok(())
}

pub async fn add(packages: &[String], dev: bool) -> Result<(), Box<dyn std::error::Error>> {
    let mut pkg = read_package_json().unwrap_or_default();

    std::fs::create_dir_all("node_modules")?;

    let client = reqwest::Client::new();

    for spec in packages {
        let (name, requested_version) = parse_package_spec(spec);

        let version_range = if requested_version.is_empty() {
            "latest".to_string()
        } else {
            requested_version.clone()
        };

        match install_package(&client, &name, &version_range, Path::new("node_modules")).await {
            Ok(ver) => {
                let range = format!("^{ver}");
                if dev {
                    pkg.dev_dependencies.insert(name.clone(), range);
                    pkg.dependencies.remove(&name);
                } else {
                    pkg.dependencies.insert(name.clone(), range);
                    pkg.dev_dependencies.remove(&name);
                }
                println!("  + {name}@{ver}");
            }
            Err(e) => {
                eprintln!("  ✗ {name}: {e}");
            }
        }
    }

    write_package_json(&pkg)?;
    Ok(())
}

pub async fn remove(packages: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let mut pkg = read_package_json()?;

    for name in packages {
        pkg.dependencies.remove(name);
        pkg.dev_dependencies.remove(name);

        let pkg_dir = Path::new("node_modules").join(name);
        if pkg_dir.exists() {
            std::fs::remove_dir_all(&pkg_dir)?;
        }
        println!("  - {name}");
    }

    write_package_json(&pkg)?;
    Ok(())
}

fn parse_package_spec(spec: &str) -> (String, String) {
    // Handle scoped packages: @scope/name@version
    if spec.starts_with('@') {
        if let Some(at_pos) = spec[1..].find('@') {
            let at_pos = at_pos + 1;
            return (spec[..at_pos].to_string(), spec[at_pos + 1..].to_string());
        }
        return (spec.to_string(), String::new());
    }
    // Regular: name@version
    if let Some(at_pos) = spec.find('@') {
        (spec[..at_pos].to_string(), spec[at_pos + 1..].to_string())
    } else {
        (spec.to_string(), String::new())
    }
}

async fn install_package(
    client: &reqwest::Client,
    name: &str,
    version_range: &str,
    node_modules: &Path,
) -> Result<String, Box<dyn std::error::Error>> {
    // Check if already installed
    let pkg_dir = node_modules.join(name);
    if pkg_dir.exists() {
        if let Ok(content) = std::fs::read_to_string(pkg_dir.join("package.json")) {
            if let Ok(installed_pkg) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(ver) = installed_pkg.get("version").and_then(|v| v.as_str()) {
                    return Ok(ver.to_string());
                }
            }
        }
    }

    // Fetch package metadata from npm registry
    let url = format!("{REGISTRY}/{}", urlencoded_name(name));
    let resp = client
        .get(&url)
        .header("Accept", "application/vnd.npm.install-v1+json")
        .send()
        .await?;
    if !resp.status().is_success() {
        return Err(format!("Package '{}' not found ({})", name, resp.status()).into());
    }

    let meta: NpmPackageMeta = resp.json().await?;

    // Resolve version
    let resolved_version = resolve_version(&meta, version_range)?;

    let version_meta = meta
        .versions
        .as_ref()
        .and_then(|v| v.get(&resolved_version))
        .ok_or_else(|| format!("Version {} not found for {}", resolved_version, name))?;

    let dist = version_meta
        .dist
        .as_ref()
        .ok_or("No dist info in package metadata")?;

    // Download tarball
    let tarball_bytes = client.get(&dist.tarball).send().await?.bytes().await?;

    // Extract to node_modules/name
    extract_tarball(&tarball_bytes, &pkg_dir)?;

    // Install sub-dependencies (one level deep for simplicity)
    for (dep_name, dep_range) in &version_meta.dependencies {
        let dep_dir = node_modules.join(dep_name);
        if !dep_dir.exists() {
            if let Err(e) =
                Box::pin(install_package(client, dep_name, dep_range, node_modules)).await
            {
                eprintln!("    Warning: failed to install {dep_name}: {e}");
            }
        }
    }

    Ok(resolved_version)
}

fn urlencoded_name(name: &str) -> String {
    // Scoped packages: @scope/name -> @scope%2fname
    name.replace('/', "%2f")
}

fn resolve_version(
    meta: &NpmPackageMeta,
    range: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    // "latest" → use dist-tags.latest
    if range == "latest" || range.is_empty() {
        if let Some(tags) = &meta.dist_tags {
            if let Some(latest) = tags.get("latest") {
                return Ok(latest.clone());
            }
        }
    }

    // Exact version
    if let Some(versions) = &meta.versions {
        if versions.contains_key(range) {
            return Ok(range.to_string());
        }
    }

    // Semver range resolution
    if let Some(versions) = &meta.versions {
        let mut all_versions: Vec<&str> = versions.keys().map(|s| s.as_str()).collect();
        all_versions.sort_by(|a, b| {
            semver_compare(b, a) // reverse sort: highest first
        });

        let req = parse_version_range(range);
        for ver in &all_versions {
            if satisfies(ver, &req) {
                return Ok(ver.to_string());
            }
        }
    }

    Err(format!("Could not resolve version '{range}'").into())
}

struct VersionReq {
    op: &'static str, // ">=", "^", "~", "=", "*"
    major: u64,
    minor: u64,
    patch: u64,
}

fn parse_version_range(range: &str) -> VersionReq {
    let range = range.trim();
    let (op, ver_str) = if range.starts_with("^") {
        ("^", &range[1..])
    } else if range.starts_with("~") {
        ("~", &range[1..])
    } else if range.starts_with(">=") {
        (">=", &range[2..])
    } else if range == "*" {
        return VersionReq {
            op: "*",
            major: 0,
            minor: 0,
            patch: 0,
        };
    } else {
        ("^", range) // default: caret
    };

    let parts: Vec<&str> = ver_str.trim().split('.').collect();
    let major = parts.first().and_then(|s| s.parse().ok()).unwrap_or(0);
    let minor = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let patch = parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(0);

    VersionReq {
        op,
        major,
        minor,
        patch,
    }
}

fn satisfies(version: &str, req: &VersionReq) -> bool {
    // Skip pre-release versions
    if version.contains('-') {
        return false;
    }

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

fn semver_compare(a: &str, b: &str) -> std::cmp::Ordering {
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

fn extract_tarball(tarball_bytes: &[u8], dest: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let gz = GzDecoder::new(tarball_bytes);
    let mut archive = tar::Archive::new(gz);

    if dest.exists() {
        std::fs::remove_dir_all(dest)?;
    }
    std::fs::create_dir_all(dest)?;

    for entry in archive.entries()? {
        let mut entry = entry?;
        let path = entry.path()?;
        let path_str = path.to_string_lossy();

        // npm tarballs have a "package/" prefix
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
