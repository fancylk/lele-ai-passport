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

# OTA 回滚守卫 (§六十六): 上次升级中断(升级中途断电/崩溃) → /ota.pending 存在
# → 从 /backup 逐文件还原, 保证设备永远能启动到上一个完整版本.
try:
    import os
    if "/ota.pending" in os.listdir("/"):
        names = open("/ota.pending").read().split()
        for n in names:
            n = n.strip()
            if not n:
                continue
            try:
                os.rename("/backup/" + n.replace("/", "_"), "/" + n)
                print("[OTA] 回滚:", n)
            except OSError:
                pass
        os.remove("/ota.pending")
except Exception as e:
    print("[OTA] 回滚守卫异常:", e)
