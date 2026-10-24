//! 输入法切换 (§六十八): 仅 macOS 有"切输入法"语义 (Carbon TIS);
//! Windows 上微信输入法快捷键直接合成, 无需切换 —— ensure_current 恒 true.

#[cfg(target_os = "macos")]
mod imp {
use std::ffi::{c_char, c_void};
    
    type CFTypeRef = *const c_void;
    type CFStringRef = *const c_void;
    type CFArrayRef = *const c_void;
    
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x0800_0100;
    
    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFStringGetCString(s: CFStringRef, buf: *mut c_char, len: isize, enc: u32) -> bool;
        fn CFRelease(x: CFTypeRef);
        fn CFArrayGetCount(a: CFArrayRef) -> isize;
        fn CFArrayGetValueAtIndex(a: CFArrayRef, i: isize) -> CFTypeRef;
    }
    
    #[link(name = "Carbon", kind = "framework")]
    extern "C" {
        static kTISPropertyInputSourceID: CFStringRef;
        fn TISCreateInputSourceList(props: CFTypeRef, include_all: bool) -> CFArrayRef;
        fn TISSelectInputSource(src: *const c_void) -> i32;
        fn TISCopyCurrentKeyboardInputSource() -> *const c_void;
        fn TISGetInputSourceProperty(src: *const c_void, key: CFStringRef) -> CFTypeRef;
    }
    
    fn cf_to_string(s: CFTypeRef) -> Option<String> {
        if s.is_null() {
            return None;
        }
        let mut buf = [0u8; 512];
        let ok = unsafe {
            CFStringGetCString(s, buf.as_mut_ptr() as *mut c_char, buf.len() as isize, K_CF_STRING_ENCODING_UTF8)
        };
        if ok {
            let len = buf.iter().position(|&b| b == 0).unwrap_or(0);
            Some(String::from_utf8_lossy(&buf[..len]).into_owned())
        } else {
            None
        }
    }
    
    fn source_id_of(src: *const c_void) -> Option<String> {
        unsafe {
            let key = kTISPropertyInputSourceID;
            if key.is_null() {
                return None;
            }
            cf_to_string(TISGetInputSourceProperty(src, key))
        }
    }
    
    /// 当前输入源 ID (如 com.tencent.inputmethod.wetype.pinyin)
    pub fn current_source_id() -> Option<String> {
        unsafe {
            let src = TISCopyCurrentKeyboardInputSource();
            if src.is_null() {
                return None;
            }
            source_id_of(src)
        }
    }
    
    /// 枚举输入源, 返回各 (id, 指针); include_all=false 只看已启用.
    fn enumerate(include_all: bool) -> Vec<(String, *const c_void)> {
        unsafe {
            let list = TISCreateInputSourceList(std::ptr::null(), include_all);
            if list.is_null() {
                return Vec::new();
            }
            let n = CFArrayGetCount(list);
            let mut out = Vec::with_capacity(n as usize);
            for i in 0..n {
                let src = CFArrayGetValueAtIndex(list, i);
                if let Some(id) = source_id_of(src) {
                    out.push((id, src));
                }
            }
            CFRelease(list);
            out
        }
    }
    
    /// 把输入源切到指定 bundle id.
    /// Err 的 message 已区分 "未启用" 与 "未安装" (便于 doctor 诊断).
    ///
    /// 要害: 源指针从 TISCreateInputSourceList 的数组借用而来, 数组一旦 CFRelease
    /// 指针即悬空 → TISSelectInputSource 落在已释放对象上 = EXC_BREAKPOINT
    /// (__CF_IS_OBJC 断言, 三份崩溃报告同一栈). 因此选择必须发生在数组存活期间.
    pub fn select_source(id: &str) -> Result<(), String> {
        let target = id.to_string();
        unsafe {
            let list = TISCreateInputSourceList(std::ptr::null(), false);
            if list.is_null() {
                return Err("TISCreateInputSourceList 失败".into());
            }
            let mut hit: Option<*const c_void> = None;
            let n = CFArrayGetCount(list);
            for i in 0..n {
                let src = CFArrayGetValueAtIndex(list, i);
                if source_id_of(src).as_deref() == Some(target.as_str()) {
                    hit = Some(src);
                    break;
                }
            }
            let result = match hit {
                Some(src) => {
                    let st = TISSelectInputSource(src);
                    if st == 0 {
                        Ok(())
                    } else {
                        Err(format!("TISSelectInputSource osstatus={st}"))
                    }
                }
                None => {
                    if enumerate(true).iter().any(|(sid, _)| sid == &target) {
                        Err("输入源已安装但未启用 (系统设置→键盘→输入法里添加)".into())
                    } else {
                        Err("输入源不存在 (微信输入法未安装?)".into())
                    }
                }
            };
            CFRelease(list);
            result
        }
    }
    
    /// 当前输入源已是目标则原样返回 true; 否则切换. 返回是否就位.
    pub fn ensure_current(id: &str) -> bool {
        if current_source_id().as_deref() == Some(id) {
            return true;
        }
        match select_source(id) {
            Ok(()) => {
                crate::logi!("[IME] 已切换输入法 → {id}");
                true
            }
            Err(e) => {
                crate::logi!("[IME] 切换输入法失败: {e}");
                false
            }
        }
    }
    
    /// 诊断: 输入源是否已安装/已启用/是否为当前
    pub fn probe_source(id: &str) -> &'static str {
        if current_source_id().as_deref() == Some(id) {
            return "当前输入法";
        }
        if enumerate(false).iter().any(|(sid, _)| sid == id) {
            "已启用(非当前)"
        } else if enumerate(true).iter().any(|(sid, _)| sid == id) {
            "已安装未启用"
        } else {
            "未安装"
        }
    }
    
    /// 调试: 枚举全部输入源的 ID (cargo test ime_debug -- --nocapture)
    #[cfg(test)]
    mod tests {
        use super::*;
    
        #[test]
        fn ime_debug() {
            println!("当前: {:?}", current_source_id());
            for (id, _) in enumerate(false) {
                println!("  已启用: {id}");
            }
        }
    
        /// 真实切换往返: ABC → 切回 wetype. 会动真实输入法, 显式 --ignored 运行.
        #[test]
        #[ignore]
        fn ime_switch_roundtrip() {
            let before = current_source_id();
            println!("切换前: {before:?}");
            select_source("com.apple.keylayout.ABC").expect("切 ABC");
            std::thread::sleep(std::time::Duration::from_millis(300));
            let mid = current_source_id();
            println!("切到 ABC 后: {mid:?}");
            assert_eq!(mid.as_deref(), Some("com.apple.keylayout.ABC"), "TIS 切换未生效");
            select_source("com.tencent.inputmethod.wetype.pinyin").expect("切回 wetype");
            std::thread::sleep(std::time::Duration::from_millis(300));
            let after = current_source_id();
            println!("切回后: {after:?}");
            assert_eq!(after.as_deref(), Some("com.tencent.inputmethod.wetype.pinyin"));
        }
    }
    
}

#[cfg(not(target_os = "macos"))]
mod imp {
    pub fn current_source_id() -> Option<String> {
        None
    }

    pub fn ensure_current(_id: &str) -> bool {
        true // Windows: 用户默认即微信输入法; 切换未实现, 恒放行
    }

    pub fn probe_source(_id: &str) -> &'static str {
        "N/A (Windows)"
    }
}

#[cfg(target_os = "macos")]
pub use imp::select_source;

/// 排障子命令 switch-ime 的入口 (mac 实切 / win 提示不支持)
pub fn manual_switch(id: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        select_source(id)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = id;
        Err("switch-ime 仅 macOS 支持 (Windows 直接合成快捷键, 无需切 IME)".into())
    }
}

pub use imp::current_source_id;
pub use imp::ensure_current;
pub use imp::probe_source;
