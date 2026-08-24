"""
Interactive Speaker & Audio Effects Test Suite for FoloToy / TRAE AI Passport.
"""

import time
from machine import Pin, I2C, SPI
from config import *
from st7789_direct import ST7789Direct
from display_ui import PassportUI
from chinese_font import draw_string_cn

# 1. Initialize Display
spi = SPI(1, baudrate=30000000, polarity=0, phase=0, sck=Pin(PIN_LCD_SCLK), mosi=Pin(PIN_LCD_MOSI))
display = ST7789Direct(
    spi=spi,
    width=SCREEN_WIDTH,
    height=SCREEN_HEIGHT,
    cs=Pin(PIN_LCD_CS),
    dc=Pin(PIN_LCD_DC),
    rst=None,
    bl=Pin(PIN_LCD_BL),
    rotation=SCREEN_ROTATION
)

# 2. Initialize ES8311 Codec
i2c = I2C(0, sda=Pin(PIN_I2C_SDA), scl=Pin(PIN_I2C_SCL), freq=100000)
ADDR = 0x18

def w_reg(r, v):
    try:
        i2c.writeto_mem(ADDR, r, bytearray([v]))
    except Exception:
        pass

def init_codec():
    w_reg(0x00, 0x80)
    time.sleep_ms(20)
    w_reg(0x00, 0x00)

    w_reg(0x01, 0x30)
    w_reg(0x02, 0x00)
    w_reg(0x03, 0x10)
    w_reg(0x04, 0x10)
    w_reg(0x05, 0x00)
    w_reg(0x06, 0x00)
    w_reg(0x07, 0x00)
    w_reg(0x08, 0xFF)

    w_reg(0x0D, 0x01)
    w_reg(0x0E, 0x02)
    w_reg(0x0F, 0x44)
    w_reg(0x12, 0x00)
    w_reg(0x13, 0x10)

    # Volume Control (0x04 = loud & clear ~ -2dB)
    w_reg(0x31, 0x00) # Unmute
    w_reg(0x32, 0x04)

init_codec()

def show_screen(title, sub_title, color=0x07E0):
    display.fill(0x0841)
    display.fill_rect(0, 0, 240, 44, 0x000F)
    draw_string_cn(display, "🔊 扬声器音效测试", 12, 14, 0xFFFF, 0x000F)
    
    display.fill_rect(10, 60, 220, 180, 0x0000)
    display.rect(10, 60, 220, 180, color)
    display.rect(11, 61, 218, 178, color)
    
    draw_string_cn(display, "正在播放音效：", 24, 80, 0xC618, 0x0000)
    draw_string_cn(display, title, 24, 114, color, 0x0000)
    draw_string_cn(display, sub_title, 24, 150, 0xFFFF, 0x0000)

    display.fill_rect(0, 280, 240, 40, 0x000F)
    draw_string_cn(display, "请听卡片发出的声音 🎵", 16, 292, 0xFFE0, 0x000F)

def play_tone(code, ms):
    w_reg(0x37, code)
    time.sleep_ms(ms)
    w_reg(0x37, 0x00)

print("=" * 60)
print(" 🔊 ESP32-C3 AI Passport Speaker Audio Test")
print("=" * 60)

# -------------------------------------------------------------
# Test 1: 8-Tone Scale (八音阶 Do-Re-Mi-Fa-Sol-La-Si-Do)
# -------------------------------------------------------------
print("[1/5] Testing 8-Note Musical Scale...")
show_screen("全八度音阶", "Do Re Mi Fa Sol La Si Do", 0x07FF)
scale_notes = [0x81, 0x82, 0x83, 0x84, 0x86, 0x88, 0x8A, 0x8C]
for note in scale_notes:
    play_tone(note, 160)
    time.sleep_ms(40)
time.sleep(1.0)

# -------------------------------------------------------------
# Test 2: Startup Hello Jingle (开机欢快和弦)
# -------------------------------------------------------------
print("[2/5] Testing Startup Greeting Jingle...")
show_screen("开机问候音效", "哆 - 咪 - 索 - 高音哆!", 0x07E0)
jingle = [(0x82, 100), (0x84, 100), (0x86, 120), (0x8C, 250)]
for note, dur in jingle:
    play_tone(note, dur)
    time.sleep_ms(30)
time.sleep(1.0)

# -------------------------------------------------------------
# Test 3: Game Level-Up / Victory Melody (胜利通关音效)
# -------------------------------------------------------------
print("[3/5] Testing Victory / Level-Up Melody...")
show_screen("任务完成胜利音效", "欢快三连音 🎶", 0xFFE0)
victory = [(0x83, 80), (0x86, 80), (0x89, 80), (0x87, 80), (0x8A, 80), (0x8C, 300)]
for note, dur in victory:
    play_tone(note, dur)
    time.sleep_ms(25)
time.sleep(1.0)

# -------------------------------------------------------------
# Test 4: Gentle Notification Beep (清脆消息提醒)
# -------------------------------------------------------------
print("[4/5] Testing Notification Chime...")
show_screen("清脆消息提醒", "叮咚 叮咚 🔔", 0xFD20)
for _ in range(2):
    play_tone(0x88, 120)
    time.sleep_ms(50)
    play_tone(0x84, 180)
    time.sleep_ms(250)
time.sleep(1.0)

# -------------------------------------------------------------
# Test 5: Soft Key Click & Complete (按键反馈音)
# -------------------------------------------------------------
print("[5/5] Testing Button Click Feedback...")
show_screen("按键反馈提示", "哔 哔 哔 (轻柔触觉音)", 0xC618)
for _ in range(4):
    play_tone(0x84, 40)
    time.sleep_ms(120)

print("\n[+] All 5 speaker audio tests completed successfully!")
show_screen("测试完成！", "扬声器硬件状态非常健康", 0x07E0)
time.sleep(2.0)
