//! lele-voice-daemon —— 乐乐语音桥 Mac 常驻守护 (§六十五).
//!
//! 一个二进制替代散落脚本:
//!   1. 监听工牌 UDP 音频流(中转订阅/LAN 直连) → 重采样 → 写 BlackHole 虚拟麦克风
//!      (流常开, 语音未开时输出静音, 保证微信输入法"麦克风可用"不漂移)
//!   2. 识别工牌按键控制帧 DICT1/DICT0(语音开关) / PTTD1/PTTD0(按住说话)
//!      → 自动切输入法到微信输入法 → 合成其语音快捷键(Fn / Fn+空格)
//!   3. LaunchAgent 开机自启 (install 子命令)
//!
//! 用法: lele-voice-daemon run [--config PATH] | doctor | install | uninstall | config-template

mod audio;
mod config;
mod ime;
mod inject;
mod install;
#[macro_use]
mod logx;
mod mic;
mod net;
mod notify;
#[cfg(target_os = "windows")]
mod tray;
mod trigger;

use std::sync::Arc;
use config::Config;

const VERSION: &str = env!("CARGO_PKG_VERSION");

extern "C" fn sig_handler(sig: libc::c_int) {
    mic::cleanup_mic_on_exit();
    std::process::exit(128 + sig);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(|s| s.as_str()).unwrap_or("run") {
        "run" => run(&args[2..]),
        "doctor" => install::doctor(),
        "switch-ime" => {
            // 调试/排障用: 手动把输入法切到指定 bundle id
            let Some(id) = args.get(2) else {
                return eprintln!("用法: lele-voice-daemon switch-ime <input-source-id>");
            };
            println!("[dbg] 当前: {:?}", ime::current_source_id());
            match ime::manual_switch(id) {
                Ok(()) => println!("[+] 已切换 → {id}"),
                Err(e) => {
                    eprintln!("[!] {e}");
                    std::process::exit(1);
                }
            }
        }
        "install" => install::install(),
        "uninstall" => install::uninstall(),
        "config-template" => {
            let p = install::write_config_template(
                args.iter().any(|a| a == "--force"),
            );
            println!("配置: {}", p.display());
        }
        other => {
            eprintln!("lele-voice-daemon {VERSION}");
            eprintln!("用法: lele-voice-daemon run [--config PATH] | doctor | install | uninstall | config-template [--force]");
            eprintln!("未知子命令: {other}");
            std::process::exit(2);
        }
    }
}

fn run(args: &[String]) {
    unsafe {
        libc::signal(libc::SIGINT, sig_handler as *const () as usize);
        libc::signal(libc::SIGTERM, sig_handler as *const () as usize);
    }

    let (cfg, cfg_path) = config::load(args);
    logi!("lele-voice-daemon {VERSION} 启动 (配置: {})",
        cfg_path.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "内置默认".into()));
    logi!("  中转={}:{} 探测={} 设备={:?} 触发={} ptt={:?} toggle={:?} mods={:?} ime={} switch_mic={}",
        cfg.relay.host, cfg.relay.port, cfg.relay.ping_port, cfg.audio.device,
        cfg.trigger.enabled, cfg.trigger.ptt_keys, cfg.trigger.toggle_keys,
        cfg.trigger.mods, cfg.trigger.input_source_id, cfg.trigger.switch_mic);

    if !inject::ax_trusted() {
        logi!("[!] 辅助功能权限缺失 → 快捷键注入会被系统静默丢弃(音频/切输入法不受影响).");
        logi!("    系统设置→隐私与安全性→辅助功能 请勾选: {}", std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default());
    }

    let trigger = trigger::Trigger::new(&cfg.trigger, &cfg.audio.device);
    notify::set_enabled(cfg.ui.notify);

    let stats = Arc::new(audio::Stats::default());
    {
        // notify 开关热重载: 30s 轮询配置文件 (菜单栏 App 切换开关后无需重启)
        let cfg_path_for_notify = cfg_path.clone();
        std::thread::Builder::new().name("notify-rl".into()).spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_secs(30));
            let Some(p) = cfg_path_for_notify.clone().or_else(config::default_path) else { continue };
            if let Ok(text) = std::fs::read_to_string(&p) {
                if let Ok(c) = toml::from_str::<Config>(&text) {
                    notify::set_enabled(c.ui.notify);
                }
            }
        }).ok();
    }
    let shared = audio::SinkShared::new();
    let params = Arc::new(audio::DeviceParams::default());
    // 音频 owner 线程自带限时打开/自愈/设备缺席重试, 不阻塞主流程
    audio::spawn_owner(cfg.audio.device.clone(), shared.clone(), params.clone(), stats.clone());
    let feeder = audio::Feeder::new(shared, params, stats.clone());

    // 收流循环移入后台线程 (Windows 主线程要跑托盘消息循环)
    {
        let cfg2 = cfg.clone();
        std::thread::Builder::new()
            .name("net".into())
            .spawn(move || net::run(&cfg2, feeder, stats, trigger))
            .expect("spawn net");
    }

    #[cfg(target_os = "macos")]
    {
        // macOS: 主线程挂起 (SIGINT/SIGTERM 由 sig_handler 处理, mic 自愈还原)
        loop {
            std::thread::sleep(std::time::Duration::from_secs(3600));
        }
    }
    #[cfg(target_os = "windows")]
    {
        // Windows: 主线程 = 托盘消息循环 (守护与托盘同进程, §六十九)
        crate::tray::run(cfg, cfg_path);
    }
}
