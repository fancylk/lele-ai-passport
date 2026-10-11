//! 配置: ~/.config/lele-voice/config.toml (缺省即默认值, 全部字段可覆盖).
//!
//! 键名既支持数字(Mac keycode)也支持助记名: fn/space/ctrl/alt/cmd/shift/tab/
//! enter/esc/f1..f12, 逗号分隔组合键.

use serde::Deserialize;

#[derive(Deserialize, Clone, Default)]
pub struct Config {
    #[serde(default)]
    pub relay: RelayCfg,
    #[serde(default)]
    pub audio: AudioCfg,
    #[serde(default)]
    pub trigger: TriggerCfg,
    #[serde(default)]
    pub punch: PunchCfg,
}

/// UDP 打洞 (§六十五): 经中转换到双方公网映射地址后互发 PNCH,
/// 工牌收到 PNCH 即直连发音频(10s 无 PNCH 自动回退中转).
#[derive(Deserialize, Clone)]
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

#[derive(Deserialize, Clone)]
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

#[derive(Deserialize, Clone)]
pub struct AudioCfg {
    /// 输出设备名(子串匹配) = 虚拟麦克风宿主
    #[serde(default = "d_device")]
    pub device: String,
    /// 工牌推流采样率(固定 16k)
    #[serde(default = "d_rate")]
    pub source_rate: u32,
}

#[derive(Deserialize, Clone)]
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
}

fn d_host() -> String { "124.221.187.167".into() }
fn d_port() -> u16 { 9761 }
fn d_ping() -> u16 { 9762 }
fn d_token() -> String { "lele-6deb6d37".into() }
fn d_tag() -> String { "mac".into() }
fn d_device() -> String { "BlackHole 2ch".into() }
fn d_rate() -> u32 { 16000 }
fn d_true() -> bool { true }
fn d_ptt() -> String { "63".into() }
fn d_toggle() -> String { "63,49".into() }
fn d_mods() -> String { "fn".into() }
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
        }
    }
}

/// Mac keycode 助记名表
pub fn name_keycode(name: &str) -> Option<u16> {
    Some(match name {
        "fn" => 63, "space" => 49, "ctrl" => 59, "alt" | "option" => 58,
        "cmd" | "command" => 55, "shift" => 56, "tab" => 48,
        "enter" | "return" => 36, "esc" => 53,
        "f1" => 122, "f2" => 120, "f3" => 99, "f4" => 118, "f5" => 96,
        "f6" => 97, "f7" => 98, "f8" => 100, "f9" => 101, "f10" => 109,
        "f11" => 103, "f12" => 111,
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

pub fn default_path() -> Option<std::path::PathBuf> {
    std::env::var("HOME").ok().map(|h| {
        std::path::PathBuf::from(h).join(".config/lele-voice/config.toml")
    })
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
