# lele-voice/ —— 乐乐语音桥（工牌语音输入系统）

> 本文件夹是 [github.com/fancylk/lele-ai-passport](https://github.com/fancylk/lele-ai-passport)
> 的代码快照（2026-10-12 状态，cm311 仓库内快照），收录进 cm311 仓库便于
> 跨机器/跨会话直接开工。**开发请在 lele 主仓库进行，改完再同步回来**
> （或把本文件夹当唯一现场，见下方"双现场说明"）。

## 它是什么

工牌（FoloToy/TRAE AI Passport，ESP32-C3+ES8311+MicroPython）被清零重设计为
**常开麦克风语音输入音源**：对它说话 → 腾讯云中转 → 任意一台电脑的虚拟声卡
→ 微信输入法语音输入 → 出中文字。工牌屏幕实时显示到中转的 RTT/码率/丢包。

**当前状态：Mac 端端到端已验证可用（用户直接用工牌 dictate 与 AI 对话）；Mac 端已由 Rust
常驻守护（`macos-daemon/`，launchd 自启）+ 菜单栏小程序（`macos-menubar/`）接管，详见下方"功能进度"。**
Windows 端配置见 [docs/windows-guide.md](docs/windows-guide.md)。

## 目录

| 目录 | 内容 |
|---|---|
| `firmware/` | 工牌 MicroPython 固件（main.py 启动器+多应用+屏显 RTT，voice_stream.py=ES8311+I2S+UDP+DICT/PTTD 控制帧，ota.py=HTTP OTA，font16.bin 含 Unifont ASCII 的 v4 字库） |
| `tools/` | 电脑端接收器（voice_receiver.py 双模式+语音控制帧触发/`start_receiver.bat` Windows 一键启动/verify_blackhole.sh 电平验证/serial_grab.py REPL 抢救/spike_weetype_hotkey.py 快捷键自检） |
| `relay/` | 腾讯云 UDP 中转（部署在 `ssh tencent:/opt/lele-relay/`，systemd 单元 `lele-relay`；SRCQ/PNCH/PONG 汇聚动词支持打洞） |
| `scripts/` | OTA 与部署（ota_publish.sh 发布 OTA manifest、deploy_wireless_ota_mac.sh 无线推固件、deploy_serial_nas.sh NAS USB 串口部署） |
| `voice-daemon/` | Mac 常驻守护（Rust，launchd 自启）：中转/LAN 收流→重采样→BlackHole、DICT/PTT 控制帧→切输入法+合成快捷键、UDP 打洞直传、doctor/install 子命令（§六十五） |
| `menubar/` | Mac 菜单栏小程序（Swift AppKit 单文件，零三方依赖）：状态图标 🎙/🔗/☁️/⚠️、状态总览、实时日志、配置指引与自愈、通知开关、重启守护（§六十七、§六十八） |
| `docs/` | **voice-bridge.md=全案架构与实装记录；windows-guide.md=Windows 配置与开发指南（含空对话开场白）** |

## 📦 跨平台发布包 (v1.0.0)

GitHub Release: **[lele-voice-v1.0.0](https://github.com/fancylk/cm311/releases/tag/lele-voice-v1.0.0)**

| 平台 / 固件 | 安装包文件 | 安装使用方式 |
|---|---|---|
| **macOS (Apple Silicon / Intel)** | [lele-voice-mac.dmg](https://github.com/fancylk/cm311/releases/download/lele-voice-v1.0.0/lele-voice-mac.dmg) | 挂载镜像，双击【一键安装.command】，自动安装 Daemon 与 Menubar 并引导权限 |
| **Windows 10 / 11 (x64)** | [lele-voice-windows.zip](https://github.com/fancylk/cm311/releases/download/lele-voice-v1.0.0/lele-voice-windows.zip) | 解压后右键管理员运行 `install.bat`，自动配置依赖与开机静默后台运行 |
| **工牌麦克风固件 (ESP32-C3)** | [lele-voice-mic-firmware.zip](https://github.com/fancylk/cm311/releases/download/lele-voice-v1.0.0/lele-voice-mic-firmware.zip) | 解压后运行 `flash_usb.bat` (Win) 或 `flash_usb.sh` (Mac) 一键 USB 烧入工牌 |

## 功能进度（依据 docs/交接文档.md §六十～§六十九）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| §六十～六十二 | 方案定稿+实装+收官：工牌常开麦克风 → 腾讯云 UDP 中转 → 虚拟声卡 → 微信输入法出字；代码入库 cm311，Windows 交接 | 已完成（Mac 端到端验证） |
| §六十四 | 工牌按键 → 微信输入法语音控制：固件 DICT/PTTD 控制帧（连发 3 遍抗丢包），接收器零依赖注入（Mac=CGEvent） | 已完成（Windows 注入未实测） |
| §六十五 | Mac 端散落脚本重写为单一 Rust 常驻守护 `voice-daemon/`（launchd 自启，实测全通） | 已完成 |
| §六十五补记 | UDP 打洞端到端直传（SRCQ/PNCH/PONG 捎带 PEER，向后兼容，对称 NAT 自动留中转无损） | 已完成（跨 NAT 延迟量测待 OTA 后） |
| §六十六 | 工牌多应用启动器（voice_bridge/guide/answer/catch，崩溃兜底不变砖）+ HTTP OTA（crc32+/otastage 暂存+/backup 回滚守卫，真机全流程）+ 打洞 PNCHA 双向确认 | 已完成（真机验证） |
| §六十七 | 菜单栏小程序 `menubar/`（原生 AppKit）+ 守护系统通知（osascript 限频，[ui] notify 30s 热重载） | 已完成 |
| §六十八 | 固件关键 Bug 修复（OTA v8：ota.pending 回滚守卫/长按 OK 回菜单/接球 C_RED）+ 菜单栏配置引导与自愈 + 授权弹窗治理 | 已完成 |
| §六十九 | 重构推流保活状态机（按住保持、消化 1.5s 尾音、250ms/600ms 自动上屏、待机防误唤醒、单元测试通过）+ 交付跨平台安装包 | 已完成（v1.0.0 发布） |
| §七十 | Windows 快捷键注入实测收官（2026-10-21）：微信输入法默认 按住说话=Ctrl+Win/长输入=Ctrl+Shift+Win 无需改绑；SendInput 扩展键标志+0.2s 和弦；状态机对齐 Mac（长输入点按翻转+3s 链路超时自愈）；pythonw 无黑窗口自启+receiver.log；**默认麦克风动态热切换**（IPolicyConfig COM，对齐 Mac b3c4a34，根治"调起但不出字"）；SUB_OK 信令帧误触发修复；**播放器重写**（callback 常开流+300ms 预缓冲+水位伺服，移植 audio.rs，抖动压测零裂缝） | 已完成（端到端验证：TTS 语音经伪造工牌会话识别上屏） |

**未完成 / 已知问题：**
1. 二期"识别文字回推盒子 InputPad → RDP Ctrl+V"未做（§六十/§六十二）。
2. 接收器被强杀时默认麦克风可能停留在 CABLE Output（无还原钩子），重开接收器或手动改回（见 windows-guide.md §十）。

## 运行参数速查

- 中转：`124.221.187.167`，UDP 9761（音频）/ 9762（探测），token `lele-6deb6d37`
- 工牌：192.168.31.133（家庭网），WebREPL 密码 `folotoy`
- 音频：16kHz/16bit/mono，1024B/包=32ms
- Windows 启动：双击 `tools\start_receiver.bat`；Mac：`tools/voice_receiver.sh start`

## 二期（待开发）

识别文字回推：电脑侧抓微信输入法上屏文字 → UDP 回中转 → 盒子 InputPad（192.168.31.103，剪贴板桥）→ RDP Ctrl+V。设计要点见 windows-guide.md 第四节。
