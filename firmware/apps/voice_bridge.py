"""远程麦克风应用 (乐乐语音桥, §六十四/§六十五) —— 由多应用启动器调起 (§六十六).

按键: 上=语音开关 下=按住说话 OK=翻页, 长按OK=菜单 (目标主机在开机页选择 §六十八)
语音关 = 广播控制帧 + 1.5s 收尾宽限后静音省电; 开机即待机, 握手照发保中转注册.
屏幕实时显示到主机端的延迟(RTT)/码率/丢包/信号.

性能铁律(实测): 8.5ms/汉字 + 56ms/整页清除 → 整页重画≈500ms 会饿死 32ms 的
音频节拍. 因此整页只在启动/翻页时画一次, 运行期每 500ms 只增量刷新一行.
"""

import gc
import os
import time
from machine import Pin, SPI, ADC, I2C
from config import (STREAM_IP, STREAM_PORT, PING_PORT, SAMPLE_RATE, CHUNK_BYTES)
from st7789_direct import ST7789Direct
from chinese_font import draw_string_cn
from wifi_manager import WiFiManager
from battery import BatteryGauge
from voice_stream import VoiceStream

# --- 颜色 ---
C_BG      = 0x0841
C_BAR     = 0x000F
C_WHITE   = 0xFFFF
C_GREY    = 0xC618
C_GREEN   = 0x07E0
C_RED     = 0xF800
C_YELLOW  = 0xFFE0
C_CYAN    = 0x07FF

BOOT_TIME = 0

# 页面行 y 坐标 (16px 字高, 行距 28)
Y_STATUS = 48
Y_RTT    = 78
Y_HOST   = 108
Y_RATE   = 138
Y_SENT   = 168
Y_RSSI   = 198
Y_DETAIL0 = 48   # 详情页起始, 行距 24

MENU_FLAG = "/menu.flag"
OK_MENU_MS = 1000   # 长按 OK 回菜单


