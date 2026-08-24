import time
import struct
from machine import Pin, SPI

print("=" * 65)
print(" ESP32-C3 SLOW-PACED VISUAL SCREEN CALIBRATION TEST")
print(" Please watch the card screen carefully!")
print("=" * 65)

# Keep all potential backlight & power pins HIGH
for p in [0, 1, 2, 3, 4, 5, 8, 10, 11, 20, 21]:
    try:
        Pin(p, Pin.OUT).value(1)
    except Exception:
        pass

def write_cmd_data(spi, dc, cs, is_cmd, data):
    dc.value(0 if is_cmd else 1)
    cs.value(0)
    if isinstance(data, int):
        spi.write(bytearray([data]))
    elif isinstance(data, list):
        spi.write(bytearray(data))
    else:
        spi.write(data)
    cs.value(1)

def run_visual_profile(idx, name, sck, mosi, cs_pin, dc_pin, rst_pin, width=240, height=240, x_off=0, y_off=0, inv=True):
    print(f"\n" + "#" * 60)
    print(f" >>> [PROFILE {idx}/8] {name}")
    print(f"     PINS: SCK=GPIO{sck} | MOSI=GPIO{mosi} | CS=GPIO{cs_pin} | DC=GPIO{dc_pin} | RST=GPIO{rst_pin}")
    print(f"     RES : {width}x{height} (Offset: X={x_off}, Y={y_off})")
    print(f"     Starting in 2 seconds... PLEASE LOOK AT THE SCREEN NOW!")
    print("#" * 60)
    time.sleep(2.0)

    try:
        spi = SPI(1, baudrate=12000000, polarity=0, phase=0, sck=Pin(sck), mosi=Pin(mosi))
        cs = Pin(cs_pin, Pin.OUT, value=1)
        dc = Pin(dc_pin, Pin.OUT, value=0)
        rst = Pin(rst_pin, Pin.OUT, value=1) if rst_pin is not None else None

        # Reset Screen
        if rst:
            rst.value(0)
            time.sleep_ms(60)
            rst.value(1)
            time.sleep_ms(120)

        # ST7789 Initialization Sequence
        write_cmd_data(spi, dc, cs, True, 0x01) # SWRESET
        time.sleep_ms(120)
        write_cmd_data(spi, dc, cs, True, 0x11) # SLPOUT
        time.sleep_ms(120)
        write_cmd_data(spi, dc, cs, True, 0x3A) # COLMOD
        write_cmd_data(spi, dc, cs, False, 0x55) # 16-bit RGB565
        write_cmd_data(spi, dc, cs, True, 0x36) # MADCTL
        write_cmd_data(spi, dc, cs, False, 0x00)
        write_cmd_data(spi, dc, cs, True, 0x21 if inv else 0x20) # Inversion
        write_cmd_data(spi, dc, cs, True, 0x13) # NORON
        time.sleep_ms(10)
        write_cmd_data(spi, dc, cs, True, 0x29) # DISPON
        time.sleep_ms(60)

        # Set Draw Window
        write_cmd_data(spi, dc, cs, True, 0x2A) # CASET
        write_cmd_data(spi, dc, cs, False, [x_off >> 8, x_off & 0xFF, (x_off + width - 1) >> 8, (x_off + width - 1) & 0xFF])
        write_cmd_data(spi, dc, cs, True, 0x2B) # RASET
        write_cmd_data(spi, dc, cs, False, [y_off >> 8, y_off & 0xFF, (y_off + height - 1) >> 8, (y_off + height - 1) & 0xFF])
        write_cmd_data(spi, dc, cs, True, 0x2C) # RAMWR

        def fill_color(c, duration=1.5, label=""):
            print(f"     -> Displaying FULL {label} for {duration}s...")
            dc.value(1)
            cs.value(0)
            row_buf = struct.pack(">H", c) * width
            for _ in range(height):
                spi.write(row_buf)
            cs.value(1)
            time.sleep(duration)

        # Phase 1: Pure Solid RED
        fill_color(0xF800, 1.5, "RED")
        # Phase 2: Pure Solid GREEN
        fill_color(0x07E0, 1.5, "GREEN")
        # Phase 3: Pure Solid BLUE
        fill_color(0x001F, 1.5, "BLUE")

        # Phase 4: Vivid 5-Stripe Rainbow Pattern
        print(f"     -> Displaying RAINBOW STRIPES for 3.0s...")
        colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0xFFE0] # Red, Green, Blue, White, Yellow
        stripe_h = max(1, height // len(colors))
        dc.value(1)
        cs.value(0)
        for c in colors:
            chunk = struct.pack(">H", c) * width
            for _ in range(stripe_h):
                spi.write(chunk)
        cs.value(1)
        time.sleep(3.0)

        print(f"     [+] Profile {idx} test completed successfully!")
        return True
    except Exception as e:
        print(f"     [-] Profile {idx} failed with error: {e}")
        return False

# 8 Well-Known ESP32-C3 LCD Profiles
PROFILES = [
    (1, "Profile 1: Standard C3 240x240", 6, 7, 10, 2, 3, 240, 240, 0, 0, True),
    (2, "Profile 2: Standard C3 240x280 (Offset Y=20)", 6, 7, 10, 2, 3, 240, 280, 0, 20, True),
    (3, "Profile 3: FoloToy / Waveshare 240x240", 4, 6, 7, 2, 1, 240, 240, 0, 0, True),
    (4, "Profile 4: FoloToy / Waveshare 240x280 (Offset Y=20)", 4, 6, 7, 2, 1, 240, 280, 0, 20, True),
    (5, "Profile 5: 1.47-inch 172x320 (Offset X=34)", 6, 7, 10, 2, 3, 172, 320, 34, 0, True),
    (6, "Profile 6: LilyGO T-QT / T-Display (8/7/5/6/1)", 8, 7, 5, 6, 1, 240, 240, 0, 0, True),
    (7, "Profile 7: Generic C3 SPI (4/5/7/6/8)", 4, 5, 7, 6, 8, 240, 240, 0, 0, True),
    (8, "Profile 8: DevKit C3 SPI (2/3/7/6/10)", 2, 3, 7, 6, 10, 240, 240, 0, 0, False)
]

for p in PROFILES:
    run_visual_profile(p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10], p[11])

print("\n" + "=" * 65)
print(" ALL 8 PROFILES COMPLETED!")
print(" Which Profile Number (1 to 8) showed clear Red/Green/Blue/Rainbow?")
print("=" * 65)
