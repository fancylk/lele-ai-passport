//! 音频输出: 工牌 16k/mono/s16 → 线性插值重采样 → cpal 输出流写虚拟声卡
//! (BlackHole 2ch = 微信输入法的"麦克风"). 流常开——设备始终处于运行态,
//! 语音未开时输出静音, 保证"麦克风可用"不再漂移 (§六十五).
//!
//! 线程模型(要害):
//!   - cpal Stream 非 Send 且打开可能永久阻塞(实测: launchd 裸进程上下文会让
//!     CoreAudio 的 stream-usage 握手死等, 楔死 coreaudiod 的设备打开)——
//!   - 打开放在专用 owner→open 线程, 主流程限时等结果; 超时=放弃本次尝试
//!     (退避重试), 绝不阻塞收流主循环;
//!   - 打开成功后由同一线程常驻持有流并自愈重建(流不跨线程);
//!   - 设备参数走属性快查(main 预取 + owner 每次打开后刷新), 重采样器每包动态读.

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{BufferSize, Stream, StreamConfig};
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Default)]
pub struct Stats {
    pub pkts: AtomicU64,
    pub bytes: AtomicU64,
    /// 本统计窗口内输入音频峰值 |s16| (0=静音) —— 判断"有没有真声音"最直观
    pub peak: AtomicU32,
    pub drops: AtomicU64,
    pub underruns: AtomicU64,
    /// 本机→中转 RTT ms (relay 模式)
    pub rtt_ms: AtomicU32,
}

impl Stats {
    pub fn peak_swap_reset(&self) -> u32 {
        self.peak.swap(0, Ordering::Relaxed)
    }
}

/// 设备参数单元: owner 每次成功打开后刷新, feeder 每包动态读取
#[derive(Default)]
pub struct DeviceParams {
    pub rate: AtomicU32,    // 0 = 未知(设备未打开)
    pub channels: AtomicU32,
}

impl DeviceParams {
    pub fn set(&self, rate: u32, ch: u16) {
        self.rate.store(rate, Ordering::Relaxed);
        self.channels.store(ch as u32, Ordering::Relaxed);
    }
    pub fn get(&self) -> (u32, u16) {
        (self.rate.load(Ordering::Relaxed), self.channels.load(Ordering::Relaxed) as u16)
    }
}

pub struct SinkShared {
    q: Mutex<VecDeque<f32>>,
    prebuffer: AtomicU32, // 样本数(含声道)
    max: AtomicU32,
    started: AtomicBool,
    dead: AtomicBool,
}

impl SinkShared {
    /// 占位参数创建(真实参数 owner 打开后再刷新)
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            q: Mutex::new(VecDeque::new()),
            prebuffer: AtomicU32::new(48000 * 2 * 60 / 1000),
            max: AtomicU32::new(48000 * 2),
            started: AtomicBool::new(false),
            dead: AtomicBool::new(false),
        })
    }
}

/// 设备参数快查(纯属性查询, 不建流 —— coreaudiod 异常时也不挂)
pub fn probe_output_config(name_hint: &str) -> Option<(u32, u16, String)> {
    let host = cpal::default_host();
    let device = resolve_device(&host, name_hint)?;
    let name = device.name().unwrap_or_else(|_| "?".into());
    let scfg = device.default_output_config().ok()?;
    Some((scfg.sample_rate().0, scfg.channels(), name))
}

fn resolve_device(host: &cpal::Host, hint: &str) -> Option<cpal::Device> {
    host.output_devices().ok()?.find(|d| {
        d.name().map(|n| n.to_lowercase().contains(&hint.to_lowercase())).unwrap_or(false)
    })
}

const OPEN_TIMEOUT: Duration = Duration::from_secs(15);

