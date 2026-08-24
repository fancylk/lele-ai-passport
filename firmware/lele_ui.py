"""
Lele AI Tour Guide 240x320 UI Renderer with Real Voice Text & MIMO Proposal Display.
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
COLOR_CARD_BG     = 0x18C3
COLOR_BG          = 0x0841  # Slate Dark

STATE_GUIDE      = 0
STATE_LISTENING  = 1
STATE_PROPOSAL   = 2
STATE_DEPLOYING  = 3
STATE_SUCCESS    = 4

class LeleUI:
    def __init__(self, display=None, width=240, height=320):
        self.display = display
        self.width = width
        self.height = height
        self.state = STATE_GUIDE
        
        # Guide data
        self.spot = "白马寺"
        self.city = "洛阳"
        self.grade = "历史典故必知"
        self.poem = "《题白马寺》· 贾岛"
        self.verse = "白马驮经自宛延，空门从此度人天。"
        self.celebrity = "汉明帝、摄摩腾竺法兰"
        self.quiz = "‘白马驮经’四字口诀！"
        self.index = 0
        self.total = 16
        self.battery_pct = 100
        
        # Real Transcribed Voice & MIMO Proposal (Step 2)
        self.user_text = ""
        self.prop_title = ""
        self.prop_desc = ""
        self.prop_quiz = ""

    def update_guide(self, data):
        self.spot = data.get("spot", self.spot)
        self.city = data.get("city", self.city)
        self.grade = data.get("grade", self.grade)
        self.poem = data.get("poem", self.poem)
        self.verse = data.get("verse", self.verse)
        self.celebrity = data.get("celebrity", self.celebrity)
        self.quiz = data.get("quiz", self.quiz)
        self.index = data.get("index", self.index)
        self.total = data.get("total", self.total)
        if self.state == STATE_GUIDE:
            self.render()

    def render(self):
        if not self.display:
            return
        d = self.display

        if self.state == STATE_GUIDE:
            self._render_guide_screen()
        elif self.state == STATE_LISTENING:
            self._render_listening_modal()
        elif self.state == STATE_PROPOSAL:
            self._render_proposal_screen()
        elif self.state == STATE_DEPLOYING:
            self._render_deploying_modal()
        elif self.state == STATE_SUCCESS:
            self._render_success_modal()

    def _render_guide_screen(self):
        d = self.display

        # 1. Top Header Bar (0-36)
        d.fill_rect(0, 0, self.width, 36, COLOR_NAVY)
        draw_string_cn(d, "乐乐小导游通行证", 6, 10, COLOR_WHITE, COLOR_NAVY)
        bat_str = f"{self.battery_pct}%"
        d.text(bat_str, self.width - 46, 6, COLOR_GREEN, COLOR_NAVY)
        idx_str = f"{self.index+1}/{self.total}"
        d.text(idx_str, self.width - 46, 20, COLOR_YELLOW, COLOR_NAVY)

        # 2. City & Spot Banner (38-92)
        d.fill_rect(0, 36, self.width, 58, COLOR_BG)
        d.fill_rect(6, 40, self.width - 12, 50, COLOR_BLACK)
        d.rect(6, 40, self.width - 12, 50, COLOR_CYAN)
        spot_title = f"[{self.city}] {self.spot}"
        draw_string_cn(d, spot_title, 12, 46, COLOR_YELLOW, COLOR_BLACK)
        draw_string_cn(d, self.grade, 12, 68, COLOR_LIGHTGREY, COLOR_BLACK)

        # 3. Poetry Card (96-174)
        d.fill_rect(0, 94, self.width, 82, COLOR_BG)
        d.fill_rect(6, 96, self.width - 12, 78, COLOR_CARD_BG)
        d.rect(6, 96, self.width - 12, 78, COLOR_ORANGE)
        draw_string_cn(d, f"必背:{self.poem}", 12, 104, COLOR_YELLOW, COLOR_CARD_BG)
        draw_string_cn(d, self.verse[:14], 12, 128, COLOR_WHITE, COLOR_CARD_BG)
        if len(self.verse) > 14:
            draw_string_cn(d, self.verse[14:28], 12, 150, COLOR_WHITE, COLOR_CARD_BG)

        # 4. Celebrity & Quiz Card (178-282)
        d.fill_rect(0, 176, self.width, 108, COLOR_BG)
        d.fill_rect(6, 178, self.width - 12, 104, COLOR_BLACK)
        d.rect(6, 178, self.width - 12, 104, COLOR_GREEN)
        draw_string_cn(d, f"名人:{self.celebrity[:12]}", 12, 186, COLOR_CYAN, COLOR_BLACK)
        draw_string_cn(d, "乐乐考考爸妈:", 12, 212, COLOR_YELLOW, COLOR_BLACK)
        draw_string_cn(d, self.quiz[:14], 12, 236, COLOR_WHITE, COLOR_BLACK)
        if len(self.quiz) > 14:
            draw_string_cn(d, self.quiz[14:28], 12, 258, COLOR_WHITE, COLOR_BLACK)

        # 5. Bottom Navigation Bar (286-320)
        d.fill_rect(0, 286, self.width, 34, COLOR_NAVY)
        draw_string_cn(d, "按住上键说话 下键翻页", 8, 294, COLOR_YELLOW, COLOR_NAVY)

    def _render_listening_modal(self):
        d = self.display
        d.fill_rect(10, 60, self.width - 20, 200, COLOR_BLACK)
        d.rect(10, 60, self.width - 20, 200, COLOR_YELLOW)
        d.rect(11, 61, self.width - 22, 198, COLOR_YELLOW)
        draw_string_cn(d, "🎙️ 正在录制乐乐语音...", 20, 80, COLOR_CYAN, COLOR_BLACK)
        draw_string_cn(d, "请对着工牌麦克风说话", 20, 120, COLOR_WHITE, COLOR_BLACK)
        draw_string_cn(d, "松开上键传送至 MIMO 大模型！", 20, 160, COLOR_YELLOW, COLOR_BLACK)

    def _render_proposal_screen(self):
        d = self.display
        # Header
        d.fill_rect(0, 0, self.width, 36, COLOR_ORANGE)
        draw_string_cn(d, "🤖 MIMO 大模型建议方案", 8, 10, COLOR_BLACK, COLOR_ORANGE)

        # Proposal Box
        d.fill_rect(0, 36, self.width, 250, COLOR_BG)
        d.fill_rect(8, 40, self.width - 16, 240, COLOR_BLACK)
        d.rect(8, 40, self.width - 16, 240, COLOR_GREEN)

        # 1. Real Transcribed Speech
        draw_string_cn(d, "🗣️ 乐乐原话:", 14, 48, COLOR_CYAN, COLOR_BLACK)
        utext = self.user_text if self.user_text else "（已收到语音）"
        draw_string_cn(d, f"“{utext[:12]}”", 14, 72, COLOR_WHITE, COLOR_BLACK)
        if len(utext) > 12:
            draw_string_cn(d, f"{utext[12:24]}”", 14, 94, COLOR_WHITE, COLOR_BLACK)

        # 2. Dynamic Proposed Tour Task
        draw_string_cn(d, "💡 建议新内容:", 14, 122, COLOR_YELLOW, COLOR_BLACK)
        draw_string_cn(d, self.prop_title[:14], 14, 146, COLOR_WHITE, COLOR_BLACK)

        # 3. Dynamic Narrative Description
        draw_string_cn(d, "📖 讲解提纲:", 14, 172, COLOR_CYAN, COLOR_BLACK)
        draw_string_cn(d, self.prop_desc[:14], 14, 196, COLOR_LIGHTGREY, COLOR_BLACK)
        if len(self.prop_desc) > 14:
            draw_string_cn(d, self.prop_desc[14:28], 14, 218, COLOR_LIGHTGREY, COLOR_BLACK)

        draw_string_cn(d, "确认要添加到行程吗？", 14, 248, COLOR_YELLOW, COLOR_BLACK)

        # Action Bar (Bottom)
        d.fill_rect(0, 286, self.width, 34, COLOR_NAVY)
        draw_string_cn(d, "[OK 确认提交] [下键 取消]", 8, 294, COLOR_GREEN, COLOR_NAVY)

    def _render_deploying_modal(self):
        d = self.display
        d.fill_rect(10, 80, self.width - 20, 160, COLOR_BLACK)
        d.rect(10, 80, self.width - 20, 160, COLOR_CYAN)
        d.rect(11, 81, self.width - 22, 158, COLOR_CYAN)
        draw_string_cn(d, "🚀 正在提交并发布...", 20, 110, COLOR_YELLOW, COLOR_BLACK)
        draw_string_cn(d, "GitHub 部署流水线运行中", 20, 150, COLOR_WHITE, COLOR_BLACK)
        draw_string_cn(d, "稍候 2 秒自动刷新 iPad", 20, 190, COLOR_CYAN, COLOR_BLACK)

    def _render_success_modal(self):
        d = self.display
        d.fill_rect(10, 80, self.width - 20, 160, COLOR_BLACK)
        d.rect(10, 80, self.width - 20, 160, COLOR_GREEN)
        d.rect(11, 81, self.width - 22, 158, COLOR_GREEN)
        draw_string_cn(d, "🎉 任务已成功发布！", 20, 110, COLOR_GREEN, COLOR_BLACK)
        draw_string_cn(d, "快看 iPad 上的新内容！", 20, 150, COLOR_YELLOW, COLOR_BLACK)
        draw_string_cn(d, "网页已自动刷新完成", 20, 190, COLOR_WHITE, COLOR_BLACK)

    def show_listening(self):
        self.state = STATE_LISTENING
        self.render()

    def show_proposal(self, user_text, title, desc, quiz=""):
        self.state = STATE_PROPOSAL
        self.user_text = user_text
        self.prop_title = title
        self.prop_desc = desc
        self.prop_quiz = quiz
        self.render()

    def show_deploying(self):
        self.state = STATE_DEPLOYING
        self.render()

    def show_success(self):
        self.state = STATE_SUCCESS
        self.render()

    def show_guide(self):
        self.state = STATE_GUIDE
        self.render()
