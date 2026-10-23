//! 系统级默认输入麦克风控制与动态热切换模块 (macOS CoreAudio 原生 C API)
//!
//! 功能:
//!   1. 查询系统当前默认输入设备 ID 与名称 (kAudioHardwarePropertyDefaultInputDevice)
//!   2. 切换系统默认输入设备到目标虚拟麦克风 (如 "BlackHole 2ch")
//!   3. 推流/说话结束后还原至切换前的原始设备
//!   4. 全局原子/互斥锁保证进程退出或收到信号 (SIGINT/SIGTERM) 时能够无条件自愈还原.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Mutex;

#[repr(C)]
#[derive(Clone, Copy, Debug)]
#[allow(non_snake_case)]
pub struct AudioObjectPropertyAddress {
    pub mSelector: u32,
    pub mScope: u32,
    pub mElement: u32,
}

pub type AudioObjectID = u32;
pub type AudioDeviceID = AudioObjectID;
pub type OSStatus = i32;

pub const K_AUDIO_OBJECT_SYSTEM_OBJECT: AudioObjectID = 1;
pub const K_AUDIO_OBJECT_PROPERTY_SCOPE_GLOBAL: u32 = 0x676c6f62; // 'glob'
pub const K_AUDIO_OBJECT_PROPERTY_SCOPE_INPUT: u32 = 0x696e7074;  // 'inpt'
pub const K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN: u32 = 0;          // kAudioObjectPropertyElementMaster
pub const K_AUDIO_HARDWARE_PROPERTY_DEFAULT_INPUT_DEVICE: u32 = 0x64496e20; // 'dIn '
pub const K_AUDIO_HARDWARE_PROPERTY_DEVICES: u32 = 0x64657623;    // 'dev#'
pub const K_AUDIO_OBJECT_PROPERTY_NAME: u32 = 0x6c6e616d;         // 'lnam' (kAudioDevicePropertyDeviceNameCFString)
pub const K_AUDIO_DEVICE_PROPERTY_STREAMS: u32 = 0x73746d23;      // 'stm#'

#[link(name = "CoreAudio", kind = "framework")]
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn AudioObjectGetPropertyData(
        inObjectID: AudioObjectID,
        inAddress: *const AudioObjectPropertyAddress,
        inQualifierDataSize: u32,
        inQualifierData: *const std::ffi::c_void,
        ioDataSize: *mut u32,
        outData: *mut std::ffi::c_void,
    ) -> OSStatus;

    fn AudioObjectGetPropertyDataSize(
        inObjectID: AudioObjectID,
        inAddress: *const AudioObjectPropertyAddress,
        inQualifierDataSize: u32,
        inQualifierData: *const std::ffi::c_void,
        outDataSize: *mut u32,
    ) -> OSStatus;

    fn AudioObjectSetPropertyData(
        inObjectID: AudioObjectID,
        inAddress: *const AudioObjectPropertyAddress,
        inQualifierDataSize: u32,
        inQualifierData: *const std::ffi::c_void,
        inDataSize: u32,
        inData: *const std::ffi::c_void,
    ) -> OSStatus;

    fn CFStringGetCString(
        theString: *const std::ffi::c_void,
        buffer: *mut libc::c_char,
        bufferSize: isize,
        encoding: u32,
    ) -> bool;

    fn CFRelease(cf: *const std::ffi::c_void);
}

/// 全局保存的原始麦克风 ID (0 表示未发生切换或已还原), 供退出信号处理函数直接还原
static GLOBAL_SAVED_DEVICE_ID: AtomicU32 = AtomicU32::new(0);

/// 获取当前系统默认输入设备 ID
pub fn get_default_input_device() -> Option<AudioDeviceID> {
    let addr = AudioObjectPropertyAddress {
        mSelector: K_AUDIO_HARDWARE_PROPERTY_DEFAULT_INPUT_DEVICE,
        mScope: K_AUDIO_OBJECT_PROPERTY_SCOPE_GLOBAL,
        mElement: K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN,
    };
    let mut id: AudioDeviceID = 0;
    let mut size = std::mem::size_of::<AudioDeviceID>() as u32;
    let status = unsafe {
        AudioObjectGetPropertyData(
            K_AUDIO_OBJECT_SYSTEM_OBJECT,
            &addr,
            0,
            std::ptr::null(),
            &mut size,
            &mut id as *mut _ as *mut std::ffi::c_void,
        )
    };
    if status == 0 {
        Some(id)
    } else {
        None
    }
}

