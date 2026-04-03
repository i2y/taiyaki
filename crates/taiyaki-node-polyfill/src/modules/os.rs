use taiyaki_core::engine::{EngineError, HostCallback, JsValue};

pub fn host_functions() -> Vec<(&'static str, HostCallback)> {
    vec![
        ("__os_hostname", Box::new(os_hostname)),
        ("__os_homedir", Box::new(os_homedir)),
        ("__os_tmpdir", Box::new(os_tmpdir)),
        ("__os_platform", Box::new(os_platform)),
        ("__os_arch", Box::new(os_arch)),
        ("__os_type", Box::new(os_type)),
        ("__os_release", Box::new(os_release)),
        ("__os_cpus", Box::new(os_cpus)),
        ("__os_totalmem", Box::new(os_totalmem)),
        ("__os_freemem", Box::new(os_freemem)),
        ("__os_uptime", Box::new(os_uptime)),
        ("__os_endianness", Box::new(os_endianness)),
    ]
}

fn os_hostname(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let mut buf = [0u8; 256];
    let ret = unsafe { libc::gethostname(buf.as_mut_ptr() as *mut libc::c_char, buf.len()) };
    if ret != 0 {
        return Ok(JsValue::String(String::new()));
    }
    let len = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
    Ok(JsValue::String(
        String::from_utf8_lossy(&buf[..len]).into_owned(),
    ))
}

fn os_homedir(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::String(std::env::var("HOME").unwrap_or_default()))
}

fn os_tmpdir(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::String(
        std::env::temp_dir().to_string_lossy().into_owned(),
    ))
}

fn os_platform(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::String(super::node_platform().to_string()))
}

fn os_arch(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::String(super::node_arch().to_string()))
}

fn os_type(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let t = match std::env::consts::OS {
        "macos" => "Darwin",
        "linux" => "Linux",
        "windows" => "Windows_NT",
        other => other,
    };
    Ok(JsValue::String(t.to_string()))
}

fn os_release(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let mut info: libc::utsname = unsafe { std::mem::zeroed() };
    let ret = unsafe { libc::uname(&mut info) };
    if ret != 0 {
        return Ok(JsValue::String(String::new()));
    }
    let release = unsafe {
        std::ffi::CStr::from_ptr(info.release.as_ptr())
            .to_string_lossy()
            .into_owned()
    };
    Ok(JsValue::String(release))
}

fn os_cpus(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let count = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1);
    Ok(JsValue::Number(count as f64))
}

#[cfg(target_os = "macos")]
fn os_totalmem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let mut size: u64 = 0;
    let mut len = std::mem::size_of::<u64>();
    let mib = [libc::CTL_HW, libc::HW_MEMSIZE];
    let ret = unsafe {
        libc::sysctl(
            mib.as_ptr() as *mut _,
            2,
            &mut size as *mut u64 as *mut _,
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    if ret != 0 {
        return Ok(JsValue::Number(0.0));
    }
    Ok(JsValue::Number(size as f64))
}

#[cfg(target_os = "linux")]
fn os_totalmem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let info = unsafe {
        let mut info: libc::sysinfo = std::mem::zeroed();
        libc::sysinfo(&mut info);
        info
    };
    Ok(JsValue::Number(
        (info.totalram * info.mem_unit as u64) as f64,
    ))
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn os_totalmem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::Number(0.0))
}

#[cfg(target_os = "macos")]
fn os_freemem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) } as u64;
    let mut count: u32 = 0;
    let mut len = std::mem::size_of::<u32>();
    // vm.page_free_count
    let name = std::ffi::CString::new("vm.page_free_count").unwrap();
    let ret = unsafe {
        libc::sysctlbyname(
            name.as_ptr(),
            &mut count as *mut u32 as *mut _,
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    if ret != 0 {
        return Ok(JsValue::Number(0.0));
    }
    Ok(JsValue::Number((count as u64 * page_size) as f64))
}

#[cfg(target_os = "linux")]
fn os_freemem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    let info = unsafe {
        let mut info: libc::sysinfo = std::mem::zeroed();
        libc::sysinfo(&mut info);
        info
    };
    Ok(JsValue::Number(
        (info.freeram * info.mem_unit as u64) as f64,
    ))
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn os_freemem(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    Ok(JsValue::Number(0.0))
}

fn os_uptime(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    #[cfg(target_os = "macos")]
    {
        let mut tv: libc::timeval = unsafe { std::mem::zeroed() };
        let mut len = std::mem::size_of::<libc::timeval>();
        let mib = [libc::CTL_KERN, libc::KERN_BOOTTIME];
        let ret = unsafe {
            libc::sysctl(
                mib.as_ptr() as *mut _,
                2,
                &mut tv as *mut libc::timeval as *mut _,
                &mut len,
                std::ptr::null_mut(),
                0,
            )
        };
        if ret != 0 {
            return Ok(JsValue::Number(0.0));
        }
        let now = unsafe { libc::time(std::ptr::null_mut()) };
        return Ok(JsValue::Number((now - tv.tv_sec) as f64));
    }
    #[cfg(target_os = "linux")]
    {
        let info = unsafe {
            let mut info: libc::sysinfo = std::mem::zeroed();
            libc::sysinfo(&mut info);
            info
        };
        return Ok(JsValue::Number(info.uptime as f64));
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    {
        Ok(JsValue::Number(0.0))
    }
}

fn os_endianness(_args: &[JsValue]) -> Result<JsValue, EngineError> {
    if cfg!(target_endian = "little") {
        Ok(JsValue::String("LE".to_string()))
    } else {
        Ok(JsValue::String("BE".to_string()))
    }
}
