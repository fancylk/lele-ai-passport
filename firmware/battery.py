"""
CW2017 Battery Fuel Gauge Reader for MicroPython.
"""

from machine import Pin, I2C

class BatteryGauge:
    def __init__(self, i2c=None, sda_pin=10, scl_pin=7, addr=0x63):
        self.addr = addr
        self.ready = False
        if i2c:
            self.i2c = i2c
        else:
            try:
                self.i2c = I2C(0, sda=Pin(sda_pin), scl=Pin(scl_pin), freq=100000)
            except Exception:
                self.i2c = None
        
        if self.i2c:
            try:
                # Test read SOC
                data = self.i2c.readfrom_mem(self.addr, 0x04, 1)
                self.ready = True
            except Exception:
                pass

    def get_info(self):
        """Returns (soc_percent, voltage_mv)."""
        if not self.ready:
            return 100, 4000
        try:
            soc_data = self.i2c.readfrom_mem(self.addr, 0x04, 2)
            soc = int(soc_data[0] + (soc_data[1] / 256.0))
            soc = max(0, min(100, soc))

            v_data = self.i2c.readfrom_mem(self.addr, 0x02, 2)
            raw_v = (v_data[0] << 8) | v_data[1]
            v_mv = raw_v * 305 // 1000
            return soc, v_mv
        except Exception:
            return 100, 4000
