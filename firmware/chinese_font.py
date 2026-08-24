"""
High-Performance Universal 16x16 Chinese & ASCII Bitmap Font Engine for MicroPython.
Renders glyphs via direct 16x16 SPI block blits for maximum speed and crisp rendering.
"""

import struct

_font_engine = None

class ChineseFontEngine:
    def __init__(self, font_path="font16.bin"):
        self.f = open(font_path, "rb")
        magic = self.f.read(4)
        self.count = struct.unpack("<I", self.f.read(4))[0]
        self.index_offset = 8
        self.data_offset = 8 + self.count * 8
        self.cache = {}
        # Pre-allocated 16x16 RGB565 buffer (512 bytes)
        self.char_buf = bytearray(512)

    def get_glyph(self, ch):
        if ch in self.cache:
            return self.cache[ch]
        code = ord(ch)
        low = 0
        high = self.count - 1
        while low <= high:
            mid = (low + high) // 2
            self.f.seek(self.index_offset + mid * 8)
            m_code, m_offset = struct.unpack("<II", self.f.read(8))
            if m_code == code:
                self.f.seek(self.data_offset + m_offset)
                data = self.f.read(32)
                if len(self.cache) < 256:
                    self.cache[ch] = data
                return data
            elif m_code < code:
                low = mid + 1
            else:
                high = mid - 1
        return None

def get_engine():
    global _font_engine
    if _font_engine is None:
        try:
            _font_engine = ChineseFontEngine("font16.bin")
        except Exception:
            pass
    return _font_engine

def draw_char_cn(display, ch, x, y, fg=0xFFFF, bg=0x0000):
    engine = get_engine()
    if not engine or not display:
        return 16
    
    if x >= display.width or y >= display.height or x + 8 <= 0 or y + 16 <= 0:
        return 16

    glyph = engine.get_glyph(ch)
    is_ascii = ord(ch) < 128
    width = 8 if is_ascii else 16

    # If character out of right bound, clip
    draw_w = min(width, display.width - x)
    if draw_w <= 0:
        return width

    fg_hi = (fg >> 8) & 0xFF
    fg_lo = fg & 0xFF
    bg_val = bg if bg is not None else 0x0000
    bg_hi = (bg_val >> 8) & 0xFF
    bg_lo = bg_val & 0xFF

    # Convert 1-bit bitmap to RGB565 block
    buf = engine.char_buf
    idx = 0

    if glyph:
        for row in range(16):
            row_bits = (glyph[row * 2] << 8) | glyph[row * 2 + 1]
            for col in range(draw_w):
                if row_bits & (1 << (15 - col)):
                    buf[idx] = fg_hi
                    buf[idx+1] = fg_lo
                else:
                    buf[idx] = bg_hi
                    buf[idx+1] = bg_lo
                idx += 2
    else:
        # Fallback space/empty
        for i in range(0, draw_w * 16 * 2, 2):
            buf[i] = bg_hi
            buf[i+1] = bg_lo
        idx = draw_w * 16 * 2

    # Blit directly to ST7789 window in ONE SPI transaction
    display.set_window(x, y, x + draw_w - 1, y + 15)
    if display.dc:
        display.dc.value(1)
    if display.cs:
        display.cs.value(0)
    display.spi.write(memoryview(buf)[:idx])
    if display.cs:
        display.cs.value(1)

    return width

def draw_string_cn(display, text, x, y, fg=0xFFFF, bg=0x0000, max_width=240):
    curr_x = x
    curr_y = y
    for ch in text:
        if ch == '\n':
            curr_y += 18
            curr_x = x
            continue
        is_ascii = ord(ch) < 128
        char_w = 8 if is_ascii else 16
        if curr_x + char_w > max_width:
            curr_y += 18
            curr_x = x
        draw_char_cn(display, ch, curr_x, curr_y, fg, bg)
        curr_x += char_w
    return curr_x, curr_y
