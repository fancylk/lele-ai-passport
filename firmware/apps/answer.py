"""答案之书 (§六十六, 自 ESP-IDF demo_answer.c 移植到 MicroPython):
心中默想一个问题, 按任意键翻开一页神秘答案. 200 条签文, 连续两次不重复.
按键: UP/DOWN/OK 任意 = 翻开; 长按 OK = 回应用菜单."""

import machine
import os
import random
import time

from machine import Pin, SPI, ADC
from st7789_direct import ST7789Direct
from chinese_font import draw_string_cn
from apps.answer_data import ANSWERS
from keyinput import read_btn as _read_btn

MENU_FLAG = "/menu.flag"
OK_MENU_MS = 1000

C_NIGHT  = 0x000A   # 深夜蓝黑
C_STAR   = 0x4210   # 暗星
C_GOLD   = 0xFD20   # 鎏金
C_WHITE  = 0xFFFF
C_GREY   = 0x630C




def _stars(display):
    display.fill(C_NIGHT)
    for _ in range(60):
        x = random.getrandbits(8) * 240 // 256
        y = random.getrandbits(8) * 320 // 256
        display.fill_rect(x, y, 1, 1, C_STAR)


def _wrap(text, width=11):
    return [text[i:i + width] for i in range(0, len(text), width)]


def run(display=None):
    print("[+] 答案之书")
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

    last_answer = None
    ok_down = None
    ok_menu_fired = False
    last_btn = None
    last_t = 0

    _stars(display)
    display.fill_rect(0, 40, 240, 60, C_NIGHT)
    draw_string_cn(display, "答案之书", 80, 48, C_GOLD, C_NIGHT)
    draw_string_cn(display, "心中默想一个问题", 30, 150, C_GREY, C_NIGHT)
    draw_string_cn(display, "按任意键翻开", 52, 176, C_GREY, C_NIGHT)
    display.fill_rect(0, 296, 240, 24, C_NIGHT)
    draw_string_cn(display, "按键翻页 长按OK菜单", 8, 301, C_GREY, C_NIGHT)

    while True:
        now = time.ticks_ms()
        btn = _read_btn(adc)
        if btn != last_btn and time.ticks_diff(now, last_t) > 120:
            last_t = now
            if btn and not ok_menu_fired:
                if btn == "OK":
                    ok_down = now
                    ok_menu_fired = False
                else:
                    ok_down = None
                # 翻开一页
                i = random.getrandbits(8) % len(ANSWERS)
                if i == last_answer:
                    i = (i + 1) % len(ANSWERS)
                last_answer = i
                ans = ANSWERS[i]
                _stars(display)
                display.fill_rect(0, 40, 240, 60, C_NIGHT)
                draw_string_cn(display, "第 %d 页" % (i + 1), 72, 48, C_GREY, C_NIGHT)
                display.fill_rect(30, 110, 180, 96, C_NIGHT)
                color = C_GOLD if len(ans) <= 6 else C_WHITE
                for j, line in enumerate(_wrap(ans)):
                    x = 120 - len(line) * 8
                    draw_string_cn(display, line, x, 122 + j * 28, color, C_NIGHT)
                draw_string_cn(display, "再按继续 · 长按OK菜单", 8, 240, C_GREY, C_NIGHT)
                time.sleep_ms(250)   # 翻页防抖
            elif not btn:
                last_answer = last_answer  # 释放无操作
            last_btn = btn
        # OK 长按 → 菜单
        if btn == "OK" and ok_down is not None and not ok_menu_fired \
                and time.ticks_diff(now, ok_down) > OK_MENU_MS:
            ok_menu_fired = True
            try:
                open(MENU_FLAG, "w").write("1")
            except Exception:
                pass
            machine.reset()
        time.sleep_ms(10)