/// 获取指定音频设备的显示名称
pub fn get_device_name(id: AudioDeviceID) -> Option<String> {
    let addr = AudioObjectPropertyAddress {
        mSelector: K_AUDIO_OBJECT_PROPERTY_NAME,
        mScope: K_AUDIO_OBJECT_PROPERTY_SCOPE_GLOBAL,
        mElement: K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN,
    };
    let mut cf_ptr: *const std::ffi::c_void = std::ptr::null();
    let mut size = std::mem::size_of::<*const std::ffi::c_void>() as u32;
    let status = unsafe {
        AudioObjectGetPropertyData(
            id,
            &addr,
            0,
            std::ptr::null(),
            &mut size,
            &mut cf_ptr as *mut _ as *mut std::ffi::c_void,
        )
    };
    if status != 0 || cf_ptr.is_null() {
        return None;
    }
    let mut buf = vec![0 as libc::c_char; 256];
    let ok = unsafe {
        CFStringGetCString(
            cf_ptr,
            buf.as_mut_ptr(),
            buf.len() as isize,
            0x08000100, // kCFStringEncodingUTF8
        )
    };
    unsafe { CFRelease(cf_ptr) };
    if ok {
        let u8_slice: &[u8] = unsafe { std::slice::from_raw_parts(buf.as_ptr() as *const u8, buf.len()) };
        let len = u8_slice.iter().position(|&c| c == 0).unwrap_or(u8_slice.len());
        String::from_utf8(u8_slice[..len].to_vec()).ok()
    } else {
        None
    }
}

/// 设置系统默认输入设备 ID
pub fn set_default_input_device(id: AudioDeviceID) -> bool {
    let addr = AudioObjectPropertyAddress {
        mSelector: K_AUDIO_HARDWARE_PROPERTY_DEFAULT_INPUT_DEVICE,
        mScope: K_AUDIO_OBJECT_PROPERTY_SCOPE_GLOBAL,
        mElement: K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN,
    };
    let size = std::mem::size_of::<AudioDeviceID>() as u32;
    let status = unsafe {
        AudioObjectSetPropertyData(
            K_AUDIO_OBJECT_SYSTEM_OBJECT,
            &addr,
            0,
            std::ptr::null(),
            size,
            &id as *const _ as *const std::ffi::c_void,
        )
    };
    status == 0
}

/// 根据名称模糊查找具备输入流 (Input Stream) 的音频设备
pub fn find_input_device_by_hint(hint: &str) -> Option<(AudioDeviceID, String)> {
    let addr = AudioObjectPropertyAddress {
        mSelector: K_AUDIO_HARDWARE_PROPERTY_DEVICES,
        mScope: K_AUDIO_OBJECT_PROPERTY_SCOPE_GLOBAL,
        mElement: K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN,
    };
    let mut size = 0u32;
    if unsafe {
        AudioObjectGetPropertyDataSize(
            K_AUDIO_OBJECT_SYSTEM_OBJECT,
            &addr,
            0,
            std::ptr::null(),
            &mut size,
        )
    } != 0
    {
        return None;
    }

    let count = size as usize / std::mem::size_of::<AudioDeviceID>();
    let mut devices = vec![0 as AudioDeviceID; count];
    if unsafe {
        AudioObjectGetPropertyData(
            K_AUDIO_OBJECT_SYSTEM_OBJECT,
            &addr,
            0,
            std::ptr::null(),
            &mut size,
            devices.as_mut_ptr() as *mut _,
        )
    } != 0
    {
        return None;
    }

    for dev in devices {
        let stream_addr = AudioObjectPropertyAddress {
            mSelector: K_AUDIO_DEVICE_PROPERTY_STREAMS,
            mScope: K_AUDIO_OBJECT_PROPERTY_SCOPE_INPUT,
            mElement: K_AUDIO_OBJECT_PROPERTY_ELEMENT_MAIN,
        };
        let mut stm_size = 0u32;
        if unsafe { AudioObjectGetPropertyDataSize(dev, &stream_addr, 0, std::ptr::null(), &mut stm_size) } == 0
            && stm_size > 0
        {
            if let Some(name) = get_device_name(dev) {
                if name.to_lowercase().contains(&hint.to_lowercase()) {
                    return Some((dev, name));
                }
            }
        }
    }
    None
}

