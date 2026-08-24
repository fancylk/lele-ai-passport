"""
Pure MicroPython ST7789 Display Driver with FrameBuffer Support.
Works on ANY generic MicroPython build without requiring custom C bindings.
"""

import time
import framebuf
from machine import Pin, SPI

# ST7789 Commands
ST7789_NOP     = 0x00
ST7789_SWRESET = 0x01
ST7789_SLPIN   = 0x10
ST7789_SLPOUT  = 0x11
ST7789_NORON   = 0x13
ST7789_INVOFF  = 0x20
ST7789_INVON   = 0x21
ST7789_DISPOFF = 0x28
ST7789_DISPON  = 0x29
ST7789_CASET   = 0x2A
ST7789_RASET   = 0x2B
ST7789_RAMWR   = 0x2C
ST7789_MADCTL  = 0x36
ST7789_COLMOD  = 0x3A

# Color formats
COLOR_MODE_65K = 0x55  # 16-bit RGB565

class ST7789(framebuf.FrameBuffer):
    def __init__(self, spi, width=240, height=240, cs=None, dc=None, rst=None, bl=None,
                 x_offset=0, y_offset=0, rotation=0, inversion=True):
        self.spi = spi
        self.width = width
        self.height = height
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.bl = bl
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.rotation = rotation
        self.inversion = inversion

        # Initialize Pin modes
        if self.cs:
            self.cs.init(Pin.OUT, value=1)
        if self.dc:
            self.dc.init(Pin.OUT, value=0)
        if self.rst:
            self.rst.init(Pin.OUT, value=1)
        if self.bl:
            self.bl.init(Pin.OUT, value=1) # Enable Backlight!

        # Allocate FrameBuffer in RGB565 format (width * height * 2 bytes)
        # For 240x240 in RGB565: 115,200 bytes.
        # On memory constrained devices (C3 has ~384KB SRAM), we allocate the full buffer or band buffer.
        try:
            self.buffer = bytearray(self.width * self.height * 2)
            super().__init__(self.buffer, self.width, self.height, framebuf.RGB565)
            self._has_full_fb = True
        except MemoryError:
            # Fallback to smaller buffer (240x120 or line buffer)
            print("[!] Large buffer MemoryError, using direct draw mode")
            self.buffer = bytearray(self.width * 40 * 2)
            super().__init__(self.buffer, self.width, 40, framebuf.RGB565)
            self._has_full_fb = False

        self.init_display()

    def _write_cmd(self, cmd):
        if self.dc:
            self.dc.value(0)
        if self.cs:
            self.cs.value(0)
        self.spi.write(bytearray([cmd]))
        if self.cs:
            self.cs.value(1)

    def _write_data(self, data):
        if self.dc:
            self.dc.value(1)
        if self.cs:
            self.cs.value(0)
        if isinstance(data, int):
            self.spi.write(bytearray([data]))
        else:
            self.spi.write(data)
        if self.cs:
            self.cs.value(1)

    def init_display(self):
        """Hardware reset and initialize ST7789 controller."""
        if self.rst:
            self.rst.value(0)
            time.sleep_ms(50)
            self.rst.value(1)
            time.sleep_ms(150)

        # Software Reset
        self._write_cmd(ST7789_SWRESET)
        time.sleep_ms(150)

        # Exit Sleep Mode
        self._write_cmd(ST7789_SLPOUT)
        time.sleep_ms(120)

        # Color Mode: 16-bit / pixel (RGB565)
        self._write_cmd(ST7789_COLMOD)
        self._write_data(COLOR_MODE_65K)
        time.sleep_ms(10)

        # Memory Data Access Control (Orientation)
        self._write_cmd(ST7789_MADCTL)
        # 0x00 = Normal, 0x60 = 90 deg, 0xC0 = 180 deg, 0xA0 = 270 deg
        madctl_map = [0x00, 0x60, 0xC0, 0xA0]
        self._write_data(madctl_map[self.rotation % 4])

        # Color Inversion (ST7789 IPS panels almost always require INVON)
        if self.inversion:
            self._write_cmd(ST7789_INVON)
        else:
            self._write_cmd(ST7789_INVOFF)
        time.sleep_ms(10)

        # Normal Display Mode On
        self._write_cmd(ST7789_NORON)
        time.sleep_ms(10)

        # Display ON
        self._write_cmd(ST7789_DISPON)
        time.sleep_ms(100)

        # Turn Backlight On
        if self.bl:
            self.bl.value(1)

    def set_window(self, x0, y0, x1, y1):
        """Set address window for RAM write."""
        x0 += self.x_offset
        x1 += self.x_offset
        y0 += self.y_offset
        y1 += self.y_offset

        self._write_cmd(ST7789_CASET)
        self._write_data(bytearray([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))

        self._write_cmd(ST7789_RASET)
        self._write_data(bytearray([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))

        self._write_cmd(ST7789_RAMWR)

    def show(self):
        """Flush the framebuffer memory to physical display over SPI."""
        if not self._has_full_fb:
            return
        self.set_window(0, 0, self.width - 1, self.height - 1)
        if self.dc:
            self.dc.value(1)
        if self.cs:
            self.cs.value(0)
        
        # Write in chunks of 4KB to avoid memory spike on ESP32
        chunk_size = 4096
        mv = memoryview(self.buffer)
        for i in range(0, len(self.buffer), chunk_size):
            self.spi.write(mv[i:i + chunk_size])

        if self.cs:
            self.cs.value(1)
