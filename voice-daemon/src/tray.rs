//! Windows 托盘 (§六十九): 任务栏图标 + 菜单 + 气泡通知 + 消息循环.
//!
//! 守护与托盘同进程 (Windows 无需独立菜单栏进程): 主线程跑 Win32 消息循环,
//! 收流/触发/音频在后台线程 (见 main.rs).
//! 图标: 任务栏常驻; 状态经菜单首行 + 气泡通知呈现 (图标动态绘制后续版本).
//! 菜单: 状态总览 / 语音目标 (TSET@mac|pc 直发中转) / 打开日志 / 编辑配置 /
//!       系统通知开关 / 重启 / 退出.

#![cfg(target_os = "windows")]

use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::{Arc, Mutex};

use crate::config::{self, Config};

// ---------- Win32 常量 ----------
const WM_APP_TRAY: u32 = 0x8001; // WM_APP+1 托盘回调
const WM_APP_NOTIFY: u32 = 0x8003; // WM_APP+3 气泡通知 (notify.rs)
const WM_TIMER: u32 = 0x0113;
const WM_COMMAND: u32 = 0x0111;
const WM_DESTROY: u32 = 0x0002;
const WM_CLOSE: u32 = 0x0010;
const WM_LBUTTONUP: u32 = 0x0202;
const WM_RBUTTONUP: u32 = 0x0205;
const WM_CONTEXTMENU: u32 = 0x007B;
const WM_NULL: u32 = 0x0000;

const NIM_ADD: u32 = 0;
const NIM_MODIFY: u32 = 1;
const NIM_DELETE: u32 = 2;
const NIF_MESSAGE: u32 = 0x1;
const NIF_ICON: u32 = 0x2;
const NIF_TIP: u32 = 0x4;
const NIF_INFO: u32 = 0x10;
const NIIF_INFO: u32 = 0x1;
const IDI_APPLICATION: usize = 32512;

const TPM_RIGHTBUTTON: u32 = 0x2;
const TPM_RETURNCMD: u32 = 0x100;
const TPM_NONOTIFY: u32 = 0x80;
const MF_STRING: u32 = 0x0;
const MF_GRAYED: u32 = 0x1;
const MF_CHECKED: u32 = 0x8;
const MF_SEPARATOR: u32 = 0x800;

const ID_STATUS: usize = 101;
const ID_EVENT: usize = 102;
const ID_ROSTER_REFRESH: usize = 112;
const ID_OPEN_LOG: usize = 120;
const ID_EDIT_CFG: usize = 121;
const ID_NOTIFY: usize = 122;
const ID_RESTART: usize = 130;
const ID_QUIT: usize = 131;

// ---------- 跨线程共享状态 ----------
#[derive(Default)]
pub struct TrayState {
    pub alive: AtomicBool,
    pub direct: AtomicBool,
    pub sound: AtomicBool,
    pub notify_on: AtomicBool,
    pub pkts: Mutex<String>,
    pub kbps: Mutex<String>,
    pub rtt: Mutex<String>,
    pub recent: Mutex<String>,
    pub target: Mutex<Option<String>>, // None=广播
}

struct TrayCtx {
    cfg: Config,
    state: Arc<TrayState>,
    hwnd: AtomicIsize,
    last_log_size: Mutex<u64>,
}

/// §七十 在线花名册 (query_roster_async 更新, build_menu 读取)
static ROSTER: Mutex<Vec<(String, String, String)>> = Mutex::new(Vec::new()); // (tag, host, os)

// ---------- Win32 FFI ----------
#[allow(non_snake_case)]
mod win {
    use std::ffi::c_void;

    pub type HWND = isize;
    pub type HICON = isize;
    pub type HMENU = isize;
    pub type HINSTANCE = isize;
    pub type WPARAM = usize;
    pub type LPARAM = isize;
    pub type LRESULT = isize;

    #[repr(C)]
    pub struct POINT {
        pub x: i32,
        pub y: i32,
    }

    #[repr(C)]
    pub struct MSG {
        pub hwnd: HWND,
        pub message: u32,
        pub wparam: WPARAM,
        pub lparam: LPARAM,
        pub pt: POINT,
        pub time: u32,
        pub pprivate: usize,
    }

