"""应用菜单 (§六十六): UP/DOWN 选择, OK 确认; 含 OTA 检查更新入口."""

import machine
import os
import time

from chinese_font import draw_string_cn
import ota
from keyinput import read_btn as _read_btn
from apps.registry import APPS, APP_NAME

APP_PATH = "/app.txt"
APP_DEFAULT = "voice_bridge"

C_BG     = 0x0841
C_BAR    = 0x000F
C_WHITE  = 0xFFFF
C_GREY   = 0xC618
C_YELLOW = 0xFFE0
C_GREEN  = 0x07E0
C_RED    = 0xF800




def _render(display, items, idx, note):
    display.fill(C_BG)
    display.fill_rect(0, 0, 240, 36, C_BAR)
    draw_string_cn(display, "应用菜单", 8, 10, C_WHITE, C_BAR)
    for i, (_, label) in enumerate(items):
        y = 60 + i * 30
        cur = "▶" if i == idx else "  "
        color = C_GREEN if i == idx else C_WHITE
        draw_string_cn(display, cur + " " + label, 16, y, color, C_BG)
    y_ota = 60 + len(items) * 30
    cur = "▶" if idx == len(items) else "  "
    color = C_GREEN if idx == len(items) else C_WHITE
    draw_string_cn(display, cur + " OTA 检查更新", 16, y_ota, color, C_BG)
    display.fill_rect(0, 296, 240, 24, C_BAR)
    draw_string_cn(display, "上下选 OK确认", 8, 301, C_GREY, C_BAR)
    if note:
        display.fill_rect(0, 262, 240, 24, C_BG)
        draw_string_cn(display, note[:14], 8, 266, C_YELLOW, C_BG)


def run(display, adc):
    print("[+] 应用菜单")
    try:
        cur = open(APP_PATH).read().strip()
    except Exception:
        cur = APP_DEFAULT
    idx = 0
    for i, (mod, _) in enumerate(APPS):
        if mod == cur:
            idx = i
            break
    items = APPS + [("ota", "OTA 检查更新")]
    note = ""
    last_btn = None
    last_t = 0
    while True:
        btn = _read_btn(adc)
        if btn != last_btn and time.ticks_diff(time.ticks_ms(), last_t) > 150:
            last_t = time.ticks_ms()
            if btn == "UP" and idx > 0:
                idx -= 1
                _render(display, items, idx, note)
            elif btn == "DOWN" and idx < len(items) - 1:
                idx += 1
                _render(display, items, idx, note)
            elif btn == "OK":
                mod, label = items[idx]
                if mod == "ota":
                    note = _ota_flow(display)
                    _render(display, items, idx, note)
                else:
                    try:
                        with open(APP_PATH, "w") as f:
                            f.write(mod)
                    except Exception:
                        pass
                    print("[+] 选择应用:", mod, "→ 重启")
                    machine.reset()
            last_btn = btn


def _ota_flow(display):
    """WiFi 连接 → 检查 → 下载应用 → 重启. 返回给菜单的提示文字(不重启的情况)."""
    from wifi_manager import WiFiManager
    _line(display, "OTA: 连接 WiFi...")
    wifi = WiFiManager()
    try:
        if not wifi.connect(timeout=8):
            return "OTA: WiFi 未连上"
    except Exception:
        return "OTA: WiFi 异常"
    _line(display, "OTA: 检查版本...")
    try:
        r = ota.check()
    except Exception as e:
        return "OTA: %s" % str(e)[:14]
    if r is None:
        _line(display, "OTA: 已是最新")
        time.sleep(1.2)
        return "已是最新"
    newv, files = r
    _line(display, "OTA: 更新 v%d %d个" % (newv, len(files)))
    try:
        ota.download_and_apply(newv, files, log=lambda s: _line(display, s[:14]))
    except Exception as e:
        _line(display, "OTA 失败, 已回滚")
        print("[!] OTA 失败:", e)
        time.sleep(1.5)
        return "OTA 失败"
    machine.reset()   # 升级成功, 重启进入新固件


def _line(display, text):
    display.fill_rect(0, 262, 240, 24, C_BG)
    draw_string_cn(display, text[:15], 8, 266, C_YELLOW, C_BG)
