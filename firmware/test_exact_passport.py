import time
import struct
from machine import Pin, SPI, PWM, ADC

print("=" * 60)
print(" Testing EXACT FoloToy / TRAE AI Passport ST7789P3 Display")
print("=" * 60)

# 1. Backlight on GPIO 21 (PWM 5kHz 100% duty)
bl_pwm = PWM(Pin(21), freq=5000, duty_u16=65535)
print("[+] Backlight enabled on GPIO 21 (100% brightness)")

# 2. SPI Initialization
# MOSI=9, SCLK=8, CS=1, DC=20, Width=240, Height=320
spi = SPI(1, baudrate=30000000, polarity=0, phase=0, sck=Pin(8), mosi=Pin(9))
cs = Pin(1, Pin.OUT, value=1)
dc = Pin(20, Pin.OUT, value=0)

def write_cmd(c):
    dc.value(0)
    cs.value(0)
    spi.write(bytearray([c]))
    cs.value(1)

def write_data(d):
    dc.value(1)
    cs.value(0)
    if isinstance(d, int):
        spi.write(bytearray([d]))
    elif isinstance(d, list):
        spi.write(bytearray(d))
    else:
        spi.write(d)
    cs.value(1)

print("[+] Initializing ST7789P3 Panel with Factory Gamma & Power sequences...")

# SWRESET
write_cmd(0x01)
time.sleep_ms(150)

# SLPOUT
write_cmd(0x11)
time.sleep_ms(120)

# COLMOD: 16-bit RGB565
write_cmd(0x3A)
write_data(0x55)

# Factory ST7789P3 Initialization Table
ST7789P3_CMDS = [
    (0xB2, [0x05, 0x05, 0x00, 0x33, 0x33]),  # PORCTRL
    (0xB7, [0x35]),                          # GCTRL
    (0xBB, [0x21]),                          # VCOMS
    (0xC0, [0x2C]),                          # LCMCTRL
    (0xC2, [0x01]),                          # VDVVRHEN
    (0xC3, [0x0B]),                          # VRHS
    (0xC4, [0x20]),                          # VDVSET
    (0xC6, [0x0F]),                          # FRCTRL2 60Hz
    (0xD0, [0xA7, 0xA1]),                    # PWCTRL1
    (0xD0, [0xA4, 0xA1]),                    # PWCTRL1
    (0xD6, [0xA1]),
    (0xE0, [0xD0, 0x04, 0x08, 0x0A, 0x09, 0x05, 0x2D, 0x43, 0x49, 0x09, 0x16, 0x15, 0x26, 0x2B]), # Positive Gamma
    (0xE1, [0xD0, 0x03, 0x09, 0x0A, 0x0A, 0x06, 0x2E, 0x44, 0x40, 0x3A, 0x15, 0x15, 0x26, 0x2A]), # Negative Gamma
]

for cmd, data in ST7789P3_CMDS:
    write_cmd(cmd)
    write_data(data)

# Invert Color
write_cmd(0x21) # INVON

# MADCTL (Orientation: 0x00 Portrait 240x320)
write_cmd(0x36)
write_data(0x00)

# Display ON
write_cmd(0x13) # NORON
time.sleep_ms(10)
write_cmd(0x29) # DISPON
time.sleep_ms(100)

print("[+] Display Ready! Drawing Crisp UI Test Pattern...")

# Set Address Window: 0..239 x 0..319
write_cmd(0x2A) # CASET
write_data([0, 0, 0, 239])
write_cmd(0x2B) # RASET
write_data([0, 0, 1, 63]) # 319 = 0x013F
write_cmd(0x2C) # RAMWR

# Draw 240x320 Color Blocks (Dark Navy Background + Vivid Cards)
WIDTH = 240
HEIGHT = 320

# 1. Header (Dark Navy)
c_navy = struct.pack(">H", 0x000F) * WIDTH
# 2. Cyan Card
c_cyan = struct.pack(">H", 0x07FF) * WIDTH
# 3. Green Card
c_green = struct.pack(">H", 0x07E0) * WIDTH
# 4. Orange Card
c_orange = struct.pack(">H", 0xFD20) * WIDTH
# 5. Red Card
c_red = struct.pack(">H", 0xF800) * WIDTH
# 6. White Card
c_white = struct.pack(">H", 0xFFFF) * WIDTH
# 7. Black
c_black = struct.pack(">H", 0x0000) * WIDTH

dc.value(1)
cs.value(0)

# Header: 40 lines
for _ in range(40):
    spi.write(c_navy)

# Cyan Block: 45 lines
for _ in range(45):
    spi.write(c_cyan)

# Green Block: 45 lines
for _ in range(45):
    spi.write(c_green)

# Orange Block: 45 lines
for _ in range(45):
    spi.write(c_orange)

# Red Block: 45 lines
for _ in range(45):
    spi.write(c_red)

# White Block: 45 lines
for _ in range(45):
    spi.write(c_white)

# Footer: 55 lines
for _ in range(55):
    spi.write(c_navy)

cs.value(1)

print("[+] ST7789P3 Drawing Complete! Look at the card screen now!")
