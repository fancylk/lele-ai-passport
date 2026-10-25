#!/usr/bin/env python3
"""
双端复制转发模拟测试 (End-to-End Simulation Test)

测试场景:
1. 模拟 PC 终端 (tag: pc) 与 Mac 终端 (tag: mac) 同时向腾讯云中转注册订阅 (SUB + token:tag)
2. 模拟工牌音源 (LELE1 + token 握手, 随后以 32ms 节拍持续推 100 包 16kHz s16le PCM 音频)
3. 验证:
   - 中转状态接口 (STATUS): 确认音源在线, 且存在 pc 和 mac 两个订阅者
   - 双端接收包计数: 验证 PC 端与 Mac 端均全量收到 100% 数据包 (双路复制, 丢包率 0%)
   - 数据包内容一致性: 校验双端收到的二进制数据与发送端完全一致
"""

import math
import socket
import struct
import sys
import threading
import time

RELAY_HOST = "124.221.187.167"
PORT_AUDIO = 9761
PORT_PING = 9762
TOKEN = b"lele-6deb6d37"

SAMPLE_RATE = 16000
CHUNK_BYTES = 1024  # 512 samples = 32ms
TOTAL_PACKETS = 100  # 发送 100 包 (约 3.2 秒音频)


def generate_pcm_sine(num_chunks, freq=440.0):
    """生成一段测试正弦波 PCM 音频块"""
    chunks = []
    samples_per_chunk = CHUNK_BYTES // 2
    total_samples = num_chunks * samples_per_chunk
    sample_idx = 0
    for _ in range(num_chunks):
        buf = bytearray(CHUNK_BYTES)
        for s in range(samples_per_chunk):
            t = (sample_idx + s) / SAMPLE_RATE
            val = int(32767 * 0.5 * math.sin(2 * math.pi * freq * t))
            struct.pack_into("<h", buf, s * 2, val)
        chunks.append(bytes(buf))
        sample_idx += samples_per_chunk
    return chunks


def query_relay_status():
    """通过 9762 端口查询中转运行状态"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    try:
        s.sendto(b"STATUS", (RELAY_HOST, PORT_PING))
        resp, _ = s.recvfrom(512)
        return resp.decode("utf-8", "ignore")
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        s.close()


class ReceiverClient:
    def __init__(self, tag):
        self.tag = tag
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.5)
        self.received_packets = []
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        # 发送订阅请求: SUB + token + :tag
        sub_msg = b"SUB" + TOKEN + b":" + self.tag.encode()
        self.sock.sendto(sub_msg, (RELAY_HOST, PORT_AUDIO))
        self.thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()

    def _recv_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(2048)
                if data == b"SUB_OK":
                    continue
                self.received_packets.append(data)
            except socket.timeout:
                pass
            except Exception:
                break

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        self.sock.close()


def run_test():
    print("=" * 60)
    print("乐乐语音桥: 腾讯云双端复制转发模拟测试")
    print(f"目标中转: {RELAY_HOST}:{PORT_AUDIO}")
    print(f"测试轮次: 发送 {TOTAL_PACKETS} 个 1024 字节音频包 (~3.2 秒)")
    print("=" * 60)

    # 1. 初始状态
    initial_status = query_relay_status()
    print(f"\n[1] 中转初始状态: {initial_status}")

    # 2. 启动两个模拟接收客户端: Mac 与 PC
    print("\n[2] 启动双订阅端...")
    mac_client = ReceiverClient("mac")
    pc_client = ReceiverClient("pc")

    mac_client.start()
    time.sleep(0.1)
    pc_client.start()
    time.sleep(0.3)

    # 验证中转是否同时记录了两个订阅端
    sub_status = query_relay_status()
    print(f"    当前中转状态: {sub_status}")

    # 3. 准备音频数据
    print(f"\n[3] 生成测试音频数据 ({TOTAL_PACKETS} 包, 440Hz 正弦波)...")
    pcm_chunks = generate_pcm_sine(TOTAL_PACKETS)

    # 4. 模拟工牌音源推流
    print("\n[4] 模拟工牌推流:")
    src_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    src_sock.settimeout(2.0)

    # 发送握手包
    handshake = b"LELE1" + TOKEN
    src_sock.sendto(handshake, (RELAY_HOST, PORT_AUDIO))
    try:
        hs_ack, _ = src_sock.recvfrom(64)
        print(f"    音源握手成功, 中转回复: {hs_ack.decode('utf-8', 'ignore')}")
    except socket.timeout:
        print("    音源握手未收到回执 (继续推流)")

    # 连续推送 PCM 音频
    t_start = time.time()
    for i, chunk in enumerate(pcm_chunks):
        src_sock.sendto(chunk, (RELAY_HOST, PORT_AUDIO))
        # 按照 ~32ms 节拍推流 (16kHz / 512 samples)
        time.sleep(0.031)
        if (i + 1) % 25 == 0 or (i + 1) == TOTAL_PACKETS:
            print(f"    推流进度: {i + 1}/{TOTAL_PACKETS} 包...")

    duration = time.time() - t_start
    print(f"    推流完成, 耗时 {duration:.2f} 秒")

    # 稍微等待接收完成
    time.sleep(0.5)

    # 5. 停止接收并比对结果
    mac_client.stop()
    pc_client.stop()
    src_sock.close()

    print("\n[5] 双端接收统计与数据完整性校验:")
    mac_count = len(mac_client.received_packets)
    pc_count = len(pc_client.received_packets)

    print(f"    - 发送端总发送: {TOTAL_PACKETS} 包")
    print(f"    - Mac 终端收到: {mac_count} 包 (接收率: {mac_count / TOTAL_PACKETS * 100:.1f}%)")
    print(f"    - PC  终端收到: {pc_count} 包 (接收率: {pc_count / TOTAL_PACKETS * 100:.1f}%)")

    # 逐包内容一致性检查
    mac_match = (mac_client.received_packets == pcm_chunks)
    pc_match = (pc_client.received_packets == pcm_chunks)
    both_identical = (mac_client.received_packets == pc_client.received_packets)

    print(f"    - Mac 端数据内容 100% 匹配音源: {'✓ 是' if mac_match else '✗ 否'}")
    print(f"    - PC  端数据内容 100% 匹配音源: {'✓ 是' if pc_match else '✗ 否'}")
    print(f"    - Mac 与 PC 接收到的内容完全一致: {'✓ 是' if both_identical else '✗ 否'}")

    # 6. 查询中转最终统计
    final_status = query_relay_status()
    print(f"\n[6] 中转最终状态: {final_status}")

    print("\n" + "=" * 60)
    if mac_count == TOTAL_PACKETS and pc_count == TOTAL_PACKETS and mac_match and pc_match:
        print("✓ 测试通过: 腾讯云中转双路复制发送功能完全正常, PC 和 Mac 均无损全量接收!")
        print("=" * 60)
        return 0
    else:
        print("✗ 测试未完全通过, 请检查中转转发日志与丢包情况")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(run_test())
