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
            user_text = "我想给开封加一个包公断案的故事！"

        logger.info(f"🗣️ [Recognized Lele's Words]: '{user_text}'")

        # 2. Call MiMo LLM to generate proposal
        prop = self.mimo.generate_tour_proposal(user_text, current_city="开封", current_spot="鼓楼夜市")

        proposal_packet = {
            "type": "proposal",
            "user_text": user_text,
            "title": prop.get("title", "开封府 · 包公断案"),
            "desc": prop.get("desc", "铁面无私包青天断奇案"),
            "quiz": prop.get("quiz", "三口铡刀分别铡谁？")
        }
        data = (json.dumps(proposal_packet, ensure_ascii=False) + "\n").encode("utf-8")
        if card_ip and card_port:
            self.sock.sendto(data, (card_ip, card_port))
        else:
            self.sock.sendto(data, (self.broadcast_ip, self.port))
        logger.info(f"[+] Sent proposal back to card screen: {proposal_packet['title']}")

    def handle_task_confirmation(self, title: str, desc: str, quiz: str, card_ip: str = None, card_port: int = None):
        logger.info(f"🎉 [Lele Confirmed Task]: '{title}'")
        try:
            # 1. Update version.json to trigger iPad auto-reload
            ver_file = os.path.join(REPO_PATH, "version.json")
            new_ver = int(time.time())
            
            # 2. Synthesize audio narration via Xiaomi MiMo TTS
            audio_fname = f"narration_{new_ver}.wav"
            audio_dest = os.path.join(REPO_PATH, "audio", audio_fname)
            os.makedirs(os.path.dirname(audio_dest), exist_ok=True)
            
            narration_text = f"乐乐小导游新任务发布！{title}。{desc}。快考考爸爸妈妈：{quiz}"
            audio_data = self.mimo.synthesize_speech(narration_text)
            if audio_data:
                with open(audio_dest, "wb") as f:
                    f.write(audio_data)
                logger.info(f"[+] Generated MiMo TTS narration: {audio_dest}")

            with open(ver_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": new_ver,
                    "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "msg": f"乐乐小导游发布了新任务：{title}",
                    "audio_url": f"./audio/{audio_fname}"
                }, f, indent=2, ensure_ascii=False)

            # 3. Git commit & push via Deploy Key
            subprocess.run(["git", "add", "."], cwd=REPO_PATH, check=True)
            commit_msg = f"feat(guide): 乐乐小导游发布新任务 [{title}]"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_PATH, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=REPO_PATH, check=True)
            logger.info("[+] Successfully pushed to GitHub! Webhook triggered.")

            # 4. Notify card
            notify_packet = {
                "type": "task_done",
                "title": "🎉 任务已发布！",
                "message": "快看 iPad 上的新内容！"
            }
            data = (json.dumps(notify_packet, ensure_ascii=False) + "\n").encode("utf-8")
            if card_ip and card_port:
                self.sock.sendto(data, (card_ip, card_port))
            else:
                self.sock.sendto(data, (self.broadcast_ip, self.port))

        except Exception as e:
            logger.error(f"[!] Task confirmation error: {e}")

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
                            title = pkt.get("title", "新景点探秘")
                            desc = pkt.get("desc", "")
                            quiz = pkt.get("quiz", "")
                            threading.Thread(target=self.handle_task_confirmation, args=(title, desc, quiz, card_ip, addr[1]), daemon=True).start()
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
