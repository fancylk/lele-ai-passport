"""乐乐工牌多应用启动器 (§六十六): 多应用 + OTA 升级 + §六十八 启动选主机.

启动流程:
  boot.py (WebREPL + OTA 回滚守卫) → 本文件:
    1. 连接主机选择页 (§六十八): **停住等待用户选择** —— UP/DOWN 切 Mac/Windows,
       OK 确认才继续 (/target.txt 持久化, 高亮上次连接); 不设超时
    2. 应用菜单窗口 2s: 任意键 → 菜单; 否则自动 OTA → 启动 /app.txt 应用
    3. 应用内约定: 长按 OK(>1s) 写 /menu.flag 并重启 → 回菜单
    4. 应用崩溃自动兜底: 显示错误 3s 后回菜单

应用注册表见 apps/menu.py; OTA 升级入口也在菜单里 (走腾讯 nginx HTTP,
scripts/ota_publish.sh 发布). 详见 lele-voice/docs/voice-bridge.md §六十六/§六十八.
"""

import gc
import os
import time
from machine import Pin, SPI, ADC, reset
from config import APP_DEFAULT, STREAM_IP, STREAM_PORT, STREAM_TOKEN
from st7789_direct import ST7789Direct
from chinese_font import draw_string_cn
import keyinput

MENU_FLAG = "/menu.flag"
APP_PATH = "/app.txt"

C_BG     = 0x0841
C_BAR    = 0x000F
C_WHITE  = 0xFFFF
C_GREY   = 0xC618
C_YELLOW = 0xFFE0
C_GREEN  = 0x07E0
C_RED    = 0xF800


def make_display():
    return ST7789Direct(
        spi=SPI(1, baudrate=30000000, polarity=0, phase=0,
                sck=Pin(8), mosi=Pin(9)),
        width=240, height=320,
        cs=Pin(1), dc=Pin(20), rst=None, bl=Pin(21), rotation=0)



def read_btn(adc):
    return keyinput.read_btn(adc)


def current_app():
    try:
        with open(APP_PATH) as f:
            a = f.read().strip()
            if a:
                return a
    except Exception:
        pass
    return APP_DEFAULT


def read_target():
    try:
        with open("/target.txt") as f:
            t = f.read().strip()
            if t in ("mac", "pc"):
                return t
    except Exception:
        pass
    return "mac"


def write_target(t):
    try:
        with open("/target.txt", "w") as f:
            f.write(t)
    except Exception:
        pass


def select_target(display, adc):
    """§七十 启动选主机 (花名册版): 停住等待用户选择, 只允许在线设备.
    页面状态: 连 WiFi → 拉花名册 → 列表选择(UP/DOWN/OK) → TSET 声明 + 持久化.
    失败/空列表: 显示原因, 按 OK 重试 (永不进应用, 直到选定在线主机)."""
    from wifi_manager import WiFiManager
    wifi = WiFiManager()
    while True:
        # 1) WiFi
        display.fill(C_BG)
        display.fill_rect(0, 0, 240, 36, C_BAR)
        draw_string_cn(display, "连接哪台主机?", 8, 10, C_WHITE, C_BAR)
        draw_string_cn(display, "正在连接 WiFi...", 8, 120, C_GREY, C_BG)
        ok = False
        try:
            ok = wifi.connect(timeout=8)
        except Exception:
            pass
        if not ok:
            _wait_retry(display, adc, "WiFi 未连接", "检查路由器后重试")
            continue
        # 2) 花名册
        draw_string_cn(display, "查询在线主机...", 8, 120, C_GREY, C_BG)
        r = rqst_roster()
        if r is None:
            _wait_retry(display, adc, "查询主机列表失败", "服务器无响应, 重试")
            continue
        cur_target, roster = r
        if not roster:
            _wait_retry(display, adc, "暂无在线主机", "主机开机后按 OK 重试")
            continue
        # 3) 列表选择
        idx = 0
        for i, (tag, _, _) in enumerate(roster):
            if tag == (cur_target or read_target()):
                idx = i
                break
        items = roster + [(None, "↻ 刷新列表", "")]
        picked = None
        last_btn = None
        last_t = 0
        while picked is None:
            display.fill(C_BG)
            display.fill_rect(0, 0, 240, 36, C_BAR)
            draw_string_cn(display, "连接哪台主机?", 8, 10, C_WHITE, C_BAR)
            y = 60
            for i, (tag, host, os_name) in enumerate(items):
                if y > 270:
                    break
                cur = "▶" if i == idx else " "
                color = C_GREEN if i == idx else C_WHITE
                label = host[:12] + ("" if os_name == "" else " · " + ("Mac" if os_name == "macos" else os_name[:6]))
                draw_string_cn(display, cur + " " + label, 8, y, color, C_BG)
                y += 30
            draw_string_cn(display, "上下选 · OK 确认", 8, 296, C_GREY, C_BAR)
            btn = read_btn(adc)
            if btn != last_btn and time.ticks_diff(time.ticks_ms(), last_t) > 120:
                last_t = time.ticks_ms()
                if btn == "UP":
                    idx = (idx - 1) % len(items)
                elif btn == "DOWN":
                    idx = (idx + 1) % len(items)
                elif btn == "OK":
                    picked = items[idx]
                last_btn = btn
            time.sleep_ms(20)
        tag, host, _ = picked
        if tag is None:      # 刷新
            continue
        # 4) 声明 + 持久化
        draw_string_cn(display, "连接 %s..." % host[:12], 8, 130, C_YELLOW, C_BG)
        tset_target(tag)
        write_target(tag)
        draw_string_cn(display, "已连接 %s   " % host[:10], 8, 130, C_GREEN, C_BG)
        time.sleep_ms(800)
        return tag


