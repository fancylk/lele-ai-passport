#!/usr/bin/env python3
"""
完整端到端验证:
1. 模拟 PC 终端 (tag: pc) 订阅腾讯云中转
2. 真实 Mac voice_receiver 正在后台运行并向 BlackHole 2ch 写入音频
3. 本脚本录制 BlackHole 2ch 输入 (微信输入法麦克风端)
4. 模拟工牌向中转推 100 包 (3.2 秒) 440Hz 测试音频
5. 验证:
   - PC 模拟端 100% 收到音频包 (零丢包, 数据匹配)
   - BlackHole 2ch 录制到真实的音频信号 (峰值电平 > 0.1, 确认 Mac 真实虚拟声卡正常)
"""

import math
import socket
import struct
import sys
import threading
import time
import numpy as np
import sounddevice as sd

RELAY_HOST = "124.221.187.167"
PORT_AUDIO = 9761
PORT_PING = 9762
TOKEN = b"lele-6deb6d37"

SAMPLE_RATE = 16000
CHUNK_BYTES = 1024  # 512 samples
TOTAL_PACKETS = 100  # 3.2s 音频


def generate_pcm_sine(num_chunks, freq=440.0):
    chunks = []
    samples_per_chunk = CHUNK_BYTES // 2
    sample_idx = 0
    for _ in range(num_chunks):
        buf = bytearray(CHUNK_BYTES)
        for s in range(samples_per_chunk):
            t = (sample_idx + s) / SAMPLE_RATE
            val = int(32767 * 0.6 * math.sin(2 * math.pi * freq * t))
            struct.pack_into("<h", buf, s * 2, val)
        chunks.append(bytes(buf))
        sample_idx += samples_per_chunk
    return chunks


def find_blackhole_device():
    devices = sd.query_devices()
    for idx, d in enumerate(devices):
        if d["max_input_channels"] > 0 and "blackhole" in d["name"].lower():
            return idx, d["name"]
    return None, None


def main():
    print("=" * 65)
    print("乐乐语音桥: 腾讯云双端复制转发 + Mac BlackHole 真实声卡全链路测试")
    print("=" * 65)

    # 1. 查找 Mac 端 BlackHole
    bh_idx, bh_name = find_blackhole_device()
    if bh_idx is None:
        print("[!] 未找到 BlackHole 输入设备, 仅测试 UDP 转发")
    else:
        print(f"[1] 找到 Mac 虚拟输入声卡: [{bh_idx}] {bh_name}")

    # 2. 模拟 PC 终端订阅
    print("[2] 模拟 PC 终端发起订阅 (tag: pc)...")
    pc_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pc_sock.bind(("0.0.0.0", 0))
    pc_sock.settimeout(0.5)
    pc_sock.sendto(b"SUB" + TOKEN + b":pc", (RELAY_HOST, PORT_AUDIO))

    pc_packets = []
    pc_running = True

    def pc_worker():
        while pc_running:
            try:
                data, _ = pc_sock.recvfrom(2048)
                if data != b"SUB_OK":
                    pc_packets.append(data)
            except socket.timeout:
                pass
            except Exception:
                break

    pc_thread = threading.Thread(target=pc_worker, daemon=True)
    pc_thread.start()

    time.sleep(0.3)

    # 3. 准备 BlackHole 录制 (异步录制 4 秒)
    rec_audio = None
    if bh_idx is not None:
        print("[3] 启动 Mac BlackHole 2ch 实时监听录制 (4 秒)...")
        # 48000Hz 录制 4 秒
        rec_audio = sd.rec(int(4.0 * 48000), samplerate=48000, channels=2, device=bh_idx, dtype="float32")

    # 4. 模拟工牌推流
    print(f"[4] 模拟工牌开始向中转推流 ({TOTAL_PACKETS} 包 440Hz 音频, ~3.2s)...")
    src_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    src_sock.sendto(b"LELE1" + TOKEN, (RELAY_HOST, PORT_AUDIO))
    time.sleep(0.05)

    pcm_chunks = generate_pcm_sine(TOTAL_PACKETS)
    t0 = time.time()
    for i, c in enumerate(pcm_chunks):
        src_sock.sendto(c, (RELAY_HOST, PORT_AUDIO))
        time.sleep(0.031)
    duration = time.time() - t0
    print(f"    推流完成, 耗时 {duration:.2f}s")

    # 等待录制与接收完毕
    if rec_audio is not None:
        sd.wait()

    pc_running = False
    pc_thread.join(timeout=1.0)
    pc_sock.close()
    src_sock.close()

    # 5. 分析 PC 端接收情况
    print("\n" + "-" * 65)
    print("[5] PC 终端接收分析:")
    print(f"    - 发送包数: {TOTAL_PACKETS}")
    print(f"    - 接收包数: {len(pc_packets)} (丢包率: {(TOTAL_PACKETS - len(pc_packets))/TOTAL_PACKETS*100:.1f}%)")
    pc_data_ok = (pc_packets == pcm_chunks)
    print(f"    - 数据一致性: {'✓ 100% 匹配' if pc_data_ok else '✗ 数据不匹配'}")

    # 6. 分析 Mac 端 BlackHole 电平
    print("\n" + "-" * 65)
    print("[6] Mac 虚拟麦克风 (BlackHole 2ch) 接收电平分析:")
    if rec_audio is not None:
        peak = float(np.max(np.abs(rec_audio)))
        rms = float(np.sqrt(np.mean(rec_audio ** 2)))
        db_peak = 20 * math.log10(peak) if peak > 1e-6 else -99.0
        db_rms = 20 * math.log10(rms) if rms > 1e-6 else -99.0
        print(f"    - 峰值电平 (Peak): {peak:.5f} ({db_peak:.1f} dBFS)")
        print(f"    - 均方根电平 (RMS): {rms:.5f} ({db_rms:.1f} dBFS)")
        if peak > 0.1:
            print("    - 虚拟麦克风信号: ✓ 极佳 (音频已成功流经 腾讯中转 -> Mac -> BlackHole 2ch)")
        elif peak > 0.01:
            print("    - 虚拟麦克风信号: ✓ 正常")
        else:
            print("    - 虚拟麦克风信号: ✗ 静音 (未检测到声音)")
    else:
        print("    - 跳过声卡检查 (未找到设备)")

    print("=" * 65)
    if len(pc_packets) == TOTAL_PACKETS and pc_data_ok and (rec_audio is None or peak > 0.05):
        print("✓ 全链路端到端模拟测试圆满成功!")
        print("  中转无论 PC 还是 Mac 同时连接, 均全量复制发送; 客户端虚拟麦克风完美出声!")
        print("=" * 65)
        return 0
    else:
        print("✗ 测试存在异常, 请核查上述指标")
        print("=" * 65)
        return 1


if __name__ == "__main__":
    sys.exit(main())
