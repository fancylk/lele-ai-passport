//! 网络面: 工牌/中转 UDP 收流 + 保活 + 帧分类.
//!   relay 模式: 单 socket 临时端口; 每 20s SUB(→9761)、每 5s PING(→9762 测
//!               本机→中转 RTT); 音频/控制帧/PONG 都回到同一 socket.
//!   LAN 模式:   绑 0.0.0.0:9761 收工牌推流; 另一 socket 绑 9762 应答工牌 PING.

use std::net::UdpSocket;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::audio::{Feeder, Stats};
use crate::config::Config;
use crate::trigger::Trigger;

/// 主循环独占 feeder; 音频流的打开/自愈在 audio owner 线程 (见 audio.rs).
pub fn run(cfg: &Config, mut feeder: Feeder, stats: Arc<Stats>, trigger: Arc<Trigger>) {
    let relay_mode = !cfg.relay.host.is_empty();

    let sock = Arc::new(if relay_mode {
        let s = UdpSocket::bind("0.0.0.0:0").expect("bind udp");
        crate::logi!("[+] 订阅模式: udp://{}:{} [tag: {}]", cfg.relay.host, cfg.relay.port, cfg.relay.tag);
        s
    } else {
        let s = UdpSocket::bind(("0.0.0.0", cfg.relay.port)).expect("bind 9761");
        crate::logi!("[+] LAN 直连模式: 收音 udp://0.0.0.0:{}", cfg.relay.port);
        s
    });
    sock.set_read_timeout(Some(Duration::from_millis(200))).ok();

    // 打洞汇聚状态: peer=音源映射地址(SRCQ 得到), direct=直连已建立的对端地址与最近活跃时间
    let peer_cell: Arc<Mutex<Option<std::net::SocketAddr>>> = Arc::new(Mutex::new(None));
    let direct_cell: Arc<Mutex<Option<(std::net::SocketAddr, Instant)>>> = Arc::new(Mutex::new(None));

    if relay_mode {
        let s = sock.clone();
        let host = cfg.relay.host.clone();
        let audio_port = cfg.relay.port;
        let ping_port = cfg.relay.ping_port;
        let tag = cfg.relay.tag.clone();
        let token = cfg.relay.token.clone();
        std::thread::Builder::new().name("keepalive".into())
            .spawn(move || keepalive_loop(s, &host, audio_port, ping_port, &tag, &token))
            .expect("spawn keepalive");
        if cfg.punch.enabled {
            let s = sock.clone();
            let host = cfg.relay.host.clone();
            let port = cfg.relay.port;
            let token = cfg.relay.token.clone();
            let peer = peer_cell.clone();
            let interval = Duration::from_millis(cfg.punch.interval_ms);
            let probe = cfg.punch.probe_every;
            std::thread::Builder::new().name("punch".into())
                .spawn(move || punch_loop(s, host, port, token, peer, interval, probe))
                .expect("spawn punch");
        }
    } else {
        let ping_port = cfg.relay.ping_port;
        std::thread::Builder::new().name("ping-resp".into())
            .spawn(move || lan_ping_responder(ping_port))
            .expect("spawn ping responder");
    }

    {
        let stats = stats.clone();
        let direct = direct_cell.clone();
        std::thread::Builder::new().name("stats".into())
            .spawn(move || stats_loop(stats, relay_mode, direct))
            .expect("spawn stats");
    }

    crate::logi!("[+] 等待工牌推流/控制帧...");
    let mut buf = [0u8; 4096];
    loop {
        match sock.recv_from(&mut buf) {
            Ok((n, addr)) => handle(&buf[..n], addr, &sock, &cfg.relay.token, &cfg.relay.tag, cfg.audio.source_rate,
                                    &mut feeder, &trigger, &stats, &peer_cell, &direct_cell),
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(e) => {
                crate::logi!("[!] UDP 接收异常(忽略): {e}");
                std::thread::sleep(Duration::from_millis(50));
            }
        }
    }
}

