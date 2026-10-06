"""
乐乐语音桥 (Lele Voice Bridge) —— 常开麦克风 → UDP 推流 → Mac/BlackHole.

按键: 上=静音切换  下=立即测延迟  OK=主页/详情翻页
屏幕实时显示到主机端的延迟(RTT)/码率/丢包/信号, 用于评估链路质量.
(旧三步导游版见 git 历史: 重写前的 main.py)
"""

import gc
import sys
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
C_ORANGE  = 0xFD20

BOOT_TIME = time.ticks_ms()


def setup_display():
    spi = SPI(1, baudrate=30000000, polarity=0, phase=0,
              sck=Pin(8), mosi=Pin(9))
    return ST7789Direct(spi=spi, width=240, height=320,
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


class BridgeUI:
    """两页式界面: 0=主页(状态+延迟) 1=详情(网络/统计)."""

    def __init__(self, display):
        self.d = display
        self.page = 0

    def frame(self):
        self.d.fill(C_BG)
        self.d.fill_rect(0, 0, 240, 36, C_BAR)
        draw_string_cn(self.d, "乐乐语音桥", 8, 10, C_WHITE, C_BAR)
        self.d.fill_rect(0, 296, 240, 24, C_BAR)
        draw_string_cn(self.d, "上静音 下测延 OK翻页", 8, 301, C_GREY, C_BAR)

    def text(self, s, x, y, fg, bg=C_BG):
        draw_string_cn(self.d, s, x, y, fg, bg)

    def clear_body(self):
        self.d.fill_rect(0, 36, 240, 260, C_BG)


def fmt_bytes(n):
    if n >= 1 << 20:
        return "%.1fMB" % (n / (1 << 20))
    if n >= 1 << 10:
        return "%.1fKB" % (n / (1 << 10))
    return "%dB" % n


def main():
    print("[+] Lele Voice Bridge boot")
    display = setup_display()
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
    if not stream_ok:
        ui.frame()
        ui.text("音频链路初始化失败!", 8, 60, C_RED)
        ui.text("检查 I2S/ES8311/UDP", 8, 90, C_GREY)
        draw_string_cn(display, "查看 REPL 日志", 8, 120, C_YELLOW, C_BG)

    adc = ADC(Pin(0))
    try:
        adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass

    ui.frame()
    last_ui = 0
    last_btn = None
    last_btn_time = 0
    show_rtt = None

    while True:
        now = time.ticks_ms()
        btn = read_btn(adc)
        if btn and btn != last_btn and time.ticks_diff(now, last_btn_time) > 200:
            last_btn_time = now
            if btn == "UP" and stream_ok:
                voice.set_muted(not voice.muted)
                ui.clear_body()          # 状态行变色, 整体重画
                last_ui = 0
            elif btn == "DOWN" and stream_ok:
                voice._last_ping_ms = 0  # 立即触发一次 PING
                voice._poll_ping()
            elif btn == "OK":
                ui.page = 1 - ui.page
                ui.frame()
                ui.clear_body()
                last_ui = 0
        last_btn = btn

        if stream_ok:
            voice.poll()                 # 32ms 节拍

        # WiFi 看门狗
        if wifi.wlan and not wifi.wlan.isconnected():
            connected = False
            try:
                wifi.connect(timeout=4)
                connected = wifi.is_connected
            except Exception:
                pass

        # 每 500ms 刷新一屏
        if time.ticks_diff(time.ticks_ms(), last_ui) >= 500:
            last_ui = time.ticks_ms()
            try:
                ui.battery_pct, _ = battery.get_info()
            except Exception:
                pass
            rssi = None
            try:
                if wifi.wlan.isconnected():
                    rssi = wifi.wlan.status("rssi")
            except Exception:
                pass

            if ui.page == 0:
                y = 48
                ui.clear_body()
                # 状态行
                if not connected:
                    ui.text("✗ WiFi 未连接", 8, y, C_RED); y += 26
                elif not stream_ok:
                    ui.text("✗ 推流未启动", 8, y, C_RED); y += 26
                elif voice.muted:
                    ui.text("⏸ 已静音 (暂停发送)", 8, y, C_YELLOW); y += 26
                else:
                    ui.text("● 推流中 → Mac", 8, y, C_GREEN); y += 26
                # 延迟大字
                rtt = voice.rtt_ms if (time.ticks_diff(
                    time.ticks_ms(), voice.last_pong_ms or 0) < 4000) else None
                if rtt is None:
                    ui.text("延迟 RTT: ---", 8, y + 6, C_GREY)
                else:
                    show_rtt = rtt
                    color = C_GREEN if rtt < 30 else (C_YELLOW if rtt < 80 else C_RED)
                    ui.text("延迟 RTT: %dms" % rtt, 8, y + 6, color)
                y += 40
                ui.text("主机 %s:%d" % (STREAM_IP, STREAM_PORT), 8, y, C_GREY); y += 26
                ui.text("码率: %dkbps" % (SAMPLE_RATE * 16 // 1024), 8, y, C_WHITE); y += 26
                ui.text("已发: %s (%d包)" % (fmt_bytes(voice.bytes_sent), voice.pkts), 8, y, C_WHITE); y += 26
                sig = ("%d dBm" % rssi) if rssi else "---"
                ui.text("WiFi 信号: %s" % sig, 8, y, C_WHITE); y += 26
                ui.text("电量: %d%%" % ui.battery_pct, 8, y, C_WHITE)
            else:
                y = 48
                ui.clear_body()
                ui.text("── 详情 ──", 8, y, C_CYAN); y += 26
                ui.text("本机 IP: %s" % (wifi.ip if connected else "---"), 8, y, C_WHITE); y += 24
                ui.text("探测端口: %d" % PING_PORT, 8, y, C_GREY); y += 24
                ui.text("RTT 最小: %s" % (voice.rtt_min if voice.rtt_min is not None else "---"), 8, y, C_WHITE); y += 24
                ui.text("RTT 最大: %s" % (voice.rtt_max if voice.rtt_max is not None else "---"), 8, y, C_WHITE); y += 24
                ui.text("PING 发/收: %d/%d" % (voice.pings_sent, voice.pongs_recv), 8, y, C_WHITE); y += 24
                ui.text("丢 PING: %d" % max(0, voice.pings_sent - voice.pongs_recv), 8, y,
                        C_RED if voice.pings_sent > voice.pongs_recv else C_WHITE); y += 24
                ui.text("发送错误: %d" % voice.send_errors, 8, y, C_WHITE); y += 24
                ui.text("块大小: %dB=32ms" % CHUNK_BYTES, 8, y, C_GREY); y += 24
                ui.text("采样: %dHz/16bit/单声道" % SAMPLE_RATE, 8, y, C_GREY); y += 24
                ui.text("Codec: %s" % ("OK" if codec_ok else "失败"), 8, y,
                        C_GREEN if codec_ok else C_RED); y += 24
                up_s = time.ticks_diff(time.ticks_ms(), BOOT_TIME) // 1000
                ui.text("运行: %02d:%02d" % (up_s // 60, up_s % 60), 8, y, C_GREY)

            # 头栏电量
            draw_string_cn(display, "%d%%" % ui.battery_pct, 174, 10, C_YELLOW, C_BAR)

        gc.collect()
        time.sleep_ms(1)


if __name__ == "__main__":
    main()
