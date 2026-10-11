#!/usr/bin/env python3
"""自检: 合成微信输入法语音快捷键, 验证本机注入链路是否通 (§六十四).

必须在"将来运行 voice_receiver.py 的同一个终端环境"里跑 (通常是 Terminal.app,
需在 系统设置→隐私与安全性→辅助功能 勾选 Terminal). 在其它无授权的上下文
(如后台守护的子进程) 里合成事件会被系统静默丢弃 —— AXIsProcessTrusted=True
也不代表能注入, 以面板是否出现为准.

用法 (Mac):
  python3 spike_weetype_hotkey.py probe     # 查辅助功能授权状态
  python3 spike_weetype_hotkey.py toggle    # Fn+空格 轻击 → 微信输入法长输入面板应开/关
  python3 spike_weetype_hotkey.py ptt [ms]  # Fn 按住 ms 再松开 (默认 1500) → 说话应上屏
  python3 spike_weetype_hotkey.py fnnoflag  # 对照: 只发 keycode 63 不带 Fn flag
选项:
  --source hid|session|private   事件源 (默认 hid = 最接近物理按键;
                                 private 源可绕过部分系统级消费方)

判读:
  toggle/ptt 无反应 → 先确认微信输入法是当前输入源; 仍无反应 = 合成 Fn 被过滤,
  兜底: 在微信输入法设置里把两语音快捷键改绑普通组合键(如 F9), 然后
  voice_receiver.py 加 --voice-ptt-key 101 --voice-mods "" 传新键.
"""
import ctypes
import ctypes.util
import sys
import time

cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
ax = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))

cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
cg.CGEventSetSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
cg.CGEventSourceCreate.restype = ctypes.c_void_p
cg.CGEventSourceCreate.argtypes = [ctypes.c_uint32]
cf.CFRelease.argtypes = [ctypes.c_void_p]
ax.AXIsProcessTrusted.restype = ctypes.c_bool

kCGHIDEventTap = 0
SRC = {"hid": 1, "session": 0, "private": 2}   # kCGEventSourceState*
FLAG_FN = 0x00400000                            # kCGEventFlagMaskSecondaryFn
K_FN = 63                                       # Fn/Globe = 微信输入法 PTT 键
K_SPACE = 49                                    # 长输入 = Fn+空格


class Injector:
    """与 voice_receiver.py 的 MacInjector 同款 (改参数时两边保持一致)."""

    def __init__(self, source="hid", flag=FLAG_FN):
        self.tap_id = kCGHIDEventTap
        self.flag = flag
        self.src = cg.CGEventSourceCreate(SRC[source]) if source != "hid" else None

    def _post(self, keycode, down):
        ev = cg.CGEventCreateKeyboardEvent(None, keycode, down)
        if self.flag:
            cg.CGEventSetFlags(ev, self.flag)
        if self.src:
            cg.CGEventSetSource(ev, self.src)
        cg.CGEventPost(self.tap_id, ev)
        cf.CFRelease(ev)

    def combo(self, keycodes, down):
        for k in (keycodes if down else list(reversed(keycodes))):
            self._post(k, down)

    def tap(self, keycodes, gap=0.04):
        self.combo(keycodes, True)
        time.sleep(gap)
        self.combo(keycodes, False)


def main():
    args = sys.argv[1:]
    trusted = bool(ax.AXIsProcessTrusted())
    print(f"[*] AXIsProcessTrusted = {trusted}"
          f"  (False 时注入必失败; True 也不保证, 以面板是否出现为准)")
    if not args or args[0] == "probe":
        print("[*] 提示: 盯着屏幕, 微信输入法需是当前输入源")
        return
    src = "hid"
    if "--source" in args:
        i = args.index("--source")
        src = args[i + 1]
        args = args[:i] + args[i + 2:]
    inj = Injector(src)
    mode = args[0]
    if mode == "ptt":
        ms = int(args[1]) if len(args) > 1 else 1500
        print(f"[*] Fn 按住 {ms}ms ... (应看到微信输入法语音面板, 对它说话)")
        inj.combo([K_FN], True)
        time.sleep(ms / 1000)
        inj.combo([K_FN], False)
        print("[*] Fn 已松开 (识别应结束并上屏)")
    elif mode == "toggle":
        print("[*] Fn+空格 轻击 ... (微信输入法长输入面板应切换)")
        inj.tap([K_FN, K_SPACE])
        print("[*] 完成")
    elif mode == "fnnoflag":
        print("[*] keycode 63 无 flag 轻击 (对照实验)")
        saved = inj.flag
        inj.flag = 0
        inj.tap([K_FN])
        inj.flag = saved
    else:
        sys.exit(f"未知模式 {mode}")


if __name__ == "__main__":
    main()
