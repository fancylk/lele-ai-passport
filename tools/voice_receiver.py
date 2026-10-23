#!/usr/bin/env python3
"""
乐乐语音桥 Mac/Windows 端接收器.

两种模式:
  1) LAN 直连(默认):  本机绑 UDP 9761 收工牌 PCM; 9762 应答工牌 PING.
  2) --relay HOST:    腾讯云中转订阅模式 —— 每 20s 向 HOST:9761 发 SUB+TOKEN,
                      收中转转发的 PCM; 每 5s PING HOST:9762 测本机到中转这一跳.
  音频 → 虚拟声卡实时播放(Mac=BlackHole 2ch, Windows=VB-Cable "CABLE Input"),
  mono 复制立体声.

语音输入触发(2026-10-11 §六十四): 识别工牌控制帧 DICT1/DICT0(长输入开/关)与
PTTD1/PTTD0(按住说话 按下/抬起), 在后台线程合成微信输入法语音快捷键:
  Mac 默认 = PTT [63](Fn) / 长输入 [63,49](Fn+空格), 与微信输入法设置存储实测一致;
  Windows 无 Fn 虚拟键, 需先在微信输入法设置把两快捷键改绑普通组合键, 再用
  --voice-ptt-key/--voice-toggle-key/--voice-mods 传同样的键
  (例: 改绑 Ctrl+空格 后 --voice-ptt-key space --voice-mods ctrl).
  Mac 注入需辅助功能权限: 系统设置→隐私和安全性→辅助功能→勾选启动本脚本的终端.
  --no-voice-trigger 关闭. 自检工具: tools/spike_weetype_hotkey.py

Windows 注入实测(2026-10-21, tyz86, WeType 3.0.0.37): 默认快捷键实测为
按住说话=Ctrl+Win、启动语音输入(长输入)=Ctrl+Shift+Win, 组合键直接写进参数:
  --voice-ptt-key ctrl,win --voice-toggle-key ctrl,shift,win
三个注入要点(缺一不触发): ①Win 等扩展键必须带 KEYEVENTF_EXTENDEDKEY;
②和弦保持 ~0.2s 再松开; ③长输入为"点按翻转"语义(DICT1 点按开启、DICT0 后再
点按关闭), PTT 为按住/松开语义.

Windows 加固(2026-10-07, tyz86): 音频端点可能被系统临时失效(驱动装完重枚举/
睡眠唤醒/音频服务重启), 症状=PortAudioError "There is no driver installed" /
MME error 6. 现在写失败自动按设备名重扫重连; 设备不存在时等待其出现,
不再崩溃退出, 也绝不回落默认扬声器(避免语音外放).

无控制台后台运行(2026-10-21, tyz86): 自启改用 pythonw.exe 直启(GUI 子系统,
不创建任何控制台, 根治开机黑窗口). pythonw 下 sys.stdout/stderr 为 None,
任何 print 都会 AttributeError 崩溃 → 无控制台时自动重定向到脚本同目录
receiver.log (启动时超 2MB 轮转为 .old), 排障直接看该日志.

用法:
  python3 voice_receiver.py [--relay 124.221.187.167] [--token lele-6deb6d37]
                            [--device "CABLE Input"] [--rate 16000] [--quiet]
Ctrl-C 退出并打印汇总. 后台托管用 voice_receiver.sh start|stop.
"""

import argparse
import atexit
import ctypes
import ctypes.util
import os
import queue
import socket
import struct
import sys
import threading
import time

try:
    import sounddevice as sd
except ImportError:
    sys.exit("缺少 sounddevice: pip3 install sounddevice")


