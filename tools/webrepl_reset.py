#!/usr/bin/env python3
"""WebREPL 软重启: python3 webrepl_reset.py <ip> [password]"""
import socket
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from webrepl_cli import client_handshake, websocket, login  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: webrepl_reset.py <ip> [password]")
    host = sys.argv[1]
    passwd = sys.argv[2] if len(sys.argv) > 2 else "folotoy"
    s = socket.socket()
    s.settimeout(5)
    s.connect(socket.getaddrinfo(host, 8266)[0][-1])
    client_handshake(s)
    ws = websocket(s)
    login(ws, passwd)
    time.sleep(0.3)
    try:
        ws.read(4096, text_ok=True)
    except Exception:
        pass
    ws.write(b"\x04")  # Ctrl-D 软重启
    time.sleep(1.5)
    out = b""
    try:
        s.settimeout(2)
        for _ in range(5):
            out += ws.read(4096, text_ok=True)
    except Exception:
        pass
    print((out[-400:] or b"[no output]").decode("utf-8", "replace"))
    print("[+] soft reset sent")


if __name__ == "__main__":
    main()
