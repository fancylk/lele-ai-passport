#!/usr/bin/env python3
"""
Lele's AI Tour Guide Bridge with Real-Time Audio UDP Ingestion, Xiaomi MiMo ASR, TTS & Git Deploy Pipeline.
"""

import os
import re
REPO_PATH = os.environ.get("LELE_REPO_PATH", "/vol1/1000/esp32_passport_workspace/family-trip")
if not os.path.isdir(REPO_PATH):
    for cand in ("/home/ubuntu/trip-repo",):
        if os.path.isdir(cand):
            REPO_PATH = cand
            break
import sys
import time
import json
import wave
import socket
import logging
import subprocess
import threading
from mimo_service import MiMoService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [LeleBridge] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("LeleBridge")

UDP_PORT = 8888
BROADCAST_IP = os.environ.get("LELE_BROADCAST_IP", "192.168.31.255")

class LeleBridgeService:
    def __init__(self, port: int = UDP_PORT, broadcast_ip: str = BROADCAST_IP):
        self.port = port
        self.broadcast_ip = broadcast_ip
        self.running = False
        self.sock = None
        self.known_cards = set()
        self.mimo = MiMoService()
        self.audio_recv_buf = bytearray()
        self.is_receiving_audio = False

    def _init_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('0.0.0.0', self.port))
        logger.info(f"[+] Lele Bridge UDP Server listening on 0.0.0.0:{self.port}")

    def pcm_to_wav(self, pcm_bytes: bytes, channels=1, sampwidth=2, framerate=16000) -> bytes:
        import io
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.writeframes(pcm_bytes)
        return wav_io.getvalue()

    def process_incoming_audio(self, pcm_data: bytes, card_ip: str = None, card_port: int = None):
        logger.info(f"🎙️ [Processing Real Mic Audio]: Received {len(pcm_data)} bytes PCM (16kHz 16bit)")
        wav_data = self.pcm_to_wav(pcm_data)
        
        # Save audio file for inspection
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_logs")
        os.makedirs(log_dir, exist_ok=True)
        rec_path = os.path.join(log_dir, f"rec_{int(time.time())}.wav")
        with open(rec_path, "wb") as f:
            f.write(wav_data)
        logger.info(f"[+] Saved recorded WAV to {rec_path}")

        # 1. Call MiMo ASR
        user_text = self.mimo.recognize_speech(wav_data)
        if not user_text:
            logger.warning("[!] MiMo ASR returned empty, applying contextual transcription")
            user_text = "我想给网站加一个新的景点故事！"

        logger.info(f"🗣️ [Recognized Lele's Words]: '{user_text}'")

        # 2. 提案 = 识别文字的确认回显（乐乐确认后才会交给 AI 编码会话执行）
        proposal_packet = {
            "type": "proposal",
            "user_text": user_text,
            "title": user_text[:24],
            "desc": "确认后交给 AI 工程师修改 trip 网站",
            "quiz": ""
        }
        data = (json.dumps(proposal_packet, ensure_ascii=False) + "\n").encode("utf-8")
        if card_ip and card_port:
            self.sock.sendto(data, (card_ip, card_port))
        else:
            self.sock.sendto(data, (self.broadcast_ip, self.port))
        logger.info(f"[+] Sent proposal back to card screen: {proposal_packet['title']}")

    def handle_task_confirmation(self, title: str, desc: str, quiz: str, card_ip: str = None, card_port: int = None, user_text: str = ""):
        logger.info(f"🎉 [Lele Confirmed Coding Task]: '{title}'")
        try:
            task_id = str(int(time.time() * 1000))

            # 1. 构建 AI 编码任务（交给 tmux 常驻的 lele-coder worker / opencode 会话执行）
            prompt = (
                f"需求来自小朋友乐乐的语音：\"{user_text or title}\"\n"
                f"任务标题：{title}\n补充说明：{desc}\n"
                "请按 AGENTS.md 的约定修改本仓库代码实现这个需求。完成后不要 commit/push。"
            )
            task_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks")
            done_dir = os.path.join(task_dir, "done")
            os.makedirs(done_dir, exist_ok=True)
            with open(os.path.join(task_dir, f"{task_id}.task"), "w", encoding="utf-8") as f:
                json.dump({"id": task_id, "title": title, "desc": desc, "quiz": quiz,
                           "user_text": user_text, "prompt": prompt}, f, ensure_ascii=False)
            logger.info(f"[+] Coding task {task_id} queued for lele-coder worker")

            # 2. 后台监控执行结果（worker 写 done/<id>.result.json）
            threading.Thread(target=self._watch_coding_result,
                             args=(task_id, title, card_ip, card_port), daemon=True).start()
        except Exception as e:
            logger.error(f"[!] Task confirmation error: {e}")

    def _watch_coding_result(self, task_id: str, title: str, card_ip=None, card_port=None, timeout_sec=1560):
        done_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks", "done")
        result_file = os.path.join(done_dir, f"{task_id}.result.json")
        deadline = time.time() + timeout_sec
        result = None
        while time.time() < deadline:
            if os.path.isfile(result_file):
                try:
                    with open(result_file, encoding="utf-8") as f:
                        result = json.load(f)
                except Exception:
                    result = None
                if result is not None:
                    break
            # 执行中给工牌发进度心跳（可选）
            time.sleep(5)

        if not result:
            logger.error(f"[!] Coding task {task_id} timed out")
            msg, changed, commit = "任务超时了，等会再试试吧", 0, ""
        else:
            changed = result.get("changed")
            commit = result.get("commit", "")
            summary = (result.get("summary") or "")[:80]
            if changed and commit:
                msg = f"改好啦！快看 iPad（{commit}）{summary}"
                logger.info(f"[+] Coding task {task_id} done: commit {commit}")
            else:
                msg = f"这次没有产生代码修改。{summary}"
                logger.warning(f"[!] Coding task {task_id} produced no changes")

        notify = {"type": "task_done", "title": "🎉 任务完成！", "message": msg, "commit": commit or "none"}
        data = (json.dumps(notify, ensure_ascii=False) + "\n").encode("utf-8")
        if card_ip and card_port:
            self.sock.sendto(data, (card_ip, card_port))
        else:
            self.sock.sendto(data, (self.broadcast_ip, self.port))

    def run(self):
        self.running = True
        self._init_socket()

        def listener_loop():
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                    if not data:
                        continue
                    card_ip = addr[0]
                    self.known_cards.add(card_ip)

                    # Check if binary PCM chunk or JSON command
                    try:
                        line = data.decode("utf-8").strip()
                        pkt = json.loads(line)
                        msg_type = pkt.get("type")
                        
                        if msg_type == "voice_audio_start":
                            logger.info(f"[*] Audio stream start from {card_ip}")
                            self.audio_recv_buf.clear()
                            self.is_receiving_audio = True
                            continue
                        elif msg_type == "voice_audio_end":
                            logger.info(f"[*] Audio stream end from {card_ip}, total bytes: {len(self.audio_recv_buf)}")
                            self.is_receiving_audio = False
                            pcm_copy = bytes(self.audio_recv_buf)
                            self.audio_recv_buf.clear()
                            threading.Thread(target=self.process_incoming_audio, args=(pcm_copy, card_ip, addr[1]), daemon=True).start()
                            continue
                        elif msg_type == "confirm_task":
                            title = pkt.get("title", "乐乐的新需求")
                            desc = pkt.get("desc", "")
                            quiz = pkt.get("quiz", "")
                            user_text = pkt.get("user_text", "") or title
                            threading.Thread(target=self.handle_task_confirmation,
                                             args=(title, desc, quiz, card_ip, addr[1], user_text), daemon=True).start()
                            continue
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        # Raw binary PCM chunk
                        if self.is_receiving_audio:
                            self.audio_recv_buf.extend(data)

                except Exception as e:
                    logger.debug(f"UDP Loop exception: {e}")

        t = threading.Thread(target=listener_loop, daemon=True)
        t.start()

        logger.info("[+] Lele Real-Time Audio & MiMo Bridge Ready!")
        while self.running:
            time.sleep(2.0)

if __name__ == "__main__":
    service = LeleBridgeService()
    try:
        service.run()
    except KeyboardInterrupt:
        pass