    #[repr(C)]
    pub struct WNDCLASSW {
        pub style: u32,
        pub lpfnwndproc: usize,          // WNDPROC
        pub cbclsextra: i32,
        pub cbwndextra: i32,
        pub hinstance: HINSTANCE,
        pub hicon: HICON,
        pub hcursor: isize,
        pub hbrbackground: isize,
        pub lpszmenuname: *const u16,
        pub lpszclassname: *const u16,
    }

    #[repr(C)]
    pub struct NOTIFYICONDATAW {
        pub cbsize: u32,
        pub hwnd: HWND,
        pub uid: u32,
        pub uflags: u32,
        pub ucallbackmessage: u32,
        pub hicon: HICON,
        pub sztip: [u16; 128],
        pub dwstate: u32,
        pub dwstatemask: u32,
        pub szinfo: [u16; 256],
        pub uversion: u32,
        pub szinfotitle: [u16; 64],
        pub dwinfoflags: u32,
        pub guiditem: [u8; 16],
        pub hballoonicon: HICON,
    }

    #[link(name = "user32")]
    extern "system" {
        pub fn RegisterClassW(wc: *const WNDCLASSW) -> u16;
        pub fn CreateWindowExW(
            exstyle: u32, class: *const u16, title: *const u16, style: u32,
            x: i32, y: i32, w: i32, h: i32, parent: HWND, menu: HMENU,
            inst: HINSTANCE, param: *mut c_void,
        ) -> HWND;
        pub fn DefWindowProcW(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT;
        pub fn GetMessageW(msg: *mut MSG, hwnd: HWND, min: u32, max: u32) -> i32;
        pub fn TranslateMessage(msg: *const MSG) -> i32;
        pub fn DispatchMessageW(msg: *const MSG) -> isize;
        pub fn PostQuitMessage(code: i32);
        pub fn PostMessageW(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> i32;
        pub fn SetTimer(hwnd: HWND, id: usize, ms: u32, proc: usize) -> usize;
        pub fn Shell_NotifyIconW(msg: u32, data: *const NOTIFYICONDATAW) -> i32;
        pub fn LoadIconW(inst: HINSTANCE, name: *const u16) -> HICON;
        pub fn CreatePopupMenu() -> HMENU;
        pub fn AppendMenuW(menu: HMENU, flags: u32, id: usize, text: *const u16) -> i32;
        pub fn TrackPopupMenu(
            menu: HMENU, flags: u32, x: i32, y: i32, reserved: i32, hwnd: HWND, rect: *const c_void,
        ) -> i32;
        pub fn DestroyMenu(menu: HMENU) -> i32;
        pub fn SetForegroundWindow(hwnd: HWND) -> i32;
        pub fn GetCursorPos(pt: *mut POINT) -> i32;
        pub fn GetModuleHandleW(name: *const u16) -> HINSTANCE;
    }

    #[link(name = "kernel32")]
    extern "system" {
        pub fn GetCurrentProcessId() -> u32;
    }
}

use win::*;

// ---------- 工具 ----------
fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// 按 UTF-16 单元数截断 (szTip/szInfo 定长缓冲, 禁止在 char 边界中间切)
fn fit(s: &str, units: usize) -> String {
    if s.chars().count() <= units {
        return s.to_string();
    }
    s.chars().take(units).collect()
}

fn reg_set(path: &str, name: &str, value: &str) -> bool {
    std::process::Command::new("reg")
        .args(["add", path, "/v", name, "/t", "REG_SZ", "/d", value, "/f"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn reg_delete(path: &str, name: &str) {
    let _ = std::process::Command::new("reg")
        .args(["delete", path, "/v", name, "/f"])
        .output();
}

pub fn run_key_path() -> &'static str {
    r"Software\Microsoft\Windows\CurrentVersion\Run"
}

// ---------- 中转目标 RPC (与 Mac 菜单栏同款) ----------
fn config_value(text: &str, key: &str) -> Option<String> {
    for line in text.lines() {
        let t = line.trim();
        if let Some(rest) = t.strip_prefix(&format!("{key} ")) {
            return Some(rest.trim().trim_matches('"').to_string());
        }
        if t.starts_with(&format!("{key}=")) {
            return Some(t[key.len() + 1..].trim().trim_matches('"').to_string());
        }
    }
    None
}

fn relay_rpc(payload: &str, timeout: f64) -> Option<String> {
    use std::net::UdpSocket;
    let cfg_text = std::fs::read_to_string(config::default_path()?).ok()?;
    let host = config_value(&cfg_text, "host").unwrap_or_else(|| "124.221.187.167".into());
    let token = config_value(&cfg_text, "token").unwrap_or_else(|| "lele-6deb6d37".into());
    let msg = payload.replace("$TOKEN", &token);
    let sock = UdpSocket::bind("0.0.0.0:0").ok()?;
    sock.set_read_timeout(Some(std::time::Duration::from_secs_f64(timeout))).ok()?;
    sock.send_to(msg.as_bytes(), (host.as_str(), 9761)).ok()?;
    let mut buf = [0u8; 64];
    let n = sock.recv(&mut buf).ok()?;
    Some(String::from_utf8_lossy(&buf[..n]).to_string())
}

fn set_target_async(target: &'static str, state: Arc<TrayState>) {
    std::thread::Builder::new()
        .name("tset".into())
        .spawn(move || {
            let resp = relay_rpc(&format!("TSET$TOKEN@{target}"), 1.5);
            if resp.as_deref().map(|r| r.starts_with("TSET_OK")).unwrap_or(false) {
                *state.target.lock().unwrap() = Some(target.to_string());
                crate::notify::send("target", "乐乐语音桥", &format!("语音目标已切到 {target}"));
            } else {
                crate::notify::send("target", "乐乐语音桥", "目标切换失败 (中转无响应)");
            }
        })
        .ok();
}

fn query_roster_async(state: Arc<TrayState>) {
    std::thread::Builder::new()
        .name("roster".into())
        .spawn(move || {
            let Some(resp) = relay_rpc("RQST$TOKEN", 2.0) else { return };
            let Some(json) = resp.strip_prefix("RST ") else { return };
            let Ok(v) = serde_json::from_str::<serde_json::Value>(json) else { return };
            let mut list = Vec::new();
            if let Some(hosts) = v.get("hosts").and_then(|h| h.as_object()) {
                for (tag, info) in hosts {
                    let host = info.get("host").and_then(|x| x.as_str()).unwrap_or(tag).to_string();
                    let os = info.get("os").and_then(|x| x.as_str()).unwrap_or("?").to_string();
                    list.push((tag.clone(), host, os));
                }
            }
            list.sort_by(|a, b| a.1.cmp(&b.1));
            let t = v.get("target").and_then(|x| x.as_str()).map(|x| x.to_string());
            *ROSTER.lock().unwrap() = list;
            *state.target.lock().unwrap() = t;
        })
        .ok();
}

// ---------- 日志尾部状态解析 (与 Mac 菜单栏同款语义) ----------
fn poll_state(state: &Arc<TrayState>, ctx: &TrayCtx) {
    let path = crate::install::log_path();
    let Ok(meta) = std::fs::metadata(&path) else {
        state.alive.store(false, Ordering::Relaxed);
        return;
    };
    let size = meta.len();
    let mut last = ctx.last_log_size.lock().unwrap();
    let mut fresh = String::new();
    if size > *last && *last > 0 && size - *last < 2 * 1024 * 1024 {
        if let Ok(mut f) = std::fs::File::open(&path) {
            use std::io::{Read, Seek, SeekFrom};
            if f.seek(SeekFrom::Start(*last)).is_ok() {
                let mut buf = Vec::new();
                if f.read_to_end(&mut buf).is_ok() {
                    fresh = String::from_utf8_lossy(&buf).to_string();
                }
            }
        }
    }
    *last = size;
    drop(last);

    for line in fresh.split('\n') {
        if line.contains("🎙") || line.contains("打洞") || line.contains("目标") {
            *state.recent.lock().unwrap() = line.trim().chars().rev().take(110).collect::<String>().chars().rev().collect();
        }
    }

    let Ok(mut f) = std::fs::File::open(&path) else {
        state.alive.store(false, Ordering::Relaxed);
        return;
    };
    use std::io::{Read, Seek, SeekFrom};
    let from = size.saturating_sub(65536);
    if f.seek(SeekFrom::Start(from)).is_err() {
        return;
    }
    let mut buf = Vec::new();
    if f.read_to_end(&mut buf).is_err() {
        return;
    }
    let tail = String::from_utf8_lossy(&buf);
    let mut alive = false;
    for line in tail.lines().rev() {
        if line.contains("] 收 ") && line.contains("包") {
            alive = true;
            state.direct.store(line.contains("直连✓"), Ordering::Relaxed);
            state.sound.store(!line.contains("[静音!]"), Ordering::Relaxed);
            if let Some(r) = regex_lite_capture(line, "收 ", " 包") {
                *state.pkts.lock().unwrap() = r;
            }
            if let Some(r) = regex_lite_capture(line, "(", "kbps)") {
                *state.kbps.lock().unwrap() = r;
            }
            if let Some(r) = regex_lite_capture(line, "RTT≈", "ms") {
                *state.rtt.lock().unwrap() = r;
            }
            break;
        }
    }
    state.alive.store(alive, Ordering::Relaxed);
}

/// 极简子串捕获: 取 line 中 `a..b` 之间的内容 (替代 regex 依赖)
fn regex_lite_capture(line: &str, a: &str, b: &str) -> Option<String> {
    let i = line.find(a)? + a.len();
    let j = line[i..].find(b)? + i;
    Some(line[i..j].to_string())
}

// ---------- 托盘上下文 ----------
static TRAY_HWND: AtomicIsize = AtomicIsize::new(0);

unsafe fn tray_modify(ctx: &TrayCtx, tip: &str, info: Option<(&str, &str)>) {
    let hwnd = ctx.hwnd.load(Ordering::Relaxed);
    if hwnd == 0 {
        return;
    }
    let mut nid = NOTIFYICONDATAW {
        cbsize: std::mem::size_of::<NOTIFYICONDATAW>() as u32,
        hwnd,
        uid: 1,
        uflags: NIF_INFO | NIF_TIP,
        ..std::mem::zeroed()
    };
    let tipw = to_wide(&fit(tip, 126));
    nid.sztip[..tipw.len()].copy_from_slice(&tipw);
    if let Some((t, b)) = info {
        nid.uflags |= NIF_INFO;
        let tw = to_wide(&fit(t, 62));
        let bw = to_wide(&fit(b, 254));
        nid.szinfotitle[..tw.len()].copy_from_slice(&tw);
        nid.szinfo[..bw.len()].copy_from_slice(&bw);
        nid.dwinfoflags = NIIF_INFO;
    }
    Shell_NotifyIconW(NIM_MODIFY, &nid);
}

unsafe fn build_menu(ctx: &TrayCtx) -> HMENU {
    let st = &ctx.state;
    let menu = CreatePopupMenu();
    let alive = st.alive.load(Ordering::Relaxed);
    let status = if alive {
        format!(
            "收 {} 包 · {}kbps · RTT {}ms · {}",
            st.pkts.lock().unwrap(),
            st.kbps.lock().unwrap(),
            st.rtt.lock().unwrap(),
            if st.direct.load(Ordering::Relaxed) { "直连" } else { "中转" }
        )
    } else {
        "守护待机/未收到工牌推流".to_string()
    };
    AppendMenuW(menu, MF_STRING | MF_GRAYED, ID_STATUS, to_wide(&status).as_ptr());
    let recent = st.recent.lock().unwrap().clone();
    if !recent.is_empty() {
        AppendMenuW(menu, MF_STRING | MF_GRAYED, ID_EVENT, to_wide(&format!("最近: {recent}")).as_ptr());
    }
    AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
    let target = st.target.lock().unwrap().clone();
    AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, to_wide(&format!("语音目标: {}", target.clone().unwrap_or_else(|| "未设置".into()))).as_ptr());
    AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, to_wide("在线主机 (点选切换):").as_ptr());
    let roster = ROSTER.lock().unwrap().clone();
    if roster.is_empty() {
        AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, to_wide("   (无在线主机)").as_ptr());
    } else {
        for (i, (tag, host, os)) in roster.iter().enumerate() {
            let _ = tag;
            let os_disp = if os == "macos" { "Mac" } else { os };
            AppendMenuW(
                menu,
                MF_STRING | if target.as_deref() == Some(tag.as_str()) { MF_CHECKED } else { MF_STRING },
                500 + i,
                to_wide(&format!("   {host} · {os_disp}")).as_ptr(),
            );
        }
    }
    AppendMenuW(menu, MF_STRING, ID_ROSTER_REFRESH, to_wide("↻ 刷新主机列表").as_ptr());
    AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
    AppendMenuW(menu, MF_STRING, ID_OPEN_LOG, to_wide("打开日志 (记事本)").as_ptr());
    AppendMenuW(menu, MF_STRING, ID_EDIT_CFG, to_wide("编辑配置 (记事本)").as_ptr());
    AppendMenuW(
        menu,
        MF_STRING | if st.notify_on.load(Ordering::Relaxed) { MF_CHECKED } else { MF_STRING },
        ID_NOTIFY,
        to_wide("系统通知").as_ptr(),
    );
    AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
    AppendMenuW(menu, MF_STRING, ID_RESTART, to_wide("重启程序").as_ptr());
    AppendMenuW(menu, MF_STRING, ID_QUIT, to_wide("退出").as_ptr());
    menu
}

unsafe fn show_menu(ctx: &TrayCtx) {
    let hwnd = ctx.hwnd.load(Ordering::Relaxed);
    let menu = build_menu(ctx);
    let mut pt = POINT { x: 0, y: 0 };
    GetCursorPos(&mut pt);
    SetForegroundWindow(hwnd); // 托盘菜单前置技巧
    let cmd = TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, std::ptr::null());
    PostMessageW(hwnd, WM_NULL, 0, 0);
    DestroyMenu(menu);
    match cmd as usize {

        ID_OPEN_LOG => {
            let _ = std::process::Command::new("notepad.exe").arg(crate::install::log_path()).spawn();
        }
        ID_EDIT_CFG => {
            let p = config::default_path().unwrap_or_default();
            if p.exists() {
                let _ = std::process::Command::new("notepad.exe").arg(p).spawn();
            } else {
                crate::install::write_config_template(false);
                let _ = std::process::Command::new("notepad.exe").arg(config::default_path().unwrap_or_default()).spawn();
            }
        }
        ID_NOTIFY => {
            let on = !ctx.state.notify_on.load(Ordering::Relaxed);
            ctx.state.notify_on.store(on, Ordering::Relaxed);
            crate::notify::set_enabled(on);
            let path = config::default_path().unwrap_or_default();
            if let Ok(text) = std::fs::read_to_string(&path) {
                let mut has_line = false;
                let mut in_ui = false;
                let mut out: Vec<String> = Vec::new();
                for l in text.lines() {
                    let t = l.trim();
                    if t.starts_with('[') {
                        // 段切换: [ui] 内无 notify 行则补写 (bugbot: 无行时只改内存不落盘)
                        if in_ui && !has_line {
                            out.push(format!("notify = {}", on));
                            has_line = true;
                        }
                        in_ui = t.replace(' ', "") == "[ui]";
                    }
                    if in_ui && t.starts_with("notify") {
                        has_line = true;
                        out.push(format!("notify = {}", on));
                        continue;
                    }
                    out.push(l.to_string());
                }
                if in_ui && !has_line {
                    out.push(format!("notify = {}", on));
                }
                let mut body = out.join("\n");
                if !body.ends_with('\n') {
                    body.push('\n');
                }
                let _ = std::fs::write(&path, body);
            }
        }
        ID_RESTART => {
            let exe = std::env::current_exe().unwrap_or_default();
            let _ = std::process::Command::new("cmd")
                .args(["/C", &format!("timeout /t 2 /nobreak >nul & start \"\" \"{}\" run", exe.display())])
                .spawn();
            PostQuitMessage(0);
        }
        ID_QUIT => PostQuitMessage(0),
        _ => {}
    }
}

