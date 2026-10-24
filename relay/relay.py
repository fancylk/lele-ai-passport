#!/usr/bin/env python3
"""
乐乐语音桥 · 腾讯云中转 (UDP 枢纽, §七十 设备花名册版)

核心语义 (2026-10-24 §七十, 用户定稿):
  1. 单目标转发: 音频/控制帧/打洞包一律只发给 current_target 一台,
     不再广播 (无目标 = 丢弃, 直到工牌/菜单设定目标).
  2. 设备花名册: 接收端以 REG1+token+@tag|host|os|ver 登记 (20s 心跳=订阅),
     中转维护 tag → {host, os, ver, last_seen}, 在线=90s 内有心跳.
  3. 持久化: /opt/lele-relay/known_hosts.json (roster + current_target),
     变更即落盘, 重启不丢; 记录保留 30 天, 超期清除.
  4. 工牌花名册查询: RQST+token → RST+JSON (仅在线设备 + 当前目标).
  5. 打洞 (§六十五): SRCQ/PONG|PEER 的 PEER 现在取"当前 target"的映射地址.

历史兼容:
  - SUB+token[:tag] 老订阅仍被接受 (元数据缺省, 不影响转发);
  - TSET/TSET0/TGTQ/STATUS/PING-PONG 语义不变 (STATUS 尾部加 roster).

线程模型: 单线程 select-free (音频口 0.5s 超时轮询 + 探测口非阻塞).
"""

import json
import os
import socket
import sys
import time

TOKEN = b"lele-6deb6d37"
PORT_AUDIO = 9761
PORT_PING = 9762
SUB_TIMEOUT = 90.0          # 在线判定: 90s 无心跳视为离线
SOURCE_TIMEOUT = 60.0
STATS_INTERVAL = 60.0
RECORD_TTL_DAYS = 30        # 花名册记录保留 30 天 (§七十 用户定稿)
KNOWN_HOSTS = os.environ.get("LELE_KNOWN_HOSTS", "/var/lib/lele-relay/known_hosts.json")  # /opt 只读, 放可写层(仿真用 env 覆盖)


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)


def load_known_hosts():
    """持久化: {"target": tag|null, "hosts": {tag: {host,os,ver,last_seen}}}"""
    try:
        os.makedirs(os.path.dirname(KNOWN_HOSTS), exist_ok=True)
    except Exception:
        pass
    try:
        with open(KNOWN_HOSTS) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("hosts"), dict):
            return d
    except Exception:
        pass
    return {"target": None, "hosts": {}}


