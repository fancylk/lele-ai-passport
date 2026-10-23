//! 安装(LaunchAgent 开机自启) / 卸载 / 体检(doctor) / 默认配置模板.

use std::path::PathBuf;
use std::process::Command;

use cpal::traits::{DeviceTrait, HostTrait};

pub const LABEL: &str = "cn.taoge.lele-voice-daemon";
pub const MENUBAR_LABEL: &str = "cn.taoge.lele-voice-menubar";

pub fn plist_path() -> PathBuf {
    home().join("Library/LaunchAgents").join(format!("{LABEL}.plist"))
}

pub fn log_path() -> PathBuf {
    home().join("Library/Logs").join(format!("{LABEL}.log"))
}

fn home() -> PathBuf {
    crate::config::home_dir()
}

fn config_path() -> PathBuf {
    home().join(".config/lele-voice/config.toml")
}

fn menubar_plist_path() -> PathBuf {
    home().join("Library/LaunchAgents").join(format!("{MENUBAR_LABEL}.plist"))
}

fn menubar_bin_path() -> PathBuf {
    home().join("Applications/lele-voice-menubar")
}

/// 菜单栏小程序源码位置 (与 macos-daemon 同仓)
fn menubar_source() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let p = manifest_dir.parent()?.join("macos-menubar/main.swift");
    p.exists().then_some(p)
}

/// 编译并安装菜单栏 App + LaunchAgent (swiftc 缺席时仅提示, 不算失败)
fn install_menubar() {
    let Some(src) = menubar_source() else {
        println!("[=] 未找到菜单栏源码(macos-menubar/main.swift), 跳过菜单栏安装");
        return;
    };
    let dst = menubar_bin_path();
    if let Some(dir) = dst.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    match Command::new("swiftc")
        .arg("-O").arg(&src).arg("-o").arg(&dst)
        .status()
    {
        Ok(s) if s.success() => println!("[+] 菜单栏已安装: {}", dst.display()),
        _ => {
            println!("[!] swiftc 编译菜单栏失败, 跳过 (需要 Xcode Command Line Tools)");
            return;
        }
    }
    let plist = menubar_plist_path();
    if let Some(dir) = plist.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{MENUBAR_LABEL}</string>
    <key>ProgramArguments</key>
    <array><string>{}</string></array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>
"#,
        dst.display()
    );
    if let Err(e) = std::fs::write(&plist, xml) {
        println!("[!] 写菜单栏 plist 失败: {e}");
        return;
    }
    let uid = unsafe { libc::getuid() };
    let _ = Command::new("launchctl")
        .args(["bootout", &format!("gui/{uid}"), &plist.display().to_string()])
        .status();
    match Command::new("launchctl")
        .args(["bootstrap", &format!("gui/{uid}"), &plist.display().to_string()])
        .status()
    {
        Ok(s) if s.success() => println!("[+] 菜单栏已加载 (开机自启)"),
        _ => println!("[!] 菜单栏 launchctl bootstrap 失败"),
    }
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

[punch]
enabled = true          # 启用 UDP 打洞端到端直传
interval_ms = 1000      # PNCH 探测间隔 (ms)
probe_every = 5         # 中转音源查询间隔 (s)

[ui]
notify = true           # 收到事件(语音触发/直连建立)时发 macOS 系统通知
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
    <key>NSMicrophoneUsageDescription</key><string>乐乐语音桥需要访问音频输出与虚拟音频设备以传输工牌语音流</string>
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
    let _ = Command::new("codesign")
        .args([
            "--force",
            "--deep",
            "-s",
            "-",
            "-i",
            "cn.taoge.lele-voice-daemon",
            "-r",
            "=designated => identifier \"cn.taoge.lele-voice-daemon\"",
            &app_path().display().to_string(),
        ])
        .status();
    crate::logi!("[+] 已安装并签名 {}", app_path().display());

    write_config_template(false);
    install_menubar();

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
    <dict>
        <key>HOME</key><string>{}</string>
        <key>__CFBundleIdentifier</key><string>{LABEL}</string>
    </dict>
    <key>StandardOutPath</key><string>{}</string>
    <key>StandardErrorPath</key><string>{}</string>