/// 拉起常驻 owner 线程: 限时打开输出流; 成功后由内层线程常驻持有流并自愈.
pub fn spawn_owner(name_hint: String, shared: Arc<SinkShared>, params: Arc<DeviceParams>, stats: Arc<Stats>) {
    std::thread::Builder::new()
        .name("audio-owner".into())
        .spawn(move || {
            let mut timeouts = 0u32;
            loop {
                // 限时打开: 内层线程构建; 成功则该线程常驻接管
                let (tx, rx) = std::sync::mpsc::channel::<bool>();
                {
                    let hint = name_hint.clone();
                    let sh = shared.clone();
                    let pm = params.clone();
                    let st = stats.clone();
                    std::thread::Builder::new()
                        .name("audio-open".into())
                        .spawn(move || open_and_own(hint, sh, pm, st, tx))
                        .expect("spawn audio-open");
                }
                match rx.recv_timeout(OPEN_TIMEOUT) {
                    Ok(true) => return, // 内层线程已接管
                    Ok(false) => {
                        crate::logi!("[!] 输出流打开失败, 2s 后重试 (不回落默认扬声器)");
                        std::thread::sleep(Duration::from_secs(2));
                    }
                    Err(_) => {
                        timeouts += 1;
                        let backoff = Duration::from_secs((2u64 * timeouts as u64).min(60));
                        crate::logi!("[!] 输出流打开超时(15s), {backoff:?} 后重试 (第{timeouts}次)——coreaudiod 可能被楔死, 恢复: sudo killall coreaudiod");
                        std::thread::sleep(backoff);
                    }
                }
            }
        })
        .expect("spawn audio-owner");
}

/// 内层线程: 打开流 → 常驻监视 dead 标志, 异常时原地关旧流重建.
fn open_and_own(hint: String, shared: Arc<SinkShared>, params: Arc<DeviceParams>, stats: Arc<Stats>, tx: std::sync::mpsc::Sender<bool>) {
    let mut name;
    let mut rate;
    let mut ch;
    let mut stream: Option<Stream> = None;
    loop {
        if stream.is_none() {
            let Some((r, c, n)) = probe_output_config(&hint) else {
                crate::logi!("[!] 未找到输出设备 {hint:?}, 2s 后重试 (不回落默认扬声器)");
                let _ = tx.send(false);
                std::thread::sleep(Duration::from_secs(2));
                continue;
            };
            name = n;
            rate = r;
            ch = c;
            params.set(rate, ch);
            let per_sec = rate as usize * ch as usize;
            shared.prebuffer.store((per_sec * 150 / 1000) as u32, Ordering::Relaxed);
            shared.max.store(per_sec as u32, Ordering::Relaxed);
            shared.q.lock().unwrap().clear();
            shared.started.store(false, Ordering::Relaxed);
            match open_stream(&hint, &name, &shared, &stats, rate, ch) {
                Some(s) => {
                    let first = tx.send(true).is_err();
                    stream = Some(s);
                    if first {
                        return; // 通道对端已走(超时放弃), 但流已建好——保留常驻
                    }
                }
                None => {
                    let _ = tx.send(false);
                    std::thread::sleep(Duration::from_secs(2));
                    continue;
                }
            }
        }
        // 已持有流: 监视 dead → 原地重建
        std::thread::sleep(Duration::from_secs(2));
        if shared.dead.swap(false, Ordering::Relaxed) {
            crate::logi!("[!] 输出流异常, 原地重建...");
            stream = None; // drop 旧流
        }
    }
}

fn open_stream(hint: &str, name: &str, shared: &Arc<SinkShared>, stats: &Arc<Stats>, rate: u32, ch: u16) -> Option<Stream> {
    let host = cpal::default_host();
    let device = resolve_device(&host, hint)?;
    let sconfig = StreamConfig { channels: ch, sample_rate: cpal::SampleRate(rate), buffer_size: BufferSize::Default };

    let cb_shared = shared.clone();
    let cb_stats = stats.clone();
    let data_cb = move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
        let Ok(mut q) = cb_shared.q.try_lock() else { return }; // 争用时输出静音
        if !cb_shared.started.load(Ordering::Relaxed) {
            return; // 预缓冲未满 → 静音
        }
        for s in data.iter_mut() {
            *s = q.pop_front().unwrap_or(0.0);
        }
        if q.is_empty() {
            cb_stats.underruns.fetch_add(1, Ordering::Relaxed);
            cb_shared.started.store(false, Ordering::Relaxed); // 欠载即重新预缓冲, 否则水位永远回不满
        }
    };
    let err_shared = shared.clone();
    let err_cb = move |e: cpal::StreamError| {
        crate::logi!("[!] 输出设备异常: {e}");
        err_shared.dead.store(true, Ordering::Relaxed);
    };

    match device.build_output_stream(&sconfig, data_cb, err_cb, None) {
        Ok(stream) => {
            if let Err(e) = stream.play() {
                crate::logi!("[!] 输出流启动失败: {e}");
                return None;
            }
            crate::logi!("[+] 音频 → {name} ({rate}Hz/{ch}ch, 源16k重采样)");
            Some(stream)
        }
        Err(e) => {
            crate::logi!("[!] 设备 {name:?} 打不开: {e}");
            None
        }
    }
}