def save_known_hosts(state):
    tmp = KNOWN_HOSTS + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, KNOWN_HOSTS)
    except Exception as e:
        log(f"[!] known_hosts.json 写入失败: {e}")


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
    subs = {}                # addr -> {"last_seen": t, "tag": str}  (在线订阅, 含老 SUB)
    store = load_known_hosts()
    current_target = store.get("target") or None
    hosts = store.get("hosts", {})   # tag -> {host, os, ver, last_seen}
    log(f"relay up: audio:{PORT_AUDIO} ping:{PORT_PING} token=***{TOKEN[-4:].decode()}"
        f" | roster={len(hosts)} target={current_target or '-'} (§七十 单目标转发)")

    fwd = src_pkts = 0
    dropped_no_target = 0
    last_stats = time.time()
    last_cleanup = time.time()
    last_gc = time.time()
    last_flush = time.time()

    def tag_addr(tag):
        """在线订阅中该 tag 的地址 (同 tag 多端时取最近心跳者)"""
        cands = [(info["last_seen"], s) for s, info in subs.items() if info["tag"] == tag]
        return max(cands)[1] if cands else None

    def target_addrs():
        """§七十: 当前目标的地址列表 (0 或 1 台); 无目标 = [] (丢弃, 不广播)"""
        if not current_target:
            return []
        s = tag_addr(current_target)
        return [s] if s else []

    def persist():
        store["target"] = current_target
        store["hosts"] = hosts
        save_known_hosts(store)

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

            # 目标主机设定 (§六十八/§七十): TSET+token+@tag / TSET0 / TGTQ
            elif data.startswith(b"TSET0") and data[5:5 + len(TOKEN)] == TOKEN:
                current_target = None
                log("current target -> (none, 单目标模式: 无目标不转发)")
                persist()
                try:
                    a.sendto(b"TSET_OK", addr)
                except OSError:
                    pass
            elif data.startswith(b"TSET") and data[4:4 + len(TOKEN)] == TOKEN and data[4 + len(TOKEN):4 + len(TOKEN) + 1] == b"@":
                want = data[5 + len(TOKEN):].decode("utf-8", "ignore").strip()
                if want:
                    # bugbot 修复: 离线目标不生效 (防止"选择到声明间掉线"导致音频被丢)
                    if tag_addr(want) is not None:
                        if current_target != want:
                            current_target = want
                            persist()
                            log(f"current target -> {want!r} (在线)")
                    else:
                        log(f"current target -> {want!r} 拒绝: 离线 (保持 {current_target!r})")
                    try:
                        a.sendto(b"TSET_OK" if current_target == want else b"TSET_OFFLINE", addr)
                    except OSError:
                        pass
            elif data.startswith(b"TGTQ") and data[4:4 + len(TOKEN)] == TOKEN:
                reply = b"TGT @" + current_target.encode() if current_target else b"TGT -"
                try:
                    a.sendto(reply, addr)
                except OSError:
                    pass

            # 花名册登记 (§七十): REG1+token+@tag|host|os|ver —— 订阅+元数据+心跳
            elif data.startswith(b"REG1") and data[4:4 + len(TOKEN)] == TOKEN and data[4 + len(TOKEN):4 + len(TOKEN) + 1] == b"@":
                parts = data[5 + len(TOKEN):].decode("utf-8", "ignore").split("|")
                tag = (parts[0] if parts else "").strip() or "client"
                host = (parts[1] if len(parts) > 1 else "").strip() or tag
                os_name = (parts[2] if len(parts) > 2 else "").strip() or "?"
                ver = (parts[3] if len(parts) > 3 else "").strip() or "?"
                is_new = addr not in subs
                subs[addr] = {"last_seen": now, "tag": tag}
                rec = hosts.get(tag) or {}
                meta_changed = (rec.get("host") != host or rec.get("os") != os_name
                                or rec.get("ver") != ver or is_new or tag not in hosts)
                if is_new:
                    log(f"host registered: [{tag}] {host} ({os_name} v{ver}) from {addr[0]}:{addr[1]}")
                if meta_changed:
                    hosts[tag] = {"host": host, "os": os_name, "ver": ver, "last_seen": now}
                    persist()
                else:
                    # 心跳: 只更内存时间, 由定期兜底落盘 (bugbot 写放大修复)
                    hosts[tag]["last_seen"] = now
                try:
                    a.sendto(b"REG_OK", addr)
                except OSError:
                    pass

            # 老订阅 (兼容): SUB+token[:tag] —— 无元数据, 花名册里补占位
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
                    log(f"subscriber (legacy SUB): {addr[0]}:{addr[1]} [{tag}]")
                if tag not in hosts:
                    hosts[tag] = {"host": tag, "os": "?", "ver": "?", "last_seen": now}
                    persist()
                try:
                    a.sendto(b"SUB_OK", addr)
                except OSError:
                    pass

            # 花名册查询 (§七十): RQST+token → RST+JSON (仅在线 + 当前目标)
            elif data.startswith(b"RQST") and data[4:4 + len(TOKEN)] == TOKEN:
                online = {}
                for s, info in subs.items():
                    t = info["tag"]
                    rec = hosts.get(t, {})
                    online[t] = {"host": rec.get("host", t), "os": rec.get("os", "?"),
                                 "ver": rec.get("ver", "?")}
                payload = json.dumps({"target": current_target, "hosts": online},
                                     ensure_ascii=False, separators=(",", ":"))
                try:
                    a.sendto(b"RST " + payload.encode(), addr)
                except OSError:
                    pass

            # 打洞汇聚: 音源地址查询
            elif data.startswith(b"SRCQ") and data[4:4 + len(TOKEN)] == TOKEN:
                if source:
                    reply = b"SRC " + f"{source[0][0]}:{source[0][1]}".encode()
                else:
                    reply = b"SRC -"
                try:
                    a.sendto(reply, addr)
                except OSError:
                    pass

            # 音源数据包 (音频/控制帧/打洞): §七十 单目标转发, 不广播
            elif source and addr == source[0]:
                src_pkts += 1
                source = (addr, now)
                dsts = target_addrs()
                if not dsts:
                    dropped_no_target += 1
                    if dropped_no_target <= 3 or dropped_no_target % 100 == 0:
                        log(f"[§七十] 无目标, 丢弃音源包 (#{dropped_no_target}) — 待工牌/菜单 TSET")
                for s in dsts:
                    try:
                        a.sendto(data, s)
                        fwd += 1
                    except OSError:
                        pass

        # 定时清理: 音源/订阅超时
        if now - last_cleanup >= 5.0:
            last_cleanup = now
            if source and now - source[1] > SOURCE_TIMEOUT:
                log(f"source timeout: {source[0][0]}:{source[0][1]}")
                source = None
            dead = [s for s, info in subs.items() if now - info["last_seen"] > SUB_TIMEOUT]
            for s in dead:
                tag = subs.pop(s, {}).get("tag", "unknown")
                log(f"subscriber offline: [{tag}] (在线 {len(subs)})")

        # 花名册 last_seen 兜底落盘 (5min) + 30 天 GC + 目标失联检查 (每小时)
        if now - last_flush >= 300.0:
            last_flush = now
            persist()
        if now - last_gc >= 3600.0:
            last_gc = now
            ttl = RECORD_TTL_DAYS * 86400
            expired = [t for t, r in hosts.items() if now - r.get("last_seen", 0) > ttl]
            for t in expired:
                log(f"roster GC: {t} 超 30 天未连, 移除")
                hosts.pop(t, None)
            if expired:
                persist()
            if current_target and current_target not in hosts:
                log(f"current target {current_target} 已过期清除")
                current_target = None
                persist()

        # 探测与状态口 (UDP 9762)
        try:
            while True:
                d, addr2 = p.recvfrom(256)
                if len(d) >= 4 and d[:4] == b"PING":
                    pong = b"PONG" + d[4:12]
                    # 打洞: PEER = 当前目标的映射地址 (§七十, 原"最新订阅端"改为目标)
                    if source and current_target:
                        s = tag_addr(current_target)
                        if s:
                            pong += b"|PEER=%s:%d" % (str(s[0]).encode(), s[1])
                    p.sendto(pong, addr2)
                elif d.startswith(b"STATUS"):
                    src_str = f"{source[0][0]}:{source[0][1]}" if source else "offline"
                    sub_list = [f"{v['tag']}@{k[0]}:{k[1]}" for k, v in subs.items()]
                    roster = [f"{r['host']}({r['os']})" for t, r in hosts.items()]
                    status_resp = (f"source={src_str};subs={len(subs)};"
                                   f"list={','.join(sub_list)};src_pkts={src_pkts};fwd={fwd};"
                                   f"target={current_target or '-'};dropped={dropped_no_target};"
                                   f"roster={','.join(roster) or '-'}").encode()
                    p.sendto(status_resp, addr2)
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass

        # 定期统计
        if now - last_stats >= STATS_INTERVAL:
            last_stats = now
            sub_summary = [f"{v['tag']}@{k[0]}:{k[1]}" for k, v in subs.items()]
            log(f"stats: source={'yes' if source else 'no'} target={current_target or '-'} "
                f"subs={len(subs)} {sub_summary} src_pkts={src_pkts} forwarded={fwd} "
                f"dropped={dropped_no_target}")


if __name__ == "__main__":
    sys.exit(main())
