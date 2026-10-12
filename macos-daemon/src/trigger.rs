//! 触发器: 工牌控制帧语义 → IME 切换 + 微信输入法语音快捷键注入.
//! 后台单线程串行执行, 绝不阻塞收流循环.
//!
//! 语义(§六十四): DICT1/DICT0 都合成一次长输入组合键——微信输入法无会话状态
//! 查询接口, 开关=每按一次翻转一次, 面板被其自行结束后多按一次自愈;
//! PTTD1/PTTD0 直接映射组合键按住/松开, 无状态最可靠.

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

pub struct Trigger {
    tx: Sender<(Action, Vec<u8>)>,
    last: Mutex<(Vec<u8>, Instant)>,
    inj: Option<Injector>,
    mods: Vec<u16>,
    ptt: Vec<u16>,
    toggle: Vec<u16>,
    switch_ime: bool,
    ime_id: String,
}

const DEDUP_WINDOW: Duration = Duration::from_millis(300); // 固件每事件连发 3 遍(30ms 间隔)

impl Trigger {
    /// 解析失败时返回 disabled 实例(照常记日志, 不注入) —— 不让配置错误杀死守护.
    pub fn new(cfg: &TriggerCfg) -> Arc<Trigger> {
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
        let (tx, rx) = channel::<(Action, Vec<u8>)>();
        let t = Arc::new(Trigger {
            tx,
            last: Mutex::new((Vec::new(), Instant::now() - Duration::from_secs(1))),
            inj,
            mods,
            ptt,
            toggle,
            switch_ime: cfg.switch_ime,
            ime_id: cfg.input_source_id.clone(),
        });
        let worker = t.clone();
        std::thread::Builder::new()
            .name("trigger".into())
            .spawn(move || {
                while let Ok((a, _)) = rx.recv() {
                    worker.handle(a);
                }
            })
            .expect("spawn trigger worker");
        t
    }

    /// 收流循环调用; 帧去重后入队. 返回是否为控制帧(含去重命中).
    pub fn submit(&self, action: Action, frame: &[u8]) -> bool {
        let now = Instant::now();
        {
            let mut g = self.last.lock().unwrap();
            if g.0 == frame && now.duration_since(g.1) < DEDUP_WINDOW {
                return true;
            }
            *g = (frame.to_vec(), now);
        }
        let _ = self.tx.send((action, frame.to_vec()));
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

    fn handle(&self, a: Action) {
        let Some(inj) = &self.inj else {
            crate::logi!("[🎙] 收到 {} (触发停用/未配置)", a.label());
            return;
        };
        match a {
            Action::DictOn | Action::DictOff => {
                if self.switch_ime {
                    crate::ime::ensure_current(&self.ime_id);
                }
                inj.tap(&self.mods, &self.toggle);
                crate::logi!("[🎙] {} → 合成 {:?}+{:?}", a.label(), self.mods, self.toggle);
                crate::notify::send(
                    if a == Action::DictOn { "dict_on" } else { "dict_off" },
                    "乐乐语音桥",
                    if a == Action::DictOn { "🎙 语音输入开 (长输入会话)" } else { "🎙 语音输入结束, 文字上屏" },
                );
            }
            Action::PttDown => {
                if self.switch_ime {
                    crate::ime::ensure_current(&self.ime_id);
                }
                inj.hold(&self.mods, &self.ptt);
                crate::logi!("[🎙] {} → 按住 {:?}", a.label(), self.ptt);
                crate::notify::send("ptt_down", "乐乐语音桥", "🎙 按住说话开始");
            }
            Action::PttUp => {
                inj.release(&self.mods, &self.ptt);
                crate::logi!("[🎙] {} → 松开 {:?}", a.label(), self.ptt);
                crate::notify::send("ptt_up", "乐乐语音桥", "🎙 说话结束, 识别上屏");
            }
        }
        // 输入源漂移自愈: 纯 Fn 按住-松开(PTT 无中途击键)会被系统认作
        // "Fn 轻击" → 弹表情面板(CharacterPaletteIM 被选中)扰动当前输入法.
        // 150ms 后复查, 漂了就切回目标 IME (选输入源会顺带收起面板).
        if self.switch_ime && a != Action::PttDown {
            std::thread::sleep(Duration::from_millis(150));
            if crate::ime::current_source_id().as_deref() != Some(self.ime_id.as_str()) {
                crate::logi!("[IME] 检测到输入源漂移(系统 Fn 手势), 切回 {}", self.ime_id);
                crate::ime::ensure_current(&self.ime_id);
            }
        }
    }
}

fn build_injector(cfg: &TriggerCfg) -> Result<(Injector, Vec<u16>, Vec<u16>, Vec<u16>), String> {
    let (flag, mods) = crate::inject::mod_flag(&cfg.mods)?;
    let ptt = crate::config::parse_keys(&cfg.ptt_keys)?;
    let toggle = crate::config::parse_keys(&cfg.toggle_keys)?;
    if ptt.is_empty() && toggle.is_empty() {
        return Err("ptt_keys 与 toggle_keys 均为空".into());
    }
    Ok((Injector::new(flag), mods, ptt, toggle))
}