fn handle(
    d: &[u8], addr: std::net::SocketAddr, sock: &Arc<UdpSocket>, token: &str, own_tag: &str,
    src_rate: u32, feeder: &mut Feeder, trigger: &Arc<Trigger>, stats: &Arc<Stats>,
    peer_cell: &Arc<Mutex<Option<std::net::SocketAddr>>>,
    direct_cell: &Arc<Mutex<Option<(std::net::SocketAddr, Instant)>>>,
) {
    // 若此包来自直连对端, 刷新直连活跃时间戳
    {
        let mut cell = direct_cell.lock().unwrap();
        if let Some((direct_addr, ref mut last_seen)) = *cell {
            if direct_addr == addr {
                *last_seen = Instant::now();
            }
        }
    }

    if d.starts_with(b"PONG") {
        if d.len() >= 12 {
            let sent = f64::from_le_bytes(d[4..12].try_into().unwrap());
            let rtt = ((now_unix() - sent) * 1000.0) as i32;
            stats.rtt_ms.store(rtt.clamp(0, 9999) as u32, Ordering::Relaxed);
        }
        return;
    }
    // 打洞: 音源映射地址应答 (SRCQ → "SRC ip:port" / "SRC -")
    if d.starts_with(b"SRC ") {
        let s = String::from_utf8_lossy(&d[4..]).trim().to_string();
        if let Some(pa) = parse_sockaddr(&s) {
            let mut cell = peer_cell.lock().unwrap();
            if *cell != Some(pa) {
                crate::logi!("[打洞] 音源映射地址: {pa}");
                *cell = Some(pa);
            }
        }
        return;
    }
    // 打洞: 工牌 PNCH 到达 = 它到我们通; 回 PNCHA 作双向确认 (工牌凭 ACK 才切直连)
    if d.starts_with(b"PNCH") && d.len() > 4 && d[4..].starts_with(token.as_bytes()) {
        {
            let mut a = b"PNCHA".to_vec();
            a.extend_from_slice(token.as_bytes());
            let _ = sock.send_to(&a, addr);
        }
        let mut cell = direct_cell.lock().unwrap();
        let was_different = match *cell {
            Some((curr, _)) => curr != addr,
            None => true,
        };
        *cell = Some((addr, Instant::now()));
        if was_different {
            crate::logi!("[打洞] 工牌直连探测到达: {addr} (已回 ACK)");
            stats.direct.store(true, Ordering::Relaxed);
            crate::notify::send("direct", "乐乐语音桥", "🔗 工牌直连已建立 (音频端到端)");
        }
        return;
    }
    // §六十八 兜底: 固件二期控制帧带 @tag 尾巴, 不匹配本机 tag 则忽略
    // (relay 目标路由为主, 此处防御 relay 状态丢失/广播模式)
    if let Some(action) = Trigger::match_frame(d, token) {
        if let Some(want) = frame_target(d, token) {
            if want != own_tag {
                crate::logi!("[目标] 忽略发往 {want} 的语音帧 (本机 tag={own_tag})");
                return;
            }
        }
        trigger.submit(action, d);
        return;
    }
    if d.starts_with(b"TGTM1") && d.len() > 19 && d[5..18].eq(token.as_bytes()) && d[18] == b'@' {
        let want = String::from_utf8_lossy(&d[19..]).trim().to_string();
        let mine = want == own_tag;
        crate::logi!("[目标] 工牌目标主机 → {want}{}",
            if mine { " (本机)" } else { " (其他主机, 待机)" });
        return;
    }
    if d.starts_with(b"LELE1") || d.starts_with(b"SUB_OK") {
        return; // 工牌握手(LAN 直连才见得到)/订阅回执, 不喂声卡
    }
    // 其余 = 裸 PCM 音频 (直连包与中转转发包同样接受, 工牌负责切换)
    let n = d.len() - d.len() % 2;
    let pcm: Vec<i16> = d[..n].chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]])).collect();
    feeder.feed_pcm16(&pcm, src_rate);
    trigger.on_audio();
}

/// 控制帧尾部 @tag (§六十八): "DICT1<token>@mac" → Some("mac"); 无尾巴 → None
fn frame_target<'a>(d: &'a [u8], token: &str) -> Option<&'a str> {
    let tlen = token.len();
    if d.len() > 5 + tlen + 1 && &d[5..5 + tlen] == token.as_bytes() && d[5 + tlen] == b'@' {
        Some(std::str::from_utf8(&d[6 + tlen..]).ok()?.trim())
    } else {
        None
    }
}

fn parse_sockaddr(s: &str) -> Option<std::net::SocketAddr> {
    let (ip, port) = s.rsplit_once(':')?;
    Some(std::net::SocketAddr::from((ip.parse::<std::net::IpAddr>().ok()?, port.parse::<u16>().ok()?)))
}

