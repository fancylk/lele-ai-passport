#!/usr/bin/env python3
"""
乐乐语音桥 · 腾讯云中转 (UDP 星型多路复制枢纽)

场景: 工牌与多台终端 (Mac、PC) 不在同一局域网, 音频经本机中转.

架构特性:
  1. 多路并发复制转发 (Fan-out):
     无论同时连接多少台终端 (如 PC 和 Mac 同时订阅), 服务端对每个音频包
     均无条件完整复制并多路分发给所有活跃订阅端.
     客户端自行决定是否播放/写入虚拟声卡 (BlackHole / VB-Cable) 或解析识别.
  2. 灵活终端标识:
     订阅包支持 b"SUB" + TOKEN, 也支持扩展格式 b"SUB" + TOKEN + b":" + TAG (如 "mac", "pc").
  3. 独立保活与超时回收:
     订阅者 30s 需重发保活 (90s 无心跳自动剔除), 超时回收独立运行, 不依赖音源发包.
  4. 探测与状态监控:
     UDP :9762 支持 PING/PONG 测延迟, 亦支持 STATUS 查询活跃终端详情.
  5. 目标主机路由 (2026-10-23 §六十八): current_target 状态 (内存, 重启回广播);
     TSET+token+@tag 设定 / TSET0+token 清除 / TGTQ+token 查询 (回 TGT @tag|-(广播)).
     控制帧 (DICT*/PTTD*) 仅转发给当前目标 tag 的订阅端, 防多主机激活错乱;
     音频/PING/TGTM1 广播不变.
  6. UDP 打洞汇聚 (2026-10-11 §六十五, 向后兼容):
     终端发 SRCQ+token 查音源公网映射地址; 音源(工牌)的 PONG 响应尾部
     捎带 |PEER=ip:port (最新订阅端映射地址). 两端互发 PNCH 凿开 NAT 后
     音频端到端直传, 本机只剩保活/回退通道.
"""

import socket
import sys
import time

TOKEN = b"lele-6deb6d37"
PORT_AUDIO = 9761
PORT_PING = 9762
SUB_TIMEOUT = 90.0
SOURCE_TIMEOUT = 60.0
STATS_INTERVAL = 60.0


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)


