#!/usr/bin/env python3
"""抖动压力测试: 向 LAN 模式接收器(9761)灌 TTS 语音, 同时录 CABLE Output,
统计录音里 >40ms 的静音裂缝, 与无抖动参照对比 —— 验证播放器预缓冲/伺服
是否把网络抖动挡在声卡之外.

模拟方式: 随机游走发送延迟(限幅 0..250ms), 平均码率不变, 包"攒一下涌一下"
与真实网络抖动一致.

用法: 先启动接收器: python voice_receiver.py --device "CABLE Input" --no-voice-trigger
      python spike_jitter_test.py ref   # 无抖动参照
      python spike_jitter_test.py jit   # 注入抖动
"""

import socket
import sys
import time
import wave

import numpy as np
import sounddevice as sd

TOKEN = b"lele-6deb6d37"
DST = ("127.0.0.1", 9761)
REC_DEV = 2          # CABLE Output
LOSS_RATE = 0.02     # 随机丢包率(jit 模式)


def load_pcm(path):
    r = wave.open(path)
    raw = np.frombuffer(r.readframes(r.getnframes()), dtype=np.int16).astype(np.float64)
    sr = r.getframerate()
    t = np.arange(0, len(raw) / sr, 1 / 16000)
    return (np.interp(t, np.arange(len(raw)) / sr, raw) * 0.9).astype(np.int16).tobytes()


def analyze(rec):
    sig = rec[:, 0].astype(np.float64) / 32768.0
    loud = np.abs(sig) > 0.01
    if not loud.any():
        return None
    a, b = np.argmax(loud), len(loud) - np.argmax(loud[::-1])
    region = sig[a:b]
    silent = np.abs(region) < 0.005
    n = int(48000 * 0.04)          # 40ms
    # 向量化统计连续静音段
    padded = np.zeros(len(silent) + 2, dtype=np.int8)
    padded[1:-1] = silent
    d = np.diff(padded)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    runs = ends - starts
    gaps = int((runs >= n).sum())
    return len(region) / 48000.0, gaps, int(silent.sum()) / 48.0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "jit"
    tts = load_pcm(r"D:\CMCC\lele-voice\tools\tts_test.wav")
    pcm = tts * 3
    total_t = len(pcm) / 2 / 16000 + 2
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rng = np.random.default_rng(42)

    rec = sd.rec(int(48000 * total_t), samplerate=48000, channels=1,
                 dtype="int16", device=REC_DEV)
    print(f"[{mode}] streaming {len(pcm)/2/16000:.1f}s ...", flush=True)
    delay = 0.0
    start = time.time()
    i = 0
    while i < len(pcm) - 1024:
        if mode == "jit":
            delay += rng.uniform(-0.04, 0.04)
            delay = min(0.25, max(0.0, delay))
        target = start + (i // 1024) * 0.032 + delay
        now = time.time()
        if target > now:
            time.sleep(target - now)
        if mode != "jit" or rng.random() > LOSS_RATE:
            s.sendto(pcm[i:i + 1024], DST)
        i += 1024
    sd.wait()
    r = analyze(rec)
    if r is None:
        print("FAIL: 录音全静音")
        return
    dur, gaps, silent_ms = r
    print(f"[{mode}] 语音区 {dur:.1f}s, 静音裂缝(>40ms): {gaps} 次, "
          f"静音总时长 {silent_ms:.0f}ms (含 TTS 天然句间停顿)")


if __name__ == "__main__":
    main()
