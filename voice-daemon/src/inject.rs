//! 键盘注入 (§六十四/§六十九): 按平台分发 ——
//!   macOS: CoreGraphics CGEventPost (需宿主进程辅助功能授权, 失败全静默)
//!   Windows: user32 SendInput (无需管理员; 微信输入法语音快捷键需在其
//!            设置里改绑普通组合键后由 --voice-* / 配置传入, Windows 无 Fn 虚拟键)
//!
//! 两平台共用同一形状: hold/release(mods, keys), 由 trigger.rs 的推流状态机调用.

pub struct Injector {
    #[cfg(target_os = "macos")]
    flag: u64,
    #[cfg(not(target_os = "macos"))]
    _p: (),
}

#[cfg(target_os = "macos")]
mod imp {
    use std::ffi::c_void;

    const K_CG_HID_EVENT_TAP: u32 = 0;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGEventCreateKeyboardEvent(src: *const c_void, key: u16, down: bool) -> *mut c_void;
        fn CGEventSetFlags(ev: *mut c_void, flags: u64);
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

    impl super::Injector {
        pub fn new(flag: u64) -> Self {
            super::Injector { flag }
        }

        fn post(&self, keycode: u16, down: bool) {
            unsafe {
                let ev = CGEventCreateKeyboardEvent(std::ptr::null(), keycode, down);
                if ev.is_null() {
                    return;
                }
                if self.flag != 0 {
                    CGEventSetFlags(ev, self.flag);
                }
                CGEventPost(K_CG_HID_EVENT_TAP, ev);
                CFRelease(ev);
            }
        }

        pub fn hold(&self, mods: &[u16], keys: &[u16]) {
            for k in mods {
                self.post(*k, true);
            }
            for k in keys {
                self.post(*k, true);
            }
        }

        pub fn release(&self, mods: &[u16], keys: &[u16]) {
            for k in keys.iter().rev() {
                self.post(*k, false);
            }
            for k in mods.iter().rev() {
                self.post(*k, false);
            }
        }

    }
}

#[cfg(target_os = "windows")]
mod imp {
    const INPUT_KEYBOARD: u32 = 1;
    const KEYEVENTF_KEYUP: u32 = 0x0002;

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct KEYBDINPUT {
        w_vk: u16,
        w_scan: u16,
        dw_flags: u32,
        time: u32,
        dw_extra_info: usize,
    }

    #[repr(C)]
    union INPUTU {
        ki: KEYBDINPUT,
        pad: [u8; 32],
    }

    #[repr(C)]
    struct INPUT {
        r#type: u32,
        u: INPUTU,
    }

    extern "system" {
        fn SendInput(cinputs: u32, inputs: *const INPUT, cbsize: i32) -> u32;
    }

    impl super::Injector {
        pub fn new(_flag: u64) -> Self {
            super::Injector { _p: () }
        }

        fn key(&self, vk: u16, down: bool) {
            let mut inp = INPUT {
                r#type: INPUT_KEYBOARD,
                u: INPUTU {
                    ki: KEYBDINPUT {
                        w_vk: vk,
                        w_scan: 0,
                        dw_flags: if down { 0 } else { KEYEVENTF_KEYUP },
                        time: 0,
                        dw_extra_info: 0,
                    },
                },
            };
            unsafe {
                SendInput(1, &mut inp, std::mem::size_of::<INPUT>() as i32);
            }
        }

        pub fn hold(&self, mods: &[u16], keys: &[u16]) {
            for k in mods {
                self.key(*k, true);
            }
            for k in keys {
                self.key(*k, true);
            }
        }

        pub fn release(&self, mods: &[u16], keys: &[u16]) {
            for k in keys.iter().rev() {
                self.key(*k, false);
            }
            for k in mods.iter().rev() {
                self.key(*k, false);
            }
        }

    }
}

#[cfg(target_os = "macos")]
pub use imp::ax_trusted;

#[cfg(not(target_os = "macos"))]
pub fn ax_trusted() -> bool {
    true // Windows SendInput 无需授权; 占位保持调用面一致
}

/// 修饰键名 → (平台标志, 需补发的物理按键 keycode).
/// mac: fn 只出 CG 标志位(keycode 63 由 keys 携带), 其余修饰键出标志+物理键;
/// win: 全部作为 VK 由 keys 携带(无 CG 标志概念).
pub fn mod_flag(spec: &str) -> Result<(u64, Vec<u16>), String> {
    let mut flag = 0u64;
    let mut keys = Vec::new();
    for m in spec.split(',') {
        match m.trim().to_lowercase().as_str() {
            "" => {}
            #[cfg(target_os = "macos")]
            "fn" => flag |= 0x0040_0000, // kCGEventFlagMaskSecondaryFn
            #[cfg(target_os = "macos")]
            "ctrl" => {
                flag |= 0x0004_0000;
                keys.push(59);
            }
            #[cfg(target_os = "macos")]
            "alt" | "option" => {
                flag |= 0x0008_0000;
                keys.push(58);
            }
            #[cfg(target_os = "macos")]
            "cmd" | "command" => {
                flag |= 0x0010_0000;
                keys.push(55);
            }
            #[cfg(target_os = "macos")]
            "shift" => {
                flag |= 0x0002_0000;
                keys.push(56);
            }
            #[cfg(not(target_os = "macos"))]
            "ctrl" | "control" => keys.push(0x11),
            #[cfg(not(target_os = "macos"))]
            "alt" | "option" => keys.push(0x12),
            #[cfg(not(target_os = "macos"))]
            "shift" => keys.push(0x10),
            #[cfg(not(target_os = "macos"))]
            "win" | "cmd" | "command" => keys.push(0x5B),
            other => return Err(format!("未知修饰键 {other:?} (fn/ctrl/alt/cmd/shift)")),
        }
    }
    Ok((flag, keys))
}
