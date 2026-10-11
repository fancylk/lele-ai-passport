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
  Mac 注入需辅助功能权限: 系统设置→隐私与安全性→辅助功能→勾选启动本脚本的终端.
  --no-voice-trigger 关闭. 自检工具: tools/spike_weetype_hotkey.py

Windows 加固(2026-10-07, tyz86): 音频端点可能被系统临时失效(驱动装完重枚举/
睡眠唤醒/音频服务重启), 症状=PortAudioError "There is no driver installed" /
MME error 6. 现在写失败自动按设备名重扫重连; 设备不存在时等待其出现,
不再崩溃退出, 也绝不回落默认扬声器(避免语音外放).

用法:
  python3 voice_receiver.py [--relay 124.221.187.167] [--token lele-6deb6d37]
                            [--device "CABLE Input"] [--rate 16000] [--quiet]
Ctrl-C 退出并打印汇总. 后台托管用 voice_receiver.sh start|stop.
"""

import argparse
import ctypes
import ctypes.util
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
    微信输入法语音快捷键需在其设置改绑普通组合键后用 --voice-* 传入."""

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self):
        self.user32 = ctypes.windll.user32

    def _key(self, vk, down):
        inp = _WinINPUT(self.INPUT_KEYBOARD)
        inp.u.ki = _WinKEYBDINPUT(vk, 0, 0 if down else self.KEYEVENTF_KEYUP, 0, None)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_WinINPUT))

    def hold(self, mods, keys):
        for k in mods + keys:
            self._key(k, True)

    def release(self, mods, keys):
        for k in list(reversed(keys)) + list(reversed(mods)):
            self._key(k, False)

    def tap(self, mods, keys, gap=0.04):
        self.hold(mods, keys)
        time.sleep(gap)
        self.release(mods, keys)


class VoiceTrigger:
    """控制帧 → 快捷键注入. 后台单线程串行执行, 绝不阻塞收流循环."""

    DEDUP_WINDOW = 0.3   # 固件每事件连发 3 遍(间隔 30ms), 同帧 300ms 内视为重发

    def __init__(self, inj, ptt, toggle, mods, quiet=False):
        self.inj = inj
        self.ptt, self.toggle, self.mods = ptt, toggle, mods
        self.quiet = quiet
        self.q = queue.Queue()
        self._last_frame, self._last_t = None, 0.0
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, frame):
        action = DICT_FRAMES.get(frame[:5])
        if action is None:
            return False
        now = time.time()
        if frame == self._last_frame and now - self._last_t < self.DEDUP_WINDOW:
            return True
        self._last_frame, self._last_t = frame, now
        self.q.put(action)
        return True

    def _worker(self):
        while True:
            action = self.q.get()
            try:
                if action in ("dict_on", "dict_off"):
                    self.inj.tap(self.mods, self.toggle)
                    if not self.quiet:
                        print(f"[🎙] 长输入会话{'开' if action == 'dict_on' else '关'}"
                              f" → 合成 {self.mods + self.toggle}", flush=True)
                elif action == "ptt_down":
                    self.inj.hold(self.mods, self.ptt)
                    if not self.quiet:
                        print("[🎙] PTT 按下 (按住说话)", flush=True)
                elif action == "ptt_up":
                    self.inj.release(self.mods, self.ptt)
                    if not self.quiet:
                        print("[🎙] PTT 抬起 (识别结束, 文字应已上屏)", flush=True)
            except Exception as e:
                print(f"[!] 快捷键注入失败(不影响收流): {e}", flush=True)