def main():
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    a.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    a.bind(("0.0.0.0", PORT_AUDIO))
    a.settimeout(0.5)

    p = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    p.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    p.bind(("0.0.0.0", PORT_PING))
    p.setblocking(False)

    source = None            # (addr, last_seen)
    subs = {}                # addr -> {"last_seen": timestamp, "tag": str}
    current_target = None    # §六十八: 控制帧只发给该 tag; None=广播所有订阅端
    fwd = src_pkts = 0
    last_stats = time.time()
    last_cleanup = time.time()

    log(f"relay up: audio:{PORT_AUDIO} ping:{PORT_PING} token=***{TOKEN[-4:].decode()}")

    while True:
        try:
            data, addr = a.recvfrom(2048)
        except socket.timeout:
            data = None
        now = time.time()

        if data is not None:
            # 音源握手注册: LELE1 + token
            if data.startswith(b"LELE1") and data[5:5 + len(TOKEN)] == TOKEN:
                if source != addr:
                    log(f"source registered: {addr[0]}:{addr[1]}")
                source = (addr, now)
                try:
                    a.sendto(b"LELE1_OK", addr)
                except OSError:
                    pass

            # 目标主机设定 (§六十八): TSET+token+@tag / TSET0+token / TGTQ+token
            elif data.startswith(b"TSET0") and data[5:5 + len(TOKEN)] == TOKEN:
                current_target = None
                log("current target -> BROADCAST")
                try:
                    a.sendto(b"TSET_OK", addr)
                except OSError:
                    pass
            elif data.startswith(b"TSET") and data[4:4 + len(TOKEN)] == TOKEN and data[4 + len(TOKEN):4 + len(TOKEN) + 1] == b"@":
                want = data[5 + len(TOKEN):].decode("utf-8", "ignore").strip()
                if want:
                    current_target = want
                    online = sum(1 for info in subs.values() if info["tag"] == want)
                    log(f"current target -> {want!r} ({online} 端在线)")
                    try:
                        a.sendto(b"TSET_OK", addr)
                    except OSError:
                        pass
            elif data.startswith(b"TGTQ") and data[4:4 + len(TOKEN)] == TOKEN:
                reply = b"TGT @" + current_target.encode() if current_target else b"TGT -"
                try:
                    a.sendto(reply, addr)
                except OSError:
                    pass

            # 终端订阅注册: SUB + token 或 SUB + token + :tag
            elif data.startswith(b"SUB") and data[3:3 + len(TOKEN)] == TOKEN:
                tag = "client"
                extra = data[3 + len(TOKEN):]
                if extra.startswith(b":"):
                    try:
                        tag = extra[1:].decode("utf-8", "ignore").strip() or "client"
                    except Exception:
                        pass
                
                is_new = addr not in subs
                subs[addr] = {"last_seen": now, "tag": tag}
                if is_new:
                    active_tags = [f"{v['tag']}@{k[0]}:{k[1]}" for k, v in subs.items()]
                    log(f"subscriber added: {addr[0]}:{addr[1]} [{tag}] (total {len(subs)}: {', '.join(active_tags)})")
                
                # 回送轻量确认包, 维持双向 NAT 映射
                try:
                    a.sendto(b"SUB_OK", addr)
                except OSError:
                    pass

            # 打洞汇聚: 音源地址查询 (终端向音源发 PNCH 用, token 鉴权)
            elif data.startswith(b"SRCQ") and data[4:4 + len(TOKEN)] == TOKEN:
                if source:
                    reply = b"SRC " + f"{source[0][0]}:{source[0][1]}".encode()
                else:
                    reply = b"SRC -"
                try:
                    a.sendto(reply, addr)
                except OSError:
                    pass

            # 音频数据包: 仅转发来自音源的包
            elif source and addr == source[0]:
                src_pkts += 1
                source = (addr, now)

                # §六十八: 控制帧 (DICT*/PTTD*) 按 current_target 路由;
                # 音频/PING/TGTM1(目标切换广播)不受影响.
                dst_addrs = None
                if current_target and len(data) >= 5 and data[:4] in (b"DICT", b"PTTD"):
                    dst_addrs = [s for s, info in subs.items() if info["tag"] == current_target]

                # 双路 / 多路全量复制转发给所有当前存活订阅端
                for s in (dst_addrs if dst_addrs is not None else list(subs.keys())):
                    try:
                        a.sendto(data, s)
                        fwd += 1
                    except OSError:
                        pass

        # 定时清理超时的音源与订阅端 (独立于数据流)
        if now - last_cleanup >= 5.0:
            last_cleanup = now
            # 音源超时
            if source and now - source[1] > SOURCE_TIMEOUT:
                log(f"source timeout: {source[0][0]}:{source[0][1]}")
                source = None

            # 订阅端超时
            dead = [s for s, info in subs.items() if now - info["last_seen"] > SUB_TIMEOUT]
            for s in dead:
                tag = subs.pop(s, {}).get("tag", "unknown")
                log(f"subscriber timeout: {s[0]}:{s[1]} [{tag}] (total {len(subs)})")

        # 探测与状态口 (UDP 9762)
        try:
            while True:
                d, addr2 = p.recvfrom(128)
                if len(d) >= 4 and d[:4] == b"PING":
                    pong = b"PONG" + d[4:12]
                    # 打洞汇聚: 把最新订阅端映射地址捎给音源 (旧固件自动忽略尾巴)
                    if source and subs:
                        newest = max(subs.items(), key=lambda kv: kv[1]["last_seen"])
                        pong += b"|PEER=%s:%d" % (str(newest[0][0]).encode(), newest[0][1])
                    p.sendto(pong, addr2)
                elif d.startswith(b"STATUS"):
                    # 状态查询: 返回音源与订阅端列表
                    src_str = f"{source[0][0]}:{source[0][1]}" if source else "offline"
                    sub_list = [f"{v['tag']}@{k[0]}:{k[1]}" for k, v in subs.items()]
                    status_resp = (f"source={src_str};subs={len(subs)};"
                                   f"list={','.join(sub_list)};src_pkts={src_pkts};fwd={fwd};"
                                   f"target={current_target or '-'}").encode()
                    p.sendto(status_resp, addr2)
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass

        # 定期输出统计信息
        if now - last_stats >= STATS_INTERVAL:
            last_stats = now
            sub_summary = [f"{v['tag']}@{k[0]}:{k[1]}" for k, v in subs.items()]
            log(f"stats: source={'yes' if source else 'no'} subs={len(subs)} {sub_summary} "
                f"src_pkts={src_pkts} forwarded={fwd}")


if __name__ == "__main__":
    sys.exit(main())
