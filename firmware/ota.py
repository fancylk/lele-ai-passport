"""OTA 客户端 (§六十六): 原生 socket HTTP 拉取 manifest → crc32 校验 →
/ota 暂存 → /backup 备份 → 原地替换 → /installed.json → 重启.
中断安全: /ota.pending 在 boot.py 回滚守卫里检测, 未完成的升级从 /backup 还原.

服务端 = 腾讯 nginx 静态目录 (scripts/ota_publish.sh 发布), URL 布局:
  OTA_PATH + "manifest.json"            → {"v": N, "files": {"main.py": crc32, "apps/menu.py": ...}}
  OTA_PATH + "<设备路径 / → _>"          → 文件内容 (apps/menu.py 存为 apps_menu.py)
"""

import binascii
import gc
import json
import os
import socket

from config import OTA_HOST, OTA_PORT, OTA_PATH

INSTALL_PATH = "/installed.json"
PENDING_PATH = "/ota.pending"
STAGE_DIR = "/otastage"
BACKUP_DIR = "/backup"

_expect = {}   # manifest 的 files 字典 (check() 时刷新), 供下载后核对


def _http_get_small(path, timeout=10):
    """HTTP/1.0 GET, body 整包返回 (仅用于小文件如 manifest)."""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((OTA_HOST, OTA_PORT))
        s.send(b"GET %s%s HTTP/1.0\r\nHost: %s\r\n\r\n" % (OTA_PATH, path, OTA_HOST))
        buf = b""
        while True:
            try:
                d = s.recv(2048)
            except OSError:
                break
            if not d:
                break
            buf += d
            if len(buf) > 64 * 1024:
                raise OSError("响应过大")
    finally:
        s.close()
    i = buf.find(b"\r\n\r\n")
    if i < 0:
        raise OSError("HTTP 响应不完整")
    status = buf[:buf.find(b"\r\n")].decode()
    if " 200" not in status:
        raise OSError(status)
    return buf[i + 4:]


def _http_download(path, dest, timeout=30):
    """HTTP/1.0 GET 流式写盘 (font16.bin 282KB 不能整包进堆), 返回 crc32."""
    s = socket.socket()
    s.settimeout(timeout)
    h = 0
    try:
        s.connect((OTA_HOST, OTA_PORT))
        s.send(b"GET %s%s HTTP/1.0\r\nHost: %s\r\n\r\n" % (OTA_PATH, path, OTA_HOST))
        # 跳过响应头
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = s.recv(1024)
            if not d:
                raise OSError("HTTP 响应不完整")
            buf += d
        i = buf.find(b"\r\n\r\n")
        head_first = buf[:buf.find(b"\r\n")].decode()
        if " 200" not in head_first:
            raise OSError(head_first)
        body = buf[i + 4:]
        with open(dest, "wb") as f:
            if body:
                h = binascii.crc32(body, h)
                f.write(body)
            while True:
                try:
                    d = s.recv(2048)
                except OSError:
                    break
                if not d:
                    break
                h = binascii.crc32(d, h)
                f.write(d)
    finally:
        s.close()
    return h & 0xFFFFFFFF


def _crc_file(path):
    h = 0
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(CHUNK)
                if not b:
                    break
                h = binascii.crc32(b, h)
    except OSError:
        return None
    return h & 0xFFFFFFFF


CHUNK = 1024


def _read_installed():
    try:
        with open(INSTALL_PATH) as f:
            return json.load(f)
    except Exception:
        return {"v": 0, "files": {}}


def _safe_name(n):
    if not n or n.startswith("/") or ".." in n or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/" for c in n):
        raise ValueError("非法文件名 " + n)


def check():
    """对比 manifest 与本地已装. 返回 (新版本号, 待更新文件列表) 或 None=已最新.
    抛 OSError/ValueError = 网络或格式问题."""
    global _expect
    m = json.loads(_http_get_small("manifest.json"))
    if "v" not in m or "files" not in m:
        raise ValueError("manifest 格式错误")
    _expect = m["files"]
    inst = _read_installed().get("files", {})
    changed = [n for n, c in m["files"].items()
               if _crc_file("/" + n) != c or inst.get(n) != c]
    if not changed:
        return None
    return m["v"], sorted(set(changed))


def download_and_apply(newv, files, log=None):
    """下载待更新文件到 /ota → 落 /ota.pending → 备份 → 原地替换.
    成功后调用方应 machine.reset(); 中途断电由 boot.py 从 /backup 还原."""
    say = log or (lambda s: print(s))
    try:
        os.mkdir(STAGE_DIR)
    except OSError:
        pass
    try:
        os.mkdir(BACKUP_DIR)
    except OSError:
        pass
    for i, n in enumerate(files):
        _safe_name(n)
        say("OTA 下载 %d/%d %s" % (i + 1, len(files), n))
        crc = _http_download(n.replace("/", "_"), STAGE_DIR + "/" + n.replace("/", "_"))
        if crc != _expect.get(n):
            raise ValueError(n + " crc 校验失败")
        gc.collect()
    with open(PENDING_PATH, "w") as f:
        f.write("\n".join(files))
    for n in files:
        dst = "/" + n
        ddir = dst.rsplit("/", 1)[0]
        if ddir and ddir != "/":
            try:
                os.mkdir(ddir)
            except OSError:
                pass
        try:
            os.rename(dst, BACKUP_DIR + "/" + n.replace("/", "_"))
        except OSError:
            pass  # 新文件无旧版
        os.rename(STAGE_DIR + "/" + n.replace("/", "_"), dst)
        say("OTA 应用 " + n)
    with open(INSTALL_PATH, "w") as f:
        f.write(json.dumps({"v": newv, "files": _expect}))
    os.remove(PENDING_PATH)
    say("OTA 完成 v%d, 重启生效" % newv)
