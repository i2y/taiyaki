/// Fine-grained permission control for script execution.
///
/// By default all permissions are granted (allow-all).
/// Use `Permissions::none()` to deny all, then selectively allow.
#[derive(Debug, Clone)]
pub struct Permissions {
    /// File read access. None = all allowed, Some([]) = none allowed.
    pub read: Option<Vec<String>>,
    /// File write access.
    pub write: Option<Vec<String>>,
    /// Network access (host patterns).
    pub net: Option<Vec<String>>,
    /// Environment variable access.
    pub env: Option<Vec<String>>,
    /// Command execution access.
    pub run: Option<Vec<String>>,
}

impl Default for Permissions {
    /// Default: all permissions granted (no restrictions).
    fn default() -> Self {
        Self {
            read: None,
            write: None,
            net: None,
            env: None,
            run: None,
        }
    }
}

impl Permissions {
    /// All permissions denied (sandbox mode).
    pub fn none() -> Self {
        Self {
            read: Some(Vec::new()),
            write: Some(Vec::new()),
            net: Some(Vec::new()),
            env: Some(Vec::new()),
            run: Some(Vec::new()),
        }
    }

    /// Check if a file read is allowed.
    pub fn check_read(&self, path: &str) -> Result<(), PermissionError> {
        check_path_list(&self.read, path, "read")
    }

    /// Check if a file write is allowed.
    pub fn check_write(&self, path: &str) -> Result<(), PermissionError> {
        check_path_list(&self.write, path, "write")
    }

    /// Check if network access to a host is allowed.
    pub fn check_net(&self, host: &str) -> Result<(), PermissionError> {
        check_list(&self.net, host, "net", |pattern, val| {
            val == pattern || val.ends_with(pattern)
        })
    }

    /// Check if an environment variable access is allowed.
    pub fn check_env(&self, name: &str) -> Result<(), PermissionError> {
        check_list(&self.env, name, "env", |allowed, val| val == allowed)
    }

    /// Check if command execution is allowed.
    pub fn check_run(&self, command: &str) -> Result<(), PermissionError> {
        check_list(&self.run, command, "run", |allowed, val| val == allowed)
    }
}

fn check_list(
    list: &Option<Vec<String>>,
    value: &str,
    kind: &str,
    matches: impl Fn(&str, &str) -> bool,
) -> Result<(), PermissionError> {
    match list {
        None => Ok(()),
        Some(allowed) if allowed.is_empty() => {
            Err(PermissionError::Denied(kind.to_string(), value.to_string()))
        }
        Some(allowed) => {
            if allowed.iter().any(|a| matches(a, value)) {
                Ok(())
            } else {
                Err(PermissionError::Denied(kind.to_string(), value.to_string()))
            }
        }
    }
}

fn check_path_list(
    list: &Option<Vec<String>>,
    path: &str,
    kind: &str,
) -> Result<(), PermissionError> {
    check_list(list, path, kind, |allowed, val| val.starts_with(allowed))
}

#[derive(Debug)]
pub enum PermissionError {
    Denied(String, String),
}

impl std::fmt::Display for PermissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PermissionError::Denied(kind, resource) => {
                write!(
                    f,
                    "PermissionDenied: {kind} access to \"{resource}\" is not allowed. Use --allow-{kind} to grant access."
                )
            }
        }
    }
}

impl std::error::Error for PermissionError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_allows_all() {
        let p = Permissions::default();
        assert!(p.check_read("/any/path").is_ok());
        assert!(p.check_write("/any/path").is_ok());
        assert!(p.check_net("example.com").is_ok());
        assert!(p.check_env("HOME").is_ok());
        assert!(p.check_run("ls").is_ok());
    }

    #[test]
    fn test_none_denies_all() {
        let p = Permissions::none();
        assert!(p.check_read("/any/path").is_err());
        assert!(p.check_write("/any/path").is_err());
        assert!(p.check_net("example.com").is_err());
        assert!(p.check_env("HOME").is_err());
        assert!(p.check_run("ls").is_err());
    }

    #[test]
    fn test_selective_allow() {
        let p = Permissions {
            read: Some(vec!["/tmp".to_string(), "/home".to_string()]),
            write: Some(vec!["/tmp".to_string()]),
            net: Some(vec!["example.com".to_string()]),
            env: Some(vec!["HOME".to_string(), "PATH".to_string()]),
            run: Some(vec!["ls".to_string()]),
        };
        assert!(p.check_read("/tmp/file.txt").is_ok());
        assert!(p.check_read("/home/user").is_ok());
        assert!(p.check_read("/etc/passwd").is_err());
        assert!(p.check_write("/tmp/out.txt").is_ok());
        assert!(p.check_write("/etc/config").is_err());
        assert!(p.check_net("example.com").is_ok());
        assert!(p.check_net("evil.com").is_err());
        assert!(p.check_env("HOME").is_ok());
        assert!(p.check_env("SECRET").is_err());
        assert!(p.check_run("ls").is_ok());
        assert!(p.check_run("rm").is_err());
    }
}
