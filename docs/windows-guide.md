# Windows 端配置与开发指南（乐乐语音桥）

> **2026-10-24 §六十九 起,Windows 端首选方案 = Rust 托盘程序**（与 Mac 版同源同体验）:
> 从 GitHub Actions「build-voice-daemon」工作流下载 `lele-voice-daemon-windows-x64` Artifact 里的 exe,
> 双击即完成安装(自启+托盘),详见 `lele-voice/windows-dist/安装说明.txt`。
> 微信输入法需把语音快捷键改绑为 F9。下面的 Python 方案保留为备用/调试路径。

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
2. 设置 → 语音输入 → **麦克风保持"默认设备"**（实测 WeType 语音跟随系统默认麦克风；
   接收器推流时会自动把默认麦热切到 `CABLE Output`、结束还原，见 §十。
   也可手动固定选 `CABLE Output (VB-Audio Virtual Cable)`，但推荐跟随默认）
3. Windows 设置 → 隐私和安全性 → 麦克风 → **允许桌面应用访问麦克风**（微信输入法要能"听"虚拟声卡）

### 5. 启用工牌按键控制语音（§六十四，2026-10-21 实测更新）

微信输入法 Windows 版（3.0.0.37）默认语音快捷键实测为：**按住说话=Ctrl+Win、
启动语音输入（长输入）=Ctrl+Shift+Win**——**无需改绑**，接收器直接用同样的键即可：

```
python voice_receiver.py --relay 124.221.187.167 --device "CABLE Input" ^
    --voice-ptt-key ctrl,win --voice-toggle-key ctrl,shift,win
```

组合键写法：逗号分隔、最后一个键为主键（如 `ctrl,win` = Ctrl+Win）；也支持
十进制/0x 十六进制 VK 码。若在其他机器上改绑过快捷键，把参数换成实际键即可。

注入三要点（缺一不触发，已固化在代码里）：①Win 等扩展键带 `KEYEVENTF_EXTENDEDKEY`；
②和弦保持 ~0.2s 再松开；③前台窗口需为正在输入的应用（用户打字时天然满足）。
语义：PTT=按住/松开；长输入=点按开启、结束再点按关闭（对齐 Mac daemon）。

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
- 接收器开机自启（无黑窗口，2026-10-21 修正）：`HKCU\...\Run` 直接指向 pythonw.exe（GUI 子系统，零控制台）：
  `"C:\...\pythonw.exe" "D:\...\voice_receiver.py" --relay 124.221.187.167 --device "CABLE Input"`。
  旧写法 `cmd /c start /min "" python ...` 会闪 cmd 窗并常驻最小化黑控制台，已废弃（详见 §八）
- 本机到中转链路：232kbps 稳定收流，RTT 15~60ms，到包抖动 ±7~10ms，可满足语音识别

**踩坑：**

1. **VB-Cable 装完端点立即可用，但会"迟发失效"**：安装后 `CABLE Input/Output` 端点马上出现、能开流、环路测试通过（-12dBFS）；但运行约 10 分钟后 Windows 重枚举音频端点，运行中的流被拔（`MME error 6: There is no driver installed`），之后端点从 WASAPI/MME 消失，必须**重启电脑**才恢复。这正是官方 readme 建议重启的原因——装完驱动别拖，直接重启。
2. 端点失效期间接收器会崩溃退出 → 已加固（voice_receiver.py：按设备名每次重扫、限频重开、设备不存在进入等待模式；**绝不回落默认扬声器**，防止公司场景语音外放）。重启后由开机自启拉起，自动连上端点。
3. 微信输入法语音输入的麦克风设备在设置 UI 里选择（MMKV 二进制配置无法安全预写），选 **CABLE Output (VB-Audio Virtual Cable)**（录制端，即虚拟声卡的"另一端"）。

**第二台机器最小步骤**：装 Python+sounddevice → 装 VB-Cable（管理员）→ **重启** → 装 WeType 并扫码登录 → 微信输入法语音麦克风选 CABLE Output → 跑接收器 → 对工牌说话出字。

