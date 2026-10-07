# Windows 端配置与开发指南（乐乐语音桥）

> 适用场景：**电脑放公司（或家里另一台 Windows 机器），想用工牌做语音输入**。
> 工牌端零改动——它常开推流到腾讯中转；Windows 这边只需「收流 → 虚拟声卡 → 微信输入法」。
> 本文档同时是 **空对话/新会话的开工入口**：新 Agent 会话直接从「五、开发入口」开始。

## 〇、30 秒总览

```
[工牌 ESP32-C3] 麦克风常开, 16k/16bit/mono PCM
  → UDP 1024B/32ms → 腾讯中转 124.221.187.167:9761 (已部署, systemd 自启)
  → 中转转发给全部订阅者
[Windows 本脚本 tools/start_receiver.bat]  ← 你要跑的东西
  → VB-Cable 虚拟声卡
  → 微信输入法(语音输入麦克风选 CABLE Input) → 腾讯云识别 → 出字
```

关键参数（全部已固化在代码里）：

| 项 | 值 |
|---|---|
| 中转 | `124.221.187.167`，UDP **9761**(音频) / **9762**(探测) |
| 鉴权 token | `lele-6deb6d37`（接收器默认已带，无需输） |
| 音频格式 | 16kHz / 16bit / 单声道 s16le |
| 代码仓库 | github.com/fancylk/lele-ai-passport（或本 cm311 仓库 `lele-voice/`） |

## 一、Windows 配置（一次性，约 15 分钟）

### 1. 装 Python 3.9+
https://www.python.org/downloads/windows/ 下载安装，**务必勾选 "Add to PATH"**。
验证：开 cmd 跑 `python --version`。

### 2. 装 VB-Cable 虚拟声卡
1. https://vb-audio.com/Cable/ 下载 `VBCABLE_Driver_Pack43.zip`
2. 解压，**右键管理员运行** `VBCABLE_Setup_x64.exe` → Install
3. **重启电脑**（驱动必须重启生效）
4. 验证：`Win+R` → `mmsys.cpl` → 播放和录制设备里都出现 **CABLE Input / CABLE Output**

### 3. 跑接收器
把仓库（或 `lele-voice/`）拷到 Windows 机器，**双击 `tools\start_receiver.bat`**。
首次运行会自动 `pip install sounddevice`。看到这样的统计行就是通了：

```
[  30s] 收 875 包 875KB (232kbps) 中转RTT≈56ms 到包抖动±10.1ms 缓冲0KB
```

注意：**工牌上电后才会开始推流**（屏幕显示「● 推流中 → Mac」字样即在工作）。

### 4. 装/配微信输入法
1. https://z.weixin.qq.com 下载安装，扫码登录
2. 设置 → 语音输入 → **麦克风设备选 `CABLE Input (VB-Audio Virtual Cable)`**
3. Windows 设置 → 隐私和安全性 → 麦克风 → **允许桌面应用访问麦克风**（微信输入法要能"听"虚拟声卡）

### 5. 验证端到端
随便开个输入框 → 点微信输入法的麦克风按钮 → **对工牌说话** → 出中文字。
（此刻 Mac 端已用同一条链路验证过全流程，Windows 侧只是换了收流机器。）

## 二、排障