/// 进程退出安全恢复钩子 (可在 SIGINT / SIGTERM 信号或 atexit 中调用)
pub fn cleanup_mic_on_exit() {
    let saved = GLOBAL_SAVED_DEVICE_ID.swap(0, Ordering::SeqCst);
    if saved != 0 {
        if set_default_input_device(saved) {
            let name = get_device_name(saved).unwrap_or_else(|| "ID".into());
            eprintln!("[audio] 进程退出, 已紧急自愈还原系统默认麦克风: {name}");
        }
    }
}

/// 麦克风按需动态热切换器
pub struct MicSwitcher {
    saved_device: Mutex<Option<(AudioDeviceID, String)>>,
    enabled: bool,
}

impl MicSwitcher {
    pub fn new(enabled: bool) -> Self {
        Self {
            saved_device: Mutex::new(None),
            enabled,
        }
    }

    /// 切换到目标虚拟麦克风 (如 "BlackHole 2ch")
    pub fn switch_to_target(&self, target_hint: &str) -> bool {
        if !self.enabled {
            return false;
        }

        let mut saved_lock = self.saved_device.lock().unwrap();
        if saved_lock.is_some() {
            // 已处于切麦状态, 保持当前切麦状态 (幂等保证)
            return true;
        }

        let Some(current_id) = get_default_input_device() else {
            crate::logi!("[audio] 获取当前系统默认麦克风失败, 跳过切换");
            return false;
        };
        let current_name = get_device_name(current_id).unwrap_or_else(|| format!("ID:{current_id}"));

        let Some((target_id, target_name)) = find_input_device_by_hint(target_hint) else {
            crate::logi!("[audio] 未在系统输入设备中找到 {:?}, 跳过动态切麦", target_hint);
            return false;
        };

        // 如果当前默认输入设备已经等于目标设备，无需切换也无需暂存
        if current_id == target_id {
            crate::logi!("[audio] 当前默认麦克风已为目标设备 ({target_name}), 无需切换");
            return true;
        }

        crate::logi!(
            "[audio] 🎙 动态切换系统默认麦克风: {} -> {}",
            current_name,
            target_name
        );

        if set_default_input_device(target_id) {
            GLOBAL_SAVED_DEVICE_ID.store(current_id, Ordering::SeqCst);
            *saved_lock = Some((current_id, current_name));
            true
        } else {
            crate::logi!("[audio] 切换默认输入设备至 {} 失败", target_name);
            false
        }
    }

    /// 还原回原始系统默认麦克风
    pub fn restore(&self) -> bool {
        if !self.enabled {
            return false;
        }

        let mut saved_lock = self.saved_device.lock().unwrap();
        if let Some((orig_id, orig_name)) = saved_lock.take() {
            GLOBAL_SAVED_DEVICE_ID.store(0, Ordering::SeqCst);
            crate::logi!("[audio] 🎙 恢复系统默认麦克风 -> {}", orig_name);
            set_default_input_device(orig_id)
        } else {
            true
        }
    }
}

impl Drop for MicSwitcher {
    fn drop(&mut self) {
        self.restore();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_default_input() {
        if let Some(id) = get_default_input_device() {
            let name = get_device_name(id);
            println!("Default input: id={id}, name={name:?}");
            assert!(id > 0);
            assert!(name.is_some());
        }
    }

    #[test]
    fn test_mic_switcher_idempotent() {
        let switcher = MicSwitcher::new(true);
        // 如果系统有 BlackHole，测试切换与恢复；若无 BlackHole 则平稳返回
        if let Some((_, bh_name)) = find_input_device_by_hint("BlackHole") {
            let orig_id = get_default_input_device().unwrap();
            let switched = switcher.switch_to_target(&bh_name);
            assert!(switched);

            // 重复调用 switch_to_target 保证幂等，不覆盖原始设备
            switcher.switch_to_target(&bh_name);

            // 还原
            let restored = switcher.restore();
            assert!(restored);
            let final_id = get_default_input_device().unwrap();
            assert_eq!(orig_id, final_id);
        }
    }
}
