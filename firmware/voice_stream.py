"""
乐乐语音桥: ES8311 麦克风常开采集 + UDP PCM 推流 + 延迟探测.

硬件事实(官方 bsp_pins.h 单一事实来源):
  MCLK=GPIO6  BCLK=GPIO5  WS=GPIO3  DOUT(播放)=GPIO2  DIN(录音)=GPIO4
  MicroPython 的 machine.I2S 无 MCLK 输出 → 用 LEDC PWM 在 GPIO6 补 256*fs 时钟.
ES8311 寄存器序 1:1 复刻 esp_codec_dev 1.6.2 (open→set_fs→start, BOTH 模式,
  从机 + 外部 MCLK + I2S 标准格式 + 16bit + 16kHz), 麦克风 PGA=30dB.
"""

import socket
import struct
import time
from machine import Pin, PWM, I2S
from config import (STREAM_IP, STREAM_PORT, PING_PORT, STREAM_TOKEN,
                    SAMPLE_RATE, CHUNK_BYTES, PUNCH)

ES8311_ADDR = 0x18
MCLK_HZ = SAMPLE_RATE * 256          # 4.096MHz
HANDSHAKE = b"LELE1" + STREAM_TOKEN.encode()   # 音源注册包 (中转识别)
HANDSHAKE_EVERY_MS = 10000           # 握手纯计时, 静音期间也发: 中转音源注册 60s 过期,
                                     # 停发超时后控制帧会被当杂散包丢弃, 语音开关失灵

# 语音输入控制帧 (2026-10-11 §六十四): 接收器识别后合成微信输入法语音快捷键.
# 中转对已注册音源的未知前缀包原样转发(relay.py 音频分支), 无需改中转.
# 控制帧前缀 (发送时附 token + "@目标tag", §六十八: relay 按目标 tag 路由防多主机错乱)
CTRL_DICT_ON  = b"DICT1"   # 上键: 长输入会话开
CTRL_DICT_OFF = b"DICT0" + STREAM_TOKEN.encode()   # 上键: 长输入会话关
CTRL_PTT_DOWN = b"PTTD1"   # 下键: 按住说话 按下
CTRL_PTT_UP   = b"PTTD0"   # 下键: 按住说话 抬起
CTRL_TGTM     = b"TGTM1"   # 目标切换广播 (所有端显示用)
TARGETS = ("mac", "pc")
CTRL_RETRY    = 3                    # 每事件连发 3 遍抗 UDP 丢包 (接收端 300ms 去重)
CTRL_GAP_MS   = 30
MUTE_GRACE_MS = 1500                 # 语音关/PTT 抬起后延迟静音, 留识别端收尾音频

# I2S 引脚 (官方 bsp_pins.h)
PIN_MCLK = 6
PIN_BCLK = 5
PIN_WS   = 3
PIN_DIN  = 4   # 录音: codec → MCU

# 丢包统计窗口
PING_INTERVAL_MS = 1000


