"""
乐乐语音桥 (Lele Voice Bridge) —— 常开麦克风 → UDP 推流 → Mac/BlackHole.

按键: 上=静音切换  下=立即测延迟  OK=主页/详情翻页
屏幕实时显示到主机端的延迟(RTT)/码率/丢包/信号, 用于评估链路质量.

性能铁律(实测): 8.5ms/汉字 + 56ms/整页清除 → 整页重画≈500ms 会饿死 32ms 的
音频节拍. 因此整页只在启动/翻页时画一次, 运行期每 500ms 只增量刷新一行.
"""

import gc
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


def fmt_bytes(n):
    if n >= 1 << 20:
        return "%.1fMB" % (n / (1 << 20))
    if n >= 1 << 10:
        return "%.1fKB" % (n / (1 << 10))
    return "%dB" % n


# 页面行 y 坐标 (16px 字高, 行距 28)
Y_STATUS = 48
Y_RTT    = 78
Y_HOST   = 108
Y_RATE   = 138
Y_SENT   = 168
Y_RSSI   = 198
Y_DETAIL0 = 48   # 详情页起始, 行距 24


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
        draw_string_cn(self.d, "上静音 下测延 OK翻页", 8, 301, C_GREY, C_BAR)

    def full_render(self, connected, stream_ok, voice_muted, rssi):
        """整页重画 (只在启动/翻页时调用, ≈500ms)."""
        self.frame()
        if self.page == 0:
            self.line(Y_STATUS, self._status_text(connected, stream_ok, voice_muted),
                      self._status_color(connected, stream_ok, voice_muted))
            self.line(Y_RTT, "延迟 RTT: ---", C_GREY)
            self.line(Y_HOST, "主机 %s:%d" % (STREAM_IP, STREAM_PORT), C_GREY)
            self.line(Y_RATE, "码率: %dkbps" % (SAMPLE_RATE * 16 // 1024), C_WHITE)
            self.line(Y_SENT, "已发: 0B", C_WHITE)
            self.line(Y_RSSI, "WiFi 信号: %s" % (rssi or "---"), C_WHITE)
        else:
            for i, t in enumerate(self._detail_lines(voice, connected, codec_ok)):
                self.line(Y_DETAIL0 + i * 24, t, C_WHITE)
        draw_string_cn(self.d, "%d%%" % self.battery_pct, 174, 10, C_YELLOW, C_BAR)

    def _status_text(self, connected, stream_ok, muted):
        if not connected:
            return "✗ WiFi 未连接"
        if not stream_ok:
            return "✗ 推流未启动"
        if muted:
            return "⏸ 已静音 (暂停发送)"
        return "● 推流中 → Mac"

    def _status_color(self, connected, stream_ok, muted):
        if not connected or not stream_ok:
            return C_RED
        if muted:
            return C_YELLOW
        return C_GREEN

    def _detail_lines(self, v, connected, codec_ok):
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


def main():
    global wifi, codec_ok, voice
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
        # 电量先读一次再整页
        try:
            ui.battery_pct, _ = battery.get_info()
        except Exception:
            pass
        ui.full_render(connected, stream_ok, voice.muted, None)

    last_btn = None
    last_btn_time = 0
    tick = 0
    last_ui = time.ticks_ms()

    while True:
        now = time.ticks_ms()
        btn = read_btn(adc)
        if btn and btn != last_btn and time.ticks_diff(now, last_btn_time) > 200:
            last_btn_time = now
            if btn == "UP" and stream_ok:
                voice.set_muted(not voice.muted)
                ui.line(Y_STATUS, ui._status_text(connected, stream_ok, voice.muted),
                        ui._status_color(connected, stream_ok, voice.muted))
            elif btn == "DOWN" and stream_ok:
                voice._last_ping_ms = 0
                voice._poll_ping()
            elif btn == "OK":
                ui.page = 1 - ui.page
                ui.full_render(connected, stream_ok, voice.muted, None)
        last_btn = btn

        if stream_ok:
            voice.poll()                 # 32ms 节拍, 音频优先

        # WiFi 看门狗
        if wifi.wlan and not wifi.wlan.isconnected():
            connected = False
            try:
                wifi.connect(timeout=4)
                connected = wifi.is_connected
                ui.full_render(connected, stream_ok, voice.muted, None)
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


if __name__ == "__main__":
    main()
