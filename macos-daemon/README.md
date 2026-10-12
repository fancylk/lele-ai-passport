# lele-voice-daemon —— Mac 常驻守护(Rust)

> 2026-10-11 §六十五:用**一个 Rust 二进制**替代 Mac 端散落脚本
> (voice_receiver.py 收流 + spike 注入),开机自启,解决"微信输入法提示麦克风不可用"
> 与进程生命周期不稳的问题。Windows 仍走 `tools/voice_receiver.py`(协议同)。

## 它做什么

```
[工牌] 按键控制帧 DICT1/DICT0(上=语音开关) PTTD1/PTTD0(下=按住说话) + 16k PCM
  → UDP(腾讯中转订阅 或 LAN 直连, 配置切换)
[lele-voice-daemon]
  1. 收流 → 线性重采样 16k→48k → 写 BlackHole 2ch (流常开, 语音未开输出静音
     → 微信输入法的"麦克风"永远在运行态, 不再提示麦克风不可用)
  2. 控制帧 → 自动切输入法到微信输入法(TIS, 无需授权) → 合成其语音快捷键
     (CGEvent, 默认 Fn / Fn+空格, 与微信输入法设置实测一致)
  3. LaunchAgent 开机自启 (RunAtLoad + KeepAlive)
```

## 构建 / 安装 / 体检

```bash
cd lele-voice/macos-daemon
cargo build --release
./target/release/lele-voice-daemon install     # 装 .app + LaunchAgent + 配置模板, 立即启动
./target/release/lele-voice-daemon doctor      # 设备/输入源/授权/中转连通 一次体检
./target/release/lele-voice-daemon uninstall
./target/release/lele-voice-daemon switch-ime <bundle-id>   # 排障: 手动切输入法
launchctl kickstart -k gui/501/cn.taoge.lele-voice-daemon   # 改配置后重启
tail -f ~/Library/Logs/cn.taoge.lele-voice-daemon.log       # 日志(每5s一行统计)
```

安装物:
- `~/Applications/lele-voice-daemon.app`(二进制,**必须用 bundle 形态**——
  实测 launchd 裸二进制没有应用归属,CoreAudio 的 stream-usage 握手会死等并
  楔死 coreaudiod 的设备打开,症状=所有进程都打不开该音频设备,恢复须
  `sudo killall coreaudiod`)
- `~/Library/LaunchAgents/cn.taoge.lele-voice-daemon.plist`(RunAtLoad+KeepAlive)
- `~/.config/lele-voice/config.toml`(配置,全部字段可省略)

## 配置(~/.config/lele-voice/config.toml)

```toml
[relay]
host = "124.221.187.167"   # 留空 = LAN 直连(本机绑 9761)
port = 9761
ping_port = 9762
token = "lele-6deb6d37"
tag = "mac"

[audio]
device = "BlackHole 2ch"   # 虚拟麦克风宿主(子串匹配)
source_rate = 16000        # 工牌推流采样率

[trigger]
enabled = true
ptt_keys = "63"            # 工牌下键按住说话 = 按住该组合键 (63=Fn)
toggle_keys = "63,49"      # 工牌上键语音开关   = 轻击该组合键 (63,49=Fn+空格)
mods = "fn"                # fn/ctrl/alt/cmd/shift
switch_ime = true          # 触发前自动切输入法 + 漂移自愈
input_source_id = "com.tencent.inputmethod.wetype.pinyin"
```

键名支持 `fn/space/ctrl/alt/cmd/shift/tab/enter/esc/f1-f12` 或数字 keycode
或 `0x..`。微信输入法里改绑语音快捷键后,这里同步改。

## 一次性授权(注入快捷键必需)

系统设置 → 隐私与安全性 → **辅助功能** → 添加并勾选
`~/Applications/lele-voice-daemon.app/Contents/MacOS/lele-voice-daemon`。
不授权:音频/切输入法正常,**快捷键注入被系统静默丢弃**(无报错,症状=面板不弹)。
授权后 `launchctl kickstart -k gui/501/cn.taoge.lele-voice-daemon`。

## 验证记录(2026-10-11 全部实测)

1. launchd 下音频打开 48000Hz/2ch ✓;真实工牌音频经中转 233kbps 持续流入,
   峰值随语音波动、零丢弃 ✓
2. UDP 9762 PING→PONG 应答(LAN)/中转 RTT 统计(订阅) ✓
3. DICT1 → 输入法现场切到微信输入法(还顺带把之前切走的恢复了)✓;
   四种控制帧分发正确、固件 3 连发去重正确 ✓
4. TIS 切换往返(ABC↔微信输入法)实测通过;**切换/读当前源无需辅助功能授权**
5. 正弦探针:UDP → 重采样 → BlackHole,统计峰值=注入幅值(12000)分毫不差 ✓

## UDP 打洞直连(§六十五, 降延迟)

链路 = 工牌↔Mac 端到端直传, 中转退化为"汇聚点+回退通道":

```
SRCQ(终端→中转) → SRC ip:port      # Mac 查工牌公网映射地址
PONG …|PEER=ip:port (中转→工牌)    # 工牌从每秒探测里顺带拿到 Mac 映射地址
PNCH+token 双向互发(每秒)          # 凿开两侧 NAT 绑定
工牌收到 Mac 的 PNCH → 音频直发 Mac; 10s 无 PNCH 自动回退中转 (固件自动切换)
```

