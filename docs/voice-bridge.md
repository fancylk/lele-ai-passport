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

## 故障排查

- **屏幕 RTT --- 且 Mac 收 0 包**：WiFi 未连 / Mac IP 变了（改 config.py
  STREAM_IP）/ 接收器没跑（`voice_receiver.sh status`）
- **RTT 通但 BlackHole 无声**：接收器输出设备不对（`--device "BlackHole 2ch"`），
  系统设置→声音里确认 BlackHole 存在
- **有声音但识别差**：工牌离麦太远 → 详情页看 RSSI；或 PGA 不够（voice_stream
  REG16 调 0x06=36dB）
- **UDP 丢包高（丢 PING 上涨）**：2.4G 拥挤；可把 CHUNK_BYTES 加到 1400 降包率

## 二期（未做）

识别文字 UDP 回推盒子 192.168.31.103 的 InputPad（com.taoge.inputpad 剪贴板桥）
→ RDP 会话 Ctrl+V 粘贴（Windows App 剪贴板重定向）。Mac 侧需一个抓上屏文字的
辅助器（辅助功能 API 或手动选中复制），InputPad v2 加 UDP 监听。
