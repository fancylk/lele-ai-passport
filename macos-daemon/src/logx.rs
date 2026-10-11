//! 时间戳日志: 单行 println, launchd StandardOutPath 重定向即成日志文件
//! (Rust stdout 恒为行缓冲, 每行即落盘).

use std::time::{SystemTime, UNIX_EPOCH};

pub fn now_parts() -> String {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let (y, mo, da, h, mi, s) = local_civil(d.as_secs() as i64);
    format!("{y:04}-{mo:02}-{da:02} {h:02}:{mi:02}:{s:02}")
}

fn local_civil(secs_utc: i64) -> (i64, u32, u32, u32, u32, u32) {
    unsafe {
        let mut tm: libc::tm = std::mem::zeroed();
        let t: libc::time_t = secs_utc as libc::time_t;
        if libc::localtime_r(&t, &mut tm).is_null() {
            return (1970, 1, 1, 0, 0, 0);
        }
        (
            tm.tm_year as i64 + 1900,
            (tm.tm_mon + 1) as u32,
            tm.tm_mday as u32,
            tm.tm_hour as u32,
            tm.tm_min as u32,
            tm.tm_sec as u32,
        )
    }
}

#[macro_export]
macro_rules! logi {
    ($($arg:tt)*) => {
        println!("[{}] {}", $crate::logx::now_parts(), format_args!($($arg)*))
    };
}
