"""
Auto-reconnecting Serial Transport Layer for Host <-> ESP32 Bridge.
Handles asynchronous reception, thread-safe transmission, and automatic recovery.
"""

import os
import glob
import time
import queue
import serial
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("SerialComm")

class SerialComm:
    def __init__(self, port: str = "/dev/ttyACM0", baud: int = 115200,
                 on_line_received: Optional[Callable[[str], None]] = None):
        self.target_port = port
        self.baud = baud
        self.on_line_received = on_line_received
        self.ser: Optional[serial.Serial] = None
        self.is_running = False
        self.write_queue = queue.Queue(maxsize=100)
        
        self.reader_thread: Optional[threading.Thread] = None
        self.writer_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def find_active_port(self) -> Optional[str]:
        """Find candidate serial port matching /dev/ttyACM* or /dev/ttyUSB*."""
        if os.path.exists(self.target_port):
            return self.target_port
        candidates = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/pts/*")
        if candidates:
            # Pick first accessible
            for c in candidates:
                if os.access(c, os.R_OK | os.W_OK):
                    return c
            return candidates[0]
        return None

    def start(self):
        """Start serial communication threads."""
        self.is_running = True
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True, name="SerialReader")
        self.writer_thread = threading.Thread(target=self._writer_loop, daemon=True, name="SerialWriter")
        self.reader_thread.start()
        self.writer_thread.start()
        logger.info("Serial communication service started.")

    def stop(self):
        """Gracefully stop serial threads and close port."""
        self.is_running = False
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
        logger.info("Serial communication service stopped.")

    def send_line(self, data: str):
        """Enqueue string to be transmitted over serial (appends \\n if missing)."""
        if not data.endswith("\n"):
            data += "\n"
        try:
            self.write_queue.put_nowait(data)
        except queue.Full:
            logger.warning("Serial write queue full, dropping oldest packet.")
            try:
                self.write_queue.get_nowait()
                self.write_queue.put_nowait(data)
            except Exception:
                pass

    def _connect(self) -> bool:
        """Attempt to open the serial port."""
        port = self.find_active_port()
        if not port:
            return False
        try:
            with self.lock:
                self.ser = serial.Serial(
                    port=port,
                    baudrate=self.baud,
                    timeout=1.0,
                    write_timeout=1.0
                )
            logger.info(f"[+] Successfully connected to serial port: {port} @ {self.baud} baud")
            return True
        except serial.SerialException as e:
            logger.debug(f"Serial connect attempt failed on {port}: {e}")
            return False
        except PermissionError:
            logger.error(f"[!] Permission denied on {port}. Please add user to dialout group.")
            return False

    def _reader_loop(self):
        """Background thread: continuously reads lines and triggers callback."""
        buffer = bytearray()
        while self.is_running:
            if not self.ser or not self.ser.is_open:
                if not self._connect():
                    time.sleep(1.5)
                    continue

            try:
                # Read available bytes
                waiting = self.ser.in_waiting if hasattr(self.ser, 'in_waiting') else 1
                chunk = self.ser.read(max(1, waiting))
                if chunk:
                    buffer.extend(chunk)
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        decoded = line.decode('utf-8', errors='replace').strip()
                        if decoded and self.on_line_received:
                            try:
                                self.on_line_received(decoded)
                            except Exception as cb_err:
                                logger.error(f"Error in on_line_received callback: {cb_err}")
                else:
                    time.sleep(0.02)
            except (serial.SerialException, OSError) as e:
                logger.warning(f"Serial link lost: {e}. Reconnecting...")
                with self.lock:
                    if self.ser:
                        try:
                            self.ser.close()
                        except Exception:
                            pass
                        self.ser = None
                time.sleep(1.5)

    def _writer_loop(self):
        """Background thread: continuously flushes write_queue to serial port."""
        while self.is_running:
            try:
                item = self.write_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            sent = False
            for _ in range(3):
                with self.lock:
                    if self.ser and self.ser.is_open:
                        try:
                            self.ser.write(item.encode('utf-8'))
                            self.ser.flush()
                            sent = True
                            break
                        except Exception as e:
                            logger.warning(f"Write error: {e}")
                            try:
                                self.ser.close()
                            except Exception:
                                pass
                            self.ser = None
                time.sleep(0.1)

            if not sent:
                logger.debug("Failed to deliver packet over serial (port not open).")
            self.write_queue.task_done()