</dict>
</plist>
"#,
        dst.display(),
        home().display(),
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
    println!();
    println!("菜单栏小程序已装: 菜单栏出现 🎙/🔗/☁️ 图标, 点开即状态/日志/配置/通知开关");
}

pub fn uninstall() {
    let uid = unsafe { libc::getuid() };
    for (label, plist) in [(LABEL, plist_path()), (MENUBAR_LABEL, menubar_plist_path())] {
        let _ = Command::new("launchctl")
            .args(["bootout", &format!("gui/{uid}"), &plist.display().to_string()])
            .status();
        match std::fs::remove_file(&plist) {
            Ok(()) => println!("[+] LaunchAgent 已卸载 ({label})"),
            Err(e) => println!("[=] {label} plist 不存在: {e}"),
        }
    }
}

pub fn doctor() {
    std::env::set_var("__CFBundleIdentifier", LABEL);
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
        if st.contains("state = running") || st.contains("state = ") || st.contains("\"state\"") {
            let running = st.contains("state = running");
            println!("  已加载, state = {}", if running { "running ✓" } else { "非 running(看日志)" });
        } else {
            println!("  plist 存在但未加载 (install 或 launchctl bootstrap)");
        }
    } else {
        println!("  未安装 (lele-voice-daemon install)");
    }
    if menubar_plist_path().exists() {
        println!("菜单栏: {} ✓ (开机自启)", menubar_bin_path().display());
    } else {
        println!("菜单栏: 未安装 (install 时自动 swiftc 编译, 需 CLT)");
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
    println!("输出设备(cpal):");
    let dev_hint = cfg.audio.device.clone();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let host = cpal::default_host();
        let mut list = Vec::new();
        let mut target_found = false;
        if let Ok(devs) = host.output_devices() {
            for d in devs {
                let name = d.name().unwrap_or_else(|_| "?".into());
                let is_target = name.to_lowercase().contains(&dev_hint.to_lowercase());
                if is_target {
                    target_found = true;
                }
                list.push((name, is_target));
            }
        }
        let _ = tx.send((list, target_found));
    });

    match rx.recv_timeout(std::time::Duration::from_secs(5)) {
        Ok((list, target_found)) => {
            for (name, is_target) in list {
                println!("  - {name}{}", if is_target { " ← 配置目标" } else { "" });
            }
            println!("  {}", if target_found {
                format!("✓ 找到 {:?}", cfg.audio.device)
            } else {
                format!("✗ 未找到 {:?} — BlackHole 装了吗? brew install blackhole-2ch", cfg.audio.device)
            });
        }
        Err(_) => {
            println!("  ✗ 查询输出设备超时(5s) —— coreaudiod 可能被楔死, 终端恢复: sudo killall coreaudiod");
        }
    }
    println!();

    // 1.1 系统默认输入麦克风与动态切麦
    println!("系统输入麦克风 (CoreAudio):");
    if let Some(in_id) = crate::mic::get_default_input_device() {
        let in_name = crate::mic::get_device_name(in_id).unwrap_or_else(|| format!("ID:{in_id}"));
        println!("  - 当前默认麦克风: {in_name} (ID: {in_id})");
        if let Some((target_id, target_name)) = crate::mic::find_input_device_by_hint(&cfg.audio.device) {
            println!("  - 配套虚拟麦克风: {target_name} (ID: {target_id}) ✓");
            if cfg.trigger.switch_mic {
                println!("  - 动态切麦模式: 已启用 ✓ (推流时秒切 {target_name}, 结束秒回 {in_name})");
            } else {
                println!("  - 动态切麦模式: 已停用 (switch_mic = false)");
            }
        } else {
            println!("  ✗ 未找到配套虚拟麦克风 {:?} 输入端点!", cfg.audio.device);
        }
    } else {
        println!("  ✗ 查询系统默认输入麦克风失败");
    }
    println!();

    // 2. 输入源
    let cur = crate::ime::current_source_id().unwrap_or_default();
    let st = crate::ime::probe_source(&cfg.trigger.input_source_id);
    println!("输入源: 当前 = {cur}");
    println!("  目标 {} → {st}", cfg.trigger.input_source_id);
    println!();

    // 2.1 微信输入法设置自检 (MMKV)
    check_wetype_mmkv(&cfg.trigger);

    // 3. 辅助功能
    let ax = crate::inject::ax_trusted();
    println!("辅助功能授权: {}", if ax {
        "已授予 ✓ (注意: 无授权时注入也会静默失败, 以面板是否弹出为准)"
    } else {
        "✗ 未授予 → 快捷键注入必失效. 系统设置→隐私与安全性→辅助功能 勾选本应用"
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

fn check_wetype_mmkv(cfg: &crate::config::TriggerCfg) {
    let p = home().join("Library/Application Support/WeType/mmkv/wetype.settings");
    if !p.exists() {
        return;
    }
    let Ok(buf) = std::fs::read(&p) else { return };
    if buf.len() < 8 { return };

    let mut pos = 8;
    let mut map = std::collections::HashMap::new();
    while pos < buf.len() {
        let (klen, next_pos) = read_varint(&buf, pos);
        pos = next_pos;
        if klen == 0 || pos + klen > buf.len() { break; }
        let k = &buf[pos..pos+klen];
        pos += klen;
        let (vlen, next_pos) = read_varint(&buf, pos);
        pos = next_pos;
        if pos + vlen > buf.len() { break; }
        let v = &buf[pos..pos+vlen];
        pos += vlen;
        if let Ok(ks) = std::str::from_utf8(k) {
            map.insert(ks.to_string(), v.to_vec());
        }
    }

    println!("微信输入法设置检查 (MMKV):");
    if let Some(dev) = map.get("voice.input.preferredDeviceUID.v2") {
        let s = String::from_utf8_lossy(dev);
        let s_clean = s.trim_matches(|c: char| !c.is_alphanumeric() && c != '_');
        if s.contains("__wetype_auto__") {
            println!("  - 首选麦克风: 跟随系统默认 ({s_clean}) ✓ (完美适配动态切麦)");
        } else if s.contains("BlackHole") {
            println!("  - 首选麦克风: {s_clean} (固定选择 BlackHole 2ch) ✓");
        } else {
            println!("  - 首选麦克风: {s_clean} ⚠️ 建议在微信输入法设置中设为「自动」(跟随系统默认设备)");
        }
    }
    if let Some(toggle) = map.get("voiceToggleShortcut_keyCodes") {
        let s = String::from_utf8_lossy(toggle);
        let s_clean = s.trim_matches(|c: char| c != '[' && c != ']' && !c.is_numeric() && c != ',');
        println!("  - 长输入快捷键: {s_clean} (配置: {:?})", cfg.toggle_keys);
    }
    if let Some(ptt) = map.get("voicePTTShortcut_keyCodes") {
        let s = String::from_utf8_lossy(ptt);
        let s_clean = s.trim_matches(|c: char| c != '[' && c != ']' && !c.is_numeric() && c != ',');
        let matches = s_clean.contains(&cfg.ptt_keys);
        println!("  - 按住说话快捷键: {s_clean} (配置: {:?}){}", cfg.ptt_keys, if matches { " ✓" } else { " ⚠️ 两端不一致!" });
        if !matches {
            println!("    提示: 请在微信输入法设置→语音输入 中将【按住说话】设为 Fn 键，或修改 config.toml 中的 ptt_keys");
        }
    }
    println!();
}

fn read_varint(buf: &[u8], mut pos: usize) -> (usize, usize) {
    let mut val = 0usize;
    let mut shift = 0;
    while pos < buf.len() {
        let b = buf[pos];
        pos += 1;
        if shift < 64 {
            if let Some(s) = ((b & 0x7f) as usize).checked_shl(shift as u32) {
                val |= s;
            }
        }
        if b & 0x80 == 0 {
            break;
        }
        shift += 7;
        if shift >= 64 {
            break;
        }
    }
    (val, pos)
}
