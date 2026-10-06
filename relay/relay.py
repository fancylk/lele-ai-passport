#!/usr/bin/env python3
"""
乐乐语音桥 · 腾讯云中转 (UDP 星型枢纽)

场景: 工牌与 Mac 不在同一局域网(电脑在公司、人在家), 音频经本机中转.

  UDP :9761  音频枢纽
    - 音源注册:  数据首包 = b"LELE1"+TOKEN, 之后该地址的裸 PCM 转发给全部订阅者
    - 订阅注册:  b"SUB"+TOKEN → 记忆该地址; 每 30s 重发保活(90s 超时剔除)
    - 裸包:      来自已注册音源 → 原样转发全部订阅者(单音源, 新源顶旧源)
  UDP :9762  延迟探测
    - PING+8B → 原样回 PONG+8B (工牌/订阅者据此算各自到中转的 RTT)

转发语义: 无序不重传不缓存, 与直连 UDP 行为一致; 每包开销 = 0 字节(纯转发).
"""

import socket
import sys
import time

TOKEN = b"lele-6deb6d37"
PORT_AUDIO = 9761
PORT_PING = 9762
SUB_TIMEOUT = 90.0
SOURCE_TIMEOUT = 60.0
STATS_INTERVAL = 300.0


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)


def main():
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    a.bind(("0.0.0.0", PORT_AUDIO))
    a.settimeout(1.0)

    p = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    p.bind(("0.0.0.0", PORT_PING))
    p.setblocking(False)

    source = None            # (addr, last_seen)
    subs = {}                # addr -> last_seen
    fwd = src_pkts = 0
    last_stats = time.time()

    log(f"relay up: audio:{PORT_AUDIO} ping:{PORT_PING} token=***{TOKEN[-4:].decode()}")

    while True:
        try:
            data, addr = a.recvfrom(2048)
        except socket.timeout:
            data = None
        now = time.time()

        if data is not None:
            if data.startswith(b"LELE1") and data[5:] == TOKEN:
                if source != addr:
                    log(f"source registered: {addr[0]}:{addr[1]}")
                source = (addr, now)
            elif data.startswith(b"SUB") and data[3:] == TOKEN:
                if addr not in subs:
                    log(f"subscriber added: {addr[0]}:{addr[1]} (total {len(subs)+1})")
                subs[addr] = now
            elif source and addr == source[0]:
                src_pkts += 1
                source = (addr, now)
                dead = [s for s, t in subs.items() if now - t > SUB_TIMEOUT]
                for s in dead:
                    subs.pop(s, None)
                    log(f"subscriber timeout: {s[0]}:{s[1]} (total {len(subs)})")
                for s in subs:
                    try:
                        a.sendto(data, s)
                        fwd += 1
                    except OSError:
                        pass
            # 其余来源静默丢弃(未注册音源)

        # 音源超时
        if source and now - source[1] > SOURCE_TIMEOUT:
            log(f"source timeout: {source[0][0]}:{source[0][1]}")
            source = None

        # 探测口
        try:
            while True:
                d, addr2 = p.recvfrom(64)
                if len(d) >= 4 and d[:4] == b"PING":
                    p.sendto(b"PONG" + d[4:12], addr2)
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass

        if now - last_stats >= STATS_INTERVAL:
            last_stats = now
            log(f"stats: source={'yes' if source else 'no'} subs={len(subs)} "
                f"src_pkts={src_pkts} forwarded={fwd}")


if __name__ == "__main__":
    sys.exit(main())
