# tools/ —— 乐乐语音桥 Mac 端工具

## voice_receiver.py / voice_receiver.sh —— 音频接收器 + 语音触发

收工牌 UDP 推流并实时送进 BlackHole 虚拟声卡（微信输入法 Mac 版的"麦克风"）；
同时识别工牌控制帧，后台合成微信输入法语音快捷键（§六十四，详见 docs/voice-bridge.md）。

- `udp://0.0.0.0:9761` ← 16kHz/16bit/mono s16le PCM → BlackHole 2ch 实时播放
- `udp://0.0.0.0:9762` ← 工牌 PING 探测包 → 回 PONG（工牌据此算 RTT 上屏）
- 控制帧 `DICT1/DICT0`(长输入开/关=Fn+空格) `PTTD1/PTTD0`(按住说话=Fn 按下/抬起)
  → 需辅助功能权限(授权给启动它的终端); `--no-voice-trigger` 关闭;
  快捷键被改绑时用 `--voice-ptt-key/--voice-toggle-key/--voice-mods` 对齐

```bash
./voice_receiver.sh start    # 后台启动 (日志 /tmp/voice_receiver.log)
./voice_receiver.sh status   # 状态 + 最近统计
./voice_receiver.sh follow   # 跟日志
./voice_receiver.sh stop
```

前台跑（看实时统计）：`tools/.venv/bin/python tools/voice_receiver.py`
每 5 秒打一行：收包数/码率/到包抖动/缓冲。`静默!` 标记 = 2 秒没收到音频
（工牌待机静音时属正常）。

依赖：`python3 -m venv tools/.venv && tools/.venv/bin/pip install sounddevice`
（已装则跳过）

## spike_weetype_hotkey.py —— 语音触发自检

合成 Fn / Fn+空格 验证"辅助功能授权 + 微信输入法响应"整条注入链路。
**必须在将来运行 voice_receiver 的同一终端环境跑**（通常 Terminal.app）。
用法：`python3 spike_weetype_hotkey.py probe|toggle|ptt [ms]`，判读见文件头。

## verify_blackhole.sh —— BlackHole 链路验证

录 6 秒 BlackHole 的输入并报电平。推流中跑它，`max_volume > -25dB` = 音频真的到了虚拟声卡；无声 ≈ -91dB = 链路断。

## webrepl_cli.py / webrepl_reset.py —— 工牌 OTA 底座

MicroPython 官方 WebREPL 客户端（vendored）+ 软重启工具。
配套部署脚本见 `scripts/deploy_wireless_ota_mac.sh`。

## 首次安装（一次性）

1. **BlackHole 2ch**（需要管理员密码，二选一）：
   - 终端跑 `brew install blackhole-2ch` 输密码；或
   - 双击 `~/Downloads/BlackHole2ch-0.7.1.pkg`（已从 brew 缓存拷出）。
   - 装完若系统声音设置里看不到 BlackHole 2ch → 注销重登（或 `sudo killall coreaudiod`）。
2. **venv**（已装好）：
   `python3 -m venv tools/.venv && tools/.venv/bin/pip install sounddevice mpremote websockets`
