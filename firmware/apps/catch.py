"""左右接球游戏 (§六十六, MicroPython 重写; 原 ESP-IDF LVGL 版见 git 历史):
UP=左移 DOWN=右移, 接住下落的球 +1 分, 漏球 -1 命 (3 命), 球速渐增.
按键: OK 长按 = 回应用菜单; 游戏结束按任意键再来一局."""

import machine
import os
import random
import time

from machine import Pin, SPI, ADC
from st7789_direct import ST7789Direct
from chinese_font import draw_string_cn
from keyinput import read_btn as _read_btn

MENU_FLAG = "/menu.flag"
OK_MENU_MS = 1000

C_BG     = 0x0000
C_PADDLE = 0x07FF   # 青色球拍
C_BALL   = 0xFD20   # 金球
C_WHITE  = 0xFFFF
C_GREY   = 0x630C
C_RED    = 0xF800
C_GREEN  = 0x07E0

W, H = 240, 320
PW = 64             # 球拍宽
PH = 8
PADDLE_Y = H - 30




def _hud(display, score, lives):
    display.fill_rect(0, 0, 240, 20, C_BG)
    draw_string_cn(display, "得分:%d  命:%d" % (score, lives), 8, 2, C_WHITE, C_BG)


def run(display=None):
    print("[+] 接球游戏")
    if display is None:
        display = ST7789Direct(
            spi=SPI(1, baudrate=30000000, polarity=0, phase=0,
                    sck=Pin(8), mosi=Pin(9)),
            width=240, height=320,
            cs=Pin(1), dc=Pin(20), rst=None, bl=Pin(21), rotation=0)
    adc = ADC(Pin(0))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass

    display.fill(C_BG)
    display.fill_rect(0, 40, 240, 60, C_BG)
    draw_string_cn(display, "左右接球", 80, 48, C_PADDLE, C_BG)
    draw_string_cn(display, "上=左移 下=右移", 34, 150, C_WHITE, C_BG)
    draw_string_cn(display, "OK 长按回菜单", 52, 180, C_GREY, C_BG)

    while True:
        # 等开局按键 (任意键开始; OK 长按可回菜单)
        ok_down = None
        while True:
            btn = _read_btn(adc)
            if btn in ("UP", "DOWN"):
                break
            if btn == "OK":
                if ok_down is None:
                    ok_down = time.ticks_ms()
                elif time.ticks_diff(time.ticks_ms(), ok_down) > OK_MENU_MS:
                    try:
                        open(MENU_FLAG, "w").write("1")
                    except Exception:
                        pass
                    machine.reset()
            else:
                ok_down = None
            time.sleep_ms(20)

        # 一局
        score = 0
        lives = 3
        speed = 3.0
        px = (W - PW) // 2
        bx = random.getrandbits(7) * (W - 8) // 128
        by = 24.0
        prev = None
        ok_down = None
        while lives > 0:
            now = time.ticks_ms()
            btn = _read_btn(adc)
            if btn == "UP":
                px = max(0, px - 14)
            elif btn == "DOWN":
                px = min(W - PW, px + 14)
            if btn == "OK":
                if ok_down is None:
                    ok_down = now
                elif time.ticks_diff(now, ok_down) > OK_MENU_MS:
                    try:
                        open(MENU_FLAG, "w").write("1")
                    except Exception:
                        pass
                    machine.reset()
            else:
                ok_down = None

            # 球
            old_b = (int(bx), int(by))
            by += speed
            caught = False
            if by >= PADDLE_Y - 6 and by <= PADDLE_Y + PH:
                if px - 6 <= old_b[0] <= px + PW + 6:
                    caught = True
            if caught:
                score += 1
                speed = min(9.0, speed + 0.35)
                bx = random.getrandbits(7) * (W - 8) // 128
                by = 24.0
            elif by > H - 8:
                lives -= 1
                bx = random.getrandbits(7) * (W - 8) // 128
                by = 24.0
                speed = max(3.0, speed - 0.5)

            # 绘制 (增量)
            if prev:
                display.fill_rect(prev[0], prev[1], 6, 6, C_BG)
                display.fill_rect(prev[2], PADDLE_Y, PW, PH, C_BG)
            display.fill_rect(int(bx), int(by), 6, 6, C_BALL)
            display.fill_rect(px, PADDLE_Y, PW, PH, C_PADDLE)
            prev = (int(bx), int(by), px)
            _hud(display, score, lives)
            if caught or by > H - 10:
                display.fill_rect(0, 296, 240, 24, C_BG)
                draw_string_cn(display,
                               "接住!" if caught else "漏球!",
                               96, 300, C_GREEN if caught else C_RED, C_BG)
            time.sleep_ms(18)

        display.fill(C_BG)
        draw_string_cn(display, "本局得分: %d" % score, 52, 130, C_WHITE, C_BG)
        draw_string_cn(display, "任意键再来一局", 34, 170, C_GREY, C_BG)
        draw_string_cn(display, "OK 长按回菜单", 52, 200, C_GREY, C_BG)
        time.sleep_ms(600)
