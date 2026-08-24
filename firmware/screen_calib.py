import time
import struct
from machine import Pin, SPI

print("=" * 60)
print(" ST7789 / ST7735 Multi-Controller Display Calibration")
print("=" * 60)

# Keep all potential backlight pins HIGH
for p in [0, 1, 2, 3, 4, 5, 8, 10, 11, 20, 21]:
    try:
        Pin(p, Pin.OUT).value(1)
    except Exception:
        pass

def write_spi(spi, dc, cs, is_cmd, data):
    dc.value(0 if is_cmd else 1)
    cs.value(0)
    if isinstance(data, int):
        spi.write(bytearray([data]))
    elif isinstance(data, list):
        spi.write(bytearray(data))
    else:
        spi.write(data)
    cs.value(1)

def test_st7789_mode(sck, mosi, cs_p, dc_p, rst_p, name, width=240, height=240, x_off=0, y_off=0, inv=True):
    print(f"\n[+] Testing {name} on SCK={sck} MOSI={mosi} CS={cs_p} DC={dc_p} RST={rst_p}...")
    try:
        spi = SPI(1, baudrate=10000000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        cs = Pin(cs_p, Pin.OUT, value=1)
        dc = Pin(dc_p, Pin.OUT, value=0)
        rst = Pin(rst_p, Pin.OUT, value=1) if rst_p is not None else None

        if rst:
            rst.value(0)
            time.sleep_ms(50)
            rst.value(1)
            time.sleep_ms(150)

        # ST7789 Init
        write_spi(spi, dc, cs, True, 0x01) # SWRESET
        time.sleep_ms(150)
        write_spi(spi, dc, cs, True, 0x11) # SLPOUT
        time.sleep_ms(120)
        write_spi(spi, dc, cs, True, 0x3A) # COLMOD
        write_spi(spi, dc, cs, False, 0x55) # 16-bit RGB565
        write_spi(spi, dc, cs, True, 0x36) # MADCTL
        write_spi(spi, dc, cs, False, 0x00) # RGB
        write_spi(spi, dc, cs, True, 0x21 if inv else 0x20) # Inversion
        write_spi(spi, dc, cs, True, 0x13) # NORON
        time.sleep_ms(10)
        write_spi(spi, dc, cs, True, 0x29) # DISPON
        time.sleep_ms(100)

        # Set Window
        write_spi(spi, dc, cs, True, 0x2A) # CASET
        write_spi(spi, dc, cs, False, [x_off >> 8, x_off & 0xFF, (x_off + width - 1) >> 8, (x_off + width - 1) & 0xFF])
        write_spi(spi, dc, cs, True, 0x2B) # RASET
        write_spi(spi, dc, cs, False, [y_off >> 8, y_off & 0xFF, (y_off + height - 1) >> 8, (y_off + height - 1) & 0xFF])
        write_spi(spi, dc, cs, True, 0x2C) # RAMWR

        # Fill with alternating color stripes (RED, GREEN, BLUE, WHITE, YELLOW)
        colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0xFFE0]
        stripe_h = max(1, height // len(colors))
        
        dc.value(1)
        cs.value(0)
        for c in colors:
            chunk = struct.pack(">H", c) * width
            for _ in range(stripe_h):
                spi.write(chunk)
        cs.value(1)
        print(f"    -> [SUCCESS] Flushed Rainbow Pattern for {name}")
        time.sleep(2.5)
        return True
    except Exception as e:
        print(f"    -> [ERROR] {e}")
        return False

# Candidate pin configurations
configs = [
    # C3 Standard
    {"sck": 6, "mosi": 7, "cs": 10, "dc": 2, "rst": 3, "w": 240, "h": 240, "xo": 0, "yo": 0, "name": "ST7789 240x240 (6/7/10/2/3)"},
    {"sck": 6, "mosi": 7, "cs": 10, "dc": 2, "rst": 3, "w": 240, "h": 280, "xo": 0, "yo": 20, "name": "ST7789 240x280 (6/7/10/2/3)"},
    {"sck": 6, "mosi": 7, "cs": 10, "dc": 2, "rst": 3, "w": 172, "h": 320, "xo": 34, "yo": 0, "name": "ST7789 1.47in 172x320"},
    # FoloToy / Waveshare C3
    {"sck": 4, "mosi": 6, "cs": 7, "dc": 2, "rst": 1, "w": 240, "h": 240, "xo": 0, "yo": 0, "name": "ST7789 FoloToy A (4/6/7/2/1)"},
    {"sck": 4, "mosi": 6, "cs": 7, "dc": 2, "rst": 1, "w": 240, "h": 280, "xo": 0, "yo": 20, "name": "ST7789 FoloToy B (4/6/7/2/1)"},
    # LilyGO / T-QT
    {"sck": 8, "mosi": 7, "cs": 5, "dc": 6, "rst": 1, "w": 240, "h": 240, "xo": 0, "yo": 0, "name": "ST7789 LilyGO (8/7/5/6/1)"},
    # Generic SPI 4/5/7/6
    {"sck": 4, "mosi": 5, "cs": 7, "dc": 6, "rst": 8, "w": 240, "h": 240, "xo": 0, "yo": 0, "name": "ST7789 Generic (4/5/7/6/8)"},
    # Standard ST7735S 128x160
    {"sck": 6, "mosi": 7, "cs": 10, "dc": 2, "rst": 3, "w": 128, "h": 160, "xo": 0, "yo": 0, "name": "ST7735S 128x160 (6/7/10/2/3)"},
    {"sck": 4, "mosi": 6, "cs": 7, "dc": 2, "rst": 1, "w": 128, "h": 160, "xo": 0, "yo": 0, "name": "ST7735S 128x160 (4/6/7/2/1)"}
]

for cfg in configs:
    test_st7789_mode(
        sck=cfg["sck"], mosi=cfg["mosi"], cs_p=cfg["cs"], dc_p=cfg["dc"], rst_p=cfg["rst"],
        name=cfg["name"], width=cfg["w"], height=cfg["h"], x_off=cfg["xo"], y_off=cfg["yo"]
    )

print("\n[+] Calibration suite finished. Please check which pattern displayed clear color stripes!")
