#!/usr/bin/env python3
"""
Host Bridge Service: Dual-Mode (USB Serial + Wireless WiFi UDP) Daemon.
Monitors tmux session on N1 and communicates with ESP32 AI Card over Serial & WiFi.
"""

import os
import sys
import time
import signal
import socket
import psutil
import logging
import argparse
import threading
from typing import Dict, Any, Set

from protocol import Protocol
from tmux_monitor import TmuxMonitor
from serial_comm import SerialComm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("BridgeService")

class BridgeService:
    def __init__(self, session_name: str = "agy_workspace",
                 port: str = "/dev/ttyACM0", baud: int = 115200,
                 udp_port: int = 8888, broadcast_ip: str = "192.168.31.255",
                 interval: float = 1.0):
        self.session_name = session_name
        self.port = port
        self.baud = baud
        self.udp_port = udp_port
        self.broadcast_ip = broadcast_ip
        self.interval = interval
        self.running = False

        self.monitor = TmuxMonitor(session_name=self.session_name)
        self.serial = SerialComm(
            port=self.port,
            baud=self.baud,
            on_line_received=lambda line: self.handle_incoming_message(line, source="SERIAL")
        )

        # UDP Network Communication
        self.udp_sock = None
        self.udp_thread = None
        self.known_clients: Set[str] = set()

    def _init_udp(self):
        try:
            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.udp_sock.bind(('0.0.0.0', self.udp_port))
            logger.info(f"[+] WiFi UDP Server listening on 0.0.0.0:{self.udp_port} (Broadcast: {self.broadcast_ip})")
        except Exception as e:
            logger.error(f"[!] Failed to bind UDP server on port {self.udp_port}: {e}")

    def _udp_listener_loop(self):
        while self.running and self.udp_sock:
            try:
                data, addr = self.udp_sock.recvfrom(1024)
                if data:
                    client_ip = addr[0]
                    if client_ip not in self.known_clients:
                        self.known_clients.add(client_ip)
                        logger.info(f"[+] Discovered Wireless AI Card at IP: {client_ip}")
                    
                    line = data.decode('utf-8', errors='ignore').strip()
                    if line:
                        self.handle_incoming_message(line, source=f"WIFI:{client_ip}")
            except OSError:
                break
            except Exception as e:
                logger.warning(f"UDP Recv exception: {e}")

    def handle_incoming_message(self, line: str, source: str = "UNKNOWN"):
        logger.info(f"<- [{source}]: {line}")
        msg = Protocol.parse_line(line)
        if not msg:
            return

        msg_type = msg.get("type")
        if msg_type == Protocol.TYPE_COMMAND:
            self._handle_command(msg, source)
        elif msg_type == Protocol.TYPE_PING:
            self._broadcast_packet(Protocol.pack_ack("PING", True, "PONG"))

    def _handle_command(self, cmd: Dict[str, Any], source: str):
        action = cmd.get("action", "").upper()
        param = cmd.get("param", "")
        button = cmd.get("button_id", "")

        logger.info(f"[*] Command from [{source}]: ACTION={action}, PARAM={param}, BUTTON={button}")

        success = False
        message = ""

        if action == Protocol.ACTION_PAUSE:
            success, message = self.monitor.pause_session()
        elif action == Protocol.ACTION_RESUME:
            success, message = self.monitor.resume_session()
        elif action == Protocol.ACTION_NEXT:
            success, message = self.monitor.next_step()
        elif action == Protocol.ACTION_SEND_KEYS:
            success, message = self.monitor.send_keys(param)
        elif action == Protocol.ACTION_PING:
            success, message = True, "PONG"
        else:
            success = False
            message = f"未知指令: {action}"

        logger.info(f"[+] Command executed: success={success}, msg={message}")
        ack_packet = Protocol.pack_ack(action, success, message)
        self._broadcast_packet(ack_packet)
        self._push_telemetry()

    def _get_system_stats(self):
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            return cpu, mem
        except Exception:
            return 0.0, 0.0

    def _broadcast_packet(self, packet_str: str):
        # 1. Send to Serial USB
        self.serial.send_line(packet_str)

        # 2. Send over Wireless UDP Broadcast & to known clients
        if self.udp_sock:
            data = packet_str.encode('utf-8')
            try:
                self.udp_sock.sendto(data, (self.broadcast_ip, self.udp_port))
                for client_ip in list(self.known_clients):
                    self.udp_sock.sendto(data, (client_ip, self.udp_port))
            except Exception as e:
                logger.debug(f"UDP Broadcast send error: {e}")

    def _push_telemetry(self):
        state = self.monitor.parse_state()
        cpu, mem = self._get_system_stats()

        packet = Protocol.pack_telemetry(
            session=state["session"],
            status=state["status"],
            task=state["task"],
            progress=state["progress"],
            detail=state["detail"],
            cpu=cpu,
            mem=mem
        )
        self._broadcast_packet(packet)

    def run(self):
        self.running = True
        logger.info(f"Starting Dual-Mode Bridge Daemon for tmux session: [{self.session_name}]")
        logger.info(f"Serial: {self.port} | Wireless UDP: {self.udp_port} | Interval: {self.interval}s")

        self.serial.start()
        self._init_udp()

        if self.udp_sock:
            self.udp_thread = threading.Thread(target=self._udp_listener_loop, daemon=True, name="UDPListener")
            self.udp_thread.start()

        psutil.cpu_percent(interval=None)

        try:
            while self.running:
                self._push_telemetry()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("Interrupt received, shutting down...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        self.serial.stop()
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except Exception:
                pass
            self.udp_sock = None
        logger.info("Dual-Mode Bridge Service stopped.")

def main():
    parser = argparse.ArgumentParser(description="Dual-Mode ESP32 Task Monitor Bridge Daemon")
    parser.add_argument("--session", "-s", default="agy_workspace", help="Target tmux session (default: agy_workspace)")
    parser.add_argument("--port", "-p", default="/dev/ttyACM0", help="Serial port (default: /dev/ttyACM0)")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Serial baud rate (default: 115200)")
    parser.add_argument("--udp-port", "-u", type=int, default=8888, help="UDP port (default: 8888)")
    parser.add_argument("--broadcast", default="192.168.31.255", help="Subnet broadcast IP (default: 192.168.31.255)")
    parser.add_argument("--interval", "-i", type=float, default=1.0, help="Broadcast interval (default: 1.0)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    service = BridgeService(
        session_name=args.session,
        port=args.port,
        baud=args.baud,
        udp_port=args.udp_port,
        broadcast_ip=args.broadcast,
        interval=args.interval
    )

    def _signal_handler(sig, frame):
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    service.run()

if __name__ == "__main__":
    main()
