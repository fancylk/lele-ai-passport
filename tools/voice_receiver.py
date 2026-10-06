#!/usr/bin/env python3
"""
乐乐语音桥 Mac 端接收器.
  UDP :9761  ← 16kHz/16bit/mono PCM (工牌常开推流) → BlackHole 虚拟声卡实时播放
  UDP :9762  ← PING 探测包 → 原样回 PONG (工牌据此算 RTT 并上屏)

用法:
  python3 voice_receiver.py [--device "BlackHole 2ch"] [--port 9761]
                            [--ping-port 9762] [--rate 16000] [--quiet]
Ctrl-C 退出并打印汇总. 也可用 voice_receiver.sh start|stop|status 后台托管.
"""

import argparse
import socket
import struct
import sys
import time

try:
    import sounddevice as sd
except ImportError:
    sys.exit("缺少 sounddevice: pip3 install sounddevice")

BYTES_PER_FRAME = 2  # s16le mono → 播放时复制成双声道


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
        self.q = bytearray()      # 待播字节 (stereo s16)
        self.underruns = 0
        self._opened_at_default = False
        try:
            self.stream = sd.RawOutputStream(
                samplerate=rate, channels=self.channels, dtype="int16",
                device=device_idx, blocksize=0)
        except Exception as e:
            # BlackHole 若不吃 16k, 退回设备默认率 + 3 倍采样复制 (16k→48k)
            print(f"[!] 以 {rate}Hz 打开设备失败: {e}")
            default_rate = int(sd.query_devices(device_idx)["default_samplerate"])
            mult = max(1, round(default_rate / rate))
            self.rate = default_rate
            self.mult = mult
            self._opened_at_default = True
            self.stream = sd.RawOutputStream(
                samplerate=default_rate, channels=self.channels, dtype="int16",
                device=device_idx, blocksize=0)
            print(f"[+] 降级: 设备 {default_rate}Hz, {mult}x 粗重采样")
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
        """按实时速率消费缓冲 (粗略节拍, BlackHole 缓冲可吸收抖动)."""
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
    ap.add_argument("--port", type=int, default=9761)
    ap.add_argument("--ping-port", type=int, default=9762)
    ap.add_argument("--rate", type=int, default=16000)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    dev_idx, dev_name = pick_output(args.device)
    print(f"[+] 输出设备: {dev_name}")
    player = Player(dev_idx, args.rate)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.05)

    psock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    psock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    psock.bind(("0.0.0.0", args.ping_port))
    psock.settimeout(0)

    print(f"[+] 收音: udp://0.0.0.0:{args.port} (s16le/{args.rate}/mono)")
    print(f"[+] 探测: udp://0.0.0.0:{args.ping_port} (PING→PONG)")
    print("[+] 等待工牌音频... (Ctrl-C 退出)")

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
            # PCM 数据口
            try:
                data, addr = sock.recvfrom(4096)
                now = time.time()
                if last_arrival is not None:
                    jitter_sum += abs((now - last_arrival) * 1000 - 32.0)
                    jitter_n += 1
                last_arrival = now
                last_data = now
                if src is None or src != addr:
                    src = addr
                    print(f"[+] 音频源: {addr[0]}:{addr[1]}")
                pkts += 1
                total += len(data)
                player.feed(data)
            except socket.timeout:
                pass

            # 探测口
            try:
                while True:
                    data, addr = psock.recvfrom(64)
                    if len(data) >= 10 and data[:4] == b"PING":
                        psock.sendto(b"PONG" + data[4:10], addr)
            except (BlockingIOError, socket.timeout):
                pass
            except Exception:
                pass

            player.pump()

            now = time.time()
            if not args.quiet and now - last_stat >= 5:
                last_stat = now
                j = (jitter_sum / jitter_n) if jitter_n else 0.0
                el = now - t0
                silent = " [静默!]" if now - last_data > 2 else ""
                print(f"[{el:6.0f}s] 收 {pkts} 包 {total/1024:.0f}KB "
                      f"({total*8/el/1024:.0f}kbps) 到包抖动±{j:.1f}ms "
                      f"缓冲{len(player.q)/1024:.0f}KB{silent}")
            # 无数据时避免 CPU 空转
            if now - last_data > 2:
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        el = time.time() - t0
        print(f"\n[=] 运行 {el:.0f}s: {pkts} 包, {total} 字节 PCM, "
              f"欠载 {player.underruns} 次")
        player.close()


if __name__ == "__main__":
    main()
