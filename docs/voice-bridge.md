# 乐乐语音桥 —— 工牌按键控制 → 腾讯云中转 → 微信输入法语音输入

> 2026-10-06 定稿并实装。工牌彻底清零重设计：不再做导游演示，专职当
> **语音输入音源**（待机麦克风，按键控制），屏幕实时显示到中转的延迟，便于评估链路。
> 2026-10-11 §六十四升级：**工牌按键直接控制微信输入法语音输入**，不再需要碰键盘快捷键。

## 架构（v2: 腾讯云星型中转 + v3: 按键控制通道）

真实场景：电脑放公司、人在家远程用——工牌与主机**不在同一局域网**，
音频经腾讯云中转（工牌在家 Wi-Fi、Mac 在公司网络，都只出站连中转）：

```
[工牌 ESP32-C3+ES8311] 待机(静音省电, 握手照发) → 按键广播控制帧(DICT*/PTTD*) → 中转:9761
  语音开/PTT按下 → 解除静音, 16k/16bit/mono 1024B/32ms UDP 推流
[中转 relay.py @124.221.187.167] (systemd lele-relay, 纯标准库)
  → 已注册音源的未知前缀包原样转发(零改动透明支持控制帧), 全部订阅者(90s 超时剔除)
[Mac tools/voice_receiver.py --relay 124.221.187.167]
  → 控制帧 → 后台线程合成微信输入法语音快捷键(Fn/Fn+空格, ctypes CoreGraphics)
  → 音频 → BlackHole 2ch → 微信输入法(腾讯云 ASR) → 出字
未来订阅者: 盒子 InputPad(二期回推) 同协议接入即可.
```

延迟探测：工牌每秒 PING 中转:9762 → PONG → 工牌上屏 RTT（工牌→中转这一跳）；
Mac 侧 `--relay` 模式每 5s 也 PING，统计行显示本机→中转 RTT + 到包抖动。
鉴权：音源握手与订阅都带 token（config.py STREAM_TOKEN = relay.py TOKEN）；
音频包本身不带 header（中转按源地址识别，纯转发零开销）。

**控制帧要点**：握手(LELE1)纯计时每 10s 发送、**静音期间照发**——中转音源注册
60s 过期，停发超时后控制帧会被当杂散包丢弃（这是设计要害，别回退）。
每个控制事件连发 3 遍(间隔 30ms)抗 UDP 丢包，接收端 300ms 去重。

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
| `main.py` | 语音桥应用：上=语音开关 下=按住说话 OK=翻页/长按测延 |
| `voice_stream.py` | ES8311 init + MCLK PWM + I2S RX + UDP 推流 + 控制帧 + PING/PONG |
| `config.py` | `STREAM_IP`(中转)/9761/9762/16k/CHUNK |
| 其余 | wifi_manager / st7789_direct / chinese_font / battery 沿用 |

旧导游版（三步状态机）已整体移除，回滚看 git 历史。

## 语音输入控制通道（§六十四, 2026-10-11）

工牌按键 → 控制帧 → 接收器合成微信输入法语音快捷键，全程不碰键盘：

| 工牌按键 | 动作 | 控制帧 | 接收器合成 |
|---|---|---|---|
| 上键按一下 | 开语音(长输入会话) | `DICT1+token` | Fn+空格 轻击 |
| 上键再按一下 | 结束语音上屏 | `DICT0+token` | Fn+空格 轻击(再翻一次) |
| 下键按住 | 按住说话(PTT) | `PTTD1+token` | Fn 按下 |
| 下键松开 | 识别结束上屏 | `PTTD0+token` | Fn 抬起 |
| OK 点按 | 翻页 | — | — |
| OK 长按>600ms | 立即测延迟 | — | — |

- 静音联动：语音开=解除静音推流；语音关/PTT 松开=广播后 **1.5s 收尾宽限再静音**
  （留识别端收尾）。开机即待机（静音省电），握手照发。
- toggle 语义限制：微信输入法无会话状态查询接口，DICT1/DICT0 都合成一次
  Fn+空格（=每按一次翻转一次）。若长输入面板已被它自己结束（超时/点了完成），
  工牌再按一次"关"会把它打开——多按一次即自愈，面板状态屏上可见。
  PTT 无状态，最可靠。
