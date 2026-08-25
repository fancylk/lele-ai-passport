#!/usr/bin/env python3
"""
Virtual AI Passport Simulator (UDP edition)
Simulates the ESP32-C3 firmware app_lele_guide.c behavior over UDP:
  STATE_GUIDE -> (hold UP) voice_audio_start + PCM chunks -> voice_audio_end
  -> STATE_PROCESSING (waits proposal) -> shows proposal
  -> OK button = confirm_task -> waits task_done -> back to STATE_GUIDE
"""

import socket
import sys
import time
import json
import struct
import math
import wave
import io
import random

BRIDGE_IP = sys.argv[1] if len(sys.argv) > 1 else "124.221.187.167"
UDP_PORT = 8888
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512
MAX_REC_SEC = 4

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.2)
sock.bind(("0.0.0.0", 19950))  # dedicated reply port; bridge replies to source addr

def log(*a):
    print(f"[SIM] {' '.join(str(x) for x in a)}", flush=True)

def send_json(pkt):
    data = (json.dumps(pkt, ensure_ascii=False) + "\n").encode("utf-8")
    sock.sendto(data, (BRIDGE_IP, UDP_PORT))
    log("->", pkt.get("type"), {k: v for k, v in pkt.items() if k != "type"})

def synth_speech_beep(duration=2.0, freq=440):
    """Synthesize a 'speech-like' PCM: tone + AM modulation (simulating voice recording)."""
    n = int(SAMPLE_RATE * duration)
    pcm = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        env = 0.5 * (1 + math.sin(2 * math.pi * 3 * t))  # speech envelope ~3Hz
        v = env * math.sin(2 * math.pi * freq * t)
        pcm += struct.pack("<h", int(v * 12000))
    return bytes(pcm)

def hold_up_and_record():
    send_json({"type": "voice_audio_start"})
    pcm = synth_speech_beep(min(MAX_REC_SEC, 2.5))
    total = 0
    for off in range(0, len(pcm), CHUNK_SAMPLES * 2):
        chunk = pcm[off:off + CHUNK_SAMPLES * 2]
        sock.sendto(chunk, (BRIDGE_IP, UDP_PORT))
        total += len(chunk)
        time.sleep(0.03)  # ~real-time pacing
    send_json({"type": "voice_audio_end"})
    log(f"audio sent: {total} bytes PCM")

def wait_proposal(timeout=60):
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    pkt = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if pkt.get("type") == "proposal":
                    log("<- PROPOSAL:", pkt.get("title"), "|", pkt.get("desc"), "|", pkt.get("quiz"))
                    return pkt
                if pkt.get("type") == "task_done":
                    log("<- TASK_DONE (early):", pkt.get("message"))
                    return None
        except socket.timeout:
            continue
    log("!! no proposal within timeout")
    return None

def wait_task_done(timeout=600):
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    pkt = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if pkt.get("type") == "task_progress":
                    log(f"<- PROGRESS [{pkt.get('elapsed_min')}min] {pkt.get('stage')} ({pkt.get('progress')}%)")
                    continue
                if pkt.get("type") == "task_done":
                    log("<- TASK_DONE:", pkt.get("title"), pkt.get("message"))
                    return pkt
        except socket.timeout:
            continue
    log("!! no task_done within timeout")
    return None

def main():
    log(f"Virtual Passport targeting {BRIDGE_IP}:{UDP_PORT}")
    log("STATE=GUIDE (16 spots browse)")

    # Step 1: hold UP, stream audio
    log("USER holds UP button ...")
    hold_up_and_record()
    log("USER releases UP button")

    # Step 2: wait for proposal from bridge (MiMo ASR + LLM)
    prop = wait_proposal()
    if not prop:
        log("E2E FAILED at proposal stage")
        return 1

    # Step 3: user presses OK to confirm
    time.sleep(1)
    send_json({"type": "confirm_task", "title": prop.get("title", ""), "desc": prop.get("desc", ""), "quiz": prop.get("quiz", ""), "user_text": prop.get("user_text", "")})

    # Step 4: wait task_done (git push + webhook deploy)
    done = wait_task_done()
    if not done:
        log("E2E FAILED at deploy stage")
        return 1

    log("E2E PASS: voice -> proposal -> confirm -> published")
    return 0

if __name__ == "__main__":
    sys.exit(main())
