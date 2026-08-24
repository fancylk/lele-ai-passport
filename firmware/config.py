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
