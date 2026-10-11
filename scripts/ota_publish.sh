#!/bin/bash
# OTA 发布 (§六十六): 计算固件文件 crc32 → manifest.json → 推到腾讯 nginx
# (/var/www/html/lele-ota/, 外网 http://124.221.187.167:8090/lele-ota/manifest.json).
# 工牌端菜单 "OTA 检查更新" 即拉此目录. 版本号自动 +1 (lele-voice/ota_version.txt).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/firmware"

HOST="${OTA_HOST:-tencent}"
REMOTE_DIR="${OTA_REMOTE_DIR:-/var/www/fw/lele-ota}"

FILES=(
    main.py boot.py config.py ota.py
    voice_stream.py wifi_manager.py battery.py
    st7789_direct.py chinese_font.py font16.bin
    lele_ui.py spots_data.py audio_player.py
    apps/__init__.py apps/registry.py apps/menu.py
    apps/voice_bridge.py apps/guide.py
    apps/answer.py apps/answer_data.py apps/catch.py
)

for f in "${FILES[@]}"; do
    [ -f "$f" ] || { echo "[!] 缺文件: $f"; exit 1; }
done

V=$(( $(cat "$ROOT/ota_version.txt" 2>/dev/null || echo 0) + 1 ))
echo "$V" > "$ROOT/ota_version.txt"

python3 - "$V" "${FILES[@]}" > /tmp/lele-ota-manifest.json <<'PY'
import json, sys, zlib
v = int(sys.argv[1])
print(json.dumps({"v": v, "files": {f: zlib.crc32(open(f, "rb").read()) & 0xFFFFFFFF for f in sys.argv[2:]}}))
PY

ssh "$HOST" "mkdir -p $REMOTE_DIR"
scp -q /tmp/lele-ota-manifest.json "$HOST:$REMOTE_DIR/manifest.json"
for f in "${FILES[@]}"; do
    remote_name="${f//\//_}"          # apps/menu.py → apps_menu.py
    scp -q "$f" "$HOST:$REMOTE_DIR/$remote_name"
done
echo "[+] OTA v$V 已发布: http://124.221.187.167:8090/lele-ota/manifest.json (${#FILES[@]} 文件)"