class VoiceStream:
    """常开麦克风推流器. poll() 每次读一个 CHUNK 并发送, 由阻塞读自然节拍."""

    def __init__(self, i2c):
        # 目标主机 (§六十八): /target.txt 持久化, 上键长按切换
        try:
            self.target = open("/target.txt").read().strip() or "mac"
        except Exception:
            self.target = "mac"
        self.i2c = i2c
        self.codec_ok = False
        self.mclk = None
        self.i2s = None
        self.sock = None
        self.muted = True            # 开机待机: 按上键开语音后才推流 (握手照发, 注册不过期)
        self.dict_on = False         # 语音输入(长输入会话)开关, 由上键切换
        self.ptt_active = False      # PTT 按住中, 由下键切换
        self._mute_deadline = None   # 延迟静音时刻 (ticks_ms)
        self._last_hs_ms = 0
        # 统计
        self.pkts = 0
        self.bytes_sent = 0
        self.send_errors = 0
        self.rtt_ms = None          # 最近一次 PING/PONG 往返
        self.rtt_min = None
        self.rtt_max = None
        self.pings_sent = 0
        self.pongs_recv = 0
        self.last_pong_ms = None
        self._ping_seq = 0
        self._last_ping_ms = 0
        self._chunk = bytearray(CHUNK_BYTES)
        # UDP 打洞 (§六十五): _peer=终端映射地址(PONG|PEER= 捎来), 互发 PNCH;
        # _direct=终端地址, 收到其 PNCH 即直连发音频, 10s 无 PNCH 回退中转.
        self._peer = None
        self._direct = None
        self._direct_last_ms = 0
        self._punch_seen = 0

    # ------------------------------------------------------------------
    # ES8311 初始化 (录音通路)
    # ------------------------------------------------------------------
    def _w(self, reg, val):
        try:
            self.i2c.writeto_mem(ES8311_ADDR, reg, bytes([val]))
        except Exception as e:
            print("[!] ES8311 write %02X failed:" % reg, e)

    def _r(self, reg):
        try:
            return self.i2c.readfrom_mem(ES8311_ADDR, reg, 1)[0]
        except Exception:
            return 0

    def init_codec(self):
        """ES8311 ADC 上电. 序列 = esp_codec_dev 1.6.2 es8311.c:
        open() → set_fs(16k/16bit/I2S) → start(), 从机+外部MCLK."""
        if not self.i2c:
            print("[!] no I2C, codec skipped")
            return False
        w = self._w
        try:
            if 0x18 not in [a for a in self.i2c.scan()]:
                print("[!] ES8311 not on I2C bus")
                return False
        except Exception:
            pass

        # --- es8311_open ---
        w(0x0D, 0xFA)                 # 全关, 进入已知态
        w(0x44, 0x08)                 # I2C 抗噪 (写两次, 首写偶发丢)
        w(0x44, 0x08)
        w(0x01, 0x30)
        w(0x02, 0x00)
        w(0x03, 0x10)
        w(0x16, 0x24)
        w(0x04, 0x10)
        w(0x05, 0x00)
        w(0x0B, 0x00)
        w(0x0C, 0x00)
        w(0x10, 0x1F)
        w(0x11, 0x7F)
        w(0x00, 0x80)                 # 软复位
        w(0x00, self._r(0x00) & 0xBF) # 从机模式 (bit6=0)
        w(0x01, 0x3F)                 # 内部 MCLK=外部引脚, 不反相
        w(0x06, self._r(0x06) & ~0x20 & 0xFF)  # SCLK 不反相
        w(0x13, 0x10)
        w(0x1B, 0x0A)
        w(0x1C, 0x6A)
        w(0x44, 0x08)                 # no_dac_ref=true: 单声道采集走纯 ADC

        # --- set_fs: 16kHz, 16bit, I2S 标准 (MCLK=256fs=4096000 系数表行) ---
        w(0x09, 0x0C)                 # SDP-IN  (DAC侧) 16bit, I2S
        w(0x0A, 0x0C)                 # SDP-OUT (ADC侧) 16bit, I2S
        w(0x02, 0x00)                 # pre_div=1, mult=x1
        w(0x05, 0x00)                 # adc_div=1, dac_div=1
        w(0x03, 0x10)                 # fs_mode=SS, ADC_OSR=0x10
        w(0x04, 0x20)                 # DAC_OSR=0x20
        w(0x07, 0x00)                 # LRCK div high
        w(0x08, 0xFF)                 # LRCK div low
        w(0x06, 0x03)                 # BCLK div

        # --- es8311_start (BOTH 模式, 与官方 bsp_audio 同) ---
        w(0x00, 0x80)
        w(0x01, 0x3F)
        w(0x09, 0x0C)
        w(0x0A, 0x0C)
        w(0x17, 0xBF)                 # ADC 数字通路使能
        w(0x0E, 0x02)                 # 上电 ADC
        w(0x12, 0x00)
        w(0x14, 0x1A)                 # 模拟麦 (非 DMIC)
        w(0x0D, 0x01)                 # 上电 VREF
        w(0x15, 0x40)
        w(0x37, 0x08)                 # beep 关
        w(0x45, 0x00)
        w(0x16, 0x05)                 # 麦克风 PGA +30dB (枚举 5 = 30dB)
        # 扬声器静音: 麦在旁边, 防啸叫
        w(0x31, self._r(0x31) | 0x60) # DAC soft-mute
        w(0x32, 0x00)
        self.codec_ok = True
        print("[+] ES8311 mic ready (30dB, muted speaker)")
        return True

    # ------------------------------------------------------------------
    # 时钟 / I2S / 网络
    # ------------------------------------------------------------------
    def start(self):
        """MCLK PWM + I2S RX + UDP socket. 返回 False=致命错误."""
        # MCLK: machine.I2S 不驱动 MCLK, LEDC 补 256fs
        try:
            self.mclk = PWM(Pin(PIN_MCLK), freq=MCLK_HZ, duty_u16=32768)
            print("[+] MCLK %dHz on GPIO%d" % (MCLK_HZ, PIN_MCLK))
        except Exception as e:
            print("[!] MCLK PWM failed:", e)
            return False

        try:
            self.i2s = I2S(
                0,
                sck=Pin(PIN_BCLK),
                ws=Pin(PIN_WS),
                sd=Pin(PIN_DIN),
                mode=I2S.RX,
                bits=16,
                format=I2S.MONO,
                rate=SAMPLE_RATE,
                ibuf=CHUNK_BYTES * 8,   # 8KB = 256ms 抗抖: UI 重画期间不丢采样
            )
            print("[+] I2S0 RX 16k/16bit/mono (BCLK=%d WS=%d DIN=%d)" % (PIN_BCLK, PIN_WS, PIN_DIN))
        except Exception as e:
            print("[!] I2S init failed:", e)
            return False

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.bind(("0.0.0.0", PING_PORT))  # 固定源端口, PONG 回得来
            except OSError:
                pass                                    # 占用则用临时端口, PONG 走源地址
            self.sock.setblocking(False)
            print("[+] UDP stream -> %s:%d (ping %d)" % (STREAM_IP, STREAM_PORT, PING_PORT))
        except Exception as e:
            print("[!] UDP socket failed:", e)
            return False
        return True

    # ------------------------------------------------------------------
    # 主循环每拍: 读一包 PCM + 发送 + PING/PONG 维护
    # ------------------------------------------------------------------
    def poll(self):
        """阻塞读一个 32ms 块并推流. 返回本块字节数 (0=跳过)."""
        now = time.ticks_ms()
        # 握手纯计时: 静音期间照发, 保住中转音源注册, 控制帧才永远可达
        if time.ticks_diff(now, self._last_hs_ms) >= HANDSHAKE_EVERY_MS:
            self._last_hs_ms = now
            try:
                self.sock.sendto(HANDSHAKE, (STREAM_IP, STREAM_PORT))
            except Exception:
                pass
        # 延迟静音到期 (语音关/PTT 抬起后的收尾宽限)
        if self._mute_deadline is not None and time.ticks_diff(now, self._mute_deadline) >= 0:
            self._mute_deadline = None
            self.muted = True
        try:
            n = self.i2s.readinto(self._chunk)
        except Exception as e:
            self.send_errors += 1
            print("[!] I2S read error:", e)
            time.sleep_ms(100)
            return 0
        if n and not self.muted:
            ok = False
            # 直连优先: 收到终端 PNCH 后 10s 内音频直发终端, 不经中转
            if self._direct is not None and time.ticks_diff(now, self._direct_last_ms) > 10000:
                self._direct = None
                print("[!] 直连超时, 回退中转")
            dst = self._direct if self._direct else (STREAM_IP, STREAM_PORT)
            try:
                self.sock.sendto(memoryview(self._chunk)[:n], dst)
                ok = True
            except OSError:
                # ENOMEM: WiFi TX 队列瞬时满, 让一口气重试一次
                time.sleep_ms(3)
                try:
                    self.sock.sendto(memoryview(self._chunk)[:n], dst)
                    ok = True
                except OSError:
                    pass
            except Exception:
                pass
            if ok:
                self.pkts += 1
                self.bytes_sent += n
            else:
                self.send_errors += 1
                if self.send_errors < 5 or self.send_errors % 100 == 0:
                    print("[!] UDP send dropped (#%d)" % self.send_errors)
        self._poll_ping()
        return n

    # ------------------------------------------------------------------
    # 语音输入控制 (工牌按键 → 控制帧 → 接收器合成微信输入法快捷键)
    # ------------------------------------------------------------------
    def _send_ctrl(self, frame):
        """控制帧连发 3 遍抗丢包; 阻塞 ~90ms, I2S 8KB 缓冲(256ms)可吸收.
        帧 = 前缀 + token + "@目标tag" (§六十八, relay 按目标路由)."""
        frame = frame + STREAM_TOKEN.encode() + b"@" + self.target.encode()
        for i in range(CTRL_RETRY):
            try:
                self.sock.sendto(frame, (STREAM_IP, STREAM_PORT))
            except Exception:
                pass
            if i < CTRL_RETRY - 1:
                time.sleep_ms(CTRL_GAP_MS)

    def _unmute(self):
        self.muted = False
        self._mute_deadline = None

    def _mute_later(self):
        if not self.dict_on:         # 长输入会话开着时不静音
            self._mute_deadline = time.ticks_add(time.ticks_ms(), MUTE_GRACE_MS)

    def set_dict_mode(self, on):
        """上键: 语音输入(长输入会话)开/关. 开=先广播再解除静音; 关=广播后延迟静音."""
        self._send_ctrl(CTRL_DICT_ON if on else CTRL_DICT_OFF)
        self.dict_on = on
        if on:
            self._unmute()
        else:
            self._mute_later()

    def switch_target(self):
        """上键长按: Mac → Windows → Mac 轮换, 持久化 + TGTM1 广播(所有端显示).
        语音会话开着时无缝接力: 旧目标补 DICT0(结束), 新目标补 DICT1(接续识别)."""
        old = self.target
        i = TARGETS.index(old) if old in TARGETS else 0
        self.target = TARGETS[(i + 1) % len(TARGETS)]
        try:
            open("/target.txt", "w").write(self.target)
        except Exception:
            pass
        if self.dict_on:
            self._send_ctrl_to(CTRL_DICT_OFF, old)
            self._send_ctrl_to(CTRL_DICT_ON, self.target)
        self._send_ctrl(CTRL_TGTM)
        return self.target

    def _send_ctrl_to(self, frame, target):
        """指定目标发控制帧 (接力用, 不改 self.target)."""
        frame = frame + STREAM_TOKEN.encode() + b"@" + target.encode()
        for i in range(CTRL_RETRY):
            try:
                self.sock.sendto(frame, (STREAM_IP, STREAM_PORT))
            except Exception:
                pass
            if i < CTRL_RETRY - 1:
                time.sleep_ms(CTRL_GAP_MS)

    def set_ptt(self, down):
        """下键: 按住说话. 按下=广播+解除静音; 抬起=广播+延迟静音."""
        self._send_ctrl(CTRL_PTT_DOWN if down else CTRL_PTT_UP)
        self.ptt_active = down
        if down:
            self._unmute()
        else:
            self._mute_later()

    def _poll_ping(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_ping_ms) >= PING_INTERVAL_MS:
            self._last_ping_ms = now
            self._ping_seq = (self._ping_seq + 1) & 0xFFFF
            try:
                self.sock.sendto(
                    b"PING" + struct.pack("<HI", self._ping_seq, now),
                    (STREAM_IP, PING_PORT),
                )
                self.pings_sent += 1
            except Exception:
                pass
            # 打洞: 向终端映射地址发 PNCH (与 PING 同节拍, 每秒一次)
            if PUNCH and self._peer:
                try:
                    self.sock.sendto(b"PNCH" + STREAM_TOKEN.encode(), self._peer)
                except Exception:
                    pass
        # 收 PONG (非阻塞) / 终端 PNCH (直连建立)
        while True:
            try:
                data, addr = self.sock.recvfrom(128)
            except OSError:
                break
            except Exception:
                break
            if len(data) >= 10 and data[:4] == b"PONG":
                seq, t = struct.unpack("<HI", data[4:10])
                rtt = time.ticks_diff(time.ticks_ms(), t)
                if rtt < 0:
                    rtt = 0
                self.rtt_ms = rtt
                self.rtt_min = rtt if self.rtt_min is None else min(self.rtt_min, rtt)
                self.rtt_max = rtt if self.rtt_max is None else max(self.rtt_max, rtt)
                self.pongs_recv += 1
                self.last_pong_ms = time.ticks_ms()
                # 打洞汇聚: PONG 尾巴 |PEER=ip:port = 终端映射地址 (旧中转无尾巴)
                if PUNCH and b"|PEER=" in data:
                    try:
                        spec = data.split(b"|PEER=", 1)[1].decode()
                        ip, port = spec.rsplit(":", 1)
                        peer = (ip, int(port))
                        if peer != self._peer:
                            self._peer = peer
                            print("[+] 打洞目标(终端):", spec)
                    except Exception:
                        pass
            elif PUNCH and len(data) >= 4 and data[:4] == b"PNCH":
                # 终端 PNCH 到达 = 出站方向通; 但返回路未证, 不切直连.
                if data[4:4 + len(STREAM_TOKEN)] == STREAM_TOKEN.encode():
                    self._punch_seen = time.ticks_ms()
            elif PUNCH and len(data) >= 5 and data[:4] == b"PNCHA":
                # 终端对我方 PNCH 的回执 = 双向通, 才切直连 (防 Mac 侧对称 NAT 死空气)
                if data[5:5 + len(STREAM_TOKEN)] == STREAM_TOKEN.encode():
                    if self._direct != addr:
                        self._direct = addr
                        print("[+] 直连建立(终端, ACK 确认):", addr)
                    self._direct_last_ms = time.ticks_ms()
            # 丢弃其它杂散包

    # ------------------------------------------------------------------
    def set_muted(self, m):
        self.muted = m

    def kbps(self):
        return (self.bytes_sent * 8) // 1024  # 累计 kbit

    def close(self):
        for obj in (self.i2s, self.mclk):
            try:
                if obj:
                    obj.deinit()
            except Exception:
                pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
