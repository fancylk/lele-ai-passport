#!/bin/bash
# BlackHole 链路验证: 录 6 秒 BlackHole 2ch 输入, 报告峰值电平.
# 用法: 有声音进 BlackHole 时跑它 (推流中/放测试音), peak>0.05 即有音频到达.
set -e
OUT="${1:-/tmp/blackhole_check.wav}"
echo "[*] 录制 BlackHole 2ch 6 秒 -> $OUT"
ffmpeg -y -f avfoundation -i ":BlackHole 2ch" -t 6 "$OUT" 2>/dev/null || \
ffmpeg -y -f avfoundation -i ":0" -t 6 "$OUT" 2>/dev/null || {
  echo "[!] 录制失败: 检查 BlackHole 是否安装 (关于本机→系统设置→声音→输出)"; exit 1; }
echo "[*] 电平分析:"
ffmpeg -i "$OUT" -af astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.Peak_level \
  -f null - 2>&1 | grep "Peak_level" | tail -1
ffmpeg -i "$OUT" -af volumedetect -f null - 2>&1 | grep -E "mean_volume|max_volume"
echo "[=] 判读: max_volume > -25dB → BlackHole 有音频; ≈ -91dB/inf → 无声(链路断)"
