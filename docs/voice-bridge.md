# 乐乐语音桥 —— 工牌麦克风常开 → Mac 微信输入法语音输入

> 2026-10-06 定稿并实装。工牌彻底清零重设计：不再做导游演示，专职当
> **语音输入音源**（常开麦克风），屏幕实时显示到主机端的延迟，便于评估链路。

## 架构

```
[工牌 ESP32-C3 + ES8311]  麦克风常开采集 16kHz/16bit/mono
  → Wi-Fi UDP 推流 (1024B=32ms/包 → Mac:9761)
  → Mac voice_receiver.py → BlackHole 2ch 虚拟声卡
  → 微信输入法 Mac 版（语音输入, 麦克风选 BlackHole 2ch, 识别=腾讯云）
  → 文字落 Mac 任意应用
```

延迟探测旁路：工牌每秒发 `PING(seq,t)` → Mac:9762 → 回 `PONG` →
工牌算 RTT 上屏（主页大字），另存最小/最大/丢包数（详情页）。
Mac 侧另测**到包抖动**（每 5 秒统计行）。屏幕两页：上=状态+RTT，OK=详情。

## 硬件事实（引脚单一事实来源 = 官方 bsp_pins.h，gitee.com/FoloToy/ai-passport）

| 信号 | GPIO | 说明 |
|---|---|---|
| MCLK | 6 | machine.I2S 不驱动 MCLK → **LEDC PWM 4.096MHz**（256×16k）补时钟 |
| BCLK | 5 | I2S0 主机 |
| WS/LRCK | 3 | |
| DIN（录音） | 4 | codec → MCU |
| DOUT（播放） | 2 | 本应用不用（扬声器静音防啸叫） |
| I2C SDA/SCL | 10 / 7 | ES8311=0x18, CW2017=0x63 |

## ES8311 录音初始化（voice_stream.py）

寄存器序 1:1 复刻 esp_codec_dev 1.6.2 的 `es8311_open → set_fs(16k/16bit/I2S) →
es8311_start`（从机+外部 MCLK，BOTH 模式与官方 bsp_audio.c 一致），
最后：REG16=0x05（麦克风 PGA **+30dB**，同 bsp_audio set_in_gain(30)）、
REG31|=0x60 + REG32=0x00（DAC 静音——喇叭贴着麦克风，禁一切提示音）。

关键坑（来自 bsp_audio.c 注释）：**打开后不要手写 REG01~06 的官方驱动值以外
的分频**——本文件写的就是驱动算出的同一组值（MCLK=256fs 系数表行）。

## 固件文件（firmware/）

| 文件 | 作用 |
|---|---|
| `main.py` | 语音桥应用：按键 上=静音切换 下=立即测延迟 OK=翻页 |
| `voice_stream.py` | ES8311 init + MCLK PWM + I2S RX + UDP 推流 + PING/PONG |
| `config.py` | `STREAM_IP`(Mac=192.168.31.185)/9761/9762/16k/CHUNK |
| 其余 | wifi_manager / st7789_direct / chinese_font / battery 沿用 |

旧导游版（三步状态机）已整体移除，回滚看 git 历史。

## Mac 端（tools/）

```bash
tools/voice_receiver.sh start        # 后台收流→BlackHole
tools/verify_blackhole.sh            # 录 BlackHole 6s 报电平（验证音频真到了）
scripts/deploy_wireless_ota_mac.sh   # WebREPL OTA 固件到工牌（默认 192.168.31.133）
```

## 微信输入法 Mac 版设置

官网 z.weixin.qq.com 下载 → 登录 → 设置 → 语音输入 → 麦克风设备选
**BlackHole 2ch**。之后点它的麦克风按钮（或快捷键），对工牌说话即出字。

## 端到端验证步骤

1. Mac: `tools/voice_receiver.sh start`
2. 工牌上电（约 5 秒后开始推流，屏幕显示 ● 推流中 + RTT）
3. Mac: `tools/verify_blackhole.sh` → max_volume > -25dB = 音频到位
4. 微信输入法点麦克风 → 对工牌说话 → 出中文字

## 实装记录(2026-10-06, 已全部实证)

1. **工牌曾被恢复出厂(原厂 C 固件, OTA v2.7.8, 8266 拒连 = 没有 WebREPL)**。
   重刷 MicroPython 配方: `pip install esptool` →
   `esptool --port /dev/cu.usbmodem101 erase-flash` →
   `esptool --port … write-flash 0x0 ESP32_GENERIC_C3-…-v1.29.0.bin`
   (官方包 machine.I2S 在位; 8MB XMC flash 直接可用; 原厂固件可随时用官方
   网页刷机工具恢复, ai-passport.folotoy.cn/tools/web-flasher)。
2. **WiFi 省电模式是 UDP 推流天敌**: 默认 modem-sleep 下 sendto 大量
   `ENOMEM`(TX 队列等 DTIM 排爆), 表现 1 包/秒。**connect 后
   `wlan.config(pm=0)` 射频常开**, 之后 29.3 包/秒稳定持续。
3. **屏幕性能铁律(实测基准)**: 汉字绘制 8.5ms/字, 整页清除 56ms,
   整页≈50 字 ≈500ms → 整页周期性重画会把 32ms 的音频节拍饿死。
   对策: 整页只在启动/翻页画; 运行期每 500ms 只增量刷一行; I2S ibuf
   8KB(=256ms) 吸收绘制期抖动。
4. I2S 实测节拍 31.8ms/1024B = 精确 16kHz 实时; 空闲室内声
   peak≈0.07/rms≈0.007 = ES8311+MCLK(PWM)+I2S 链全部真实有效。

## 排障(按发生概率)

- **屏幕 RTT --- 且 Mac 收 0 包**：WiFi 未连 / Mac IP 变了（改 config.py
  STREAM_IP）/ 接收器没跑（`voice_receiver.sh status`）
- **发包速率掉到 1-5 包/秒**：wifi_manager 里 `pm=0` 丢了（重连后未生效）；
  或整页重画回归（看 main.py 是否还守"增量刷行"铁律）
- **RTT 通但 BlackHole 无声**：接收器输出设备不对（`--device "BlackHole 2ch"`），
  系统设置→声音里确认 BlackHole 存在
- **BlackHole 有流但录出来全零**：macOS 麦克风权限——抓音设备（含 BlackHole）
  无 TCC 授权时**不报错、只回全零**；系统设置→隐私与安全性→麦克风 给终端/
  微信输入法开权限
- **8266 拒绝连接**：工牌又被恢复成原厂 C 固件（串口日志是 ESP-IDF 格式+
  lele_ota OTA 检查即证据），按上面配方重刷 MicroPython
- **REPL 进不去（could not enter raw repl）**：老 main.py 死循环吃 stdin 吞了
  Ctrl-C；用 `tools/serial_grab.py`（USB-JTAG 硬复位+Ctrl-C 风暴抢窗口），
  新版 main.py 不读 stdin 无此问题
- **有声音但识别差**：工牌离麦太远 → 详情页看 RSSI；或 PGA 不够（voice_stream
  REG16 调 0x06=36dB）
- **UDP 丢包高（丢 PING 上涨）**：2.4G 拥挤；可把 CHUNK_BYTES 加到 1400 降包率

## 二期（未做）

识别文字 UDP 回推盒子 192.168.31.103 的 InputPad（com.taoge.inputpad 剪贴板桥）
→ RDP 会话 Ctrl+V 粘贴（Windows App 剪贴板重定向）。Mac 侧需一个抓上屏文字的
辅助器（辅助功能 API 或手动选中复制），InputPad v2 加 UDP 监听。