/// 推流喂入器: s16le mono PCM → 重采样 → 复制声道 → 共享队列.
/// 仅在收流线程使用 (重采样状态非原子); 设备参数每包动态读取.
pub struct Feeder {
    carry: f32,
    frac: f64,
    last_params: (u32, u16),
    sink: Arc<SinkShared>,
    params: Arc<DeviceParams>,
    stats: Arc<Stats>,
}

impl Feeder {
    pub fn new(sink: Arc<SinkShared>, params: Arc<DeviceParams>, stats: Arc<Stats>) -> Feeder {
        Feeder { carry: 0.0, frac: 1.0, last_params: (0, 0), sink, params, stats }
    }

    pub fn feed_pcm16(&mut self, pcm: &[i16], src_rate: u32) {
        if pcm.is_empty() {
            return;
        }
        self.stats.pkts.fetch_add(1, Ordering::Relaxed);
        self.stats.bytes.fetch_add(pcm.len() as u64 * 2, Ordering::Relaxed);
        let peak = pcm.iter().map(|x| x.unsigned_abs()).max().unwrap_or(0) as u32;
        self.stats.peak.fetch_max(peak, Ordering::Relaxed);

        let (rate, ch) = self.params.get();
        if rate == 0 || ch == 0 {
            return; // 设备还没打开, 丢弃
        }
        if (rate, ch) != self.last_params {
            self.last_params = (rate, ch);
            self.carry = 0.0;
            self.frac = 1.0;
        }
        let step = src_rate as f64 / rate as f64;

        let mut out: Vec<f32> = Vec::with_capacity(pcm.len() * 2 * ch as usize);
        for &s16 in pcm {
            let x = s16 as f32 / 32768.0;
            loop {
                if self.frac < 1.0 {
                    let v = self.carry + (x - self.carry) * self.frac as f32;
                    match ch {
                        2 => {
                            out.push(v);
                            out.push(v);
                        }
                        1 => out.push(v),
                        _ => out.push(v),
                    }
                    self.frac += step;
                } else {
                    self.carry = x;
                    self.frac -= 1.0;
                    break;
                }
            }
        }

        let mut q = self.sink.q.lock().unwrap();
        let max = self.sink.max.load(Ordering::Relaxed) as usize;
        if q.len() >= max {
            q.clear();
            self.sink.started.store(false, Ordering::Relaxed);
            let n = self.stats.drops.fetch_add(1, Ordering::Relaxed) + 1;
            if n < 5 || n % 50 == 0 {
                crate::logi!("[!] 积压超限, 丢弃重来 (第{n}次)");
            }
        }
        // 时钟微伺服: 源 16k 时钟与 DAC 48k 时钟无共同节拍, 稳态水位会单向
        // 漂移直到欠载/积压. 每包按水位目标增删 1 帧采样 (0.03% 变速, 不可闻),
        // 把水位钳在预缓冲附近.
        let pre = self.sink.prebuffer.load(Ordering::Relaxed) as usize;
        let frame = ch as usize;
        if out.len() > frame {
            if q.len() < pre / 2 {
                out.truncate(out.len() - frame); // 消费偏快 → 少给一帧(加速)
            } else if q.len() > pre + pre / 2 {
                let dup = out[0];
                for _ in 0..frame {
                    out.insert(0, dup); // 消费偏慢 → 多给一帧(减速)
                }
            }
        }
        q.extend(out);
        if !self.sink.started.load(Ordering::Relaxed) && q.len() >= pre {
            self.sink.started.store(true, Ordering::Relaxed);
        }
    }
}
