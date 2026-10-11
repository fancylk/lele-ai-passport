//! 安装(LaunchAgent 开机自启) / 卸载 / 体检(doctor) / 默认配置模板.

use std::path::PathBuf;
use std::process::Command;

use cpal::traits::{DeviceTrait, HostTrait};

pub const LABEL: &str = "cn.taoge.lele-voice-daemon";

pub fn plist_path() -> PathBuf {
    home().join("Library/LaunchAgents").join(format!("{LABEL}.plist"))
}

pub fn log_path() -> PathBuf {
    home().join("Library/Logs").join(format!("{LABEL}.log"))
}

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".into()))
}

fn config_path() -> PathBuf {
    home().join(".config/lele-voice/config.toml")
}

pub const EXAMPLE_TOML: &str = r#"# 乐乐语音桥 Mac 守护进程配置 (lele-voice-daemon)
# 全部字段可省略, 省略即注释中的默认值.

[relay]
# 腾讯云中转; 留空 "" = LAN 直连模式(本机绑 9761 收工牌推流)
host = "124.221.187.167"
port = 9761          # 音频/控制帧端口
ping_port = 9762     # 探测端口
token = "lele-6deb6d37"
tag = "mac"          # 中转订阅端标识

[audio]
device = "BlackHole 2ch"   # 输出设备名(子串匹配) = 微信输入法的"麦克风"
source_rate = 16000        # 工牌推流采样率(固件固定)

[trigger]
enabled = true
# 微信输入法语音快捷键 (Mac keycode): 63=Fn/Globe, 49=空格
# 与微信输入法设置 MMKV 实测一致; 在微信输入法里改绑后这里同步改
ptt_keys = "63"        # 工牌下键按住说话 = 按住该组合键
toggle_keys = "63,49"  # 工牌上键语音开关   = 轻击该组合键
mods = "fn"            # 修饰键: fn/ctrl/alt/cmd/shift
switch_ime = true      # 触发前自动切输入法到微信输入法
input_source_id = "com.tencent.inputmethod.wetype.pinyin"
"#;

pub fn write_config_template(force: bool) -> PathBuf {
    let p = config_path();
    if p.exists() && !force {
        return p;
    }
    if let Some(dir) = p.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if std::fs::write(&p, EXAMPLE_TOML).is_ok() {
        crate::logi!("[+] 配置模板已写入 {}", p.display());
    }
    p
}

/// .app bundle 安装根: 带 CFBundleIdentifier 的进程才有"应用归属"——
/// 实测 launchd 裸二进制会让 CoreAudio stream-usage 握手死等并楔死
/// coreaudiod 的设备打开(§六十五); TCC 辅助功能授权也按 bundle 展示.
pub fn app_path() -> PathBuf {
    home().join("Applications/lele-voice-daemon.app")
}

fn app_bin_path() -> PathBuf {
    app_path().join("Contents/MacOS/lele-voice-daemon")
}

fn info_plist_xml() -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>{LABEL}</string>
    <key>CFBundleName</key><string>lele-voice-daemon</string>
    <key>CFBundleExecutable</key><string>lele-voice-daemon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>LSUIElement</key><true/>
</dict>
</plist>
"#
    )
}

pub fn install() {
    let src = match std::env::current_exe() {
        Ok(p) => p,
        Err(e) => return eprintln!("[!] 找不到自身二进制: {e}"),
    };
    let dst = app_bin_path();
    if let Some(dir) = dst.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Err(e) = std::fs::write(app_path().join("Contents/Info.plist"), info_plist_xml()) {
        return eprintln!("[!] 写 Info.plist 失败: {e}");
    }
    if let Err(e) = std::fs::copy(&src, &dst) {
        return eprintln!("[!] 复制二进制 {} → {} 失败: {e}", src.display(), dst.display());
    }
    crate::logi!("[+] 已安装 {}", app_path().display());

    write_config_template(false);

    let plist = plist_path();
    if let Some(dir) = plist.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let log = log_path();
    let _ = std::fs::create_dir_all(log.parent().unwrap());
    let xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{}</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>AssociatedBundleIdentifiers</key>
    <array><string>{LABEL}</string></array>
    <key>EnvironmentVariables</key>
    <dict><key>__CFBundleIdentifier</key><string>{LABEL}</string></dict>
    <key>StandardOutPath</key><string>{}</string>
    <key>StandardErrorPath</key><string>{}</string>
</dict>
</plist>
"#,
        dst.display(),
        log.display(),
        log.display()
    );
    if let Err(e) = std::fs::write(&plist, xml) {
        return eprintln!("[!] 写 plist 失败: {e}");
    }
    let uid = unsafe { libc::getuid() };
    let _ = Command::new("launchctl")
        .args(["bootout", &format!("gui/{uid}"), &plist.display().to_string()])
        .status(); // 未加载过会报错, 忽略
    match Command::new("launchctl")
        .args(["bootstrap", &format!("gui/{uid}"), &plist.display().to_string()])
        .status()
    {
        Ok(s) if s.success() => {
            crate::logi!("[+] LaunchAgent 已加载并启动 (开机自启已生效)");
            crate::logi!("[+] 日志: {}", log.display());
        }
        Ok(s) => eprintln!("[!] launchctl bootstrap 退出码 {:?}", s.code()),
        Err(e) => eprintln!("[!] launchctl 执行失败: {e}"),
    }
    println!();
    println!("★ 最后一步(手动, 一次性): 系统设置 → 隐私与安全性 → 辅助功能 →");
    println!("  点 + 添加并勾选: {}", dst.display());
    println!("  (不授权则快捷键注入会被系统静默丢弃; 输入法切换/音频不受影响)");
    println!("  授权后: launchctl kickstart -k gui/{uid}/{LABEL}");
}

