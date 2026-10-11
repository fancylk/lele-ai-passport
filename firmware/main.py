"""乐乐工牌多应用启动器 (§六十六): 多应用 + OTA 升级.

启动流程:
  boot.py (WebREPL + OTA 回滚守卫) → 本文件:
    1. 开机画面 3s: 期间任意键 → 应用菜单; 否则启动 /app.txt 里的应用 (默认远程麦克风)
    2. 应用内约定: 长按 OK(>1s) 写 /menu.flag 并重启 → 回菜单
    3. 应用崩溃自动兜底: 显示错误 3s 后回菜单

应用注册表见 apps/menu.py; OTA 升级入口也在菜单里 (走腾讯 nginx HTTP,
scripts/ota_publish.sh 发布). 详见 lele-voice/docs/voice-bridge.md §六十六.
"""

import gc
import os
import time
from machine import Pin, SPI, ADC, reset
from config import APP_DEFAULT
from st7789_direct import ST7789Direct
from chinese_font import draw_string_cn

MENU_FLAG = "/menu.flag"
APP_PATH = "/app.txt"

C_BG     = 0x0841
C_BAR    = 0x000F
C_WHITE  = 0xFFFF
C_GREY   = 0xC618
C_YELLOW = 0xFFE0
C_GREEN  = 0x07E0


def make_display():
    return ST7789Direct(
        spi=SPI(1, baudrate=30000000, polarity=0, phase=0,
                sck=Pin(8), mosi=Pin(9)),
        width=240, height=320,
        cs=Pin(1), dc=Pin(20), rst=None, bl=Pin(21), rotation=0)


def read_btn(adc):
    try:
        mv = (adc.read() * 3300) // 4095
    except Exception:
        return None
    if mv < 300:
        return "UP"
    elif 300 <= mv < 800:
        return "DOWN"
    elif 800 <= mv < 2200:
        return "OK"
    return None


def current_app():
    try:
        with open(APP_PATH) as f:
            a = f.read().strip()
            if a:
                return a
    except Exception:
        pass
    return APP_DEFAULT


def splash(display, adc, secs=3):
    """开机画面 + 倒计时. 返回 True=期间有按键 (进菜单)."""
    from apps.registry import APP_NAME
    display.fill(C_BG)
    display.fill_rect(0, 0, 240, 36, C_BAR)
    draw_string_cn(display, "乐乐工牌", 8, 10, C_WHITE, C_BAR)
    app_label = APP_NAME.get(current_app(), current_app())
    draw_string_cn(display, "启动: " + app_label, 8, 60, C_WHITE, C_BG)
    draw_string_cn(display, "任意键 → 应用菜单", 8, 90, C_GREY, C_BG)
    draw_string_cn(display, "多应用 + OTA §六十六", 8, 120, C_GREY, C_BG)
    for i in range(secs, 0, -1):
        draw_string_cn(display, "%d " % i, 8, 180, C_YELLOW, C_BG)
        end = time.ticks_add(time.ticks_ms(), 1000)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if read_btn(adc):
                return True
            time.sleep_ms(20)
    return False


def main():
    display = make_display()
    adc = ADC(Pin(0))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass

    for d in ("/apps", "/ota", "/backup"):
        try:
            os.mkdir(d)
        except OSError:
            pass

    menu_requested = splash(display, adc)
    if not menu_requested and MENU_FLAG in os.listdir("/"):
        menu_requested = True
        try:
            os.remove(MENU_FLAG)
        except Exception:
            pass

    if menu_requested:
        import apps.menu
        apps.menu.run(display, adc)   # 菜单选择后自行写 /app.txt 并 reset
        reset()                        # 菜单返回(取消/异常) → 按当前应用重启

    app = current_app()
    gc.collect()
    try:
        draw_string_cn(display, "加载 " + app, 8, 220, C_GREY, C_BG)
        # 注意: __import__("apps.x") 返回父包, 子模块取 sys.modules
        __import__("apps." + app)
        mod = __import__("apps." + app)
        import sys
        mod = sys.modules.get("apps." + app) or getattr(mod, app)
        mod.run(display)
        # 应用正常返回(不应发生) → 重启回启动器
    except Exception as e:
        import sys
        sys.print_exception(e)
        display.fill_rect(0, 240, 240, 56, C_BAR)
        draw_string_cn(display, "应用出错, 回菜单", 8, 244, C_RED, C_BAR)
        time.sleep_ms(3000)
    reset()


main()
