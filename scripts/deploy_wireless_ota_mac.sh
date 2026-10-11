#!/bin/bash
# Mac 版无线 OTA: 把乐乐语音桥固件推到工牌 (WebREPL)
# 用法: deploy_wireless_ota_mac.sh [工牌IP] [密码]
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/tools/.venv/bin/python"
[ -x "$PY" ] || PY=python3

CARD_IP="${1:-192.168.31.133}"
PASSWORD="${2:-folotoy}"
FIRMWARE="$ROOT/firmware"

# 乐乐语音桥运行所需文件 (§六十六 多应用版: 含 apps/ 与 OTA 客户端)
# 注: /apps 目录由串口首部署(scripts/deploy_serial_nas.sh)或启动器开机创建;
#     对老固件设备推 apps/* 失败时, 先做一次串口部署.
FILES=(
    "config.py"
    "wifi_manager.py"
    "st7789_direct.py"
    "chinese_font.py"
    "font16.bin"
    "battery.py"
    "voice_stream.py"
    "main.py"
    "boot.py"
    "ota.py"
    "lele_ui.py"
    "spots_data.py"
    "audio_player.py"
    "apps/__init__.py"
    "apps/registry.py"
    "apps/menu.py"
    "apps/voice_bridge.py"
    "apps/guide.py"
    "apps/answer.py"
    "apps/answer_data.py"
    "apps/catch.py"
)

echo "================================================================="
echo " 📶 乐乐语音桥 OTA -> $CARD_IP"
echo "================================================================="

for f in "${FILES[@]}"; do
    printf "  -> %-22s " "$f"
    if "$PY" "$ROOT/tools/webrepl_cli.py" -p "$PASSWORD" "$FIRMWARE/$f" "$CARD_IP:/$f" >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"; exit 1
    fi
done

echo "[*] 软重启..."
"$PY" "$ROOT/tools/webrepl_reset.py" "$CARD_IP" "$PASSWORD" || true

echo "================================================================="
echo " 🎉 部署完成. 工牌现在以待机模式运行: 上键=语音开关 下=按住说话 (§六十四)"
echo "================================================================="