unsafe extern "system" fn tray_proc(hwnd: isize, msg: u32, wp: usize, lp: isize) -> isize {
    // GWLP_USERDATA 存 Arc<TrayCtx> 原始指针
    let ctx_ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut TrayCtx;
    let Some(ctx) = ctx_ptr.as_ref() else {
        return DefWindowProcW(hwnd, msg, wp, lp);
    };
    match msg {
        m if m == WM_APP_TRAY => {
            let ev = (lp & 0xFFFF) as u32;
            if ev == WM_LBUTTONUP || ev == WM_RBUTTONUP || ev == WM_CONTEXTMENU {
                show_menu(ctx);
            }
            0
        }
        m if m == WM_APP_NOTIFY => {
            // notify.rs 投递的气泡消息
            let payload = Box::from_raw(lp as *mut String);
            if let Some((t, b)) = payload.split_once('\u{1f}') {
                tray_modify(ctx, "乐乐语音桥", Some((t, b)));
            }
            0
        }
        m if m == WM_TIMER => {
            poll_state(&ctx.state, ctx);
            // 刷新 tooltip
            let alive = ctx.state.alive.load(Ordering::Relaxed);
            let tip = if alive {
                format!(
                    "乐乐语音桥 · {}",
                    if ctx.state.sound.load(Ordering::Relaxed) {
                        "🎙 有声音"
                    } else if ctx.state.direct.load(Ordering::Relaxed) {
                        "🔗 直连待机"
                    } else {
                        "☁ 中转待机"
                    }
                )
            } else {
                "乐乐语音桥 · 待机".to_string()
            };
            tray_modify(ctx, &tip, None);
            // 定期查目标
            static TICK: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
            let n = TICK.fetch_add(1, Ordering::Relaxed);
            if n % 3 == 0 {
                query_roster_async(ctx.state.clone());
            }
            0
        }
        WM_CLOSE | WM_DESTROY => {
            unsafe {
                // bugbot 修复: 删托盘图标, 防任务栏幽灵图标
                let mut nid = NOTIFYICONDATAW {
                    cbsize: std::mem::size_of::<NOTIFYICONDATAW>() as u32,
                    hwnd,
                    uid: 1,
                    ..std::mem::zeroed()
                };
                Shell_NotifyIconW(NIM_DELETE, &nid);
            }
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wp, lp),
    }
}

