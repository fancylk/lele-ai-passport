"""
Shared Protocol Definition for Host <-> ESP32-S3 Bridge.
Framing: Line-delimited JSON (UTF-8 encoded JSON string ending with '\n').
"""

import json
import time
from typing import Dict, Any, Optional

class Protocol:
    # Message Types
    TYPE_TELEMETRY = "telemetry"
    TYPE_COMMAND = "command"
    TYPE_ACK = "ack"
    TYPE_PING = "ping"
    TYPE_PONG = "pong"

    # Status Constants
    STATUS_IDLE = "IDLE"
    STATUS_RUNNING = "RUNNING"
    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILED = "FAILED"
    STATUS_PAUSED = "PAUSED"

    # Supported Actions (ESP32 -> Host)
    ACTION_PAUSE = "PAUSE"
    ACTION_RESUME = "RESUME"
    ACTION_NEXT = "NEXT"
    ACTION_CANCEL = "CANCEL"
    ACTION_SEND_KEYS = "SEND_KEYS"
    ACTION_PING = "PING"

    @staticmethod
    def pack_telemetry(session: str, status: str, task: str, progress: int,
                       detail: str = "", cpu: float = 0.0, mem: float = 0.0) -> str:
        """Create a telemetry JSON packet string with trailing newline."""
        payload = {
            "type": Protocol.TYPE_TELEMETRY,
            "session": session,
            "status": status,
            "task": task[:64],
            "progress": max(0, min(100, int(progress))),
            "detail": detail[:128],
            "cpu": round(cpu, 1),
            "mem": round(mem, 1),
            "timestamp": int(time.time())
        }
        return json.dumps(payload, ensure_ascii=False) + "\n"

    @staticmethod
    def pack_ack(action: str, success: bool, message: str = "") -> str:
        """Create an ACK JSON packet string with trailing newline."""
        payload = {
            "type": Protocol.TYPE_ACK,
            "action": action,
            "success": success,
            "msg": message,
            "timestamp": int(time.time())
        }
        return json.dumps(payload, ensure_ascii=False) + "\n"

    @staticmethod
    def pack_command(action: str, param: str = "", button_id: str = "") -> str:
        """Create a Command JSON packet string with trailing newline."""
        payload = {
            "type": Protocol.TYPE_COMMAND,
            "action": action,
            "param": param,
            "button_id": button_id,
            "timestamp": int(time.time())
        }
        return json.dumps(payload, ensure_ascii=False) + "\n"

    @staticmethod
    def parse_line(line: str) -> Optional[Dict[str, Any]]:
        """Parse an incoming line into a dictionary. Returns None on invalid JSON."""
        line = line.strip()
        if not line:
            return None
        # Handle raw text commands for quick serial debugging (e.g. typing "PAUSE")
        if line in (Protocol.ACTION_PAUSE, Protocol.ACTION_RESUME, Protocol.ACTION_NEXT, Protocol.ACTION_PING):
            return {"type": Protocol.TYPE_COMMAND, "action": line, "param": "", "button_id": "CLI"}
        try:
            data = json.loads(line)
            if isinstance(data, dict) and "type" in data:
                return data
        except json.JSONDecodeError:
            pass
        return None
