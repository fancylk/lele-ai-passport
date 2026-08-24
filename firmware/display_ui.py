"""
Kid-Friendly Chinese Dashboard UI with Command Confirmation Modal (ST7789P3 240x320).
"""

from chinese_font import draw_string_cn

COLOR_BLACK       = 0x0000
COLOR_WHITE       = 0xFFFF
COLOR_NAVY        = 0x000F
COLOR_DARKGREY    = 0x39E7
COLOR_LIGHTGREY   = 0xC618
COLOR_GREEN       = 0x07E0
COLOR_RED         = 0xF800
COLOR_CYAN        = 0x07FF
COLOR_YELLOW      = 0xFFE0
COLOR_ORANGE      = 0xFD20
COLOR_CARD_BG     = 0x10A2
COLOR_BG          = 0x0841  # Slate Dark

class PassportUI:
    def __init__(self, display=None, width=240, height=320):
        self.display = display
        self.width = width
        self.height = height
        self.status = "IDLE"
        self.session = "agy_workspace"
        self.task = "等待新任务开始..."
        self.progress = 0
        self.detail = "系统已就绪，随时可以工作"
        self.cpu = 0.0
        self.mem = 0.0
        self.battery_pct = 100
        self.is_modal = False

    def update_state(self, telemetry_dict):
        self.session = telemetry_dict.get("session", self.session)
        self.status = telemetry_dict.get("status", self.status)
        self.task = telemetry_dict.get("task", self.task)
        self.progress = telemetry_dict.get("progress", self.progress)
        self.detail = telemetry_dict.get("detail", self.detail)
        self.cpu = telemetry_dict.get("cpu", self.cpu)
        self.mem = telemetry_dict.get("mem", self.mem)
        if not self.is_modal:
            self.render()

    def get_status_info(self):
        if self.status == "RUNNING":
            return COLOR_CYAN, "正在努力执行中", "小助手正在认真工作中哦"
        elif self.status == "SUCCESS":
            return COLOR_GREEN, "太棒啦！任务完成", "所有步骤均已顺利搞定"
        elif self.status == "FAILED":
            return COLOR_RED, "哎呀！遇到一点问题", "请查看下方错误提示哦"
        elif self.status == "PAUSED":
            return COLOR_ORANGE, "任务已暂停休息中", "按 OK 键随时继续工作"
        return COLOR_LIGHTGREY, "休息待命中", "随时准备开始新任务"

    def render(self):
        if not self.display or self.is_modal:
            return
        d = self.display

        # 1. Top Header Bar (0-38)
        d.fill_rect(0, 0, self.width, 38, COLOR_NAVY)
        draw_string_cn(d, "AI 智能小工牌", 8, 11, COLOR_WHITE, COLOR_NAVY)
        # Battery and stats
        bat_str = f"电:{self.battery_pct}%"
        d.text(bat_str, self.width - 66, 8, COLOR_GREEN, COLOR_NAVY)
        stats_str = f"C:{int(self.cpu)}% M:{int(self.mem)}%"
        d.text(stats_str, self.width - 86, 22, COLOR_YELLOW, COLOR_NAVY)

        # 2. Status Badge Card (42-114)
        status_color, status_title, status_sub = self.get_status_info()
        d.fill_rect(0, 38, self.width, 78, COLOR_BG)
        d.fill_rect(8, 42, self.width - 16, 68, COLOR_BLACK)
        d.rect(8, 42, self.width - 16, 68, status_color)
        d.rect(9, 43, self.width - 18, 66, status_color)

        draw_string_cn(d, "当前状态", 18, 48, COLOR_LIGHTGREY, COLOR_BLACK)
        draw_string_cn(d, status_title, 18, 68, status_color, COLOR_BLACK)
        draw_string_cn(d, status_sub, 18, 88, COLOR_LIGHTGREY, COLOR_BLACK)

        # 3. Active Task Information (116-176)
        d.fill_rect(0, 116, self.width, 62, COLOR_BG)
        draw_string_cn(d, "当前任务：", 10, 122, COLOR_YELLOW, COLOR_BG)
        draw_string_cn(d, self.task[:20], 10, 144, COLOR_WHITE, COLOR_BG)

        # 4. Progress Bar & Percentage (178-234)
        d.fill_rect(0, 178, self.width, 58, COLOR_BG)
        draw_string_cn(d, "任务进度：", 10, 182, COLOR_LIGHTGREY, COLOR_BG)
        pct_str = f"{self.progress}%"
        draw_string_cn(d, pct_str, 90, 182, status_color, COLOR_BG)

        bar_x = 10
        bar_y = 204
        bar_w = self.width - 20
        bar_h = 16
        d.rect(bar_x, bar_y, bar_w, bar_h, COLOR_WHITE)
        fill_w = int((self.progress / 100.0) * (bar_w - 4))
        if fill_w > 0:
            d.fill_rect(bar_x + 2, bar_y + 2, fill_w, bar_h - 4, status_color)

        # 5. Detail / Live Output Snippet (236-288)
        d.fill_rect(0, 236, self.width, 52, COLOR_BG)
        d.fill_rect(8, 236, self.width - 16, 48, COLOR_BLACK)
        d.rect(8, 236, self.width - 16, 48, COLOR_DARKGREY)
        draw_string_cn(d, self.detail[:18], 12, 242, COLOR_LIGHTGREY, COLOR_BLACK)
        draw_string_cn(d, self.detail[18:36], 12, 262, COLOR_LIGHTGREY, COLOR_BLACK)

        # 6. Bottom Navigation Bar (290-320)
        d.fill_rect(0, 288, self.width, 32, COLOR_NAVY)
        draw_string_cn(d, "[上键:发指令] [OK:暂停]", 14, 296, COLOR_YELLOW, COLOR_NAVY)

    def render_command_modal(self, cmd_title, cmd_text, index, total):
        """Render Voice/Text Command Selection & Confirmation Modal."""
        self.is_modal = True
        d = self.display

        # Outer Frame
        d.fill(COLOR_BG)
        
        # Modal Header (0-44)
        d.fill_rect(0, 0, self.width, 44, COLOR_NAVY)
        draw_string_cn(d, "🎙️ 语音指令输入确认", 12, 14, COLOR_CYAN, COLOR_NAVY)

        # Index Indicator
        idx_str = f"[{index+1}/{total}]"
        d.text(idx_str, self.width - 50, 16, COLOR_YELLOW, COLOR_NAVY)

        # Main Card Box (52-210)
        d.fill_rect(10, 52, self.width - 20, 160, COLOR_BLACK)
        d.rect(10, 52, self.width - 20, 160, COLOR_CYAN)
        d.rect(11, 53, self.width - 22, 158, COLOR_CYAN)

        draw_string_cn(d, "待发送指令：", 20, 64, COLOR_LIGHTGREY, COLOR_BLACK)
        draw_string_cn(d, cmd_title[:14], 20, 92, COLOR_YELLOW, COLOR_BLACK)
        
        # Draw actual command in courier font
        d.fill_rect(18, 122, self.width - 36, 32, COLOR_DARKGREY)
        d.text(f"> {cmd_text[:22]}", 24, 134, COLOR_WHITE, COLOR_DARKGREY)

        draw_string_cn(d, "已准备就绪，请按键确认", 20, 172, COLOR_GREEN, COLOR_BLACK)

        # Instruction Guide (222-280)
        d.fill_rect(10, 222, self.width - 20, 60, COLOR_CARD_BG)
        d.rect(10, 222, self.width - 20, 60, COLOR_YELLOW)
        draw_string_cn(d, "👉 按 [ OK 键 ] 确认发送至主机", 16, 230, COLOR_WHITE, COLOR_CARD_BG)
        draw_string_cn(d, "👉 按 [ 下 键 ] 切换下一条指令", 16, 256, COLOR_LIGHTGREY, COLOR_CARD_BG)

        # Bottom Hints
        d.fill_rect(0, 290, self.width, 30, COLOR_NAVY)
        draw_string_cn(d, "[OK:确认发送] [下键:切换]", 16, 298, COLOR_YELLOW, COLOR_NAVY)

    def render_feedback(self, title, sub_title="", is_success=True):
        """Render temporary pop-up notification."""
        d = self.display
        color = COLOR_GREEN if is_success else COLOR_RED
        d.fill_rect(10, 100, self.width - 20, 120, COLOR_BLACK)
        d.rect(10, 100, self.width - 20, 120, color)
        d.rect(11, 101, self.width - 22, 118, color)
        draw_string_cn(d, title, 20, 130, color, COLOR_BLACK)
        if sub_title:
            draw_string_cn(d, sub_title, 20, 165, COLOR_WHITE, COLOR_BLACK)

    def exit_modal(self):
        self.is_modal = False
        self.render()
