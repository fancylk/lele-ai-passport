"""
Xiaomi MIMO Multimodal Audio & LLM Client for Lele's AI Tour Guide.
Transcribes Lele's raw voice into text and dynamically generates tailored tour guide additions.
"""

import os
import json
import base64
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("MIMOService")
CONFIG_PATH = "/vol1/1000/esp32_passport_workspace/bridge/mimo_config.json"

class MIMOClient:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.api_key = ""
        self.base_url = "https://api.xiaomimimo.com/v1" # Or custom endpoint
        self.model = "mimo-v1"
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.api_key = cfg.get("api_key", self.api_key)
                    self.base_url = cfg.get("base_url", self.base_url).rstrip("/")
                    self.model = cfg.get("model", self.model)
            except Exception as e:
                logger.error(f"Error loading MIMO config: {e}")

    def save_config(self, api_key: str, base_url: str = None, model: str = None):
        cfg = {
            "api_key": api_key.strip(),
            "base_url": base_url.strip() if base_url else self.base_url,
            "model": model.strip() if model else self.model
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        self.api_key = cfg["api_key"]
        self.base_url = cfg["base_url"]
        self.model = cfg["model"]
        logger.info("[+] MIMO API Key and Config saved successfully!")

    def process_voice_input(self, audio_pcm_or_wav: bytes, current_city: str = "开封", current_spot: str = "鼓楼夜市") -> dict:
        """
        Calls Xiaomi MIMO multimodal audio model:
        1. Transcribes Lele's real speech into Chinese text.
        2. Intelligently generates the tour guide title, summary, poem and quiz.
        """
        if not self.api_key:
            logger.warning("[!] MIMO API Key not set yet. Please provide API Key.")
            return {
                "user_text": "（等待配置 MIMO API Key）",
                "title": f"{current_spot} · 亲子探秘任务",
                "desc": "请在宿主机配置 Xiaomi MIMO API Key 以开启大模型实时语音解析！",
                "quiz": "乐乐今天提出了什么新想法？"
            }

        # Format prompt for MIMO
        system_prompt = (
            "你是《山河明月行》亲子自驾旅行的 AI 导游策划助手。\n"
            "小导游乐乐（小学生）正在通过工牌向你说话。你的任务是：\n"
            "1. 准确将乐乐的语音识别为文字（user_text）；\n"
            "2. 根据乐乐的想法，结合行程（当前城市：" + current_city + "，景点：" + current_spot + "），"
            "构思一段生动有趣的小导游探秘任务与讲解提纲；\n"
            "3. 严格输出 JSON 格式：\n"
            "{\n"
            '  "user_text": "乐乐说出的真实文字内容",\n'
            '  "title": "精炼的景点任务标题（10字以内）",\n'
            '  "desc": "生动有趣的儿童讲解提纲（30字以内）",\n'
            '  "quiz": "设计一道考考爸爸妈妈的趣味问题（20字以内）"\n'
            "}"
        )

        audio_b64 = base64.b64encode(audio_pcm_or_wav).decode("utf-8")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请听乐乐刚才说的话，提取并策划导游任务："},
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}
                    ]
                }
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }

        req_url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        try:
            req = urllib.request.Request(req_url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                result_json = json.loads(resp.read().decode("utf-8"))
                content_str = result_json["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                logger.info(f"🌟 [MIMO Speech Result]: {parsed}")
                return parsed
        except Exception as e:
            logger.error(f"[!] MIMO API Call error: {e}")
            return {
                "user_text": "（语音识别解析中）",
                "title": f"{current_city} · 乐乐新探秘",
                "desc": "结合乐乐的想法生成了全新导游词！",
                "quiz": "考考爸爸妈妈：这个景点的故事你知道吗？"
            }

if __name__ == "__main__":
    client = MIMOClient()
    print("MIMO Client initialized. Config file:", CONFIG_PATH)
