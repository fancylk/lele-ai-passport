#!/bin/bash
# 乐乐语音桥 Mac 接收器托管: start | stop | status | log | follow
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
PIDFILE="/tmp/voice_receiver.pid"
LOGFILE="/tmp/voice_receiver.log"
PORT="${VOICE_PORT:-9761}"
# 默认走腾讯中转(工牌与 Mac 不同局域网的常态); VOICE_RELAY="" 可切回 LAN 直连
RELAY="${VOICE_RELAY:-124.221.187.167}"
RELAY_ARG=""
[ -n "$RELAY" ] && RELAY_ARG="--relay $RELAY"

case "${1:-start}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "[=] 已在运行 (pid $(cat "$PIDFILE"))"; exit 0
    fi
    nohup "$PY" -u "$DIR/voice_receiver.py" --port "$PORT" $RELAY_ARG >>"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1
    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "[+] 已启动 (pid $(cat "$PIDFILE")), 日志: tail -f $LOGFILE"
    else
      echo "[!] 启动失败:"; tail -5 "$LOGFILE"; rm -f "$PIDFILE"; exit 1
    fi
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null && echo "[+] 已停止" || echo "[=] 进程不存在"
      rm -f "$PIDFILE"
    else
      echo "[=] 未在运行"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "[=] 运行中 (pid $(cat "$PIDFILE"))"; tail -3 "$LOGFILE"
    else
      echo "[=] 未运行"
    fi
    ;;
  log)   tail -20 "$LOGFILE" ;;
  follow) tail -f "$LOGFILE" ;;
  *) echo "用法: $0 start|stop|status|log|follow"; exit 1 ;;
esac
