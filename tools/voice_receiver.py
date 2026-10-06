#!/usr/bin/env python3
"""
乐乐语音桥 Mac 端接收器.

两种模式:
  1) LAN 直连(默认):  本机绑 UDP 9761 收工牌 PCM; 9762 应答工牌 PING.
  2) --relay HOST:    腾讯云中转订阅模式 —— 每 20s 向 HOST:9761 发 SUB+TOKEN,
                      收中转转发的 PCM; 每 5s PING HOST:9762 测本机到中转这一跳.
  音频 → BlackHole 2ch 虚拟声卡(微信输入法的"麦克风"), mono 复制立体声.

用法:
  python3 voice_receiver.py [--relay 124.221.187.167] [--token lele-6deb6d37]
                            [--device "BlackHole 2ch"] [--rate 16000] [--quiet]
Ctrl-C 退出并打印汇总. 后台托管用 voice_receiver.sh start|stop|status.
"""

import argparse
import socket
import sys
import time

try:
    import sounddevice as sd
except ImportError:
    sys.exit("缺少 sounddevice: pip3 install sounddevice")

TOKEN = b"lele-6deb6d37"
SUB_EVERY = 20.0
PROBE_EVERY = 5.0


def pick_output(name_hint):
    devices = sd.query_devices()
    if name_hint:
        for i, d in enumerate(devices):
            if d["max_output_channels"] > 0 and name_hint.lower() in d["name"].lower():
                return i, d["name"]
        print(f"[!] 未找到含 '{name_hint}' 的输出设备, 回退系统默认. 当前设备:")
        for i, d in enumerate(devices):
            if d["max_output_channels"] > 0:
                print(f"    [{i}] {d['name']} ({d['max_output_channels']}ch)")
    idx = sd.default.device[1]
    name = devices[idx]["name"] if isinstance(idx, int) else str(idx)
    return idx, name


class Player:
    """BlackHole 实时播放器: mono s16 复制为 stereo."""

    def __init__(self, device_idx, rate):
        self.rate = rate
        self.channels = 2
        self.stream = None
        self.q = bytearray()
        self._opened_at_default = False
        try:
            self.stream = sd.RawOutputStream(
                samplerate=rate, channels=self.channels, dtype="int16",
                device=device_idx, blocksize=0)
        except Exception as e:
            default_rate = int(sd.query_devices(device_idx)["default_samplerate"])
            mult = max(1, round(default_rate / rate))
            self.rate = default_rate
            self.mult = mult
            self._opened_at_default = True
            self.stream = sd.RawOutputStream(
                samplerate=default_rate, channels=self.channels, dtype="int16",
                device=device_idx, blocksize=0)
            print(f"[!] 以 {rate}Hz 打开设备失败, 降级 {default_rate}Hz x{mult}")
        else:
            self.mult = 1
        self.stream.start()

    def feed(self, mono: bytes):
        out = bytearray()
        if self.mult == 1:
            for i in range(0, len(mono) - 1, 2):
                out += mono[i:i + 2] * 2   # 每个样本复制 L+R
        else:
            for i in range(0, len(mono) - 1, 2):
                out += mono[i:i + 2] * 2 * self.mult
        self.q += out

    def pump(self):
        need = int(self.rate * self.channels * 2 * 0.01)  # 10ms
        while len(self.q) >= need:
            frame = bytes(self.q[:need])
            del self.q[:need]
            self.stream.write(frame)

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="BlackHole 2ch")
    ap.add_argument("--port", type=int, default=9761, help="LAN 模式监听端口")
    ap.add_argument("--relay", default=None, help="中转服务器公网 IP(订阅模式)")
    ap.add_argument("--token", default=TOKEN.decode())
    ap.add_argument("--ping-port", type=int, default=9762)
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    token = args.token.encode()

    dev_idx, dev_name = pick_output(args.device)
    print(f"[+] 输出设备: {dev_name}")
    player = Player(dev_idx, args.rate)

    if args.relay:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 0))            # 临时端口, 中转按源地址回推音频
        sock.settimeout(0.05)
        sub_last = 0.0
        probe_last = 0.0
        rtt_ms = None
        print(f"[+] 订阅模式: udp://{args.relay}:{args.port} (SUB 每{SUB_EVERY:.0f}s)")
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

    print(f"[+] 音频 → {dev_name} (s16le/{args.rate}/mono)")
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
                    sock.sendto(b"SUB" + token, (args.relay, args.port))
                if now - probe_last >= PROBE_EVERY or probe_last == 0:
                    probe_last = now
                    psock.sendto(b"PING" + b"\x00" * 8, (args.relay, args.ping_port))
                # 收 PONG
                try:
                    while True:
                        d, _ = psock.recvfrom(64)
                        if len(d) >= 12 and d[:4] == b"PONG":
                            rtt_ms = (time.time() - now) * 1000
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

            # PCM 数据口
            try:
                data, addr = sock.recvfrom(4096)
                now2 = time.time()
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
            except socket.timeout:
                pass

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
