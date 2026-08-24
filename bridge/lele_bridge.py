#!/usr/bin/env python3
"""
Lele's AI Tour Guide Bridge with Xiaomi MiMo Engine & Automated Deployment Pipeline.
"""

import os
import sys
import time
import json
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

REPO_PATH = "/vol1/1000/esp32_passport_workspace/family-trip"
UDP_PORT = 8888
BROADCAST_IP = "192.168.31.255"

class LeleBridgeService:
    def __init__(self, port: int = UDP_PORT, broadcast_ip: str = BROADCAST_IP):
        self.port = port
        self.broadcast_ip = broadcast_ip
        self.running = False
        self.sock = None
        self.known_cards = set()
        self.mimo = MiMoService()

    def _init_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('0.0.0.0', self.port))
        logger.info(f"[+] Lele Bridge UDP Server listening on 0.0.0.0:{self.port}")

    def handle_voice_query(self, query_text: str = "", city: str = "开封", spot: str = "鼓楼夜市", card_ip: str = None):
        logger.info(f"🎙️ [Processing Voice via MiMo]: '{query_text}' for {city} · {spot}")
        # Generate proposal
        prop = self.mimo.generate_tour_proposal(query_text, current_city=city, current_spot=spot)
        
        proposal_packet = {
            "type": "proposal",
            "user_text": prop.get("user_text", query_text),
            "title": prop.get("title", f"{spot} · 探秘任务"),
            "desc": prop.get("desc", ""),
            "quiz": prop.get("quiz", "")
        }
        data = (json.dumps(proposal_packet, ensure_ascii=False) + "\n").encode("utf-8")
        if card_ip:
            self.sock.sendto(data, (card_ip, self.port))
        else:
            self.sock.sendto(data, (self.broadcast_ip, self.port))
        logger.info(f"[+] Sent proposal back to card: {proposal_packet['title']}")

    def handle_task_confirmation(self, title: str, desc: str, quiz: str, card_ip: str = None):
        logger.info(f"🎉 [Lele Confirmed Task]: '{title}'")
        try:
            # 1. Update version.json to trigger iPad auto-reload
            ver_file = os.path.join(REPO_PATH, "version.json")
            new_ver = int(time.time())
            with open(ver_file, "w", encoding="utf-8") as f:
                json.dump({
                    "version": new_ver,
                    "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "msg": f"乐乐小导游发布了新任务：{title}"
                }, f, indent=2, ensure_ascii=False)

            # 2. Synthesize audio narration via Xiaomi MiMo TTS if needed
            audio_data = self.mimo.synthesize_speech(f"乐乐小导游新任务：{title}。{desc}")
            if audio_data:
                audio_fname = f"task_{new_ver}.wav"
                audio_dest = os.path.join(REPO_PATH, "audio", audio_fname)
                os.makedirs(os.path.dirname(audio_dest), exist_ok=True)
                with open(audio_dest, "wb") as f:
                    f.write(audio_data)
                logger.info(f"[+] Generated MiMo TTS narration: {audio_dest}")

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
            if card_ip:
                self.sock.sendto(data, (card_ip, self.port))
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
                    data, addr = self.sock.recvfrom(2048)
                    if not data:
                        continue
                    card_ip = addr[0]
                    self.known_cards.add(card_ip)
                    
                    line = data.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        pkt = json.loads(line)
                    except Exception:
                        continue

                    msg_type = pkt.get("type")
                    if msg_type == "voice_query":
                        text = pkt.get("text", "")
                        city = pkt.get("city", "开封")
                        spot = pkt.get("spot", "鼓楼夜市")
                        threading.Thread(target=self.handle_voice_query, args=(text, city, spot, card_ip), daemon=True).start()
                    elif msg_type == "confirm_task":
                        title = pkt.get("title", "新景点探秘")
                        desc = pkt.get("desc", "")
                        quiz = pkt.get("quiz", "")
                        threading.Thread(target=self.handle_task_confirmation, args=(title, desc, quiz, card_ip), daemon=True).start()
                    elif msg_type == "ping":
                        logger.info(f"Ping received from card {card_ip}")

                except Exception as e:
                    logger.debug(f"UDP Loop exception: {e}")

        t = threading.Thread(target=listener_loop, daemon=True)
        t.start()

        logger.info("[+] Lele Bridge with Xiaomi MiMo Service Ready!")
        while self.running:
            time.sleep(2.0)

if __name__ == "__main__":
    service = LeleBridgeService()
    try:
        service.run()
    except KeyboardInterrupt:
        pass
