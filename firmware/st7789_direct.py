"""
ST7789P3 Factory-Calibrated High-Performance Direct Driver for MicroPython.
Incorporates official vendor gamma, power, and porch calibration sequences.
"""

import time
import struct
import framebuf
from machine import Pin, SPI, PWM

# ST7789P3 Vendor Calibration Table
ST7789P3_CMDS = [
    (0xB2, [0x05, 0x05, 0x00, 0x33, 0x33]),  # PORCTRL 帧率 porch
    (0xB7, [0x35]),                          # GCTRL 栅极
    (0xBB, [0x21]),                          # VCOMS
    (0xC0, [0x2C]),                          # LCMCTRL
    (0xC2, [0x01]),                          # VDVVRHEN
    (0xC3, [0x0B]),                          # VRHS
    (0xC4, [0x20]),                          # VDVSET
    (0xC6, [0x0F]),                          # FRCTRL2 60Hz 点反转
    (0xD0, [0xA7, 0xA1]),                    # PWCTRL1
    (0xD0, [0xA4, 0xA1]),                    # PWCTRL1
    (0xD6, [0xA1]),
    (0xE0, [0xD0, 0x04, 0x08, 0x0A, 0x09, 0x05, 0x2D, 0x43,
            0x49, 0x09, 0x16, 0x15, 0x26, 0x2B]), # PVGAMCTRL 正伽马
    (0xE1, [0xD0, 0x03, 0x09, 0x0A, 0x0A, 0x06, 0x2E, 0x44,
            0x40, 0x3A, 0x15, 0x15, 0x26, 0x2A]), # NVGAMCTRL 负伽马
]

class ST7789Direct:
    def __init__(self, spi, width=240, height=320, cs=None, dc=None, rst=None, bl=None, rotation=0):
        self.spi = spi
        self.width = width
        self.height = height
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.bl = bl
        self.rotation = rotation

        if self.cs:
            self.cs.init(Pin.OUT, value=1)
        if self.dc:
            self.dc.init(Pin.OUT, value=0)
        if self.rst:
            self.rst.init(Pin.OUT, value=1)

        # Backlight setup (PWM)
        if self.bl is not None:
            try:
                self.bl_pwm = PWM(self.bl, freq=5000, duty_u16=65535)
            except Exception:
                self.bl.init(Pin.OUT, value=1)

        self._text_buf = bytearray(self.width)
        self._text_fb = framebuf.FrameBuffer(self._text_buf, self.width, 8, framebuf.MONO_VLSB)

        self.init_display()

    def _cmd(self, c):
        if self.dc:
            self.dc.value(0)
        if self.cs:
            self.cs.value(0)
        self.spi.write(bytearray([c]))
        if self.cs:
            self.cs.value(1)

    def _data(self, d):
        if self.dc:
            self.dc.value(1)
        if self.cs:
            self.cs.value(0)
        if isinstance(d, int):
            self.spi.write(bytearray([d]))
        elif isinstance(d, list):
            self.spi.write(bytearray(d))
        else:
            self.spi.write(d)
        if self.cs:
            self.cs.value(1)

    def init_display(self):
        if self.rst:
            self.rst.value(0)
            time.sleep_ms(50)
            self.rst.value(1)
            time.sleep_ms(120)

        # Soft Reset
        self._cmd(0x01)
        time.sleep_ms(150)

        # Sleep Out
        self._cmd(0x11)
        time.sleep_ms(120)

        # Color Mode: 16-bit RGB565
        self._cmd(0x3A)
        self._data(0x55)

        # Vendor ST7789P3 Calibration Sequence
        for cmd, data in ST7789P3_CMDS:
            self._cmd(cmd)
            self._data(data)

        # Inversion ON (Essential for ST7789 IPS)
        self._cmd(0x21)

        # Orientation
        self._cmd(0x36)
        madctl_map = [0x00, 0x60, 0xC0, 0xA0]
        self._data(madctl_map[self.rotation % 4])

        # Display ON
        self._cmd(0x13) # NORON
        time.sleep_ms(10)
        self._cmd(0x29) # DISPON
        time.sleep_ms(100)

    def set_window(self, x0, y0, x1, y1):
        self._cmd(0x2A) # CASET
        self._data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self._cmd(0x2B) # RASET
        self._data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self._cmd(0x2C) # RAMWR

    def pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.set_window(x, y, x, y)
            c_bytes = struct.pack(">H", color)
            if self.dc:
                self.dc.value(1)
            if self.cs:
                self.cs.value(0)
            self.spi.write(c_bytes)
            if self.cs:
                self.cs.value(1)

    def fill_rect(self, x, y, w, h, color):
        if x >= self.width or y >= self.height or w <= 0 or h <= 0:
            return
        x1 = min(x + w - 1, self.width - 1)
        y1 = min(y + h - 1, self.height - 1)
        rw = x1 - x + 1
        rh = y1 - y + 1

        self.set_window(x, y, x1, y1)

        c_bytes = struct.pack(">H", color)
        chunk_pixels = min(rw * rh, 256)
        buf = c_bytes * chunk_pixels

        if self.dc:
            self.dc.value(1)
        if self.cs:
            self.cs.value(0)

        total = rw * rh
        while total > 0:
            count = min(total, chunk_pixels)
            if count == chunk_pixels:
                self.spi.write(buf)
            else:
                self.spi.write(c_bytes * count)
            total -= count

        if self.cs:
            self.cs.value(1)

    def fill(self, color):
        self.fill_rect(0, 0, self.width, self.height, color)

    def rect(self, x, y, w, h, color):
        self.fill_rect(x, y, w, 1, color)
        self.fill_rect(x, y + h - 1, w, 1, color)
        self.fill_rect(x, y, 1, h, color)
        self.fill_rect(x + w - 1, y, 1, h, color)

    def text(self, string, x, y, color, bg_color=None):
        if y + 8 <= 0 or y >= self.height or not string:
            return
        
        for i in range(len(self._text_buf)):
            self._text_buf[i] = 0
        
        self._text_fb.text(string, 0, 0, 1)
        str_len = len(string) * 8
        draw_w = min(str_len, self.width - x)
        if draw_w <= 0:
            return

        self.set_window(x, y, x + draw_w - 1, y + 7)

        c_fg = struct.pack(">H", color)
        c_bg = struct.pack(">H", bg_color if bg_color is not None else 0x0000)

        line_data = bytearray(draw_w * 8 * 2)
        idx = 0
        for py in range(8):
            for px in range(draw_w):
                byte_idx = px
                bit_mask = 1 << py
                if (self._text_buf[byte_idx] & bit_mask) != 0:
                    line_data[idx] = c_fg[0]
                    line_data[idx+1] = c_fg[1]
                else:
                    line_data[idx] = c_bg[0]
                    line_data[idx+1] = c_bg[1]
                idx += 2

        if self.dc:
            self.dc.value(1)
        if self.cs:
            self.cs.value(0)
        self.spi.write(line_data)
        if self.cs:
            self.cs.value(1)
