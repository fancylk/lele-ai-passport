#!/bin/bash
# 串口部署 (§六十六): 在飞牛 NAS 上执行, 经 USB 串口把多应用固件推到工牌.
# 用法: 把本脚本与 firmware/ 目录同步到 NAS 后, 在 NAS 上:
#   bash scripts/deploy_serial_nas.sh
# 首次会自建 venv 并安装 mpremote.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${SERIAL_PORT:-/dev/ttyACM0}"
VENV="$ROOT/.serial-venv"

[ -c "$PORT" ] || { echo "[!] 串口设备不存在: $PORT"; exit 1; }

if [ ! -x "$VENV/bin/mpremote" ]; then
    echo "[*] 首次: 建 venv + 安装 mpremote..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q mpremote
fi
MP="$VENV/bin/mpremote"

FILES=(
    main.py boot.py config.py ota.py
    voice_stream.py wifi_manager.py battery.py
    st7789_direct.py chinese_font.py font16.bin
    lele_ui.py spots_data.py audio_player.py
    apps/__init__.py apps/registry.py apps/menu.py
    apps/voice_bridge.py apps/guide.py
    apps/answer.py apps/answer_data.py apps/catch.py
)

echo "[*] 连接 $PORT, 进入 REPL..."
"$MP" connect "$PORT" exec "import os
for d in ('/apps', '/otastage', '/backup'):
    try: os.mkdir(d)
    except OSError: pass" >/dev/null

for f in "${FILES[@]}"; do
    dir=$(dirname "$f")
    printf "  -> %-22s " "$f"
    "$MP" connect "$PORT" fs cp "$ROOT/firmware/$f" ":/$f" >/dev/null 2>&1 && echo "OK" || { echo "FAIL"; exit 1; }
done

echo "[*] 软重启..."
"$MP" connect "$PORT" soft-reset >/dev/null 2>&1 || true
"$MP" connect "$PORT" reset >/dev/null 2>&1 || true
echo "[+] 串口部署完成. 8 秒后抓启动日志:"
sleep 8
timeout 12 "$MP" connect "$PORT" 2>/dev/null | head -30 || true
