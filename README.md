# 🪪 乐乐的 AI 导游工牌 (Lele AI Tour Guide Passport)

> **为小学生亲子自驾旅行打造的智能 AI 导游与 AGY 任务控制终端**  
> 硬件平台：FoloToy / TRAE AI Passport (ESP32-C3 + 2.4" 240x320 ST7789 LCD + ES8311 音频 + 3 按键分压梯)

---

## 🌟 项目愿景与核心功能

本项目并非简单的任务监视器，而是提供给小孩子（乐乐）去**自主探索、收集旅行好玩内容、自己当导游讲解**的随身交互入口，同时作为控制 AGY 的物理入口：

1. **三步交互式确认流（Voice ➔ Preview ➔ Commit）**：
   - **第 1 步（语音表达）**：按住工牌【上键】，乐乐直接对麦克风说话说明想法；
   - **第 2 步（文字方案预览）**：松开【上键】，屏幕清晰显示识别的**乐乐原话**与大模型生成的**建议讲解提纲与考题**；
   - **第 3 步（孩子确认 ➔ 部署生效）**：乐乐按【OK 键】确认，触发 GitHub 自动构建与 Webhook 部署，2 秒后公网网页（[https://trip.taoge.xyz/](https://trip.taoge.xyz/)）自动刷新！
2. **全量离线古诗词与人文知识库**：
   - 内置 16 大经典人文景点（白马寺、龙门石窟、夫子庙、中华门、大雁塔、大唐不夜城、兵马俑、华山、函谷关、地坑院、清明上河园等）；
   - 对标小学 1~5 年级与初中语文必背古诗词、历史名人故事及“💡 乐乐考考爸妈”趣味问答；
   - 按【下键】在本地 **0 毫秒零延迟即时切页浏览**。
3. **小米 MIMO 大模型多模态赋能**：
   - 接入 Xiaomi MiMo-v2.5 多模态体系，支持 `mimo-v2.5-tts`（音色“冰糖”）儿童生动解说语音合成与 ASR 语音识别。
4. **全套中文字库引擎（GB2312 6,978 字）**：
   - 自研 16x16 高性能中文字模引擎（`chinese_font.py` + `font16.bin`），采用直写 SPI 窗口块传输，彻底解决方块乱码与闪烁。
5. **Wi-Fi 无线 OTA 空中部署**：
   - 内置 WebREPL 监听，支持随时拔掉 USB 线，通过局域网 Wi-Fi 一键空中热更新代码与字库。

---

## 🛠️ 硬件引脚定义 (ESP32-C3)

| 功能模块 | 引脚 / 通道 | 说明 |
| :--- | :--- | :--- |
| **LCD SCLK** | `GPIO 6` | SPI 硬件时钟（30MHz） |
| **LCD MOSI** | `GPIO 5` | SPI 数据输出 |
| **LCD DC** | `GPIO 2` | 数据 / 命令切换 |
| **LCD CS** | `GPIO 7` | 片选 |
| **LCD BL** | `GPIO 10` | 背光控制（高电平点亮） |
| **按键分压梯** | `GPIO 0` (ADC1_CH0) | 【上键】<300mV \| 【下键】300~800mV \| 【OK键】800~2200mV |
| **音频 Codec** | `ES8311` (I2C 0x18) | SDA: `GPIO 10`, SCL: `GPIO 7` |
| **电量计** | `CW2017` (I2C 0x63) | 实时百分比与电压监测 |

---

## 📁 目录结构

```
lele-ai-passport/
├── firmware/                  # MicroPython 端侧固件与应用程序
│   ├── boot.py                # 开机引导与 WebREPL OTA 自启
│   ├── main.py                # 主事件循环与按键三步状态机
│   ├── lele_ui.py             # 240x320 诗词导游与三步交互弹窗渲染器
│   ├── chinese_font.py        # GB2312 高性能二分查找点阵字体引擎
│   ├── font16.bin             # 272KB 全量 6978 汉字二进制点阵字库
│   ├── spots_data.py          # 16 大经典景点与中小学必背诗词离线知识库
│   ├── st7789_direct.py       # ST7789 硬件直驱驱动
│   ├── wifi_manager.py        # Wi-Fi 连网与 UDP 双向通信管理器
│   ├── audio_player.py        # ES8311 硬件音效与提示音播放器
│   ├── battery.py             # CW2017 电量计读取模块
│   └── config.py              # 全局引脚与屏幕分辨率配置
├── bridge/                    # 宿主机（N1 / Linux）后台守护桥接服务
│   ├── lele_bridge.py         # UDP 监听、Git 自动提交与 Webhook 部署分发
│   ├── mimo_service.py        # 小米 MIMO 大模型 TTS 语音合成与方案策划
│   └── mimo_client.py         # MIMO API 客户端封装
├── scripts/                   # 一键部署与运维脚本
│   ├── deploy_wireless_ota.sh # Wi-Fi 局域网空中无线部署脚本
│   └── deploy_usb.sh          # USB 串口有线固件烧录脚本
└── README.md                  # 本文档
```

---

## 🚀 快速使用

### 1. USB 首次有线部署
```bash
./scripts/deploy_usb.sh /dev/ttyACM0
```

### 2. Wi-Fi 无线 OTA 空中热更新
```bash
./scripts/deploy_wireless_ota.sh 192.168.31.133
```

### 3. 启动后台 N1 桥接守护服务
```bash
nohup python3 bridge/lele_bridge.py > bridge.log 2>&1 &
```

---

## 📜 许可与致谢
- 专为乐乐亲子旅行项目定制开发
- 感谢 FoloToy 与 TRAE 开源硬件生态
