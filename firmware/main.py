"""
Lele AI Tour Guide 3-Step Interactive Confirmation Application with Rich Sound Effects.
1. Hold UP: Ding-dong chime & speak -> 2. Release UP: Ta-da! proposal with MiMo voice -> 3. Press OK: Victory fanfare & deploy!
"""

import sys
import time
import json
import select
from machine import Pin, SPI, ADC, I2C
from config import *
from st7789_direct import ST7789Direct
from lele_ui import LeleUI, STATE_GUIDE, STATE_LISTENING, STATE_PROPOSAL, STATE_DEPLOYING, STATE_SUCCESS
from wifi_manager import WiFiManager
from audio_player import AudioPlayer
from battery import BatteryGauge
from spots_data import SPOTS

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

ui = LeleUI(display=display, width=SCREEN_WIDTH, height=SCREEN_HEIGHT)
curr_spot_idx = 0
ui.update_guide(SPOTS[curr_spot_idx])

# 2. Shared I2C for ES8311 & CW2017
shared_i2c = None
try:
    shared_i2c = I2C(0, sda=Pin(PIN_I2C_SDA), scl=Pin(PIN_I2C_SCL), freq=100000)
except Exception:
    pass

audio = AudioPlayer(i2c=shared_i2c, addr=0x18)
battery = BatteryGauge(i2c=shared_i2c, addr=0x63)
ui.battery_pct, _ = battery.get_info()

# 3. ADC Keypad on GPIO 0
adc = ADC(Pin(PIN_BTN_ADC))
try:
    adc.atten(ADC.ATTN_11DB)
except Exception:
    pass

# 4. WiFi Manager
wifi = WiFiManager()
try:
    wifi.connect(timeout=4)
except Exception:
    pass

def read_btn():
    try:
        raw = adc.read()
        mv = (raw * 3300) // 4095
    except Exception:
        return None

    if mv < 300:
        return "UP"
    elif 300 <= mv < 800:
        return "DOWN"
    elif 800 <= mv < 2200:
        return "OK"
    return None

def send_packet(d):
    pkt = (json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.write(pkt)
    if wifi.is_connected:
        wifi.send_udp(pkt)

# Voice Scenarios
SCENARIOS = [
    {
        "voice": "我想给开封加一个包公断案的故事！",
        "title": "开封府 · 包公断案与三口铜铡",
        "desc": "铁面无私包青天断奇案，设计考考爸妈三口铡刀名字！",
        "quiz": "龙头铡、虎头铡、狗头铡分别铡谁？"
    },
    {
        "voice": "我想了解华山沉香救母的神话！",
        "title": "华山西峰 · 沉香劈山救母巨石",
        "desc": "寻找西峰神石，背诵北宋神童寇准7岁咏华山名诗！",
        "quiz": "沉香一斧劈开两半的巨石在哪个峰？"
    },
    {
        "voice": "我想知道大雁塔唐僧玄奘的故事！",
        "title": "大雁塔 · 玄奘西行五万里传奇",
        "desc": "玄奘法师独自西行17年取回657部真经建塔故事！",
        "quiz": "大雁塔是哪位唐代高僧主持修建的？"
    },
    {
        "voice": "我想在洛阳龙门石窟加一个寻宝任务！",
        "title": "龙门石窟 · 寻找卢舍那大佛微笑",
        "desc": "打卡东方蒙娜丽莎与大诗人白居易琵琶峰墓园！",
        "quiz": "卢舍那大佛的面容是按哪位皇帝雕刻的？"
    }
]
scen_idx = 0

def handle_incoming_json(line_str):
    if not line_str:
        return
    try:
        pkt = json.loads(line_str)
    except Exception:
        return

    msg_type = pkt.get("type")
    if msg_type == "proposal":
        audio.play_proposal_ready()
        ui.show_proposal(pkt.get("user_text", ""), pkt.get("title", ""), pkt.get("desc", ""), pkt.get("quiz", ""))
    elif msg_type == "task_done":
        audio.play_send_success()
        ui.show_success()
        time.sleep(2.8)
        ui.show_guide()

def main():
    global curr_spot_idx, scen_idx
    print("[+] Lele Interactive Tour Guide App Running.")
    poll_obj = select.poll()
    poll_obj.register(sys.stdin, select.POLLIN)
    line_buf = []
    last_btn_time = 0
    last_btn = None

    while True:
        # Serial & WiFi poll
        events = poll_obj.poll(1)
        for fd, ev in events:
            if ev & select.POLLIN:
                chunk = sys.stdin.read(1)
                if chunk:
                    if chunk == '\n':
                        line = "".join(line_buf).strip()
                        line_buf.clear()
                        handle_incoming_json(line)
                    else:
                        line_buf.append(chunk)

        udp_pkt = wifi.poll_udp()
        if udp_pkt:
            handle_incoming_json(udp_pkt)

        # Key scan
        now = time.time()
        btn = read_btn()

        if ui.state == STATE_GUIDE:
            # 1. Hold UP -> Ding-dong chime & speech screen
            if btn == "UP":
                audio.play_record_start()
                ui.show_listening()
            elif btn and btn != last_btn:
                if now - last_btn_time > 0.2:
                    last_btn_time = now
                    if btn == "DOWN":
                        audio.play_click()
                        curr_spot_idx = (curr_spot_idx + 1) % len(SPOTS)
                        ui.update_guide(SPOTS[curr_spot_idx])
                    elif btn == "OK":
                        audio.play_click()
                        send_packet({"type": "ping"})

        elif ui.state == STATE_LISTENING:
            # 2. Release UP -> Ta-da chime & proposal screen!
            if btn != "UP":
                audio.play_record_stop()
                time.sleep(0.1)
                audio.play_proposal_ready()
                curr_scen = SCENARIOS[scen_idx]
                scen_idx = (scen_idx + 1) % len(SCENARIOS)
                ui.show_proposal(curr_scen["voice"], curr_scen["title"], curr_scen["desc"], curr_scen["quiz"])
                last_btn_time = now

        elif ui.state == STATE_PROPOSAL:
            # 3. Confirm (OK) or Cancel (DOWN)
            if btn and btn != last_btn:
                if now - last_btn_time > 0.3:
                    last_btn_time = now
                    if btn == "OK":
                        # Confirmed! -> Deploy with Victory Fanfare
                        ui.show_deploying()
                        send_packet({
                            "type": "confirm_task",
                            "title": ui.prop_title,
                            "desc": ui.prop_desc,
                            "quiz": ui.prop_quiz
                        })
                        time.sleep(1.8)
                        audio.play_send_success()
                        ui.show_success()
                        time.sleep(2.8)
                        ui.show_guide()
                    elif btn == "DOWN":
                        audio.play_cancel()
                        ui.show_guide()

        last_btn = btn
        time.sleep(0.01)

if __name__ == "__main__":
    main()
