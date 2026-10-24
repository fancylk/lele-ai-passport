//! 系统通知 (§六十七/§六十九): 按平台分发 ——
//!   macOS:   osascript display notification (子进程, 同类通知 30s 限频)
//!   Windows: 托盘气泡 (tray.rs 建窗口后 set_tray_hwnd 绑定; WM_APP+3 携带消息体)
//! 按 key 限频(默认 30s)防刷屏.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

static ENABLED: AtomicBool = AtomicBool::new(true);
static LAST: Mutex<Option<HashMap<String, Instant>>> = Mutex::new(None);
const RATE_WINDOW: Duration = Duration::from_secs(30);

#[cfg(target_os = "macos")]
mod imp {
    use std::process::Command;

    pub fn send_now(title: &str, body: &str) {
        let esc = |s: &str| s.replace('\\', "\\\\").replace('"', "'");
        let script = format!(
            "display notification \"{}\" with title \"{}\"",
            esc(body),
            esc(title)
        );
        std::thread::Builder::new()
            .name("notify".into())
            .spawn(move || {
                let _ = Command::new("osascript").arg("-e").arg(&script).output();
            })
            .ok();
    }
}

#[cfg(target_os = "windows")]
mod imp {
    use super::*;
    use std::sync::atomic::AtomicIsize;

    static TRAY_HWND: AtomicIsize = AtomicIsize::new(0);
    const WM_APP_NOTIFY: usize = 0x8003; // WM_APP+3

    extern "system" {
        fn PostMessageW(hwnd: isize, msg: u32, wparam: usize, lparam: isize) -> i32;
    }

    /// tray.rs 建好窗口后绑定 (气泡经窗口消息投递到托盘线程)
    pub fn set_tray_hwnd(hwnd: isize) {
        TRAY_HWND.store(hwnd, Ordering::Release);
    }

    pub fn send_now(title: &str, body: &str) {
        let hwnd = TRAY_HWND.load(Ordering::Acquire);
        if hwnd == 0 {
            return;
        }
        // Box<String> 原始指针经 lParam 跨线程交给托盘窗口过程 (托盘侧 Box::from_raw 回收)
        let payload = Box::into_raw(Box::new(format!("{title}\u{1f}{body}")));
        unsafe {
            if PostMessageW(hwnd, WM_APP_NOTIFY as u32, 0, payload as isize) == 0 {
                // bugbot 修复: 投递失败(窗口销毁中)回收 payload, 防泄漏
                drop(Box::from_raw(payload));
            }
        }
    }

    pub fn wm_app_notify() -> u32 {
        WM_APP_NOTIFY as u32
    }
}

pub fn set_enabled(v: bool) {
    ENABLED.store(v, Ordering::Relaxed);
}

/// 发系统通知. key 相同的通知在限频窗口内只发一次.
pub fn send(key: &str, title: &str, body: &str) {
    if !ENABLED.load(Ordering::Relaxed) {
        return;
    }
    {
        let mut g = LAST.lock().unwrap();
        let map = g.get_or_insert_with(HashMap::new);
        let now = Instant::now();
        if let Some(t) = map.get(key) {
            if now.duration_since(*t) < RATE_WINDOW {
                return;
            }
        }
        map.insert(key.to_string(), now);
    }
    imp::send_now(title, body);
}

#[cfg(target_os = "windows")]
pub use imp::set_tray_hwnd;
#[cfg(target_os = "windows")]
pub use imp::wm_app_notify;
