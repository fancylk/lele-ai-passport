"""
Lightweight Wireless WiFi & UDP Socket Manager for ESP32 MicroPython.
"""

import time
import socket
import network
import json
from config import WIFI_SSID, WIFI_PASS, HOST_IP, UDP_PORT

class WiFiManager:
    def __init__(self, on_status_cb=None):
        self.ssid = WIFI_SSID
        self.password = WIFI_PASS
        self.host_ip = HOST_IP
        self.port = UDP_PORT
        self.on_status_cb = on_status_cb
        
        self.wlan = network.WLAN(network.STA_IF)
        self.sock = None
        self.ip = "0.0.0.0"
        self.is_connected = False

    def connect(self, timeout=12):
        """Connect to WiFi access point."""
        self.wlan.active(True)
        if not self.wlan.isconnected():
            if self.on_status_cb:
                self.on_status_cb(f"正在连接：{self.ssid}")
            print(f"[*] Connecting to WiFi: {self.ssid}...")
            self.wlan.connect(self.ssid, self.password)
            
            start = time.time()
            while not self.wlan.isconnected():
                if time.time() - start > timeout:
                    print("[!] WiFi Connection Timeout!")
                    if self.on_status_cb:
                        self.on_status_cb("WiFi 连接超时")
                    return False
                time.sleep(0.5)

        self.ip = self.wlan.ifconfig()[0]
        self.is_connected = True
        print(f"[+] WiFi Connected! IP Address: {self.ip}")
        if self.on_status_cb:
            self.on_status_cb(f"已连入 WiFi: {self.ip}")

        self._setup_udp_socket()
        return True

    def _setup_udp_socket(self):
        """Create non-blocking UDP socket."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('0.0.0.0', self.port))
            self.sock.setblocking(False)
            print(f"[+] UDP Socket listening on port {self.port}")
        except Exception as e:
            print("[!] UDP Socket setup error:", e)

    def send_udp(self, json_str):
        """Send JSON string over UDP to N1 host."""
        if not self.is_connected or not self.sock:
            return False
        try:
            data = json_str.encode('utf-8') if isinstance(json_str, str) else json_str
            self.sock.sendto(data, (self.host_ip, self.port))
            return True
        except Exception as e:
            print("[!] UDP Send error:", e)
            return False

    def poll_udp(self):
        """Poll incoming UDP packet without blocking."""
        if not self.is_connected or not self.sock:
            return None
        try:
            data, addr = self.sock.recvfrom(512)
            if data:
                return data.decode('utf-8', errors='ignore').strip()
        except OSError:
            # Normal for non-blocking socket when no data is available
            pass
        except Exception as e:
            print("[!] UDP Recv error:", e)
        return None
