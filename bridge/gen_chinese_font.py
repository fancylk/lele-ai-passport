#!/usr/bin/env python3
from PIL import Image, ImageFont, ImageDraw
import struct

FONT_PATH = "/vol1/1000/esp32_passport_workspace/.cache/fonts/wqy-microhei.ttc"
OUT_PATH = "/vol1/1000/esp32_passport_workspace/firmware/micropython/chinese_font.py"

CHARS = (
    "AI智能通行证小工牌小主人任务正在努力执行中太棒啦已顺利完成"
    "哎呀出错了遇到问题已暂停休息中待机中当前进度系统负载会话确认"
    "下一步继续退出开机电量状态提示快乐学习编程代码测试开始准备成功失败等待按键"
    "主机内存处理器编译下载调试运行健康良好正常高低开关确定取消设置"
    "欢迎回来今天也是充满活力的一天加油哦"
    "语音麦克风扬声器指令发送请按下键选择切换内容待已到终端录音输入模式重启"
    "0123456789%[]:.-_/#+()=<>\"' "
)

unique_chars = []
for c in CHARS:
    if c not in unique_chars:
        unique_chars.append(c)

font = ImageFont.truetype(FONT_PATH, 14)
char_bitmaps = {}

for char in unique_chars:
    im = Image.new("1", (16, 16), 0)
    draw = ImageDraw.Draw(im)
    bbox = draw.textbbox((0, 0), char, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    ox = max(0, (16 - w) // 2)
    oy = max(0, (16 - h) // 2) - 1

    draw.text((ox, oy), char, font=font, fill=1)
    
    bytes_data = bytearray()
    for y in range(16):
        row_val = 0
        for x in range(16):
            if im.getpixel((x, y)):
                row_val |= (1 << (15 - x))
        bytes_data.extend(struct.pack(">H", row_val))
    
    char_bitmaps[char] = bytes(bytes_data)

print(f"Generated {len(char_bitmaps)} 16x16 glyphs.")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write('"""\nPrecompiled 16x16 Chinese & ASCII Bitmap Font Engine for MicroPython.\n"""\n\n')
    f.write('import struct\n\n')
    f.write('FONT_16 = {\n')
    for char, data in char_bitmaps.items():
        escaped_char = repr(char)
        f.write(f'    {escaped_char}: {repr(data)},\n')
    f.write('}\n\n')
    f.write('''
def draw_char_16(display, char, x, y, fg, bg=None):
    data = FONT_16.get(char)
    if not data:
        display.text(char, x, y + 4, fg, bg)
        return 10
    
    w = 16
    h = 16
    if x + w > display.width or y + h > display.height:
        return 16
    
    display.set_window(x, y, x + w - 1, y + h - 1)
    c_fg = struct.pack(">H", fg)
    c_bg = struct.pack(">H", bg if bg is not None else 0x0000)
    
    line_data = bytearray(w * h * 2)
    idx = 0
    for row in range(16):
        row_bits = (data[row * 2] << 8) | data[row * 2 + 1]
        for col in range(16):
            if (row_bits & (1 << (15 - col))) != 0:
                line_data[idx] = c_fg[0]
                line_data[idx+1] = c_fg[1]
            else:
                line_data[idx] = c_bg[0]
                line_data[idx+1] = c_bg[1]
            idx += 2

    if display.dc:
        display.dc.value(1)
    if display.cs:
        display.cs.value(0)
    display.spi.write(line_data)
    if display.cs:
        display.cs.value(1)
    return 16

def draw_string_cn(display, text, x, y, fg, bg=None, max_w=None):
    cur_x = x
    if max_w is None:
        max_w = display.width - x
        
    for ch in text:
        if cur_x + 16 > x + max_w:
            break
        if ord(ch) < 128:
            if ch in FONT_16:
                cur_x += draw_char_16(display, ch, cur_x, y, fg, bg)
            else:
                display.text(ch, cur_x, y + 4, fg, bg)
                cur_x += 8
        else:
            cur_x += draw_char_16(display, ch, cur_x, y, fg, bg)
''')