- 微信输入法 Mac 版快捷键实测（其设置 MMKV `wetype.settings`）：
  `voicePTTShortcut_keyCodes=[63]`、`voiceToggleShortcut_keyCodes=[63,49]`
  （63=Fn/Globe，49=空格），接收器默认值与此一致；在微信输入法设置里改绑后
  用 `--voice-ptt-key/--voice-toggle-key/--voice-mods` 传新键。
- **Mac 注入需辅助功能权限**：系统设置→隐私与安全性→辅助功能→勾选启动
  voice_receiver 的终端（nohup 从哪个终端启动就归谁）。授权缺失时合成事件被
  系统静默丢弃（`AXIsProcessTrusted()` 可能为 True 但照样丢——以面板为准）。
- 自检：`python3 tools/spike_weetype_hotkey.py toggle|ptt`（在同一个终端环境跑）。
- Windows：无 Fn 虚拟键，微信输入法 Windows 版两快捷键改绑普通组合键后
  `--voice-ptt-key space --voice-mods ctrl` 这样传入；注入走 ctypes SendInput。
- 中转零改动：已注册音源的未知前缀包原样转发（relay.py 音频分支），
  已对真实中转实测控制帧到端。

## Mac 端（tools/）

```bash
tools/voice_receiver.sh start        # 默认订阅腾讯中转 (VOICE_RELAY=IP 可换, 置空切 LAN 直连)
tools/verify_blackhole.sh            # 录 BlackHole 6s 报电平（验证音频真到了）
tools/spike_weetype_hotkey.py        # 自检合成快捷键（辅助功能授权 + 微信输入法响应）
scripts/deploy_wireless_ota_mac.sh   # WebREPL OTA 固件到工牌（默认 192.168.31.133, 工牌回家局域网时推）
```

## 中转服务器（relay/，部署在 ssh tencent）

```bash
scp relay/relay.py tencent:/tmp/ && ssh tencent \
  "sudo mv /tmp/relay.py /opt/lele-relay/ && sudo systemctl restart lele-relay"
# 腾讯控制台防火墙须放行: UDP 9761 + UDP 9762 (来源 0.0.0.0/0)
```

## 微信输入法 Mac 版设置

官网 z.weixin.qq.com 下载 → 登录 → 设置 → 语音输入 → 麦克风设备选
**BlackHole 2ch**。语音触发快捷键默认 Fn(按住说话)/Fn+空格(长输入)，
现在由工牌按键经接收器合成，无需碰键盘。

## 端到端验证步骤

1. Mac: 授辅助功能权限后 `tools/voice_receiver.sh start`（日志应出现"语音触发就绪"）
2. 工牌上电 → 屏显"⏸ 待机"
3. 按一下上键 → 屏显"🎙 语音输入中"，Mac 日志出现"长输入会话开"，
   微信输入法长输入面板弹出 → 对工牌说话 → 文字实时上屏
4. 再按一下上键 → 会话结束文字上屏，1.5s 后工牌回"⏸ 待机"
5. 按住下键说话 → 松开 → 文字上屏（PTT）
6. 按上键后 `tools/verify_blackhole.sh` → max_volume > -25dB = 音频到位

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

## 实装记录(2026-10-11, §六十四 语音控制通道)

1. **微信输入法快捷键反推**: 其设置存于 `~/Library/Application Support/WeType/
   mmkv/wetype.settings`(MMKV, key 明文), 实测 `voicePTTShortcut_keyCodes=[63]`/
   `voiceToggleShortcut_keyCodes=[63,49]`/`*_modifiers=0` —— PTT=Fn 按住,
   长输入=Fn+空格, 都是通用 keyCodes 存储 = 设置界面可改绑(= 注入失效时的兜底)。
2. **合成事件上下文要害**: CGEventPost 是否生效取决于**宿主进程的辅助功能授权**。
   实测 ZCode 后台守护(zcode-cli)的子进程里 AXIsProcessTrusted() 返回 True 但
   合成事件仍被静默丢弃(合成 ESC 连崩溃对话框都关不掉); osascript→System Events
   同样无效。结论: 接收器必须从**用户 Terminal** 启动(nohup 继承 Terminal 归属),
   给 Terminal 勾辅助功能, 用 spike 工具在 Terminal 里自检。
