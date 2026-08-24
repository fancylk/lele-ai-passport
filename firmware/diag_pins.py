import time
from machine import Pin, SPI
from st7789_direct import ST7789Direct

print("=" * 50)
print(" ESP32-C3 Screen Pinout & Backlight Diagnostic Scanner")
print("=" * 50)

# Step 1: Turn ON all possible Backlight / Power GPIOs
# Available GPIOs on C3: 0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 20, 21
possible_power_pins = [0, 1, 2, 3, 4, 5, 8, 10, 11, 20, 21]
active_pins = []

print("[1] Pulling all potential backlight & power pins HIGH...")
for p in possible_power_pins:
    try:
        pin_obj = Pin(p, Pin.OUT)
        pin_obj.value(1)
        active_pins.append(pin_obj)
        print(f"    - GPIO {p} -> HIGH")
    except Exception as e:
        print(f"    - GPIO {p} -> Skip ({e})")

# Known Pinout Profiles for ESP32-C3 Display Boards
profiles = [
    # Profile A: Standard ESP32-C3 SPI (SCK=6, MOSI=7, CS=10, DC=2, RST=3)
    {"name": "Profile A (Std C3 SPI)", "sck": 6, "mosi": 7, "cs": 10, "dc": 2, "rst": 3, "bl": 11, "inv": True},
    # Profile B: LilyGO / T-QT / T-Display C3 (SCK=8, MOSI=7, CS=5, DC=6, RST=1, BL=0)
    {"name": "Profile B (T-QT/LilyGO)", "sck": 8, "mosi": 7, "cs": 5, "dc": 6, "rst": 1, "bl": 0, "inv": True},
    # Profile C: Waveshare C3 LCD / FoloToy (SCK=4, MOSI=6, CS=7, DC=2, RST=1, BL=3)
    {"name": "Profile C (Waveshare/FoloToy)", "sck": 4, "mosi": 6, "cs": 7, "dc": 2, "rst": 1, "bl": 3, "inv": True},
    # Profile D: Generic C3 LCD 2 (SCK=4, MOSI=5, CS=7, DC=6, RST=8, BL=1)
    {"name": "Profile D (Generic C3 2)", "sck": 4, "mosi": 5, "cs": 7, "dc": 6, "rst": 8, "bl": 1, "inv": True},
    # Profile E: 0.42/0.96/1.14 C3 LCD (SCK=3, MOSI=5, CS=7, DC=2, RST=10, BL=6)
    {"name": "Profile E (Mini C3 LCD)", "sck": 3, "mosi": 5, "cs": 7, "dc": 2, "rst": 10, "bl": 6, "inv": True},
    # Profile F: ESP32-C3 DevKit LCD (SCK=2, MOSI=3, CS=7, DC=6, RST=10, BL=8)
    {"name": "Profile F (DevKit C3)", "sck": 2, "mosi": 3, "cs": 7, "dc": 6, "rst": 10, "bl": 8, "inv": False},
    # Profile G: SPI1 standard (SCK=6, MOSI=7, CS=2, DC=3, RST=1, BL=0)
    {"name": "Profile G (Alt C3 3)", "sck": 6, "mosi": 7, "cs": 2, "dc": 3, "rst": 1, "bl": 0, "inv": False}
]

colors = [0xF800, 0x07E0, 0x001F, 0xFFFF, 0x07FF] # Red, Green, Blue, White, Cyan

print("\n[2] Iterating through display profiles...")
for i, prof in enumerate(profiles):
    print(f"\n---> Testing {prof['name']}: SCK={prof['sck']} MOSI={prof['mosi']} CS={prof['cs']} DC={prof['dc']} RST={prof['rst']} BL={prof['bl']} Inv={prof['inv']}")
    try:
        spi = SPI(1, baudrate=30000000, sck=Pin(prof["sck"]), mosi=Pin(prof["mosi"]))
        disp = ST7789Direct(
            spi=spi,
            width=240,
            height=240,
            cs=Pin(prof["cs"]) if prof["cs"] is not None else None,
            dc=Pin(prof["dc"]) if prof["dc"] is not None else None,
            rst=Pin(prof["rst"]) if prof["rst"] is not None else None,
            bl=Pin(prof["bl"]) if prof["bl"] is not None else None,
            rotation=0,
            inversion=prof["inv"]
        )
        # Flash bright colors
        c = colors[i % len(colors)]
        disp.fill(c)
        disp.fill_rect(20, 20, 200, 200, 0x0000)
        disp.rect(20, 20, 200, 200, 0xFFFF)
        disp.text("ESP32-C3 SCREEN TEST", 30, 40, 0xFFFF, 0x0000)
        disp.text(f"Profile: {prof['name'][:16]}", 30, 70, 0x07FF, 0x0000)
        disp.text(f"SCK:{prof['sck']} MOSI:{prof['mosi']}", 30, 100, 0xFFE0, 0x0000)
        disp.text(f"CS:{prof['cs']} DC:{prof['dc']}", 30, 130, 0xFFE0, 0x0000)
        disp.text("IF YOU SEE THIS, THIS IS IT!", 25, 170, 0x07E0, 0x0000)
        print(f"     [OK] Drew test pattern for {prof['name']}. Waiting 3 seconds...")
        time.sleep(2.5)
    except Exception as e:
        print(f"     [FAIL] Error testing {prof['name']}: {e}")

print("\n[+] Pin scan complete! Check your board to see which profile appeared.")