## 八、无黑窗口自启修复（2026-10-21，tyz86 台式机）

**症状**：开机自启弹出黑色控制台窗口（先闪一个 cmd，再常驻一个最小化的 python 控制台在任务栏）。

**根因**：自启注册表项用的是旧写法 `cmd /c start /min "" python voice_receiver.py ...` ——
`python.exe` 是控制台程序，`start /min` 只是最小化、窗口仍在；前面的 `cmd /c` 还会闪窗。

**修复（三层）**：

1. **voice_receiver.py 无控制台安全**：`pythonw` 下 `sys.stdout/stderr` 为 `None`，
   任何 `print()` 都会直接 `AttributeError` 崩溃（这导致此前 pythonw 方案实际不可用）。
   现在检测到无控制台时自动重定向到脚本同目录 `receiver.log`（超 2MB 轮转为 `.old`），
   排障直接看该日志；前台 bat 调试行为不变。
2. **自启注册表改 pythonw 直启**（`LeleVoiceReceiver` 项）：
   `"C:\...\Python312\pythonw.exe" "D:\CMCC\lele-voice\tools\voice_receiver.py" --relay 124.221.187.167 --device "CABLE Input"`
   —— pythonw 是 GUI 子系统程序，不创建任何控制台，也不经 cmd/conhost。
3. **发行包同步**：`dist\lele-voice-windows\start_background.vbs` 去掉 `cmd.exe /c` 中转，
   改设 `ws.CurrentDirectory` 后 `pythonw.exe` 直启（原写法虽隐藏 cmd，但仍产生多余 conhost 进程）。

**验证**：`STATUS` 查询中转显示 `pc@本机公网IP` 订阅在线（与 mac 并存）；
`tools\receiver.log` 每 5s 输出统计行；进程为 `pythonw.exe` 无任何窗口。

**排障变化**：后台运行不再有窗口可看——状态看安装目录 `receiver.log`，
或双击 `start_receiver.bat` 前台调试（会显示控制台，属预期）。

## 九、语音快捷键注入实测与状态机对齐（2026-10-21，tyz86 台式机，WeType 3.0.0.37）

**快捷键配对**（设置窗口坐标 + 真键 + SendInput 三重实测）：
- 按住说话 = **Ctrl+Win**（按住面板出现、松手关闭）
- 启动语音输入（长输入）= **Ctrl+Shift+Win**（点按开启后面板**停留**，再按/Enter 关闭）

**SendInput 注入三要点**（全部固化进 `voice_receiver.py` WinInjector）：
1. Win/VK_LWIN 等扩展键必须带 `KEYEVENTF_EXTENDEDKEY`，否则事件被判畸形丢弃；
2. 和弦需保持 ~0.2s 再松开（tap gap 0.04s 不触发）；
3. 目标应用需在前台（用户打字时天然满足；后台进程 `SetForegroundWindow` 不可靠，测试时注意）。
   另：锁屏会话内注入会被系统丢弃（测试时机器自动锁屏曾造成假阴性）。

**状态机升级**（对齐 Mac daemon 语义）：
- PTT（PTTD1/首包音频）→ 按住 Ctrl+Win；PTTD0+尾音 → 松开上屏；
- 长输入（DICT1）→ 点按 Ctrl+Shift+Win 开面板持续转写；DICT0+尾音 → 再点按关闭上屏；
- 长输入会话独立超时：链路死亡 3s（无包）自动收面板、300s 硬上限，防 DICT0 丢包后面板悬挂；
- 组合键参数支持修饰键内联（`--voice-ptt-key ctrl,win`），兼容旧写法（`--voice-ptt-key 0x09 --voice-mods ctrl`），
  修复了 `0x09` 十六进制写法解析崩溃的 bug。

**端到端验证**（伪造工牌帧 PTD/DICT+PCM 直投本机 9761）：面板开/合全部符合预期。

## 十、默认麦克风动态热切换——"没识别到文字"的根因与根治（2026-10-21）

**症状**：工牌按键能调起语音面板，说完话不出字。