3. **注入从沙箱/无授权进程丢事件不报错** —— 排障时别看报错, 看面板有没有弹。
4. 控制帧经真实中转透明转发实测到端(模拟音源注册后发 DICT*/PTTD*, 订阅端
   全部收到并触发); 中转源注册"新顶旧"语义: 测试注册会短暂顶掉工牌,
   工牌 10s 握手自动抢回, 自愈无残留。
5. 接收器冒烟: DICT1 连发 3 遍正确去重为 1 次触发; LELE1 握手帧不再喂声卡
   (LAN 直连模式的历史小 bug 顺带修复); 假音频正常直通。

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
- **按工牌键微信输入法没反应**：① 接收器日志有没有 `[🎙]` 行——没有 = 控制帧没到
  （工牌还是旧固件未 OTA / 中转注册过期看"握手静音照发"是否还在）；有 `[🎙]` 行
  但面板不弹 = 合成事件被丢弃（辅助功能没授给启动接收器的终端）或快捷键被改绑
  （微信输入法设置里看实际绑定，用 --voice-* 对齐）；② 快捷键改绑兜底见上节
- **UDP 丢包高（丢 PING 上涨）**：2.4G 拥挤；可把 CHUNK_BYTES 加到 1400 降包率

## 二期（未做）

识别文字 UDP 回推盒子 192.168.31.103 的 InputPad（com.taoge.inputpad 剪贴板桥）
→ RDP 会话 Ctrl+V 粘贴（Windows App 剪贴板重定向）。Mac 侧需一个抓上屏文字的
辅助器（辅助功能 API 或手动选中复制），InputPad v2 加 UDP 监听。

## 多应用 + OTA + 打洞 ACK(§六十六, 2026-10-11 晚, NAS USB 真机调试)

应"恢复多应用 + OTA 升级"要求重开发;远程麦克风降级为其中一个应用。

### 多应用框架

```
boot.py(WebREPL + OTA 回滚守卫) → main.py 启动器:
  开机画面 3s: 任意键 → 菜单; 否则启动 /app.txt 里的应用(默认 voice_bridge)
应用注册表 apps/registry.py; 菜单 apps/menu.py(UP/DOWN 选 OK 确认);
应用内约定: 长按 OK 1s → 写 /menu.flag 重启回菜单。
apps/: voice_bridge(远程麦克风, §六十四全功能) / guide(乐乐导游, MiMo TTS 桥不在=文字降级)
       / answer(答案之书 200 签文, 自 ESP-IDF demo_answer.c 移植) / catch(接球, MicroPython 重写)
应用崩溃由启动器兜底(显示错误 3s 回菜单), 永不变砖。
```

### OTA 升级(设备自动)

- 服务端: 腾讯 nginx 8090 `/var/www/fw/lele-ota/`(fwserver 站点, 免防火墙改动),
  `scripts/ota_publish.sh` 发布 manifest(crc32)+21 个固件文件, 版本号自动 +1。
- 设备: 菜单"OTA 检查更新" → WiFi → `ota.py` 原生 socket HTTP 拉 manifest →
  逐文件 crc32 比对 → 下载到 /otastage(流式写盘, 282KB 字库不进堆) → 校验 →
  落 /ota.pending → /backup 备份 → 原地替换 → /installed.json → 重启。
- **中断安全**: 升级中途断电 → boot.py 守卫从 /backup 还原 → 永远可启动。
- 真机实测(v5): WiFi → 检查 → 21/21 下载校验 → 应用 → 重启 → installed.json v5 ✓。

### 打洞协议升级: PNCH → PNCHA 双向确认

v6 前"收到终端 PNCH 即切直连"有死空气风险: Mac 侧若是对称/受限 NAT,
工牌的音频回不来, 而 Mac 的 PNCH 每秒照到 → 10s 回退永不触发。
v7 起: 工牌收到 PNCH 只记"半通", **必须再收到终端的 PNCHA 回执(= 我方音频
能到达终端的铁证)才切直连**; 否则永远安全留在中转。10s 无 PNCHA 回退不变。
实测: 工牌 PNCH 穿透两侧 NAT 到达 Mac 守护 → ACK 回执 → 直连建立 ✓。

