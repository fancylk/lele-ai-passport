"""
Official Hardware Pinout & WiFi Configuration for FoloToy / TRAE AI Passport (ESP32-C3).
"""

# Screen: ST7789P3 240x320 4-line SPI
SCREEN_WIDTH  = 240
SCREEN_HEIGHT = 320
SCREEN_ROTATION = 0

PIN_LCD_MOSI = 9   # SPI MOSI
PIN_LCD_SCLK = 8   # SPI SCLK
PIN_LCD_CS   = 1   # Chip Select
PIN_LCD_DC   = 20  # Data/Command
PIN_LCD_RST  = None # Hardware tied to 3.3V
PIN_LCD_BL   = 21  # Backlight (LEDC PWM)

# Analog Keypad: 3 Buttons on ADC1_CH0 (GPIO 0)
PIN_BTN_ADC  = 0
BTN_MV_UP    = (0, 150)      # UP Key
BTN_MV_DOWN  = (150, 447)    # DOWN Key
BTN_MV_OK    = (447, 1900)   # OK / Action Key

# I2C: ES8311 Audio & CW2017 Fuel Gauge
PIN_I2C_SDA  = 10
PIN_I2C_SCL  = 7

# Serial Baud
SERIAL_BAUD  = 115200

# ==============================================================================
# Wireless WiFi & Network Settings
# ==============================================================================
WIFI_SSID    = "CMCC-Ab9h"
WIFI_PASS    = "tvakk9k8"
HOST_IP      = "192.168.31.102"
UDP_PORT     = 8888

# ==============================================================================
# Voice Stream (乐乐语音桥: ES8311 麦克风常开 → UDP PCM → 中转服务器)
# 架构: 工牌与主机不同局域网(电脑在公司/人在家), 经腾讯云 UDP 星型中转
#   工牌 --9761 PCM+握手--> 中转 --转发--> 全部订阅者(Mac/盒子 InputPad)
#   工牌 --9762 PING------> 中转 --PONG--> 工牌上屏 RTT(到中转这一跳)
# ==============================================================================
STREAM_IP    = "124.221.187.167"   # 中转服务器公网 IP
STREAM_PORT  = 9761               # PCM 推流端口 (s16le 16kHz mono)
PING_PORT    = 9762               # 延迟探测端口 (badge 发 PING, 中转回 PONG)
STREAM_TOKEN = "lele-6deb6d37"    # 音源/订阅注册口令 (与 relay/relay.py 一致)
SAMPLE_RATE  = 16000              # Hz
CHUNK_BYTES  = 1024               # 512 样本 = 32ms/包, UDP 载荷安全尺寸

# UDP 打洞 (§六十五): 与终端直连降延迟. 中转经 PONG 尾巴 |PEER=ip:port 捎来
# 终端映射地址; 双方互发 PNCH 凿 NAT; 收到终端 PNCH 即直连发音频,
# 10s 收不到 PNCH 自动回退中转. False = 永远走中转.
PUNCH        = True

# ==============================================================================
# 多应用 + OTA (§六十六): 启动器读 /app.txt 决定应用; OTA 走腾讯 nginx HTTP
# (scripts/ota_publish.sh 发布 manifest+文件到 /var/www/html/lele-ota/)
# ==============================================================================
APP_DEFAULT  = "voice_bridge"          # 无 /app.txt 时的默认应用
OTA_HOST     = "124.221.187.167"
OTA_PORT     = 8090
OTA_PATH     = "/lele-ota/"
