//! CGEvent 键盘注入 (CoreGraphics FFI, 零依赖绑定).
//!
//! 要害(§六十四实测): CGEventPost 是否生效取决于**宿主进程的辅助功能授权**,
//! 失败完全静默(无错误无日志)——面板没弹 = 没授权或快捷键不匹配.
//! LaunchAgent 启动的本守护进程按二进制路径归属 TCC, 授权一次永久有效.

use std::ffi::c_void;
use std::time::Duration;

const K_CG_HID_EVENT_TAP: u32 = 0;

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventCreateKeyboardEvent(src: *const c_void, key: u16, down: bool) -> *mut c_void;
    fn CGEventSetFlags(ev: *mut c_void, flags: u64);
    fn CGEventGetFlags(ev: *mut c_void) -> u64;
    fn CGEventPost(tap: u32, ev: *mut c_void);
}

#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFRelease(x: *const c_void);
}

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrusted() -> bool;
}

pub fn ax_trusted() -> bool {
    unsafe { AXIsProcessTrusted() }
}

/// 判断 keycode 是否属于 macOS 修饰键 (Shift/Ctrl/Alt/Cmd/Fn 等).
/// 修饰键在 CGEventCreateKeyboardEvent 时系统会自动生成完整的设备标志位(如 NX_SECONDARYFNMASK / 0x20800000),
/// 释放时系统也会自动清除对应标志位(0x20000000); 切勿用静态标志位无差别覆写, 否则会导致抬起状态丢失或标志位错乱.
fn is_modifier(key: u16) -> bool {
    matches!(key, 54..=63)
}

pub struct Injector {
    flag: u64,
}

impl Injector {
    pub fn new(mod_flag: u64) -> Self {
        Self { flag: mod_flag }
    }

    fn post(&self, key: u16, down: bool) {
        unsafe {
            let ev = CGEventCreateKeyboardEvent(std::ptr::null(), key, down);
            if ev.is_null() {
                return;
            }
            // 仅对普通按键 (如空格 49) 附加当前持有的修饰键标志位; 修饰键自身保持系统原生 flagsChanged 事件位
            if !is_modifier(key) && self.flag != 0 {
                let base = CGEventGetFlags(ev);
                CGEventSetFlags(ev, base | self.flag);
            }
            CGEventPost(K_CG_HID_EVENT_TAP, ev);
            CFRelease(ev);
        }
    }

    /// 按住组合键 (修饰键先按下)
    pub fn hold(&self, mods: &[u16], keys: &[u16]) {
        for k in mods {
            self.post(*k, true);
        }
        for k in keys {
            self.post(*k, true);
        }
    }

    /// 松开组合键 (键先抬, 修饰键后抬)
    pub fn release(&self, mods: &[u16], keys: &[u16]) {
        for k in keys.iter().rev() {
            self.post(*k, false);
        }
        for k in mods.iter().rev() {
            self.post(*k, false);
        }
    }

    /// 轻击一次组合键
    #[allow(dead_code)]
    pub fn tap(&self, mods: &[u16], keys: &[u16]) {
        self.hold(mods, keys);
        std::thread::sleep(Duration::from_millis(40));
        self.release(mods, keys);
    }
}

/// 修饰键名 → CG 事件标志位 + 需补发的物理按键 keycode.
/// fn 本身就是 keycode 63(由 keys 携带), 只出标志位;
/// ctrl/alt/cmd/shift 出标志位并补发物理按下, 对真实按键更保真.
pub fn mod_flag(spec: &str) -> Result<(u64, Vec<u16>), String> {
    let mut flag = 0u64;
    let mut keys = Vec::new();
    for m in spec.split(',') {
        match m.trim().to_lowercase().as_str() {
            "" => {}
            "fn" => flag |= 0x0080_0000, // NX_SECONDARYFNMASK (macOS IOLLEvent.h, 实测微信输入法精准校验)
            "ctrl" => {
                flag |= 0x0004_0000;
                keys.push(59);
            }
            "alt" | "option" => {
                flag |= 0x0008_0000;
                keys.push(58);
            }
            "cmd" | "command" => {
                flag |= 0x0010_0000;
                keys.push(55);
            }
            "shift" => {
                flag |= 0x0002_0000;
                keys.push(56);
            }
            other => return Err(format!("未知修饰键 {other:?} (fn/ctrl/alt/cmd/shift)")),
        }
    }
    Ok((flag, keys))
}