### 部署通道(三选一)

1. **OTA 自升级**(日常): 设备菜单 → OTA 检查更新;
2. **WebREPL 无线**: `scripts/deploy_wireless_ota_mac.sh`(工牌与 Mac 同网);
3. **USB 串口**: `scripts/deploy_serial_nas.sh`(工牌插 NAS/任何 Linux 的 USB,
   首次自动建 venv 装 mpremote, 推 21 文件+建目录+重启)——本节即经飞牛 NAS 真机调试落地。

### 真机调试踩坑(NAS 串口, 复写前必读)

1. **MicroPython 目录会遮蔽同名模块**: 设备上有 `/ota` 目录时 `import ota`
   得到空命名空间包(无属性) → 暂存目录改名 `/otastage`。
2. `__import__("apps.x")` 返回**父包**, 子模块要从 `sys.modules` 取。
3. **ESP32-C3 USB-SERIAL-JTAG 复位后前 2s 的输出无法被迟到的读端捕获**,
   被动抓启动日志基本是空的——改用 REPL exec 断言(sys.modules / 中转 STATUS /
   文件内容)替代日志观察; mpremote exec 打断运行中的应用会软重启(sys.modules 清空)。
4. `machine.reset()` 经 mpremote exec **必然超时**(复位杀死 raw REPL, 等不到
   回包)——复位实际已生效, 调用方要容忍 TimeoutExpired。
5. `pkill -f mpremote` 会匹配到自身 ssh 命令行自杀; 杀残留进程用 lsof 定位 PID。
6. `apps/answer.py` 的 C_BAR 类疏漏用 `py_compile` 查不出(定义存在即可),
   要靠设备端真跑——四个应用各真机 exec 一遍是最低验收线。

## 目标主机选择(§六十八, 2026-10-23, 防多主机激活错乱)

**问题**: Mac 与 Windows 接收器同时订阅中转, 工牌一说话两台机器的微信输入法
一起激活。**方案**: "当前目标主机"状态放在中转(工牌不在线也能切), 三层防错乱:

```
1. relay current_target (权威状态, 内存):
   TSET+token+@tag 设定 / TSET0+token 恢复广播 / TGTQ+token 查询(回 TGT @tag|-)
   控制帧(DICT*/PTTD*)只转发给目标 tag 的订阅端; 音频/PING/TGTM1 仍广播(无害)
   重启丢失→回广播(安全默认); STATUS 尾部 target= 可查
2. 控制帧内 @tag (固件 v9+): DICT1<token>@mac —— relay 路由为[],
   接收端兜底过滤不匹配自己 tag 的帧 (Mac daemon + voice_receiver.py 都有)
3. TGTM1+token+@tag: 工牌切换目标时广播, 所有端仅显示
```

**切换入口**:
- **菜单栏小程序**(Mac): "语音目标: Mac/Windows" radio 组, 点选即 TSET, ~12s 轮询
  TGTQ 刷新显示; UDP 直发 relay:9761(token 鉴权)
- **工牌上键长按 1s**(固件 v9+, OTA 后生效): Mac→Windows→Mac 轮换, /target.txt
  持久化, 屏显"目标: Mac/Windows", TGTM1 广播

**部署状态**: relay ✓ 已上线(双订阅端路由仿真全绿: 目标 pc 时 mac 零收到,
音频广播不变); Mac daemon+菜单栏 ✓; voice_receiver.py ✓(Windows 端下次同步生效);
工牌固件已发 OTA v9(工牌在线后菜单→OTA 检查更新, 或回家串口刷)。

**注意**: tag 约定 mac=Mac / pc=Windows(voice_receiver --tag, daemon config
relay.tag); 目标设为 pc 时 Mac 完全静默(收不到任何语音帧), 反之亦然——
这就是"防激活错乱"本身; 音频仍会广播到两端(识别不依赖激活, 无害)。