// GetWindowLongPtrW 在 64 位 windows 上叫 GetWindowLongPtrW; gnu/msvc 均有
extern "system" {
    fn GetWindowLongPtrW(hwnd: isize, index: i32) -> isize;
    fn SetWindowLongPtrW(hwnd: isize, index: i32, value: isize) -> isize;
}
const GWLP_USERDATA: i32 = -21;

/// 主线程入口 (Windows): 建托盘 + 消息循环, 永不返回.
pub fn run(cfg: Config, cfg_path: Option<std::path::PathBuf>) -> ! {
    unsafe {
        let class_name = to_wide("LeleVoiceTray");
        let hinstance = GetModuleHandleW(std::ptr::null());
        let wc = WNDCLASSW {
            style: 0,
            lpfnwndproc: tray_proc as usize,
            cbclsextra: 0,
            cbwndextra: 0,
            hinstance,
            hicon: LoadIconW(0, IDI_APPLICATION as *const u16),
            hcursor: 0,
            hbrbackground: 0,
            lpszmenuname: std::ptr::null(),
            lpszclassname: class_name.as_ptr(),
        };
        RegisterClassW(&wc);
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            to_wide("LeleVoice").as_ptr(),
            0, // 不可见
            0, 0, 0, 0,
            0, 0, hinstance, std::ptr::null_mut(),
        );
        TRAY_HWND.store(hwnd, Ordering::Release);
        crate::notify::set_tray_hwnd(hwnd);

        let state = Arc::new(TrayState {
            notify_on: AtomicBool::new(
                std::fs::read_to_string(config::default_path().unwrap_or_default())
                    .map(|t| !t.contains("notify = false"))
                    .unwrap_or(true),
            ),
            ..Default::default()
        });
        let ctx = Arc::new(TrayCtx {
            cfg,
            state,
            hwnd: AtomicIsize::new(hwnd),
            last_log_size: Mutex::new(0),
        });
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, Arc::into_raw(ctx.clone()) as isize);

        // 托盘图标注册
        let mut nid = NOTIFYICONDATAW {
            cbsize: std::mem::size_of::<NOTIFYICONDATAW>() as u32,
            hwnd,
            uid: 1,
            uflags: NIF_MESSAGE | NIF_ICON | NIF_TIP,
            ucallbackmessage: WM_APP_TRAY,
            hicon: LoadIconW(0, IDI_APPLICATION as *const u16),
            ..std::mem::zeroed()
        };
        let tip = to_wide("乐乐语音桥");
        nid.sztip[..tip.len()].copy_from_slice(&tip);
        Shell_NotifyIconW(NIM_ADD, &nid);
        SetTimer(hwnd, 1, 4000, 0);

        let _ = cfg_path; // 配置路径已在 run() 日志中体现

        let mut msg = MSG {
            hwnd: 0, message: 0, wparam: 0, lparam: 0,
            pt: POINT { x: 0, y: 0 }, time: 0, pprivate: 0,
        };
        loop {
            let r = GetMessageW(&mut msg, 0, 0, 0);
            if r <= 0 {
                break;
            }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        std::process::exit(0);
    }
}
