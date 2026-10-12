//! macOS 系统通知 (§六十七): osascript display notification, 零依赖.
//! 按 key 限频(默认 30s)防刷屏; 通知归属 Script Editor(osascript 身份), 属正常.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

static ENABLED: AtomicBool = AtomicBool::new(true);
static LAST: Mutex<Option<HashMap<String, Instant>>> = Mutex::new(None);
const RATE_WINDOW: Duration = Duration::from_secs(30);

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
    let esc = |s: &str| s.replace('\\', "\\\\").replace('"', "'");
    let script = format!(
        "display notification \"{}\" with title \"{}\"",
        esc(body),
        esc(title)
    );
    std::thread::Builder::new()
        .name("notify".into())
        .spawn(move || {
            let _ = std::process::Command::new("osascript")
                .arg("-e")
                .arg(&script)
                .output();
        })
        .ok();
}