- 配置 `[punch] enabled`(默认 true)/`interval_ms`/`probe_every`;日志统计行出现
  `直连✓` 即直传生效。
- 中转(relay.py)只加了两个 rendezvous 动词, 向后兼容: 旧固件/旧终端完全不受影响。
- 实测(2026-10-11): 汇聚交换双向 ✓、直连切换与回退逻辑 ✓、中转回退期间音频无中断 ✓。
  **跨 NAT 真打通待工牌 OTA 新固件后验证**(同机模拟受 hairpin 限制);
  家宽路由器与公司 NAT 是否支持打洞取决于其 NAT 类型, 对称 NAT 打不通会
  自动留在中转通道(无损)。

## 菜单栏小程序 + 系统通知(§六十七)

`install` 会自动用 swiftc 编译安装**菜单栏小程序**(需 Xcode CLT):
`~/Applications/lele-voice-menubar` + LaunchAgent `cn.taoge.lele-voice-menubar`。

- 菜单栏图标即状态:**🎙 有声音 / 🔗 直连待机 / ☁️ 中转待机 / ❗ 守护无响应**
- 点开菜单:状态总览(收包/码率/RTT/直连)、最近事件、**打开实时日志**(Console.app)、
  **编辑配置**(TextEdit 打开 config.toml)、**系统通知开关**(改配置文件,守护 30s 热生效)、
  **重启守护**
- **系统通知**:`[ui] notify = true`(默认开)时,收到事件即弹通知——
  🎙 语音输入开/关、按住说话开始/结束(PTT)、🔗 直连建立;同类通知 30s 限频。
  通知归属 Script Editor(osascript 身份),首次可在系统设置→通知里调整样式。

## 踩坑实录(重写前必读)

1. **TIS 三坑**(都有崩溃报告为证):
   - `TISGetInputSourceProperty` 的 propertyKey 是**按值** CFStringRef
     (头文件 TextInputSources.h:719),且属性键必须用导出常量
     `kTISPropertyInputSourceID`(extern static),自造同内容 CFString 查不到;
   - `TISCreateInputSourceList` 的过滤字典**不能配 NULL 回调**(退化为指针
     相等,永远查不到)——干脆全量枚举+字符串比较;
   - **数组 CFRelease 后源指针即悬空**,`TISSelectInputSource` 落在已释放
     对象 = EXC_BREAKPOINT(`__CF_IS_OBJC`),选择必须发生在数组存活期间。
2. **launchd 裸二进制打开音频设备会楔死 coreaudiod**:`HALC_ProxyIOContext::
   _TellServerAboutStreamUsage` mach_msg 死等,之后**所有进程**都打不开该设备
   (枚举/扬声器不受影响)。修复 = 以 .app bundle 形态安装(有 CFBundleIdentifier
   归属)。恢复被楔死的音频服务 = `sudo killall coreaudiod`(秒级自愈,无损)。
3. **cpal Stream 非 Send** 且打开可能永久阻塞:打开动作放专用线程,主流程
   限时(15s)等待,超时退避重试,绝不阻塞收流;流成功后由同一线程常驻持有。
4. **时钟漂移**:源 16k 与 DAC 48k 无共同节拍,稳态缓冲水位单向漂移 →
   周期性欠载(听感碎)。对策 = 每包按水位微伺服(增删 1 帧,0.03% 变速)
   + 150ms 预缓冲。
5. **纯 Fn 按住-松开(PTT 无中途击键)会被系统认作"Fn 轻击"** → 弹表情面板
   (CharacterPaletteIM 被选中)扰动当前输入法。对策 = 每次触发后 150ms 复查
   输入源,漂了就切回目标 IME(选择输入源会顺带收起面板)。
   彻底回避 = 把微信输入法两语音快捷键改绑成非 Fn 组合键(config 同步改)。
6. `AppleFnUsageType=1`(Fn 轻击=表情面板)与 WeType 快捷键不冲突:
   系统只消费"纯轻击",组合键归 IME。
7. **Swift 读日志尾部被汉字 UTF-8 字节边界咬**:按固定 64KB 边界 seek+读,
   首字节恰是汉字续字节时 `String(data:encoding:.utf8)` 返回 **nil**(整段变空),
   状态判定恒 false。修复=用 `String(decoding: data, as: UTF8.self)`(lossy)。
8. 直连模式下守护绑**临时端口**(connect 中转),本地想直发控制帧到 9761 是到不了
   守护的——排障时经中转触发,或看菜单栏/日志。

## 与旧方案的关系

- Mac 端 `tools/voice_receiver.py`/`voice_receiver.sh`/`spike_weetype_hotkey.py`
  保留作调试备用,日常由本守护接管(Mac 上不要同时跑,会双份喂声卡);
- Windows 端仍用 `start_receiver.bat`(注入用 SendInput,需先在微信输入法
  改绑快捷键,见 windows-guide.md §一.5);
- 协议、中转、工牌固件零改动(见 voice-bridge.md §六十四)。
