"""
Protocol Handler for ESP32 MicroPython.
Parses incoming JSON lines and prepares outgoing command JSON packets.
"""

import sys
import json
import time

class MicroProtocolHandler:
    @staticmethod
    def parse_line(line_str):
        line = line_str.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
            if isinstance(data, dict) and "type" in data:
                return data
        except Exception:
            pass
        return None

    @staticmethod
    def make_command(action, param="", button_id=""):
        payload = {
            "type": "command",
            "action": action,
            "param": param,
            "button_id": button_id,
            "timestamp": int(time.time())
        }
        return json.dumps(payload) + "\n"
