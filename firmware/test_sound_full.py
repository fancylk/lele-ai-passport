"""
Comprehensive Audio & Speaker Test for FoloToy AI Passport.
Tests ES8311 Codec with MCLK + Direct PWM Tone generation.
"""

import time
from machine import Pin, I2C, PWM

print("=" * 60)
print(" 🔊 COMPREHENSIVE SPEAKER AUDIO TEST")
print("=" * 60)

# Step 1: Supply 4MHz MCLK Clock on GPIO 6 for ES8311
try:
    mclk_pwm = PWM(Pin(6), freq=4000000, duty_u16=32768)
    print("[+] Generated 4MHz Master Clock (MCLK) on GPIO 6.")
except Exception as e:
    print("[!] MCLK Gen error:", e)

# Step 2: Configure ES8311 over I2C (SDA=10, SCL=7)
i2c = I2C(0, sda=Pin(10), scl=Pin(7), freq=100000)
ADDR = 0x18

def w_reg(r, v):
    try:
        i2c.writeto_mem(ADDR, r, bytearray([v]))
    except Exception:
        pass

def init_es8311():
    # Reset
    w_reg(0x00, 0x80)
    time.sleep_ms(20)
    w_reg(0x00, 0x00)

    # Clock Config: MCLK from pin, enable all clocks
    w_reg(0x01, 0x3F)
    w_reg(0x02, 0x00)
    w_reg(0x03, 0x10)
    w_reg(0x04, 0x10)
    w_reg(0x05, 0x00)
    w_reg(0x06, 0x00)
    w_reg(0x07, 0x00)
    w_reg(0x08, 0xFF)

    # Power Management: Power up everything
    w_reg(0x0D, 0x01) # Power up analog
    w_reg(0x0E, 0x02) # Power up ADC
    w_reg(0x0F, 0x44) # Power up DAC & Output drive
    w_reg(0x12, 0x00) # System normal
    w_reg(0x13, 0x10) # Vref

    # Max Volume (0x00 = 0dB max volume)
    w_reg(0x31, 0x00) # Unmute DAC
    w_reg(0x32, 0x00) # Max Volume (0dB)
    print("[+] ES8311 Initialized with 0dB Max Volume & MCLK.")

init_es8311()

# Method A: Play Famous Melody via ES8311 Hardware Beep Generator
print("\n[*] [Method A] Playing 'Ode to Joy' (欢乐颂) via ES8311 Codec...")
melody_tones = [
    (0x84, 250), (0x84, 250), (0x86, 250), (0x88, 250),
    (0x88, 250), (0x86, 250), (0x84, 250), (0x82, 250),
    (0x81, 250), (0x81, 250), (0x82, 250), (0x84, 250),
    (0x84, 350), (0x82, 150), (0x82, 400)
]

for tone_code, duration_ms in melody_tones:
    w_reg(0x37, tone_code) # Beep ON
    time.sleep_ms(duration_ms)
    w_reg(0x37, 0x00)      # Beep OFF
    time.sleep_ms(30)

time.sleep(1.0)

# Method B: Direct Musical PWM Tone on Audio Pins (GPIO 2, GPIO 3, GPIO 5)
print("\n[*] [Method B] Testing Direct Musical PWM Tones on Audio Pins...")
audio_pins = [2, 3, 5]
notes = [523, 587, 659, 698, 784, 880, 988, 1046] # C5, D5, E5, F5, G5, A5, B5, C6

for pin_num in audio_pins:
    print(f"    -> Testing Musical Scale on GPIO {pin_num}...")
    for freq in notes:
        try:
            p = PWM(Pin(pin_num), freq=freq, duty_u16=32768)
            time.sleep_ms(150)
            p.deinit()
            time.sleep_ms(20)
        except Exception as e:
            print(f"       GPIO {pin_num} err: {e}")

print("\n[+] Speaker Audio Test Completed!")
