//! 时间戳日志: 单行 println, launchd StandardOutPath 重定向即成日志文件
//! (Rust stdout 恒为行缓冲, 每行即落盘).

use std::time::{SystemTime, UNIX_EPOCH};

pub fn now_parts() -> String {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let (y, mo, da, h, mi, s) = local_civil(d.as_secs() as i64);
    format!("{y:04}-{mo:02}-{da:02} {h:02}:{mi:02}:{s:02}")
}

#[cfg(target_os = "macos")]
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

#[cfg(target_os = "windows")]
fn local_civil(secs_utc: i64) -> (i64, u32, u32, u32, u32, u32) {
    // 无依赖方案: UTC+8 偏移按系统时区不可零依赖取得, 用偏移查询失败则退 UTC;
    // 实测主要用途=日志排序, 这里用 libc 的 _localtime64_s 不可用, 改用 win32 GetLocalTime
    #[repr(C)]
    struct SystemTime {
        year: u16,
        month: u16,
        day_of_week: u16,
        day: u16,
        hour: u16,
        minute: u16,
        second: u16,
        millis: u16,
    }
    extern "system" {
        fn GetLocalTime(systime: *mut SystemTime);
    }
    unsafe {
        let mut st = SystemTime { year: 1970, month: 1, day_of_week: 0, day: 1, hour: 0, minute: 0, second: 0, millis: 0 };
        GetLocalTime(&mut st);
        (
            st.year as i64,
            st.month as u32,
            st.day as u32,
            st.hour as u32,
            st.minute as u32,
            st.second as u32,
        )
    }
}

#[macro_export]
macro_rules! logi {
    ($($arg:tt)*) => {
        println!("[{}] {}", $crate::logx::now_parts(), format_args!($($arg)*))
    };
}
