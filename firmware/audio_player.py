"""
ES8311 Hardware Sound Effect & Chime Player for Lele AI Passport.
Provides cheerful, distinct melodies and sound effects for each interactive step.
"""

import time
from machine import Pin, I2C

class AudioPlayer:
    def __init__(self, i2c=None, sda_pin=10, scl_pin=7, addr=0x18):
        self.addr = addr
        self.ready = False
        if i2c:
            self.i2c = i2c
        else:
            try:
                self.i2c = I2C(0, sda=Pin(sda_pin), scl=Pin(scl_pin), freq=100000)
            except Exception:
                self.i2c = None

        if self.i2c:
            self.init_codec()

    def _w(self, reg, val):
        if self.i2c:
            try:
                self.i2c.writeto_mem(self.addr, reg, bytearray([val]))
            except Exception:
                pass

    def init_codec(self):
        try:
            # 1. Reset
            self._w(0x00, 0x80)
            time.sleep_ms(15)
            self._w(0x00, 0x00)

            # 2. Clock & Power Setup
            self._w(0x01, 0x30)
            self._w(0x02, 0x00)
            self._w(0x03, 0x10)
            self._w(0x04, 0x10)
            self._w(0x05, 0x00)
            self._w(0x06, 0x00)
            self._w(0x07, 0x00)
            self._w(0x08, 0xFF)

            # Power Up Output DAC & Amp
            self._w(0x0D, 0x01)
            self._w(0x0E, 0x02)
            self._w(0x0F, 0x44)
            self._w(0x12, 0x00)
            self._w(0x13, 0x10)

            # Output Volume (Loud & Crisp)
            self._w(0x31, 0x00) # Unmute
            self._w(0x32, 0x00) # Maximum output gain (0dB)
            self.ready = True
            print("[+] ES8311 Sound Engine Initialized Successfully!")
        except Exception as e:
            print("[!] ES8311 Audio init failed:", e)

    def play_beep(self, freq_code=0x88, duration_ms=100):
        """Play hardware tone code."""
        if not self.ready:
            return
        self._w(0x37, freq_code) # Beep ON
        time.sleep_ms(duration_ms)
        self._w(0x37, 0x00)      # Beep OFF

    def play_click(self):
        """Subtle tactile key click."""
        self.play_beep(0x82, 35)

    def play_record_start(self):
        """Chime when starting to speak: 叮-咚 (Ding-Dong)."""
        self.play_beep(0x84, 90)
        time.sleep_ms(30)
        self.play_beep(0x88, 140)

    def play_record_stop(self):
        """Soft confirmation when releasing the button."""
        self.play_beep(0x86, 60)

    def play_proposal_ready(self):
        """Lively 'Ta-da!' chime when AGY returns the proposal: 咪-索-哆!"""
        self.play_beep(0x82, 70)
        time.sleep_ms(25)
        self.play_beep(0x85, 70)
        time.sleep_ms(25)
        self.play_beep(0x89, 150)

    def play_send_success(self):
        """Celebratory Victory Fanfare on task deployment: 哆-咪-索-高哆!"""
        self.play_beep(0x81, 80)
        time.sleep_ms(20)
        self.play_beep(0x83, 80)
        time.sleep_ms(20)
        self.play_beep(0x86, 90)
        time.sleep_ms(20)
        self.play_beep(0x8A, 220)

    def play_cancel(self):
        """Soft descending cancel tone."""
        self.play_beep(0x87, 80)
        time.sleep_ms(25)
        self.play_beep(0x82, 120)