def _setup_headless_logging():
    """pythonw 无控制台运行时 sys.stdout/stderr 均为 None, 任何 print 都会直接
    AttributeError 崩溃 —— 重定向到脚本同目录 receiver.log (超 2MB 轮转)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receiver.log")
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > 2 * 1024 * 1024:
            os.replace(log_path, log_path + ".old")
        f = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        f = open(os.devnull, "w")
    sys.stdout = f
    sys.stderr = f
    print(f"[=] 无控制台模式 → 日志: {log_path}", flush=True)


_setup_headless_logging()

TOKEN = b"lele-6deb6d37"
SUB_EVERY = 20.0
PROBE_EVERY = 5.0

# ---------------------------------------------------------------------------
# 语音输入触发: 工牌控制帧 → 微信输入法语音快捷键 (§六十四)
#
# 微信输入法 Mac 版语音快捷键(其设置 MMKV wetype.settings 实测):
#   voicePTTShortcut_keyCodes    = [63]      Fn 按住说话
#   voiceToggleShortcut_keyCodes = [63,49]   Fn+空格 长输入开关
# Mac keycode: 63=Fn/Globe 49=空格; CG 事件需带 kCGEventFlagMaskSecondaryFn(0x40 万位).
# 语义: DICT1/DICT0 都合成一次长输入组合键(微信输入法无会话状态查询接口,
# 开关定为"每按一次翻转一次", 若面板已被其自行结束, 多按一次自愈);
# PTTD1/PTTD0 直接映射组合键按住/松开, 无状态最可靠.
# ---------------------------------------------------------------------------
DICT_FRAMES = {
    b"DICT1": "dict_on",
    b"DICT0": "dict_off",
    b"PTTD1": "ptt_down",
    b"PTTD0": "ptt_up",
}
# 数据通道上可能出现的中转/打洞信令帧前缀: 既不喂声卡也不能当音频触发语音
# (否则中转每 20s 回的 SUB_OK 会被误判为推流, 每 20s 闪一次语音面板 —— 2026-10-21 实测踩坑)
SIGNAL_PREFIXES = (b"LELE1", b"SUB", b"PONG", b"PING", b"SRC", b"PNCH")

MOD_FLAGS = {   # CG 事件标志位
    "fn": 0x00400000, "ctrl": 0x00040000, "alt": 0x00080000,
    "cmd": 0x00100000, "shift": 0x00020000,
}
MAC_KEYCODES = {
    "fn": 63, "space": 49, "ctrl": 59, "alt": 58, "cmd": 55, "shift": 56,
    "tab": 48, "enter": 36, "esc": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
WIN_VK = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "cmd": 0x5B, "win": 0x5B,
    "fn": None,   # Windows 无 Fn 虚拟键
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}
# Windows 组合键书写约定: --voice-ptt-key/--voice-toggle-key 里逗号分隔的键序列
# 以最后一个键为主键(如 "ctrl,win" = Ctrl+Win), 其余为修饰键


class MacInjector:
    """ctypes 直调 CoreGraphics 合成键盘事件 (零依赖). 宿主进程需辅助功能权限."""

    def __init__(self, flag):
        self.flag = flag
        self.cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        self.cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        self.cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        self.cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        self.cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self.cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

    def _post(self, keycode, down):
        ev = self.cg.CGEventCreateKeyboardEvent(None, keycode, down)
        if self.flag:
            self.cg.CGEventSetFlags(ev, self.flag)
        self.cg.CGEventPost(0, ev)            # kCGHIDEventTap
        self.cf.CFRelease(ev)

    def hold(self, mods, keys):
        for k in mods + keys:
            self._post(k, True)

    def release(self, mods, keys):
        for k in list(reversed(keys)) + list(reversed(mods)):
            self._post(k, False)

    def tap(self, mods, keys, gap=0.04):
        self.hold(mods, keys)
        time.sleep(gap)
        self.release(mods, keys)


class _WinKEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class _WinINPUTUNION(ctypes.Union):
    _fields_ = [("ki", _WinKEYBDINPUT), ("pad", ctypes.c_ubyte * 32)]


class _WinINPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _WinINPUTUNION)]


class WinInjector:
    """ctypes user32 SendInput 合成键盘事件 (零依赖). Windows 无 Fn 虚拟键:
    微信输入法语音快捷键需在其设置改绑普通组合键后用 --voice-* 传入.

    实测要点 (2026-10-21, WeType 3.0.0.37, tyz86 台式机):
    - Win/VK_LWIN 等扩展键必须带 KEYEVENTF_EXTENDEDKEY, 否则事件被判畸形丢弃;
    - 和弦需保持 ~0.2s 再松开 (tap gap 0.04s 太快不触发);
    - 修饰键先按、主键(如 Win)最后按下, 和弦在主键 down 时成立."""

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001
    # Win/右Win/菜单键/PgUp-PgDn/Home/End/方向键/Ins/Del 均为扩展键
    EXTENDED_VKS = {0x5B, 0x5C, 0x5D, 0x21, 0x22, 0x23, 0x24,
                    0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}

    def __init__(self):
        self.user32 = ctypes.windll.user32

    def _key(self, vk, down):
        flags = 0 if down else self.KEYEVENTF_KEYUP
        if vk in self.EXTENDED_VKS:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        inp = _WinINPUT(self.INPUT_KEYBOARD)
        inp.u.ki = _WinKEYBDINPUT(vk, 0, flags, 0, None)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_WinINPUT))

    def hold(self, mods, keys):
        for k in mods + keys:
            self._key(k, True)

    def release(self, mods, keys):
        for k in list(reversed(keys)) + list(reversed(mods)):
            self._key(k, False)

    def tap(self, mods, keys, gap=0.2):
        self.hold(mods, keys)
        time.sleep(gap)
        self.release(mods, keys)


class WinDefaultMicSwitcher:
    """Windows 系统默认输入麦克风热切换 (纯 ctypes COM, 零依赖).

    语义对齐 Mac 侧 macos-daemon/mic.rs (b3c4a34): 推流开始把系统默认麦克风
    切到虚拟声卡录制端 (VB-Cable 即 "CABLE Output"), 结束还原. 微信输入法
    语音麦克风保持"默认设备"即可听到工牌音频, 日常通话/录音不被虚拟声卡占死.

    实现: IMMDeviceEnumerator 枚举 capture 端点/读默认; 未公开 COM 接口
    IPolicyConfig::SetDefaultEndpoint (vtable[13], CLSID CPolicyConfigClient)
    热切换, 三个 role(eConsole/eMultimedia/eCommunications) 全切.
    实测 (2026-10-21, WeType 3.0.0.37): 微信输入法语音跟随系统默认麦克风,
    切换后立即生效. 未公开接口调用失败时打印警告并静默降级, 不影响收流."""

    def __init__(self, quiet=False):
        import ctypes
        from ctypes import POINTER, c_void_p, c_wchar_p
        self.ct = ctypes
        self.POINTER, self.c_void_p, self.c_wchar_p = POINTER, c_void_p, c_wchar_p
        self.ole32 = ctypes.OleDLL("ole32")

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        class PKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("pad", ctypes.c_ubyte * 6),
                        ("pwszVal", c_void_p)]

        self.GUID, self.PKEY, self.PROPVARIANT = GUID, PKEY, PROPVARIANT

        def guid(s):
            g = GUID()
            self.ole32.CLSIDFromString(s, ctypes.byref(g))
            return g

        self.CLSID_MMDeviceEnumerator = guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        self.IID_IMMDeviceEnumerator = guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        self.CLSID_PolicyConfigClient = guid("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
        self.IID_IPolicyConfig = guid("{f8679f50-850a-41cf-9c72-430f290290c8}")
        self.PKEY_Device_FriendlyName = PKEY()
        self.ole32.CLSIDFromString(
            "{a45c254e-df1c-4efd-8020-67d146a850e0}",
            ctypes.byref(self.PKEY_Device_FriendlyName.fmtid))
        self.PKEY_Device_FriendlyName.pid = 14

    def _co_init(self):
        try:
            self.ole32.CoInitializeEx(None, 2)   # COINIT_APARTMENTTHREADED
        except OSError:
            pass  # 该线程已初始化

    def _call(self, ptr, idx, *args, argtypes=()):
        """COM vtable 调用: 对象首指针指向 vtable 指针数组."""
        ct = self.ct
        vtbl = ct.cast(ct.cast(ptr, self.POINTER(self.c_void_p)).contents,
                       self.POINTER(self.c_void_p))
        fn = ct.WINFUNCTYPE(ct.HRESULT, self.c_void_p, *argtypes)(vtbl[idx])
        return fn(ptr, *args)

    def _device_info(self, dev):
        store = self.c_void_p()
        self._call(dev, 4, 0, self.ct.byref(store),
                   argtypes=(self.ct.c_int, self.POINTER(self.c_void_p)))
        pv = self.PROPVARIANT()
        self._call(store, 5, self.ct.byref(self.PKEY_Device_FriendlyName),
                   self.ct.byref(pv), argtypes=(self.c_void_p, self.c_void_p))
        name = self.ct.wstring_at(pv.pwszVal) if pv.pwszVal else "?"
        idp = self.c_wchar_p()
        self._call(dev, 5, self.ct.byref(idp),
                   argtypes=(self.POINTER(self.c_wchar_p),))
        return idp.value, name

    def list_capture(self):
        """([(设备id, 名称)...], 当前默认 (设备id, 名称))."""
        self._co_init()
        enum = self.c_void_p()
        self.ole32.CoCreateInstance(self.ct.byref(self.CLSID_MMDeviceEnumerator), None,
                                    1, self.ct.byref(self.IID_IMMDeviceEnumerator),
                                    self.ct.byref(enum))
        coll = self.c_void_p()
        self._call(enum, 3, 1, 1, self.ct.byref(coll),
                   argtypes=(self.ct.c_int, self.ct.c_int,
                             self.POINTER(self.c_void_p)))   # EnumAudioEndpoints(eCapture, ACTIVE)
        n = self.ct.c_ulong()
        self._call(coll, 3, self.ct.byref(n),
                   argtypes=(self.POINTER(self.ct.c_ulong),))
        out = []
        for i in range(n.value):
            dev = self.c_void_p()
            self._call(coll, 4, i, self.ct.byref(dev),
                       argtypes=(self.ct.c_uint, self.POINTER(self.c_void_p)))
            out.append(self._device_info(dev))
        default = self.c_void_p()
        self._call(enum, 4, 1, 0, self.ct.byref(default),
                   argtypes=(self.ct.c_int, self.ct.c_int,
                             self.POINTER(self.c_void_p)))   # GetDefaultAudioEndpoint(eCapture, eConsole)
        d = self._device_info(default) if default.value else (None, None)
        return out, d

    def set_default(self, device_id):
        """IPolicyConfig::SetDefaultEndpoint (vtable[13]) 三个 role 全切."""
        self._co_init()
        pc = self.c_void_p()
        self.ole32.CoCreateInstance(self.ct.byref(self.CLSID_PolicyConfigClient), None,
                                    1, self.ct.byref(self.IID_IPolicyConfig),
                                    self.ct.byref(pc))
        for role in (0, 1, 2):
            hr = self._call(pc, 13, device_id, role,
                            argtypes=(self.c_wchar_p, self.ct.c_int))
            if hr != 0:
                raise OSError(f"SetDefaultEndpoint role={role} hr={hr & 0xffffffff:#x}")


class SystemMicSwitcher:
    """系统默认输入麦克风动态热切换
    (Mac: CoreAudio ctypes; Windows: IMMDeviceEnumerator + IPolicyConfig COM)."""

    def __init__(self, target_hint, enabled=True, quiet=False):
        self.target_hint = target_hint
        self.enabled = enabled
        self.quiet = quiet
        self.saved_device = None
        self._lock = threading.Lock()
        self._ca = None
        self._cf = None
        self._win = None
        if self.enabled and sys.platform == "darwin":
            try:
                self._ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
                self._cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
            except Exception as e:
                if not self.quiet:
                    print(f"[!] 加载 CoreAudio 失败: {e}", flush=True)
        if self.enabled and sys.platform.startswith("win"):
            try:
                self._win = WinDefaultMicSwitcher(quiet=quiet)
            except Exception as e:
                if not self.quiet:
                    print(f"[!] 初始化 Windows 切麦 COM 失败: {e}", flush=True)

    def switch_to_target(self):
        if not self.enabled:
            return
        with self._lock:
            if self.saved_device is not None:
                return  # 保持幂等
            if sys.platform == "darwin" and self._ca and self._cf:
                self._mac_switch()
            elif sys.platform.startswith("win") and self._win:
                self._win_switch()

    def restore(self):
        if not self.enabled:
            return
        with self._lock:
            if self.saved_device is None:
                return
            if sys.platform == "darwin" and self._ca and self._cf:
                self._mac_restore()
            elif sys.platform.startswith("win") and self._win:
                self._win_restore()

    def _mac_get_default_input(self):
        class Address(ctypes.Structure):
            _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]
        addr = Address(0x64496e20, 0x676c6f62, 0)
        dev_id = ctypes.c_uint32(0)
        size = ctypes.c_uint32(4)
        st = self._ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(dev_id))
        return dev_id.value if st == 0 else None

    def _mac_get_name(self, dev_id):
        class Address(ctypes.Structure):
            _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]
        addr = Address(0x6c6e616d, 0x676c6f62, 0)
        cf_ptr = ctypes.c_void_p(0)
        size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        st = self._ca.AudioObjectGetPropertyData(dev_id, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(cf_ptr))
        if st != 0 or not cf_ptr.value:
            return None
        buf = ctypes.create_string_buffer(256)
        ok = self._cf.CFStringGetCString(cf_ptr, buf, 256, 0x08000100)
        self._cf.CFRelease(cf_ptr)
        return buf.value.decode("utf-8", "ignore") if ok else None

    def _mac_set_default_input(self, dev_id):
        class Address(ctypes.Structure):
            _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]
        addr = Address(0x64496e20, 0x676c6f62, 0)
        dev = ctypes.c_uint32(dev_id)
        st = self._ca.AudioObjectSetPropertyData(1, ctypes.byref(addr), 0, None, 4, ctypes.byref(dev))
        return st == 0

    def _mac_find_input(self, hint):
        class Address(ctypes.Structure):
            _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32), ("mElement", ctypes.c_uint32)]
        addr = Address(0x64657623, 0x676c6f62, 0)
        size = ctypes.c_uint32(0)
        if self._ca.AudioObjectGetPropertyDataSize(1, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
            return None
        count = size.value // 4
        devs = (ctypes.c_uint32 * count)()
        if self._ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(size), devs) != 0:
            return None
        for d in devs:
            stm_addr = Address(0x73746d23, 0x696e7074, 0)
            stm_size = ctypes.c_uint32(0)
            if self._ca.AudioObjectGetPropertyDataSize(d, ctypes.byref(stm_addr), 0, None, ctypes.byref(stm_size)) == 0 and stm_size.value > 0:
                name = self._mac_get_name(d)
                if name and hint.lower() in name.lower():
                    return (d, name)
        return None

    def _mac_switch(self):
        curr_id = self._mac_get_default_input()
        if curr_id is None:
            return
        curr_name = self._mac_get_name(curr_id) or str(curr_id)
        target = self._mac_find_input(self.target_hint)
        if not target:
            return
        target_id, target_name = target
        if curr_id == target_id:
            return
        if not self.quiet:
            print(f"[audio] 🎙 动态切换系统默认麦克风: {curr_name} -> {target_name}", flush=True)
        if self._mac_set_default_input(target_id):
            self.saved_device = (curr_id, curr_name)

    def _mac_restore(self):
        if self.saved_device is None:
            return
        orig_id, orig_name = self.saved_device
        self.saved_device = None
        if not self.quiet:
            print(f"[audio] 🎙 恢复系统默认麦克风 -> {orig_name}", flush=True)
        self._mac_set_default_input(orig_id)

    def _win_switch(self):
        try:
            devs, cur = self._win.list_capture()
            target = next(((i, n) for i, n in devs
                           if self.target_hint.lower() in n.lower()), None)
            if target is None:
                if not self.quiet:
                    print(f"[!] 未找到目标麦克风 '{self.target_hint}', 跳过切麦", flush=True)
                return
            tid, tname = target
            if cur and cur[0] == tid:
                return  # 已是目标设备, 不切不暂存
            if not self.quiet:
                print(f"[audio] 🎙 动态切换系统默认麦克风: {(cur[1] if cur else '?')} -> {tname}", flush=True)
            self._win.set_default(tid)
            self.saved_device = cur
        except Exception as e:
            if not self.quiet:
                print(f"[!] 切换默认麦克风失败(忽略, 继续收流): {e}", flush=True)

    def _win_restore(self):
        orig = self.saved_device
        if not orig:
            return
        try:
            self._win.set_default(orig[0])
            if not self.quiet:
                print(f"[audio] 🎙 恢复系统默认麦克风 -> {orig[1]}", flush=True)
        except Exception as e:
            if not self.quiet:
                print(f"[!] 恢复默认麦克风失败: {e}", flush=True)
        finally:
            self.saved_device = None


class VoiceTrigger:
    """音频推流状态机 → 保持开启, 结束上屏 (§六十四, 2026-10-21 对齐 Mac daemon).

    语义 (WeType Windows 实测: 按住说话=Ctrl+Win, 启动语音输入=Ctrl+Shift+Win):
    1. PTT 推流 (PTTD1 或 首包音频): hold(ptt 组合键) —— 微信输入法「按住说话」;
       PTTD0 + 尾音结束 → release → 松手上屏.
    2. 长输入会话 (DICT1): tap(toggle 组合键) —— 「启动语音输入」面板开启后
       持续转写; DICT0 + 尾音结束 → 再 tap 一次 → 关闭并上屏.
    3. 推流中 (持续音频包): 刷新活跃时间戳, 保持会话.
    4. 待机期 (静音无推流): 绝不合成按键, 绝不误调起输入法.
    """

    DEDUP_WINDOW = 0.3
    STOP_TAIL_TIMEOUT = 0.25   # 收到停止帧后等待收尾音频结束超时 (秒)
    IDLE_TIMEOUT = 0.60        # 无停止帧音频中断保底超时 (秒, PTT)
    MAX_DURATION = 120.0       # 单次最长安全时长 (秒, PTT 按住安全上限)
    DICT_LINK_TIMEOUT = 3.0    # 长输入会话音频链路死亡判定 (秒): 面板本就持续转写,
                               # 只在链路断(无包)时收面板; 待机静音≠链路断(工牌静音期不发包,
                               # 但长输入会话期间工牌持续发包, 3s 无包=链路/固件异常)
    DICT_MAX_DURATION = 300.0  # 长输入会话硬上限 (秒): 无停止帧兜底 (DICT0 丢包时链路超时兜底)

    def __init__(self, inj, ptt_mods, ptt_keys, toggle_mods, toggle_keys,
                 mic_switcher=None, quiet=False):
        self.inj = inj
        # 任一组合键缺省时互相兜底 (与旧版行为一致)
        self.ptt_mods = ptt_mods if ptt_keys else toggle_mods
        self.ptt_keys = ptt_keys if ptt_keys else toggle_keys
        self.tgl_mods = toggle_mods if toggle_keys else ptt_mods
        self.tgl_keys = toggle_keys if toggle_keys else ptt_keys
        self.mic_switcher = mic_switcher
        self.quiet = quiet
        self.q = queue.Queue()
        self._last_frame = None
        self._last_ctrl_t = 0.0
        self._last_audio_t = 0.0
        self.is_streaming = False
        threading.Thread(target=self._worker, daemon=True).start()

    def on_audio(self):
        """每包音频到达通知."""
        self._last_audio_t = time.time()
        if not self.is_streaming:
            self.q.put(("audio_burst", None))

    def submit(self, frame):
        """控制帧到达通知."""
        action = DICT_FRAMES.get(frame[:5])
        if action is None:
            return False
        now = time.time()
        if frame == self._last_frame and now - self._last_ctrl_t < self.DEDUP_WINDOW:
            return True
        self._last_frame, self._last_ctrl_t = frame, now
        self.q.put(("ctrl", action))
        return True

    def _worker(self):
        session = None            # None | 'ptt' | 'dict'
        stop_pending = False
        stream_start_t = 0.0

        while True:
            # 等待事件，带 50ms 超时用于状态机看门狗检查
            try:
                kind, data = self.q.get(timeout=0.05)
                if kind == "ctrl":
                    action = data
                    if action in ("dict_on", "ptt_down"):
                        stop_pending = False
                        self._last_audio_t = time.time()
                        if session is None:
                            if self.mic_switcher:
                                self.mic_switcher.switch_to_target()
                            if action == "dict_on" and self.tgl_keys:
                                self.inj.tap(self.tgl_mods, self.tgl_keys)
                                session = "dict"
                                label = "长输入(tap 开启)"
                            else:
                                self.inj.hold(self.ptt_mods, self.ptt_keys)
                                session = "ptt"
                                label = "PTT(按住)"
                            self.is_streaming = True
                            stream_start_t = time.time()
                            if not self.quiet:
                                print(f"[🎙] {label} → 推流开始 (组合键 {self.tgl_mods + self.tgl_keys if session == 'dict' else self.ptt_mods + self.ptt_keys})", flush=True)
                    elif action in ("dict_off", "ptt_up"):
                        if session is not None:
                            stop_pending = True
                            if not self.quiet:
                                print("[🎙] 收到停止信号, 等待音频收尾上屏...", flush=True)
                elif kind == "audio_burst":
                    stop_pending = False
                    if session is None:
                        if self.mic_switcher:
                            self.mic_switcher.switch_to_target()
                        self.inj.hold(self.ptt_mods, self.ptt_keys)
                        session = "ptt"
                        self.is_streaming = True
                        stream_start_t = time.time()
                        if not self.quiet:
                            print(f"[🎙] 探测到推流音频到达 → PTT 按住 ({self.ptt_mods + self.ptt_keys})", flush=True)
            except queue.Empty:
                pass
            except Exception as e:
                print(f"[!] 快捷键注入异常: {e}", flush=True)

            # 看门狗检测
            if session is not None:
                now = time.time()
                elapsed = now - self._last_audio_t
                duration = now - stream_start_t

                timeout = (self.STOP_TAIL_TIMEOUT if stop_pending else
                           (self.DICT_LINK_TIMEOUT if session == "dict" else self.IDLE_TIMEOUT))
                should_stop = False
                max_dur = self.DICT_MAX_DURATION if session == "dict" else self.MAX_DURATION
                if duration >= max_dur:
                    if not self.quiet:
                        print(f"[🎙] 达到单次推流最大安全时长 ({max_dur:.0f}s), 强制停止上屏", flush=True)
                    should_stop = True
                elif elapsed >= timeout:
                    should_stop = True

                if should_stop:
                    try:
                        if session == "dict" and self.tgl_keys:
                            self.inj.tap(self.tgl_mods, self.tgl_keys)  # 再按一次 → 关闭上屏
                        else:
                            self.inj.release(self.ptt_mods, self.ptt_keys)
                    except Exception as e:
                        print(f"[!] 释放按键失败: {e}", flush=True)
                    session = None
                    stop_pending = False
                    self.is_streaming = False
                    if self.mic_switcher:
                        self.mic_switcher.restore()
                    if not self.quiet:
                        print(f"[🎙] 推流结束 ({elapsed*1000:.0f}ms 无音频) → 停止上屏", flush=True)


class Player:
    """虚拟声卡实时播放器 —— callback 常开流, 移植 macos-daemon/audio.rs 三件套
    (2026-10-21 重写, 根治"识别不稳"):

    1. 回调流由声卡时钟驱动: 播放与 UDP 收包循环彻底解耦, 写声卡永不阻塞收包
       (旧版在主循环里同步 pump(), 网络抖动 + 写阻塞 → 丢包 → 微信输入法听到断续音).
    2. 150ms 预缓冲: 音频到达先攒水位再出声; 欠载后重新预缓冲, 吸收网络抖动
       (本机到中转实测抖动可达 ±200ms 以上, 无缓冲时全部变成声卡上的静音裂缝).
    3. 无语音时输出静音: 流常开, 微信输入法永远认为"麦克风可用".
    4. 水位微伺服 + 积压清空: 工牌晶振与声卡时钟漂移用每回调 ±1 帧消化(不可闻);
       缓冲积压超 1s 直接清空重来(实时语音旧数据无意义).

    统计: underruns=欠载次数(预缓冲后仍取空), level=当前缓冲水位毫秒数.
    """

    PREBUFFER_MS = 300.0     # 默认预缓冲水位(可由 --prebuffer-ms 覆盖)
    HIGH_WATER_MS = 1000.0   # 积压清空阈值
    RETRY_EVERY = 2.0        # 设备重开限流(秒)

    def __init__(self, name_hint, rate, prebuffer_ms=None):
        self.name_hint = name_hint
        self.rate = rate            # 源采样率(工牌 16k)
        self.channels = 2           # mono 复制为 stereo
        self.mult = 1               # 设备非 16k 打开时的样本复制倍率
        if prebuffer_ms:
            self.PREBUFFER_MS = float(prebuffer_ms)
        self.lock = threading.Lock()
        self.buf = bytearray()      # mono s16 源字节
        self.primed = False
        self.underruns = 0
        self.servo_frames = 0       # 伺服累计增删帧数(诊断)
        self.clears = 0             # 积压清空次数
        self.stream = None
        self._last_try = 0.0
        if not self._open():
            print(f"[!] 未找到输出设备 '{name_hint}', 每{self.RETRY_EVERY:.0f}s 自动重试"
                  " (不会回落到默认扬声器)", flush=True)

    # -- 设备解析与开关 ------------------------------------------------------
    def _resolve(self):
        """按名字子串找输出设备索引; 找不到返回 None."""
        if not self.name_hint:
            return None
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and self.name_hint.lower() in d["name"].lower():
                return i
        return None

    def _open(self):
        """解析设备并打开 callback 输出流; 16k 打不开时按设备默认采样率降级."""
        idx = self._resolve()
        if idx is None:
            self.stream = None
            return False
        name = sd.query_devices(idx)["name"]
        try:
            self._start_stream(idx, self.rate)
        except Exception:
            try:
                default_rate = int(sd.query_devices(idx)["default_samplerate"])
                self.rate = default_rate
                self.mult = max(1, round(default_rate / 16000))
                self._start_stream(idx, default_rate)
                print(f"[!] 降级 {default_rate}Hz x{self.mult} 打开", flush=True)
            except Exception as e:
                self.stream = None
                print(f"[!] 输出设备 #{idx} {name!r} 打不开: {e}", flush=True)
                return False
        with self.lock:
            self.buf.clear()
            self.primed = False
        print(f"[+] 音频 → {name} (s16le/{self.rate}/mono, 预缓冲{self.PREBUFFER_MS:.0f}ms)", flush=True)
        return True

    def _start_stream(self, idx, rate):
        self.rate = rate
        self.stream = sd.RawOutputStream(
            samplerate=rate, channels=self.channels, dtype="int16",
            device=idx, blocksize=0, callback=self._callback)
        self.stream.start()

    def health_check(self):
        """主循环喂: 流死了/设备被系统失效(重枚举)时限流重开."""
        if self.stream is not None and self.stream.active:
            return
        now = time.time()
        if now - self._last_try < self.RETRY_EVERY:
            return
        self._last_try = now
        if self.stream is not None:
            print("[!] 输出设备异常, 转入自动重连", flush=True)
        self.close()
        if self._open():
            print("[+] 输出设备已恢复", flush=True)

    # -- 数据面 ---------------------------------------------------------------
    def feed(self, mono: bytes):
        """收包线程调用: 追加 mono s16 源数据. 永不阻塞."""
        with self.lock:
            self.buf += mono
            hi = int(self.rate * 2 * self.HIGH_WATER_MS / 1000)
            if len(self.buf) > hi:
                # 积压过多(链路闪断恢复/休眠唤醒): 旧数据无意义, 清空重新预缓冲
                del self.buf[:-1024]
                self.clears += 1
                self.primed = False

    def _callback(self, outdata, frames, time_info, status):
        """PortAudio 回调(声卡时钟驱动): mono → stereo, 静音保活, 水位伺服."""
        need_mono = frames * 2 * self.mult          # 本回调需要的 mono 源字节数
        pre = int(self.rate * 2 * self.PREBUFFER_MS / 1000)
        with self.lock:
            avail = len(self.buf)
            if not self.primed:
                if avail < pre:
                    outdata[:] = bytes(frames * self.channels * 2)   # 静音攒水位
                    return
                self.primed = True
            # 水位伺服: 高于预缓冲水位→丢1帧, 低于→补1帧(≈0.003%/回调 变速不可闻)
            if avail > pre + 4:
                del self.buf[:2]
                self.servo_frames -= 1
            elif avail < pre - 4 and avail > need_mono + 2:
                self.buf[:] = self.buf[:2] + self.buf
                self.servo_frames += 1
            take = min(need_mono, len(self.buf))
            chunk = bytes(self.buf[:take])
            del self.buf[:take]
            if take < need_mono:
                self.underruns += 1
                self.primed = False     # 欠载: 重新预缓冲
        # mono → stereo 复制
        out = bytearray()
        if self.mult == 1:
            for i in range(0, len(chunk) - 1, 2):
                out += chunk[i:i + 2] * 2
        else:
            for i in range(0, len(chunk) - 1, 2):
                out += chunk[i:i + 2] * 2 * self.mult
        out += bytes(frames * self.channels * 2 - len(out))   # 尾部补静音
        outdata[:] = out

    def level_ms(self):
        """当前缓冲水位(毫秒)."""
        with self.lock:
            return len(self.buf) * 1000.0 / (self.rate * 2)

    def close(self):
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="BlackHole 2ch")
    ap.add_argument("--port", type=int, default=9761, help="LAN 模式监听端口")
    ap.add_argument("--relay", default=None, help="中转服务器公网 IP(订阅模式)")
    default_tag = "mac" if sys.platform == "darwin" else ("pc" if sys.platform.startswith("win") else "client")
    ap.add_argument("--tag", default=default_tag, help="终端标识 (例如 mac, pc)")
    ap.add_argument("--token", default=TOKEN.decode())
    ap.add_argument("--ping-port", type=int, default=9762)
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--prebuffer-ms", type=int, default=300,
                    help="播放预缓冲水位毫秒(吸收网络抖动; 本机到中转实测抖动可达±200ms+,"
                         " Mac 家用网络 150ms 足够, 公司网络建议 300+)")
    ap.add_argument("--quiet", action="store_true")
    if sys.platform == "darwin":
        default_ptt, default_toggle, default_mods = "63", "63,49", "fn"
    else:
        # Windows 无 Fn 虚拟键: 须在微信输入法设置改绑普通组合键后显式指定
        default_ptt = default_toggle = default_mods = ""
    ap.add_argument("--no-voice-trigger", action="store_true",
                    help="忽略工牌语音控制帧(不合成微信输入法语音快捷键)")
    ap.add_argument("--voice-ptt-key", default=default_ptt,
                    help="按住说话组合键, 逗号分隔, 修饰键可直接写入 (Mac 默认 63=Fn;"
                         " Windows 如 ctrl,win; 也支持十进制/0x十六进制 VK 码)")
    ap.add_argument("--voice-toggle-key", default=default_toggle,
                    help="长输入开关组合键 (Mac 默认 63,49=Fn+空格; Windows 如 ctrl,shift,win)")
    ap.add_argument("--voice-mods", default=default_mods,
                    help="组合键修饰键 (Mac 默认 fn; ctrl/alt/cmd/shift)")
    ap.add_argument("--no-switch-mic", action="store_true",
                    help="禁用推流时自动切换系统默认麦克风")
    ap.add_argument("--mic-device", default=None,
                    help="推流时默认麦克风切换目标 (Windows 默认 CABLE Output 即 VB-Cable 录制端;"
                         " 微信输入法语音麦克风保持\"默认设备\"即可)")
    args = ap.parse_args()
    token = args.token.encode()

    mic_hint = args.mic_device or (
        "CABLE Output" if sys.platform.startswith("win") else args.device)
    mic_switcher = SystemMicSwitcher(mic_hint, enabled=not args.no_switch_mic, quiet=args.quiet)
    atexit.register(mic_switcher.restore)

    player = Player(args.device, args.rate, prebuffer_ms=args.prebuffer_ms)

    # 语音触发: 工牌控制帧 → 合成微信输入法语音快捷键 (§六十四)
    trigger = None
    if args.no_voice_trigger:
        print("[=] 语音触发已禁用 (--no-voice-trigger)")
    else:
        def keys_of(spec):
            table = MAC_KEYCODES if sys.platform == "darwin" else WIN_VK
            out = []
            for part in spec.split(","):
                p = part.strip().lower()
                if not p:
                    continue
                if p in table:
                    if table[p] is not None:
                        out.append(table[p])
                else:
                    try:
                        out.append(int(p, 0))   # 十进制或 0x 十六进制 VK 码 (如 0x09=Tab)
                    except ValueError:
                        sys.exit(f"[!] 无法解析按键 {p!r} (--voice-*: fn/space/ctrl/f1-f12 或数字)")
            return out
        ptt_keys = keys_of(args.voice_ptt_key)
        toggle_keys = keys_of(args.voice_toggle_key)
        if not ptt_keys and not toggle_keys:
            print("[!] 未配置语音组合键, 工牌语音控制帧将被忽略. Mac 默认 Fn/Fn+空格无需配置;"
                  " Windows 需先在微信输入法设置改绑快捷键, 再用 --voice-ptt-key/--voice-toggle-key 指定"
                  " (本机 WeType 3.0.0.37 实测: 按住说话=Ctrl+Win → --voice-ptt-key ctrl,win;"
                  " 启动语音输入=Ctrl+Shift+Win → --voice-toggle-key ctrl,shift,win)")
        else:
            if sys.platform == "darwin":
                mod_flag, mod_keys = 0, []
                for m in args.voice_mods.split(","):
                    m = m.strip().lower()
                    if not m:
                        continue
                    if m not in MOD_FLAGS:
                        sys.exit(f"[!] 未知修饰键 {m!r} (--voice-mods: fn/ctrl/alt/cmd/shift)")
                    mod_flag |= MOD_FLAGS[m]
                    # fn 本身就是 keycode 63 由 keys 携带; 其余修饰键补发物理按键事件更保真
                    if m != "fn":
                        mod_keys.append(MAC_KEYCODES[m])
                inj = MacInjector(mod_flag)
                try:
                    ax = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
                    ax.AXIsProcessTrusted.restype = ctypes.c_bool
                    if not ax.AXIsProcessTrusted():
                        print("[!] 辅助功能权限缺失 → 合成快捷键会被系统静默丢弃:"
                              " 系统设置→隐私和安全性→辅助功能→勾选启动本脚本的终端")
                except Exception:
                    pass
                trigger = VoiceTrigger(inj, mod_keys, ptt_keys, mod_keys, toggle_keys,
                                       mic_switcher=mic_switcher, quiet=args.quiet)
            else:
                inj = WinInjector()

                def split_combo(vks, global_mods):
                    """组合键以最后一个键为主键、其余为修饰键 (如 "ctrl,win" →
                    mods=[ctrl], keys=[win], 和弦在主键按下时成立); 只写一个键时
                    退回全局 --voice-mods (兼容旧写法 --voice-ptt-key 0x09 --voice-mods ctrl)."""
                    if len(vks) <= 1:
                        return list(global_mods), vks
                    return vks[:-1], vks[-1:]

                global_mods = keys_of(args.voice_mods)
                ptt_mods, ptt_k = split_combo(ptt_keys, global_mods)
                tgl_mods, tgl_k = split_combo(toggle_keys, global_mods)
                trigger = VoiceTrigger(inj, ptt_mods, ptt_k, tgl_mods, tgl_k,
                                       mic_switcher=mic_switcher, quiet=args.quiet)
            print(f"[+] 语音触发就绪: PTT={args.voice_ptt_key!r} "
                  f"长输入={args.voice_toggle_key!r} mods={args.voice_mods!r}")

    if args.relay:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 0))            # 临时端口, 中转按源地址回推音频
        sock.settimeout(0.05)
        sub_last = 0.0
        probe_last = 0.0
        rtt_ms = None
        ping_sent_at = None
        print(f"[+] 订阅模式: udp://{args.relay}:{args.port} [tag: {args.tag}] (SUB 每{SUB_EVERY:.0f}s)")
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", args.port))
        sock.settimeout(0.05)
        print(f"[+] LAN 模式: 收音 udp://0.0.0.0:{args.port}")

    # 探测口: LAN 模式=应答工牌 PING; relay 模式=主动 PING 中转测本跳 RTT
    psock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    psock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if args.relay:
        psock.bind(("0.0.0.0", 0))
        psock.settimeout(0)
    else:
        psock.bind(("0.0.0.0", args.ping_port))
        psock.settimeout(0)

    print("[+] 等待音频... (Ctrl-C 退出)")

    # 吸收网络突发抖动(默认接收缓冲偏小, 抖动峰值时来不及收就丢)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)

    pkts = 0
    total = 0
    src = None
    last_arrival = None
    jitter_sum = 0.0
    jitter_n = 0
    t0 = time.time()
    last_stat = t0
    last_data = t0
    gaps = 0          # 推流中 >100ms 无包的次数(链路抖动直达声卡的裂缝)
    in_gap = False

    try:
        while True:
            now = time.time()

            if args.relay:
                if now - sub_last >= SUB_EVERY or sub_last == 0:
                    sub_last = now
                    sub_payload = b"SUB" + token + (f":{args.tag}".encode("utf-8") if args.tag else b"")
                    try:
                        sock.sendto(sub_payload, (args.relay, args.port))
                    except OSError as e:
                        print(f"[!] SUB 发送失败(网络暂不可达,忽略): {e}", flush=True)
                if now - probe_last >= PROBE_EVERY or probe_last == 0:
                    probe_last = now
                    try:
                        ping_sent_at = time.time()
                        psock.sendto(b"PING" + struct.pack("<d", ping_sent_at),
                                     (args.relay, args.ping_port))
                    except OSError as e:
                        print(f"[!] PING 发送失败(网络暂不可达,忽略): {e}", flush=True)
                # 收 PONG
                try:
                    while True:
                        d, _ = psock.recvfrom(64)
                        if len(d) >= 12 and d[:4] == b"PONG":
                            try:
                                sent = struct.unpack("<d", d[4:12])[0]
                                rtt_ms = (time.time() - sent) * 1000
                            except (struct.error, ValueError):
                                rtt_ms = (time.time() - (ping_sent_at or now)) * 1000
                except (BlockingIOError, socket.timeout):
                    pass
                except Exception:
                    pass
            else:
                try:
                    while True:
                        d, a2 = psock.recvfrom(64)
                        if len(d) >= 12 and d[:4] == b"PING":
                            psock.sendto(b"PONG" + d[4:12], a2)
                except (BlockingIOError, socket.timeout):
                    pass
                except Exception:
                    pass

            # PCM 数据口 (控制帧走语音触发, 不喂声卡)
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                data = None
            if data is not None:
                now2 = time.time()
                head = data[:5]
                if head == b"TGTM1" and data[5:5 + len(token)] == token:
                    t = data[5 + len(token):].decode("utf-8", "ignore").lstrip("@")
                    print(f"[目标] 工牌目标主机 → {t}{' (本机)' if t == args.tag else ''}", flush=True)
                elif head in DICT_FRAMES and data[5:5 + len(token)] == token:
                    tail = data[5 + len(token):]
                    if tail.startswith(b"@") and tail[1:].decode("utf-8", "ignore").strip() != args.tag:
                        print(f"[目标] 忽略发往 {tail[1:].decode()} 的语音帧 (本机 tag={args.tag})", flush=True)
                    elif trigger:
                        trigger.submit(data)
                elif any(data.startswith(p) for p in SIGNAL_PREFIXES):
                    pass    # 信令/保活帧(LELE1/SUB_OK/PONG/PING/SRC/PNCH), 不进声卡不触发语音
                else:
                    if trigger:
                        trigger.on_audio()
                    if last_arrival is not None:
                        jitter_sum += abs((now2 - last_arrival) * 1000 - 32.0)
                        jitter_n += 1
                    last_arrival = now2
                    last_data = now2
                    if src is None or src != addr:
                        src = addr
                        print(f"[+] 音频源: {addr[0]}:{addr[1]}")
                    pkts += 1
                    total += len(data)
                    player.feed(data)

            player.health_check()

            now = time.time()
            # 推流中间隙检测: >100ms 无包即一次裂缝(微信输入法会听到断续)
            if trigger and trigger.is_streaming and now - last_data > 0.1:
                if not in_gap:
                    in_gap = True
                    gaps += 1
            else:
                in_gap = False
            if not args.quiet and now - last_stat >= 5:
                last_stat = now
                j = (jitter_sum / jitter_n) if jitter_n else 0.0
                el = now - t0
                silent = " [静默!]" if now - last_data > 2 else ""
                mode = f"中转RTT≈{rtt_ms:.0f}ms " if (args.relay and rtt_ms is not None) else ""
                print(f"[{el:6.0f}s] 收 {pkts} 包 {total/1024:.0f}KB "
                      f"({total*8/el/1024:.0f}kbps) {mode}到包抖动±{j:.1f}ms "
                      f"水位{player.level_ms():.0f}ms 欠载{player.underruns} 间隙{gaps}{silent}", flush=True)
            if now - last_data > 2:
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        el = time.time() - t0
        print(f"\n[=] 运行 {el:.0f}s: {pkts} 包, {total} 字节 PCM")
        player.close()


if __name__ == "__main__":
    main()
