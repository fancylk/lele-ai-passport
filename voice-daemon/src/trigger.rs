//! 触发器: 工牌控制帧语义 + 音频推流状态机 → 保持开启, 结束上屏.
//!
//! 状态机设计:
//! 1. 推流开始 (DICT1 / PTTD1 / 收到首包音频):
//!    - 切换并锁定目标输入法 (微信输入法)
//!    - 按住语音键 (Fn / ptt_keys), 开启微信语音输入, 保持开启状态
//! 2. 推流中 (持续接收音频包):
//!    - 刷新活跃时间戳, 保持语音键按住
//! 3. 推流结束 (DICT0 / PTTD0 收尾宽限完成, 或超时无音频数据):
//!    - 释放语音键, 微信语音输入立即停止并文字上屏
//!    - 自愈输入源漂移
//! 4. 待机期 (静音无推流):
//!    - 绝对不合成按键, 绝不误唤醒微信输入法

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::config::TriggerCfg;
use crate::inject::Injector;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Action {
    DictOn,
    DictOff,
    PttDown,
    PttUp,
}

impl Action {
    fn from_prefix(p: &[u8]) -> Option<Action> {
        Some(match p {
            b"DICT1" => Action::DictOn,
            b"DICT0" => Action::DictOff,
            b"PTTD1" => Action::PttDown,
            b"PTTD0" => Action::PttUp,
            _ => return None,
        })
    }
    fn label(self) -> &'static str {
        match self {
            Action::DictOn => "长输入会话开",
            Action::DictOff => "长输入会话关",
            Action::PttDown => "PTT 按下",
            Action::PttUp => "PTT 抬起",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TriggerMsg {
    Control(Action),
    AudioBurstStart,
}

pub struct Trigger {
    tx: Sender<TriggerMsg>,
    last_ctrl: Mutex<(Vec<u8>, Instant)>,
    last_off: Arc<Mutex<Instant>>,      // 停止信号时刻: 抑制尾包误触发新推流 (§七十补)
    last_audio: Arc<Mutex<Instant>>,
    is_streaming: Arc<AtomicBool>,
    inj: Option<Injector>,
    mods: Vec<u16>,
    ptt: Vec<u16>,
    #[allow(dead_code)]
    toggle: Vec<u16>,
    switch_ime: bool,
    ime_id: String,
    switch_mic: bool,
    target_mic: String,
    mic_switcher: Arc<crate::mic::MicSwitcher>,
}

const DEDUP_WINDOW: Duration = Duration::from_millis(300); // 固件每事件连发 3 遍 (30ms 间隔)
const TAIL_SUPPRESS: Duration = Duration::from_millis(2000); // 停止后 2s 内的工牌收尾尾包不触发新推流 (§七十补)
const IDLE_TIMEOUT: Duration = Duration::from_millis(600); // 未收到停止控制帧但音频中断的保底超时 (600ms 无音频即上屏)
const MAX_STREAM_DURATION: Duration = Duration::from_secs(120); // 单次推流最大安全时长 (120s 强制上屏, 防遗忘)
const WATCHDOG_INTERVAL: Duration = Duration::from_millis(50); // 状态机看门狗心跳 (50ms)

impl Trigger {
    /// 解析失败时返回 disabled 实例(照常记日志, 不注入) —— 不让配置错误杀死守护.
    pub fn new(cfg: &TriggerCfg, audio_device: &str) -> Arc<Trigger> {
        let (inj, mods, ptt, toggle) = if !cfg.enabled {
            (None, Vec::new(), Vec::new(), Vec::new())
        } else {
            match build_injector(cfg) {
                Ok(t) => (Some(t.0), t.1, t.2, t.3),
                Err(e) => {
                    crate::logi!("[!] 语音触发配置有误, 触发停用: {e}");
                    (None, Vec::new(), Vec::new(), Vec::new())
                }
            }
        };
        let (tx, rx) = channel::<TriggerMsg>();
        let is_streaming = Arc::new(AtomicBool::new(false));
        let last_audio = Arc::new(Mutex::new(Instant::now() - Duration::from_secs(3600)));
        let last_off = Arc::new(Mutex::new(Instant::now() - Duration::from_secs(3600)));
        let mic_switcher = Arc::new(crate::mic::MicSwitcher::new(cfg.switch_mic));
        let t = Arc::new(Trigger {
            tx,
            last_ctrl: Mutex::new((Vec::new(), Instant::now() - Duration::from_secs(1))),
            last_audio: last_audio.clone(),
            last_off: last_off.clone(),
            is_streaming: is_streaming.clone(),
            inj,
            mods,
            ptt,
            toggle,
            switch_ime: cfg.switch_ime,
            ime_id: cfg.input_source_id.clone(),
            switch_mic: cfg.switch_mic,
            target_mic: audio_device.to_string(),
            mic_switcher,
        });

        let worker = t.clone();
        std::thread::Builder::new()
            .name("trigger".into())
            .spawn(move || {
                let mut key_held = false;
                let mut stream_start_time = Instant::now();

                loop {
                    match rx.recv_timeout(WATCHDOG_INTERVAL) {
                        Ok(TriggerMsg::Control(action)) => {
                            match action {
                                Action::DictOn | Action::PttDown => {
                                    *worker.last_audio.lock().unwrap() = Instant::now();
                                    if !key_held {
                                        worker.press_key();
                                        key_held = true;
                                        stream_start_time = Instant::now();
                                        worker.is_streaming.store(true, Ordering::Relaxed);
                                        crate::logi!(
                                            "[🎙] {} → 推流开始, 保持开启状态 (按住 {:?})",
                                            action.label(),
                                            worker.ptt
                                        );
                                        crate::notify::send(
                                            if action == Action::DictOn { "dict_on" } else { "ptt_down" },
                                            "乐乐语音桥",
                                            "🎙 语音输入开 (推流中)",
                                        );
                                    }
                                }
                                Action::DictOff | Action::PttUp => {
                                    if key_held {
                                        // §七十补: 立即释放 —— 微信输入法 Fn 松开即上屏,
                                        // 尾包(工牌 1.5s 静音宽限)由 last_off 抑制窗丢弃
                                        *worker.last_off.lock().unwrap() = Instant::now();
                                        worker.release_key();
                                        key_held = false;
                                        worker.is_streaming.store(false, Ordering::Relaxed);
                                        crate::logi!(
                                            "[🎙] {} → 立即释放, 文字上屏",
                                            action.label()
                                        );
                                        crate::notify::send("stream_end", "乐乐语音桥", "🎙 说话结束, 文字上屏");
                                    }
                                }
                            }
                        }
                        Ok(TriggerMsg::AudioBurstStart) => {
                            if *worker.last_off.lock().unwrap() + TAIL_SUPPRESS > Instant::now() {
                                // 停止后的工牌收尾尾包: 抑制, 不重新开启
                            } else if !key_held {
                                worker.press_key();
                                key_held = true;
                                stream_start_time = Instant::now();
                                worker.is_streaming.store(true, Ordering::Relaxed);
                                crate::logi!(
                                    "[🎙] 探测到推流音频到达 → 保持开启状态 (按住 {:?})",
                                    worker.ptt
                                );
                                crate::notify::send("stream_start", "乐乐语音桥", "🎙 语音输入开 (推流中)");
                            }
                        }
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
                        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                    }

                    // 看门狗: 仅处理"无停止信号的音频中断"保底超时
                    if key_held {
                        let now = Instant::now();
                        let last_time = *worker.last_audio.lock().unwrap();
                        let elapsed = now.duration_since(last_time);
                        let duration = now.duration_since(stream_start_time);

                        let should_stop = if duration >= MAX_STREAM_DURATION {
                            crate::logi!("[🎙] 达到单次推流最大安全时长 (120s), 强制停止上屏");
                            true
                        } else {
                            elapsed >= IDLE_TIMEOUT
                        };

                        if should_stop {
                            *worker.last_off.lock().unwrap() = Instant::now();
                            worker.release_key();
                            key_held = false;
                            worker.is_streaming.store(false, Ordering::Relaxed);
                            crate::logi!(
                                "[🎙] 推流结束 ({}ms 无音频) → 停止上屏 (释放 {:?})",
                                elapsed.as_millis(),
                                worker.ptt
                            );
                            crate::notify::send("stream_end", "乐乐语音桥", "🎙 说话结束, 文字上屏");

                            // 输入源漂移自愈: 纯 Fn 按住-松开会被系统认作轻击, 弹表情面板扰动当前输入法
                            if worker.switch_ime {
                                std::thread::sleep(Duration::from_millis(150));
                                if crate::ime::current_source_id().as_deref() != Some(worker.ime_id.as_str()) {
                                    crate::logi!("[IME] 检测到输入源漂移(系统 Fn 手势), 切回 {}", worker.ime_id);
                                    crate::ime::ensure_current(&worker.ime_id);
                                }
                            }
                        }
                    }
                }
            })
            .expect("spawn trigger worker");
        t
    }

    /// 音频数据包到达通知 (由 net.rs 收流循环在每包喂入声卡后调用)
    pub fn on_audio(&self) {
        let now = Instant::now();
        *self.last_audio.lock().unwrap() = now;
        if !self.is_streaming.load(Ordering::Relaxed) {
            let _ = self.tx.send(TriggerMsg::AudioBurstStart);
        }
    }

    /// 控制帧到达调用 (由 net.rs 识别后调用); 帧去重后入队.
    pub fn submit(&self, action: Action, frame: &[u8]) -> bool {
        let now = Instant::now();
        {
            let mut g = self.last_ctrl.lock().unwrap();
            if g.0 == frame && now.duration_since(g.1) < DEDUP_WINDOW {
                return true;
            }
            *g = (frame.to_vec(), now);
        }
        let _ = self.tx.send(TriggerMsg::Control(action));
        true
    }

    pub fn match_frame(d: &[u8], token: &str) -> Option<Action> {
        if d.len() > 5 {
            let tok = token.as_bytes();
            if d[5..].starts_with(tok) {
                return Action::from_prefix(&d[..5]);
            }
        }
        None
    }

    fn press_key(&self) {
        if self.switch_mic {
            self.mic_switcher.switch_to_target(&self.target_mic);
        }
        let Some(inj) = &self.inj else {
            crate::logi!("[🎙] 触发停用/未配置");
            return;
        };
        if self.switch_ime {
            crate::ime::ensure_current(&self.ime_id);
        }
        inj.hold(&self.mods, &self.ptt);
    }

    fn release_key(&self) {
        if let Some(inj) = &self.inj {
            inj.release(&self.mods, &self.ptt);
        }
        if self.switch_mic {
            self.mic_switcher.restore();
        }
    }
}

fn build_injector(cfg: &TriggerCfg) -> Result<(Injector, Vec<u16>, Vec<u16>, Vec<u16>), String> {
    let (flag, mods) = crate::inject::mod_flag(&cfg.mods)?;
    let mut ptt = crate::config::parse_keys(&cfg.ptt_keys)?;
    let toggle = crate::config::parse_keys(&cfg.toggle_keys)?;
    if ptt.is_empty() {
        ptt = toggle.clone();
    }
    if ptt.is_empty() {
        return Err("ptt_keys 与 toggle_keys 均为空".into());
    }
    Ok((Injector::new(flag), mods, ptt, toggle))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_match_frame() {
        let tok = "test-token";
        assert_eq!(
            Trigger::match_frame(b"DICT1test-token", tok),
            Some(Action::DictOn)
        );
        assert_eq!(
            Trigger::match_frame(b"DICT0test-token", tok),
            Some(Action::DictOff)
        );
        assert_eq!(
            Trigger::match_frame(b"PTTD1test-token", tok),
            Some(Action::PttDown)
        );
        assert_eq!(
            Trigger::match_frame(b"PTTD0test-token", tok),
            Some(Action::PttUp)
        );
        assert_eq!(Trigger::match_frame(b"DICT1wrong-token", tok), None);
        assert_eq!(Trigger::match_frame(b"LELE1test-token", tok), None);
    }

    #[test]
    fn test_state_machine_stream_gating() {
        let cfg = TriggerCfg {
            enabled: false,
            ptt_keys: "63".into(),
            toggle_keys: "63,49".into(),
            mods: "fn".into(),
            switch_ime: false,
            input_source_id: "test".into(),
            switch_mic: false,
        };
        let t = Trigger::new(&cfg, "BlackHole 2ch");
        assert!(!t.is_streaming.load(Ordering::Relaxed));

        // 1. 模拟推流开始: DICT1 到达
        t.submit(Action::DictOn, b"DICT1test");
        std::thread::sleep(Duration::from_millis(100));
        assert!(t.is_streaming.load(Ordering::Relaxed), "推流应进入开启状态");

        // 2. 模拟持续推流: 持续收到音频包
        for _ in 0..5 {
            t.on_audio();
            std::thread::sleep(Duration::from_millis(30));
        }
        assert!(t.is_streaming.load(Ordering::Relaxed), "持续推流中应保持开启状态");

        // 3. 模拟收到停止信号: DICT0 → 立即释放 (§七十补: 微信 Fn 松开即上屏)
        t.submit(Action::DictOff, b"DICT0test");
        std::thread::sleep(Duration::from_millis(60));
        assert!(!t.is_streaming.load(Ordering::Relaxed), "停止信号应立即释放");

        // 4. 停止后 2s 内的工牌收尾尾包应被抑制, 不重新开启
        for _ in 0..3 {
            t.on_audio();
            std::thread::sleep(Duration::from_millis(30));
        }
        std::thread::sleep(Duration::from_millis(100));
        assert!(!t.is_streaming.load(Ordering::Relaxed), "收尾尾包不应触发新推流");

        // 5. 抑制窗过后, 新音频正常开启 (保底首包自动开启)
        std::thread::sleep(Duration::from_millis(2100));
        t.on_audio();
        std::thread::sleep(Duration::from_millis(100));
        assert!(t.is_streaming.load(Ordering::Relaxed), "抑制窗后新音频应自动开启");

        // 6. 无停止信号但音频中断 (>600ms)
        std::thread::sleep(Duration::from_millis(700));
        assert!(!t.is_streaming.load(Ordering::Relaxed), "音频中断保底超时后应自动释放上屏");
    }
}
