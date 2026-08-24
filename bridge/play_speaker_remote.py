#!/usr/bin/env python3
"""
Remote Wireless Audio Test Trigger via WebREPL WebSocket.
"""

import sys
import time
import socket
import websocket # from Pillow or websocket-client

HOST = "192.168.31.133"
PORT = 8266
PASS = "folotoy"

print(f"[*] Connecting wirelessly to ESP32 Card at ws://{HOST}:{PORT}...")
ws = websocket.create_connection(f"ws://{HOST}:{PORT}/", timeout=5)

# Read password prompt
prompt = ws.recv()
print("Prompt:", prompt)

# Send password
ws.send(PASS + "\n")
auth_res = ws.recv()
print("Auth:", auth_res)

# Send Python command to run test_speaker.py
print("[+] Triggering Speaker Audio Test on the Card...")
ws.send("import test_speaker\n")

time.sleep(1.0)
ws.close()
print("[+] Speaker audio test executed! Listen to the card's speaker now!")
