//! 配置: ~/.config/lele-voice/config.toml (缺省即默认值, 全部字段可覆盖).
//!
//! 键名既支持数字(Mac keycode)也支持助记名: fn/space/ctrl/alt/cmd/shift/tab/
//! enter/esc/f1..f12, 逗号分隔组合键.

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct Config {
    #[serde(default)]
    pub relay: RelayCfg,
    #[serde(default)]
    pub audio: AudioCfg,
    #[serde(default)]
    pub trigger: TriggerCfg,
    #[serde(default)]
    pub punch: PunchCfg,
    #[serde(default)]
    pub ui: UiCfg,
}

/// 菜单栏 App / 系统通知相关 (§六十七)
#[derive(Serialize, Deserialize, Clone)]
pub struct UiCfg {
    /// 收到事件(语音触发/直连建立)时发 macOS 系统通知
    #[serde(default = "d_true")]
    pub notify: bool,
}

impl Default for UiCfg {
    fn default() -> Self {
        Self { notify: true }
    }
}

/// UDP 打洞 (§六十五): 经中转换到双方公网映射地址后互发 PNCH,
/// 工牌收到 PNCH 即直连发音频(10s 无 PNCH 自动回退中转).
#[derive(Serialize, Deserialize, Clone)]
pub struct PunchCfg {
    #[serde(default = "d_true")]
    pub enabled: bool,
    /// PNCH 间隔 ms (也用于刷新双方 NAT 绑定)
    #[serde(default = "d_punch_interval")]
    pub interval_ms: u64,
    /// 音源地址查询间隔 s
    #[serde(default = "d_punch_probe")]
    pub probe_every: u64,
}

fn d_punch_interval() -> u64 { 1000 }
fn d_punch_probe() -> u64 { 5 }

impl Default for PunchCfg {
    fn default() -> Self {
        Self { enabled: true, interval_ms: d_punch_interval(), probe_every: d_punch_probe() }
    }
}

