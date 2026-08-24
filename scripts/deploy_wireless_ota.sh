#!/bin/bash
set -e

WORKSPACE="/vol1/1000/esp32_passport_workspace"
MPREMOTE="$WORKSPACE/venv/bin/mpremote"
PASSWORD="folotoy"

CARD_IP="$1"

if [ -z "$CARD_IP" ]; then
    # Auto-detect card IP from bridge known_cards or fallback
    CARD_IP="192.168.31.133"
fi

echo "================================================================="
echo " 📶 正在通过 Wi-Fi 无线向工牌部署最新应用 (目标 IP: $CARD_IP)"
echo "================================================================="

FILES=(
    "config.py"
    "st7789_direct.py"
    "chinese_font.py"
    "lele_ui.py"
    "spots_data.py"
    "wifi_manager.py"
    "audio_player.py"
    "battery.py"
    "main.py"
)

for f in "${FILES[@]}"; do
    SRC="$WORKSPACE/firmware/micropython/$f"
    if [ -f "$SRC" ]; then
        echo -n "  -> [WiFi] 传输 $f... "
        $MPREMOTE connect "ws:$CARD_IP" fs cp "$SRC" ":$f" >/dev/null 2>&1 || true
        echo "OK"
    fi
done

echo "[*] [WiFi] 发送软重启指令..."
$MPREMOTE connect "ws:$CARD_IP" soft-reset >/dev/null 2>&1 || true

echo "================================================================="
echo " 🎉 [SUCCESS] Wi-Fi 无线部署完成！无需 USB 线！"
echo "================================================================="