| 症状 | 原因/处置 |
|---|---|
| 统计行一直 0 包 [静默！] | 工牌没上电/不在同一中转；查中转日志 `ssh tencent "sudo journalctl -u lele-relay -n 20"`（应能看到 source registered 和你的 SUB） |
| 收到包但微信输入法没反应 | ①mmsys.cpl 看 CABLE Input 电平格有没有跳动（有跳动=音频到了，是微信输入法设置问题）②隐私设置没放开 ③微信输入法麦克风没选 CABLE Input |
| sounddevice 报 PortAudio 错 | VB-Cable 没装好/没重启；重装驱动再重启 |
| pip 装 sounddevice 失败 | 公司网络代理问题：`python -m pip install sounddevice -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 声音断续 | 公司网络对 UDP 限速/丢包：看统计行「到包抖动」，>50ms 说明链路差；中转与工牌端都无法优化，只能换网络 |

## 三、架构与代码事实（开发前必读）

- **协议**（`relay/relay.py`，纯标准库）：
  - 音源注册：向 `中转:9761` 发 `b"LELE1"+token`，之后该源地址的裸包转发给所有订阅者（单音源，新顶旧，60s 静默剔除）
  - 订阅：发 `b"SUB"+token`，每 20s 重发保活（90s 超时）；音频以**源地址回推**，无需固定端口
  - 探测：`PING+8B` → `9762` → `PONG+8B` 原样回（带时间戳回显，用于算 RTT）
  - 未注册来源一律静默丢弃
- **Mac 接收器** `tools/voice_receiver.py`：argparse 双模式（`--relay` 订阅 / 默认 LAN 直连），sounddevice 播放到虚拟声卡。Windows 完全兼容（bat 里指定 `--device "CABLE Input"` 而已），改功能就在这一个文件上
- **工牌固件** `firmware/`（MicroPython）：`voice_stream.py`=ES8311 采集+UDP 推流+PING；`main.py`=应用与屏幕 UI。Windows 开发一般不碰，改了也用 `scripts/deploy_wireless_ota_mac.sh`（Mac 上跑）无线推送
- **中转服务器**：`ssh tencent`（124.221.187.167），服务=`systemctl status lele-relay`，代码=`/opt/lele-relay/relay.py`，本仓库 `relay/relay.py` 同步版本。防火墙已放行 UDP 9761/9762

## 四、二期开发任务（当前未做，Windows 侧可独立推进）

**识别文字回推**：微信输入法出的字现在只落在当前电脑——目标是回推到盒子（192.168.31.103 的 InputPad `com.taoge.inputpad`，剪贴板桥）→ RDP 会话 Ctrl+V。

设计要点（已定稿待实现）：
1. Windows 侧需要一个「文字抓取器」：微信输入法落字后，把文本从当前应用取到（Windows 上可用剪贴板监听：微信输入法语音输入完成后模拟 Ctrl+C 或用 UI Automation）
2. 抓到文本 → UDP 发给中转 9761（`SUB` 同源注册机制可复用，或定义 `TEXT1`+token 新包类型，改 `relay/relay.py` 十行）
3. 盒子端 InputPad v2 加 UDP 监听收文本 → 落输入框/剪贴板 → RDP Ctrl+V 粘贴
4. 中转目前是"工牌→订阅者"单向；回推是"订阅者→工牌/盒子"反向，建议直接在 relay.py 加一条独立端口（如 9763）做文本分发，互不干扰

## 五、空对话/新会话开场白（复制给新 Agent 即可直接开工）

```
我在开发"乐乐语音桥"（工牌语音输入系统）的 Windows 端。
先读这两份文档再动手：
1. <仓库路径>/docs/windows-guide.md  （Windows 配置+开发指南，本文件的同步版）
2. <仓库路径>/docs/voice-bridge.md    （全案架构与固件细节）
已就绪事实（勿重新考证）：
- 腾讯中转 124.221.187.167，UDP 9761(音频)/9762(探测)，token=lele-6deb6d37
- 工牌(ESP32-C3, MicroPython)常开推流 16k/16bit/mono，固件在 firmware/
- 接收器 tools/voice_receiver.py 双模式(--relay 订阅/LAN 直连)，Windows 用 tools/start_receiver.bat 启动
- Mac 端全链已验证可用；中转服务 systemd 单元名 lele-relay（ssh tencent 管理）
本次任务：<在这里写本次要做什么>
```

## 六、附：Mac 侧对照（如需在 Mac 上调试）

```bash
tools/voice_receiver.sh start        # 默认已订阅同一中转
tools/verify_blackhole.sh            # 验证虚拟声卡电平
scripts/deploy_wireless_ota_mac.sh   # 工牌 OTA（WebREPL，默认 192.168.31.133）
```