#[derive(Serialize, Deserialize, Clone)]
pub struct RelayCfg {
    /// 中转服务器 IP; 留空 = LAN 直连模式(本机绑 9761 收工牌推流)
    #[serde(default = "d_host")]
    pub host: String,
    #[serde(default = "d_port")]
    pub port: u16,
    #[serde(default = "d_ping")]
    pub ping_port: u16,
    #[serde(default = "d_token")]
    pub token: String,
    #[serde(default = "d_tag")]
    pub tag: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct AudioCfg {
    /// 输出设备名(子串匹配) = 虚拟麦克风宿主
    #[serde(default = "d_device")]
    pub device: String,
    /// 工牌推流采样率(固定 16k)
    #[serde(default = "d_rate")]
    pub source_rate: u32,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct TriggerCfg {
    #[serde(default = "d_true")]
    pub enabled: bool,
    /// 按住说话组合键 (对应工牌下键 PTTD1/PTTD0)
    #[serde(default = "d_ptt")]
    pub ptt_keys: String,
    /// 长输入开关组合键 (对应工牌上键 DICT1/DICT0)
    #[serde(default = "d_toggle")]
    pub toggle_keys: String,
    /// 组合键修饰键: fn/ctrl/alt/cmd/shift
    #[serde(default = "d_mods")]
    pub mods: String,
    /// 触发语音前自动把当前输入法切到微信输入法
    #[serde(default = "d_true")]
    pub switch_ime: bool,
    /// 目标输入法 bundle id
    #[serde(default = "d_ime")]
    pub input_source_id: String,
    /// 触发语音输入时自动切换系统默认麦克风至虚拟声卡, 结束后自动还原
    #[serde(default = "d_true")]
    pub switch_mic: bool,
}

fn d_host() -> String { "124.221.187.167".into() }
fn d_port() -> u16 { 9761 }
fn d_ping() -> u16 { 9762 }
fn d_token() -> String { "lele-6deb6d37".into() }
fn d_tag() -> String { "mac".into() }
#[cfg(target_os = "macos")]
fn d_device() -> String { "BlackHole 2ch".into() }
#[cfg(not(target_os = "macos"))]
fn d_device() -> String { "CABLE Input".into() }   // VB-Cable 播放端 (微信输入法选 CABLE Output)
fn d_rate() -> u32 { 16000 }
fn d_true() -> bool { true }
#[cfg(target_os = "macos")]
fn d_ptt() -> String { "63".into() }        // Fn 按住
#[cfg(target_os = "macos")]
fn d_toggle() -> String { "63,49".into() }  // Fn+空格
#[cfg(target_os = "macos")]
fn d_mods() -> String { "fn".into() }
#[cfg(not(target_os = "macos"))]
fn d_ptt() -> String { "".into() }          // Windows 无 Fn 虚拟键: 微信输入法改绑后显式配置
#[cfg(not(target_os = "macos"))]
fn d_toggle() -> String { "F9".into() }     // 与 windows-guide 建议的改绑键一致
#[cfg(not(target_os = "macos"))]
fn d_mods() -> String { "".into() }
fn d_ime() -> String { "com.tencent.inputmethod.wetype.pinyin".into() }

impl Default for RelayCfg {
    fn default() -> Self {
        Self { host: d_host(), port: d_port(), ping_port: d_ping(), token: d_token(), tag: d_tag() }
    }
}
impl Default for AudioCfg {
    fn default() -> Self {
        Self { device: d_device(), source_rate: d_rate() }
    }
}
impl Default for TriggerCfg {
    fn default() -> Self {
        Self {
            enabled: true, ptt_keys: d_ptt(), toggle_keys: d_toggle(),
            mods: d_mods(), switch_ime: true, input_source_id: d_ime(),
            switch_mic: true,
        }
    }
}

/// 按键助记名表 (Mac=CG keycode / Windows=VK)
pub fn name_keycode(name: &str) -> Option<u16> {
    Some(match name {
        "space" => if cfg!(target_os = "macos") { 49 } else { 0x20 },
        "ctrl" | "control" => if cfg!(target_os = "macos") { 59 } else { 0x11 },
        "alt" | "option" => if cfg!(target_os = "macos") { 58 } else { 0x12 },
        "cmd" | "command" => if cfg!(target_os = "macos") { 55 } else { 0x5B },
        "shift" => if cfg!(target_os = "macos") { 56 } else { 0x10 },
        "tab" => if cfg!(target_os = "macos") { 48 } else { 0x09 },
        "enter" | "return" => if cfg!(target_os = "macos") { 36 } else { 0x0D },
        "esc" => if cfg!(target_os = "macos") { 53 } else { 0x1B },
        "fn" if cfg!(target_os = "macos") => 63,
        "f1" => if cfg!(target_os = "macos") { 122 } else { 0x70 },
        "f2" => if cfg!(target_os = "macos") { 120 } else { 0x71 },
        "f3" => if cfg!(target_os = "macos") { 99 } else { 0x72 },
        "f4" => if cfg!(target_os = "macos") { 118 } else { 0x73 },
        "f5" => if cfg!(target_os = "macos") { 96 } else { 0x74 },
        "f6" => if cfg!(target_os = "macos") { 97 } else { 0x75 },
        "f7" => if cfg!(target_os = "macos") { 98 } else { 0x76 },
        "f8" => if cfg!(target_os = "macos") { 100 } else { 0x77 },
        "f9" => if cfg!(target_os = "macos") { 101 } else { 0x78 },
        "f10" => if cfg!(target_os = "macos") { 109 } else { 0x79 },
        "f11" => if cfg!(target_os = "macos") { 103 } else { 0x7A },
        "f12" => if cfg!(target_os = "macos") { 111 } else { 0x7B },
        _ => return None,
    })
}

/// "63,49" / "f9,ctrl" / "0x70" → keycode 列表
pub fn parse_keys(spec: &str) -> Result<Vec<u16>, String> {
    let mut out = Vec::new();
    for part in spec.split(',') {
        let p = part.trim().to_lowercase();
        if p.is_empty() {
            continue;
        }
        if let Some(k) = name_keycode(&p) {
            out.push(k);
        } else if let Some(hex) = p.strip_prefix("0x") {
            out.push(u16::from_str_radix(hex, 16).map_err(|_| format!("非法十六进制键值 {p:?}"))?);
        } else if let Ok(v) = p.parse::<u16>() {
            out.push(v);
        } else {
            return Err(format!("无法解析按键 {p:?} (支持 fn/space/ctrl/f1-f12 或数字 keycode)"));
        }
    }
    Ok(out)
}

/// 配置路径: --config 显式指定 > ~/.config/lele-voice/config.toml > 内置默认
pub fn resolve_path(args: &[String]) -> Option<std::path::PathBuf> {
    if let Some(i) = args.iter().position(|a| a == "--config") {
        return args.get(i + 1).map(std::path::PathBuf::from);
    }
    None
}

pub fn home_dir() -> std::path::PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Ok(h) = std::env::var("USERPROFILE") {
            if !h.trim().is_empty() {
                return std::path::PathBuf::from(h);
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(h) = std::env::var("HOME") {
            if !h.trim().is_empty() {
                return std::path::PathBuf::from(h);
            }
        }
        unsafe {
            let pw = libc::getpwuid(libc::getuid());
            if !pw.is_null() && !(*pw).pw_dir.is_null() {
                let s = std::ffi::CStr::from_ptr((*pw).pw_dir).to_string_lossy();
                if !s.is_empty() {
                    return std::path::PathBuf::from(s.as_ref());
                }
            }
        }
    }
    #[cfg(target_os = "windows")]
    {
        return std::env::var("LOCALAPPDATA").map(std::path::PathBuf::from).unwrap_or_else(|_| std::path::PathBuf::from("C:\\Temp"));
    }
    #[cfg(not(target_os = "windows"))]
    std::path::PathBuf::from("/tmp")
}

pub fn default_path() -> Option<std::path::PathBuf> {
    Some(home_dir().join(".config/lele-voice/config.toml"))
}

pub fn load(args: &[String]) -> (Config, Option<std::path::PathBuf>) {
    let path = resolve_path(args).or_else(default_path);
    let Some(p) = &path else { return (Config::default(), None) };
    match std::fs::read_to_string(p) {
        Ok(text) => match toml::from_str(&text) {
            Ok(c) => (c, Some(p.clone())),
            Err(e) => {
                eprintln!("[!] 配置解析失败 {p:?}: {e} —— 使用内置默认值");
                (Config::default(), Some(p.clone()))
            }
        },
        Err(_) => (Config::default(), Some(p.clone())),
    }
}