class BridgeUI:
    def __init__(self, display):
        self.d = display
        self.page = 0
        self.battery_pct = 100

    def line(self, y, text, fg, bg=C_BG):
        """增量刷新一行: 清 24px 高的行再画字 (~10-15ms+8.5ms/字)."""
        self.d.fill_rect(0, y, 240, 20, bg)
        draw_string_cn(self.d, text, 8, y, fg, bg)

    def frame(self):
        self.d.fill(C_BG)
        self.d.fill_rect(0, 0, 240, 36, C_BAR)
        draw_string_cn(self.d, "乐乐语音桥", 8, 10, C_WHITE, C_BAR)
        self.d.fill_rect(0, 296, 240, 24, C_BAR)
        draw_string_cn(self.d, "上语音 下说话 长按OK菜单", 8, 301, C_GREY, C_BAR)

    def full_render(self, connected, stream_ok, voice, rssi):
        """整页重画 (只在启动/翻页时调用, ≈500ms)."""
        self.frame()
        if self.page == 0:
            self.line(Y_STATUS, self._status_text(connected, stream_ok, voice),
                      self._status_color(connected, stream_ok, voice))
            self.line(Y_RTT, "延迟 RTT: ---", C_GREY)
            tgt = getattr(voice, "target", "mac")
            self.line(Y_HOST, "目标: %s" % ("Windows" if tgt == "pc" else "Mac"), C_CYAN)
            self.line(Y_RATE, "码率: %dkbps" % (SAMPLE_RATE * 16 // 1024), C_WHITE)
            self.line(Y_SENT, "已发: 0B", C_WHITE)
            self.line(Y_RSSI, "WiFi 信号: %s" % (rssi or "---"), C_WHITE)
        else:
            for i, t in enumerate(self._detail_lines(voice, connected)):
                self.line(Y_DETAIL0 + i * 24, t, C_WHITE)
        draw_string_cn(self.d, "%d%%" % self.battery_pct, 174, 10, C_YELLOW, C_BAR)

    def _status_text(self, connected, stream_ok, v):
        if not connected:
            return "✗ WiFi 未连接"
        if not stream_ok:
            return "✗ 推流未启动"
        if v.ptt_active:
            return "🎙 按住说话..."
        if v.dict_on:
            return "🎙 语音输入中"
        if v.muted:
            return "⏸ 待机 (上键开语音)"
        return "● 推流中"

    def _status_color(self, connected, stream_ok, v):
        if not connected or not stream_ok:
            return C_RED
        if v.muted and not v.ptt_active and not v.dict_on:
            return C_YELLOW
        return C_GREEN

    def _detail_lines(self, v, connected):
        up_s = time.ticks_diff(time.ticks_ms(), BOOT_TIME) // 1000
        return [
            "── 详情 ──",
            "本机 IP: %s" % (wifi.ip if connected else "---"),
            "探测端口: %d" % PING_PORT,
            "RTT 最小: %s" % (v.rtt_min if v.rtt_min is not None else "---"),
            "RTT 最大: %s" % (v.rtt_max if v.rtt_max is not None else "---"),
            "PING 发/收: %d/%d" % (v.pings_sent, v.pongs_recv),
            "丢 PING: %d" % max(0, v.pings_sent - v.pongs_recv),
            "发送错误: %d" % v.send_errors,
            "块: %dB=32ms  %dHz" % (CHUNK_BYTES, SAMPLE_RATE),
            "Codec: %s  运行: %02d:%02d" % ("OK" if codec_ok else "失败",
                                            up_s // 60, up_s % 60),
        ]


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


def fmt_bytes(n):
    if n >= 1 << 20:
        return "%.1fMB" % (n / (1 << 20))
    if n >= 1 << 10:
        return "%.1fKB" % (n / (1 << 10))
    return "%dB" % n


def run(display=None):
    global BOOT_TIME, wifi, voice, codec_ok
    import machine
    BOOT_TIME = time.ticks_ms()
    print("[+] 远程麦克风应用启动")
    if display is None:
        display = ST7789Direct(
            spi=SPI(1, baudrate=30000000, polarity=0, phase=0,
                    sck=Pin(8), mosi=Pin(9)),
            width=240, height=320,
            cs=Pin(1), dc=Pin(20), rst=None, bl=Pin(21), rotation=0)
    ui = BridgeUI(display)

    shared_i2c = None
    try:
        shared_i2c = I2C(0, sda=Pin(10), scl=Pin(7), freq=100000)
    except Exception:
        pass

    battery = BatteryGauge(i2c=shared_i2c, addr=0x63)

    wifi = WiFiManager()
    connected = False
    try:
        connected = wifi.connect(timeout=6)
    except Exception:
        pass

    voice = VoiceStream(i2c=shared_i2c)
    codec_ok = voice.init_codec()
    stream_ok = voice.start() if codec_ok else False
    if connected:
        voice.announce_target()   # §六十八: 开机选定的目标声明给中转

    adc = ADC(Pin(0))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass

    if not stream_ok:
        ui.frame()
        ui.line(Y_STATUS, "音频链路初始化失败!", C_RED)
        ui.line(Y_RTT, "检查 I2S/ES8311", C_GREY)
        ui.line(Y_HOST, "查看 REPL 日志", C_YELLOW)
    else:
        try:
            ui.battery_pct, _ = battery.get_info()
        except Exception:
            pass
        ui.full_render(connected, stream_ok, voice, None)

    last_btn = None
    last_btn_time = 0
    ok_down_ms = None        # OK 按下时刻: 点按=翻页, 长按>1s=回菜单
    ok_long_fired = False
    tick = 0
    last_ui = time.ticks_ms()

    while True:
        now = time.ticks_ms()
        btn = read_btn(adc)
        # 按键边沿检测: 未过防抖门的边沿不更新 last_btn → 事件延迟而非丢失
        if btn != last_btn and time.ticks_diff(now, last_btn_time) > 120:
            last_btn_time = now
            if last_btn == "DOWN" and btn != "DOWN" and stream_ok:
                voice.set_ptt(False)     # 抬起 (释放弹跳经过 OK 电压段也按抬起处理)
                ui.line(Y_STATUS, ui._status_text(connected, stream_ok, voice),
                        ui._status_color(connected, stream_ok, voice))
            elif btn == "DOWN" and stream_ok and last_btn != "DOWN":
                voice.set_ptt(True)
                ui.line(Y_STATUS, ui._status_text(connected, stream_ok, voice),
                        ui._status_color(connected, stream_ok, voice))
            elif btn == "UP" and stream_ok and last_btn != "DOWN":
                voice.set_dict_mode(not voice.dict_on)
                ui.line(Y_STATUS, ui._status_text(connected, stream_ok, voice),
                        ui._status_color(connected, stream_ok, voice))
            elif btn == "OK" and last_btn != "DOWN":
                ok_down_ms = now
                ok_long_fired = False
            elif btn is None and last_btn == "OK":
                if ok_down_ms is not None and not ok_long_fired:
                    ui.page = 1 - ui.page
                    ui.full_render(connected, stream_ok, voice, None)
                ok_down_ms = None
            last_btn = btn
        # OK 长按 ≥1s → 重启进应用菜单 (§六十六)
        if btn == "OK" and ok_down_ms is not None and not ok_long_fired \
                and time.ticks_diff(now, ok_down_ms) > OK_MENU_MS:
            ok_long_fired = True
            try:
                open(MENU_FLAG, "w").write("1")
            except Exception:
                pass
            machine.reset()

        if stream_ok:
            voice.poll()                 # 32ms 节拍, 音频优先

        # WiFi 看门狗
        if wifi.wlan and not wifi.wlan.isconnected():
            connected = False
            try:
                wifi.connect(timeout=4)
                connected = wifi.is_connected
                if connected:
                    voice.announce_target()
                ui.full_render(connected, stream_ok, voice, None)
            except Exception:
                pass

        # 每 500ms 增量刷新一行 (轮转), 绝不整页
        if time.ticks_diff(time.ticks_ms(), last_ui) >= 500:
            last_ui = time.ticks_ms()
            tick = (tick + 1) % 4
            if ui.page == 0:
                if tick == 0:
                    fresh = voice.rtt_ms if (voice.last_pong_ms and
                            time.ticks_diff(time.ticks_ms(), voice.last_pong_ms) < 4000) else None
                    if fresh is None:
                        ui.line(Y_RTT, "延迟 RTT: ---", C_GREY)
                    else:
                        color = C_GREEN if fresh < 30 else (C_YELLOW if fresh < 80 else C_RED)
                        ui.line(Y_RTT, "延迟 RTT: %dms" % fresh, color)
                elif tick == 1:
                    ui.line(Y_SENT, "已发: %s (%d包)" % (fmt_bytes(voice.bytes_sent), voice.pkts), C_WHITE)
                elif tick == 2:
                    rssi = None
                    try:
                        if wifi.wlan.isconnected():
                            rssi = wifi.wlan.status("rssi")
                    except Exception:
                        pass
                    ui.line(Y_RSSI, "WiFi 信号: %s" % (("%d dBm" % rssi) if rssi else "---"), C_WHITE)
                else:
                    try:
                        ui.battery_pct, _ = battery.get_info()
                    except Exception:
                        pass
                    draw_string_cn(display, "%d%%" % ui.battery_pct, 174, 10, C_YELLOW, C_BAR)
                    # 状态行低频补偿刷新: 收尾宽限到期转待机/远端状态变化能上屏
                    ui.line(Y_STATUS, ui._status_text(connected, stream_ok, voice),
                            ui._status_color(connected, stream_ok, voice))
            else:
                # 详情页: 每 tick 刷两行 (RTT 极值/统计)
                if tick == 0:
                    ui.line(Y_DETAIL0 + 3 * 24, "RTT 最小: %s" % (voice.rtt_min if voice.rtt_min is not None else "---"), C_WHITE)
                elif tick == 1:
                    ui.line(Y_DETAIL0 + 4 * 24, "RTT 最大: %s" % (voice.rtt_max if voice.rtt_max is not None else "---"), C_WHITE)
                elif tick == 2:
                    ui.line(Y_DETAIL0 + 5 * 24, "PING 发/收: %d/%d" % (voice.pings_sent, voice.pongs_recv), C_WHITE)
                    ui.line(Y_DETAIL0 + 6 * 24, "丢 PING: %d" % max(0, voice.pings_sent - voice.pongs_recv),
                            C_RED if voice.pings_sent > voice.pongs_recv else C_WHITE)
                else:
                    ui.line(Y_DETAIL0 + 7 * 24, "发送错误: %d" % voice.send_errors, C_WHITE)

        gc.collect()
        time.sleep_ms(1)