/// 打洞线程: 定期 SRCQ 查音源映射地址, 每包向其发 PNCH 凿 NAT 绑定.
/// 音源侧(工牌固件)对称地经 PONG 捎带的 |PEER= 向本机发 PNCH.
fn punch_loop(
    sock: Arc<UdpSocket>, host: String, port: u16, token: String,
    peer_cell: Arc<Mutex<Option<std::net::SocketAddr>>>, interval: Duration, probe_every: u64,
) {
    let mut probe_last = 0.0f64;
    loop {
        let now = now_unix();
        if now - probe_last >= probe_every as f64 {
            probe_last = now;
            let mut q = b"SRCQ".to_vec();
            q.extend_from_slice(token.as_bytes());
            let _ = sock.send_to(&q, (host.as_str(), port));
        }
        if let Some(pa) = peer_cell.lock().unwrap().clone() {
            let mut p = b"PNCH".to_vec();
            p.extend_from_slice(token.as_bytes());
            let _ = sock.send_to(&p, pa);
        }
        std::thread::sleep(interval);
    }
}

fn keepalive_loop(sock: Arc<UdpSocket>, host: &str, audio_port: u16, ping_port: u16, tag: &str, token: &str) {
    let audio_dst = (host.to_string(), audio_port);
    let ping_dst = (host.to_string(), ping_port);
    let mut sub_payload: Vec<u8> = b"SUB".to_vec();
    sub_payload.extend_from_slice(token.as_bytes());
    sub_payload.extend_from_slice(format!(":{tag}").as_bytes());

    let mut sub_last = 0.0f64;
    let mut ping_last = 0.0f64;
    loop {
        let now = now_unix();
        if now - sub_last >= 20.0 {
            sub_last = now;
            if let Err(e) = sock.send_to(&sub_payload, audio_dst.clone()) {
                crate::logi!("[!] SUB 发送失败(网络暂不可达, 忽略): {e}");
            }
        }
        if now - ping_last >= 5.0 {
            ping_last = now;
            let mut p = b"PING".to_vec();
            p.extend_from_slice(&now.to_le_bytes());
            let _ = sock.send_to(&p, ping_dst.clone());
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

fn stats_loop(stats: Arc<Stats>, relay_mode: bool, direct_cell: Arc<Mutex<Option<(std::net::SocketAddr, Instant)>>>) {
    let mut last_bytes = 0u64;
    let t0 = Instant::now();
    loop {
        std::thread::sleep(Duration::from_secs(5));
        let direct_active = {
            let mut cell = direct_cell.lock().unwrap();
            if let Some((_, last_seen)) = *cell {
                if last_seen.elapsed() > Duration::from_secs(10) {
                    *cell = None;
                    stats.direct.store(false, Ordering::Relaxed);
                    false
                } else {
                    true
                }
            } else {
                false
            }
        };
        let pkts = stats.pkts.load(Ordering::Relaxed);
        let bytes = stats.bytes.load(Ordering::Relaxed);
        let kbps = (bytes - last_bytes) * 8 / 1024 / 5;
        last_bytes = bytes;
        let peak = stats.peak_swap_reset();
        let drops = stats.drops.load(Ordering::Relaxed);
        let underruns = stats.underruns.load(Ordering::Relaxed);
        let rtt = stats.rtt_ms.load(Ordering::Relaxed);
        let relay_info = if relay_mode { format!("中转RTT≈{rtt}ms ") } else { String::new() };
        let direct = if direct_active { "直连✓ " } else { "" };
        crate::logi!(
            "[{:6.0}s] 收 {pkts} 包 {}KB ({kbps}kbps) {}{}峰值{peak} 丢弃{drops} 欠载{underruns}{}",
            t0.elapsed().as_secs_f32(), bytes / 1024, relay_info, direct,
            if peak == 0 { " [静音!]" } else { "" }
        );
    }
}

fn lan_ping_responder(port: u16) {
    let Ok(s) = UdpSocket::bind(("0.0.0.0", port)) else {
        crate::logi!("[!] LAN PING 应答口 {port} 绑定失败");
        return;
    };
    s.set_read_timeout(Some(Duration::from_millis(500))).ok();
    let mut buf = [0u8; 128];
    loop {
        match s.recv_from(&mut buf) {
            Ok((n, addr)) => {
                if n >= 12 && buf.starts_with(b"PING") {
                    let _ = s.send_to(&buf[4..12], addr);
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(_) => {}
        }
    }
}

fn now_unix() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|x| x.as_secs_f64())
        .unwrap_or(0.0)
}