class Player:
    """虚拟声卡实时播放器: mono s16 复制为 stereo.

    按设备名(子串, 不区分大小写)解析输出设备; 每次打开前重扫设备列表,
    这样端点重枚举后索引变化也能找回. 指定设备不存在 → 等待, 不回落默认.
    """

    RETRY_EVERY = 2.0  # 重连节流(秒)

    def __init__(self, name_hint, rate):
        self.name_hint = name_hint
        self.rate = rate
        self.channels = 2
        self.q = bytearray()
        self.mult = 1
        self.stream = None
        self._opened_at_default = False
        self._last_try = 0.0
        if not self._open():
            print(f"[!] 未找到输出设备 '{name_hint}', 每{self.RETRY_EVERY:.0f}s 自动重试"
                  " (不会回落到默认扬声器)", flush=True)

    def _resolve(self):
        """按名字子串找输出设备索引; 找不到返回 None."""
        if not self.name_hint:
            return None
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and self.name_hint.lower() in d["name"].lower():
                return i
        return None

    def _open(self):
        """解析设备并打开输出流; 16k 打不开时按设备默认采样率降级. 失败返回 False."""
        idx = self._resolve()
        if idx is None:
            self.stream = None
            return False
        name = sd.query_devices(idx)["name"]
        try:
            self.stream = sd.RawOutputStream(
                samplerate=self.rate, channels=self.channels, dtype="int16",
                device=idx, blocksize=0)
        except Exception:
            try:
                default_rate = int(sd.query_devices(idx)["default_samplerate"])
                self.rate = default_rate
                self.mult = max(1, round(default_rate / 16000))
                self._opened_at_default = True
                self.stream = sd.RawOutputStream(
                    samplerate=default_rate, channels=self.channels, dtype="int16",
                    device=idx, blocksize=0)
                print(f"[!] 降级 {default_rate}Hz x{self.mult} 打开", flush=True)
            except Exception as e:
                self.stream = None
                print(f"[!] 输出设备 #{idx} {name!r} 打不开: {e}", flush=True)
                return False
        self.stream.start()
        print(f"[+] 音频 → {name} (s16le/{self.rate}/mono)", flush=True)
        return True

    def feed(self, mono: bytes):
        out = bytearray()
        if self.mult == 1:
            for i in range(0, len(mono) - 1, 2):
                out += mono[i:i + 2] * 2   # 每个样本复制 L+R
        else:
            for i in range(0, len(mono) - 1, 2):
                out += mono[i:i + 2] * 2 * self.mult
        self.q += out

    def _reopen(self):
        """端点失效后的自动恢复: 关旧流, 限频重试, 丢弃积压(实时语音旧数据无意义)."""
        self.close()
        self.q.clear()
        now = time.time()
        if now - self._last_try < self.RETRY_EVERY:
            return
        self._last_try = now
        if self._open():
            print("[+] 输出设备已恢复", flush=True)

    def pump(self):
        if self.stream is None:
            self._reopen()
            return
        need = int(self.rate * self.channels * 2 * 0.01)  # 10ms
        while len(self.q) >= need:
            frame = bytes(self.q[:need])
            del self.q[:need]
            try:
                self.stream.write(frame)
            except (sd.PortAudioError, OSError) as e:
                print(f"[!] 输出设备异常, 转入自动重连: {e}", flush=True)
                self._reopen()
                return

    def close(self):
        try:
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
    ap.add_argument("--quiet", action="store_true")
    if sys.platform == "darwin":
        default_ptt, default_toggle, default_mods = "63", "63,49", "fn"
    else:
        # Windows 无 Fn 虚拟键: 须在微信输入法设置改绑普通组合键后显式指定
        default_ptt = default_toggle = default_mods = ""
    ap.add_argument("--no-voice-trigger", action="store_true",
                    help="忽略工牌语音控制帧(不合成微信输入法语音快捷键)")
    ap.add_argument("--voice-ptt-key", default=default_ptt,
                    help="按住说话组合键, 逗号分隔 (Mac 默认 63=Fn; fn/space/ctrl/f1-f12 或数字)")
    ap.add_argument("--voice-toggle-key", default=default_toggle,
                    help="长输入开关组合键 (Mac 默认 63,49=Fn+空格)")
    ap.add_argument("--voice-mods", default=default_mods,
                    help="组合键修饰键 (Mac 默认 fn; ctrl/alt/cmd/shift)")
    args = ap.parse_args()
    token = args.token.encode()

    player = Player(args.device, args.rate)

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
                elif p.isdigit():
                    out.append(int(p))
                else:
                    sys.exit(f"[!] 无法解析按键 {p!r} (--voice-*: fn/space/ctrl/f1-f12 或数字)")
            return out
        ptt_keys = keys_of(args.voice_ptt_key)
        toggle_keys = keys_of(args.voice_toggle_key)
        if not ptt_keys and not toggle_keys:
            print("[!] 未配置语音组合键, 工牌语音控制帧将被忽略. Mac 默认 Fn/Fn+空格无需配置;"
                  " Windows 需先在微信输入法设置改绑快捷键, 再用 --voice-ptt-key/--voice-toggle-key 指定")
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
                              " 系统设置→隐私与安全性→辅助功能→勾选启动本脚本的终端")
                except Exception:
                    pass
            else:
                inj = WinInjector()
                mod_keys = keys_of(args.voice_mods)
            trigger = VoiceTrigger(inj, ptt_keys, toggle_keys, mod_keys, quiet=args.quiet)
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

    pkts = 0
    total = 0
    src = None
    last_arrival = None
    jitter_sum = 0.0
    jitter_n = 0
    t0 = time.time()
    last_stat = t0
    last_data = t0

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
                if head in DICT_FRAMES and data[5:5 + len(token)] == token:
                    if trigger:
                        trigger.submit(data)
                elif head == b"LELE1":
                    pass    # LAN 模式直连会收到工牌握手, 忽略(不喂声卡)
                else:
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

            player.pump()

            now = time.time()
            if not args.quiet and now - last_stat >= 5:
                last_stat = now
                j = (jitter_sum / jitter_n) if jitter_n else 0.0
                el = now - t0
                silent = " [静默!]" if now - last_data > 2 else ""
                mode = f"中转RTT≈{rtt_ms:.0f}ms " if (args.relay and rtt_ms is not None) else ""
                print(f"[{el:6.0f}s] 收 {pkts} 包 {total/1024:.0f}KB "
                      f"({total*8/el/1024:.0f}kbps) {mode}到包抖动±{j:.1f}ms "
                      f"缓冲{len(player.q)/1024:.0f}KB{silent}", flush=True)
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
