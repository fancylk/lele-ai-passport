#!/bin/bash
set -e
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-/dev/ttyACM0}"

echo "================================================================="
echo " 🔌 正在通过 USB 串口向工牌部署固件与应用 (端口: $PORT)"
echo "================================================================="

if [ ! -e "$PORT" ]; then
    echo "[!] 错误：未检测到串口 $PORT，请确认工牌已通过 USB 连接。"
    exit 1
fi

MPREMOTE="mpremote"
if ! command -v mpremote &> /dev/null; then
    MPREMOTE="/vol1/1000/esp32_passport_workspace/venv/bin/mpremote"
fi

FILES=(
    "config.py"
    "st7789_direct.py"
    "chinese_font.py"
    "font16.bin"
    "lele_ui.py"
    "spots_data.py"
    "wifi_manager.py"
    "audio_player.py"
    "battery.py"
    "webrepl_cfg.py"
    "boot.py"
    "main.py"
)

for f in "${FILES[@]}"; do
    SRC="$WORKSPACE/firmware/$f"
    if [ -f "$SRC" ]; then
        echo -n "  -> 传输 $f... "
        $MPREMOTE connect "$PORT" fs cp "$SRC" ":$f"
        echo "OK"
    fi
done

echo "[*] 重启工牌..."
$MPREMOTE connect "$PORT" soft-reset
echo "🎉 [SUCCESS] USB 部署完成！"