**排查链**（方法可复用）：
1. `receiver.log` 确认音频包到达（~28 包/秒，链路通）；
2. VB-Cable 环路测试（CABLE Input 播正弦音 + CABLE Output 录音，-13.9dBFS，通路好）；
3. **TTS 决定性实验**：用 SAPI 生成中文语音直接灌进 CABLE Input + 打开语音面板 →
   WeType 诊断日志（`%TEMP%\WeTypeVoiceDiagnostic_*.log`）显示 `finished_without_text`，零 emit
   → **微信输入法根本没在听 CABLE**；
4. 枚举系统默认录制设备 = 物理"麦克风阵列"而非 CABLE Output →
   **根因：WeType 语音麦克风跟随系统默认设备**。

**根治（对齐 Mac b3c4a34）**：`voice_receiver.py` 新增 `WinDefaultMicSwitcher`
（纯 ctypes COM：IMMDeviceEnumerator 枚举 + 未公开 IPolicyConfig::SetDefaultEndpoint，
vtable[13]，三个 role 全切）。推流开始自动把系统默认麦切到 `CABLE Output`，
结束/中断还原物理麦——日常通话录音不被虚拟声卡占死，与 Mac 完全同语义。
`--mic-device` 可改目标设备名，`--no-switch-mic` 禁用。原型工具 `tools/spike_win_micswitch.py`。

**最终端到端实测**（伪造 PTT 帧 + TTS 语音当"工牌音频"）：默认麦三态切换正确
（物理→CABLE→物理），微信输入法识别出"今天天气很好，我们…"并上屏到记事本。

**注意**：进程被强杀（taskkill / 任务管理器）不会触发还原钩子，默认麦会停留在
CABLE Output——重启接收器或到 mmsys.cpl 手动改回即可；正常停止（stop_receiver.bat
外其余路径）走 atexit 还原。

## 十一、播放器重写——"识别不稳"的根治（2026-10-21）

**症状**：面板正常调起、能出字，但识别断断续续，明显差于 Mac。

**根因（两层叠加）**：
1. **链路抖动**：本机（公司网）到中转实测到包抖动 ±200ms+、RTT 31~560ms 波动
   （Mac 家用网络仅 ±7~10ms、15~60ms）；
2. **播放器架构放大抖动**：旧 Player 在 UDP 收包主循环里同步写声卡（pump 10ms 一帧），
   写阻塞时收包停摆丢包；且**零缓冲**——网络抖动直接变成 CABLE 上的静音裂缝，
   微信输入法听到的就是断续音频。

**重写（移植 macos-daemon/audio.rs 全套设计）**：
- **callback 常开流**：由声卡时钟驱动，播放与收包彻底解耦，写声卡永不阻塞收包；
- **300ms 预缓冲**（`--prebuffer-ms` 可调，Mac 是 150ms，公司网络建议 300+）：
  音频先攒水位再出声，欠载后自动重新预缓冲；
- **无语音输出静音**：微信输入法永远认为麦克风可用；
- **水位微伺服**（每回调 ±1 帧消化工牌/声卡时钟漂移）+ **1s 积压清空**；
- **SO_RCVBUF 512KB**：吸收 UDP 突发；
- 统计行新增 `水位/欠载/间隙`：水位=缓冲毫秒数、欠载=预缓冲后仍取空次数、
  间隙=推流中 >100ms 无包次数——稳定性从此可量化。

**抖动压力实测**（`tools/spike_jitter_test.py`，TTS 语音 ×随机游走延迟 0~250ms+2% 丢包，
录 CABLE Output 数裂缝，与无抖动参照对比）：
- 参照：9 次裂缝（TTS 天然句间停顿）/9550ms 静音
- 注入抖动：**9 次裂缝**/9301ms 静音 —— **零新增裂缝**，抖动被完全吸收（间隙0）。

**后续根治方向**：UDP 打洞直连（移植 macos-daemon net.rs 的 SRCQ/PNCH/PNCHA），
绕开中转跳，从源头降抖动。