def _wait_retry(display, adc, title, hint):
    display.fill(C_BG)
    display.fill_rect(0, 0, 240, 36, C_BAR)
    draw_string_cn(display, title, 8, 10, C_WHITE, C_BAR)
    draw_string_cn(display, hint, 8, 120, C_GREY, C_BG)
    draw_string_cn(display, "按 OK 重试", 8, 160, C_YELLOW, C_BG)
    while read_btn(adc) != "OK":
        time.sleep_ms(30)
    while read_btn(adc) is not None:   # 等松开
        time.sleep_ms(30)


def splash(display, adc, secs=2):
    """应用菜单窗口. 返回 True=期间有按键 (进菜单)."""
    from apps.registry import APP_NAME
    display.fill(C_BG)
    display.fill_rect(0, 0, 240, 36, C_BAR)
    draw_string_cn(display, "乐乐工牌", 8, 10, C_WHITE, C_BAR)
    app_label = APP_NAME.get(current_app(), current_app())
    draw_string_cn(display, "启动: " + app_label, 8, 60, C_WHITE, C_BG)
    draw_string_cn(display, "任意键 → 应用菜单", 8, 90, C_GREY, C_BG)
    for i in range(secs, 0, -1):
        draw_string_cn(display, "%d " % i, 8, 180, C_YELLOW, C_BG)
        end = time.ticks_add(time.ticks_ms(), 1000)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if read_btn(adc):
                return True
            time.sleep_ms(20)
    return False


def auto_ota(display):
    """开机自动检查更新 (§六十八): 仅当有新版才下载应用; 失败静默继续启动."""
    from wifi_manager import WiFiManager
    draw_string_cn(display, "检查更新…", 8, 220, C_GREY, C_BG)
    wifi = WiFiManager()
    try:
        if not wifi.connect(timeout=8):
            return
    except Exception:
        return
    import ota
    try:
        r = ota.check()
    except Exception as e:
        print("[OTA] 自动检查失败:", e)
        return
    if r is None:
        return
    newv, files = r
    draw_string_cn(display, "发现新版本 v%d, 升级中" % newv, 8, 220, C_YELLOW, C_BG)
    print("[OTA] 自动升级 v%d (%d 文件)…" % (newv, len(files)))
    try:
        ota.download_and_apply(newv, files, log=lambda s2: draw_string_cn(display, s2[:15], 8, 244, C_GREY, C_BG))
        reset()   # 升级成功, 重启进入新固件
    except Exception as e:
        print("[!] 自动 OTA 失败(已可回滚):", e)
        draw_string_cn(display, "升级失败, 继续启动", 8, 244, C_RED, C_BG)
        time.sleep_ms(1500)


def main():
    display = make_display()
    adc = ADC(Pin(0))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass

    for d in ("/apps", "/otastage", "/backup"):
        try:
            os.mkdir(d)
        except OSError:
            pass
    try:
        if "ota" in os.listdir("/"):
            os.rmdir("/ota")
    except Exception:
        pass

    # §六十八补3: 开机先停在选择页, 用户按 OK 确认连接哪台主机 (不设超时)
    select_target(display, adc)

    menu_requested = splash(display, adc)
    if not menu_requested and "menu.flag" in os.listdir("/"):
        menu_requested = True
        try:
            os.remove(MENU_FLAG)
        except Exception:
            pass

    if menu_requested:
        import apps.menu
        apps.menu.run(display, adc)   # 菜单选择后自行写 /app.txt 并 reset
        reset()                        # 菜单返回(取消/异常) → 按当前应用重启

    # 开机自动 OTA (§六十八): WiFi 幂等, 检查 ~2s; 有新版自动升级重启, 无新版直接进应用.
    # v7 升到本版仍需菜单手动一次; 本版起永久自动.
    auto_ota(display)

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
