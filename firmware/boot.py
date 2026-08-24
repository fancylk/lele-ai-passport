# This file is executed on every boot (including wake-boot from deepsleep)
import esp
esp.osdebug(None)

import gc
gc.collect()

# Enable Wireless WebREPL for Wireless OTA App Deployment
try:
    import webrepl
    webrepl.start(password='folotoy')
except Exception:
    pass