pub fn uninstall() {
    let uid = unsafe { libc::getuid() };
    let plist = plist_path();
    let _ = Command::new("launchctl")
        .args(["bootout", &format!("gui/{uid}"), &plist.display().to_string()])
        .status();
    match std::fs::remove_file(&plist) {
        Ok(()) => println!("[+] LaunchAgent 已卸载 ({})", plist.display()),
        Err(e) => println!("[=] plist 不存在或删除失败: {e}"),
    }
}

pub fn doctor() {
    let cfg_path = config_path();
    println!("── lele-voice-daemon doctor ──");
    println!("二进制: {}", std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default());
    println!("LaunchAgent: {}", plist_path().display());
    if plist_path().exists() {
        let uid = unsafe { libc::getuid() };
        let st = Command::new("launchctl")
            .args(["print", &format!("gui/{uid}/{LABEL}")])
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).to_string())
            .unwrap_or_default();
        if st.contains("\"state\"") {
            let running = st.contains("state = running");
            println!("  已加载, state = {}", if running { "running ✓" } else { "非 running(看日志)" });
        } else {
            println!("  plist 存在但未加载 (install 或 launchctl bootstrap)");
        }
    } else {
        println!("  未安装 (lele-voice-daemon install)");
    }
    println!();

    let (cfg, path) = crate::config::load(&[]);
    match path {
        Some(p) if cfg_path.exists() => println!("配置: {} ✓", p.display()),
        Some(p) => println!("配置: {} 不存在 → 内置默认值 (install 会写模板)", p.display()),
        None => println!("配置: 内置默认值"),
    }
    println!("  中转: {}:{} 探测:{} tag={}", cfg.relay.host, cfg.relay.port, cfg.relay.ping_port, cfg.relay.tag);
    println!("  触发: enabled={} ptt={:?} toggle={:?} mods={:?} ime={}",
        cfg.trigger.enabled, cfg.trigger.ptt_keys, cfg.trigger.toggle_keys, cfg.trigger.mods, cfg.trigger.input_source_id);
    println!();

    // 1. 输出设备(虚拟麦克风宿主)
    let host = cpal::default_host();
    let mut found = false;
    println!("输出设备(cpal):");
    if let Ok(devs) = host.output_devices() {
        for d in devs {
            let name = d.name().unwrap_or_else(|_| "?".into());
            let mark = if name.to_lowercase().contains(&cfg.audio.device.to_lowercase()) { found = true; " ← 配置目标" } else { "" };
            println!("  - {name}{mark}");
        }
    }
    println!("  {}", if found { format!("✓ 找到 {:?}", cfg.audio.device) } else { format!("✗ 未找到 {:?} — BlackHole 装了吗? brew install blackhole-2ch", cfg.audio.device) });
    println!();

    // 2. 输入源
    let cur = crate::ime::current_source_id().unwrap_or_default();
    let st = crate::ime::probe_source(&cfg.trigger.input_source_id);
    println!("输入源: 当前 = {cur}");
    println!("  目标 {} → {st}", cfg.trigger.input_source_id);
    println!();

    // 3. 辅助功能
    let ax = crate::inject::ax_trusted();
    println!("辅助功能授权: {}", if ax {
        "已授予 ✓ (注意: 无授权时注入也会静默失败, 以面板是否弹出为准)"
    } else {
        "✗ 未授予 → 快捷键注入必失效. 系统设置→隐私与安全性→辅助功能 添加本二进制"
    });
    println!();

    // 4. 中转连通
    if !cfg.relay.host.is_empty() {
        use std::net::UdpSocket;
        if let Ok(s) = UdpSocket::bind("0.0.0.0:0") {
            let _ = s.set_read_timeout(Some(std::time::Duration::from_secs(2)));
            let _ = s.send_to(b"STATUS", (cfg.relay.host.as_str(), cfg.relay.ping_port));
            let mut buf = [0u8; 512];
            match s.recv_from(&mut buf) {
                Ok((n, _)) => println!("中转 STATUS: {}", String::from_utf8_lossy(&buf[..n])),
                Err(e) => println!("中转 STATUS: 无响应 ({e}) —— 中转挂了? ssh tencent systemctl status lele-relay"),
            }
        }
    } else {
        println!("LAN 直连模式: 无中转探测");
    }
}
