# Windows 端配置与开发指南（乐乐语音桥）

> 适用场景：**电脑放公司（或家里另一台 Windows 机器），想用工牌做语音输入**。
> 工牌端零改动——它待机省电、按键才推流(§六十四)；Windows 这边只需「收流 → 虚拟声卡 → 微信输入法」，
> 并可选启用「工牌按键 → 合成微信输入法语音快捷键」控制通道。
> 本文档同时是 **空对话/新会话的开工入口**：新 Agent 会话直接从「五、开发入口」开始。

## 〇、30 秒总览

```
[工牌 ESP32-C3] 待机(静音, 握手照发) —按键→ 广播控制帧(DICT*/PTTD*) + 16k/16bit/mono PCM
  → UDP → 腾讯中转 124.221.187.167:9761 (已部署, systemd 自启, 控制帧透明转发)
  → 中转转发给全部订阅者
[Windows 本脚本 tools/start_receiver.bat]  ← 你要跑的东西
  → 控制帧 → 合成微信输入法语音快捷键(SendInput, 需先改绑快捷键, 见 §一.5)
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

注意：**工牌上电后处于待机(静音)不推流**，按一下工牌上键(语音开关)才开始推流
（屏幕显示「🎙 语音输入中」即在工作）。

### 4. 装/配微信输入法
1. https://z.weixin.qq.com 下载安装，扫码登录
2. 设置 → 语音输入 → **麦克风设备选 `CABLE Input (VB-Audio Virtual Cable)`**
3. Windows 设置 → 隐私和安全性 → 麦克风 → **允许桌面应用访问麦克风**（微信输入法要能"听"虚拟声卡）

### 5. 启用工牌按键控制语音（可选，§六十四）

Mac 上合成 Fn 可行；**Windows 没有可合成的 Fn 虚拟键**，所以要先在微信输入法
设置里把两个语音快捷键**改绑成普通组合键**（建议：按住说话=``Ctrl+` ``，
长输入=F9，任选不冲突的），然后给接收器传同样的键（VK 码，逗号分隔）：

```
python voice_receiver.py --relay 124.221.187.167 --device "CABLE Input" ^
    --voice-ptt-key 0x09 --voice-mods ctrl --voice-toggle-key 0x78
```

（`0x09`=Tab 作按住说话键+Ctrl 修饰、`0x78`=F9 长输入；按键名支持
ctrl/alt/shift/space/f1-f12 或数字 VK。自启注册表项同样追加这几个参数。
改绑前先在微信输入法设置确认其默认快捷键是什么，以实际为准。）

**注意**：Windows 侧注入(SendInput)尚未实测——启用时先在记事本里按一次
工牌上键，看长输入面板是否弹出；不弹检查微信输入法实际改绑的键与参数是否一致。

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
- 腾讯中转 124.221.187.167，UDP 9761(音频+控制帧)/9762(探测)，token=lele-6deb6d37
- 工牌(ESP32-C3, MicroPython)待机省电、按键推流：上=语音开关(DICT1/DICT0) 下=按住说话(PTTD1/PTTD0)，固件在 firmware/
- 接收器 tools/voice_receiver.py 双模式(--relay 订阅/LAN 直连)，识别控制帧后合成微信输入法语音快捷键
  （Mac 默认 Fn/Fn+空格 已实测一致；Windows 需微信输入法改绑普通组合键后 --voice-ptt-key/--voice-toggle-key/--voice-mods 传入）
- Windows 用 tools/start_receiver.bat 启动；开机自启=HKCU Run 键（追加 --voice-* 参数即启用控制通道）
- Mac 端全链已验证可用(§六十四)；中转服务 systemd 单元名 lele-relay（ssh tencent 管理）
本次任务：<在这里写本次要做什么>
```

## 六、附：Mac 侧对照（如需在 Mac 上调试）

```bash
tools/voice_receiver.sh start        # 默认已订阅同一中转
tools/verify_blackhole.sh            # 验证虚拟声卡电平
scripts/deploy_wireless_ota_mac.sh   # 工牌 OTA（WebREPL，默认 192.168.31.133）
```

## 七、Windows 实装记录（2026-10-07，tyz86 台式机，Windows 11 x64）

本节是首台 Windows 实机的踩坑实录，第二台机器可直接照抄。

**已验证可行：**

- Python 3.12 + `pip install sounddevice`（清华镜像秒装）
- 微信输入法安装器支持 `/S` 静默安装（`WeTypeSetup_3.0.0.17_3.exe /S`），装完服务与进程自启，无需向导点击
- 麦克风隐私：`HKCU\...\CapabilityAccessManager\ConsentStore\microphone`（及 `NonPackaged` 子键）`Value=Allow` 即可放行桌面应用
- 接收器开机自启：`HKCU\...\Run` 加 `cmd /c start /min "" python voice_receiver.py --relay 124.221.187.167 --device "CABLE Input"`
- 本机到中转链路：232kbps 稳定收流，RTT 15~60ms，到包抖动 ±7~10ms，可满足语音识别

**踩坑：**

1. **VB-Cable 装完端点立即可用，但会"迟发失效"**：安装后 `CABLE Input/Output` 端点马上出现、能开流、环路测试通过（-12dBFS）；但运行约 10 分钟后 Windows 重枚举音频端点，运行中的流被拔（`MME error 6: There is no driver installed`），之后端点从 WASAPI/MME 消失，必须**重启电脑**才恢复。这正是官方 readme 建议重启的原因——装完驱动别拖，直接重启。
2. 端点失效期间接收器会崩溃退出 → 已加固（voice_receiver.py：按设备名每次重扫、限频重开、设备不存在进入等待模式；**绝不回落默认扬声器**，防止公司场景语音外放）。重启后由开机自启拉起，自动连上端点。
3. 微信输入法语音输入的麦克风设备在设置 UI 里选择（MMKV 二进制配置无法安全预写），选 **CABLE Output (VB-Audio Virtual Cable)**（录制端，即虚拟声卡的"另一端"）。

**第二台机器最小步骤**：装 Python+sounddevice → 装 VB-Cable（管理员）→ **重启** → 装 WeType 并扫码登录 → 微信输入法语音麦克风选 CABLE Output → 跑接收器 → 对工牌说话出字。

