"""
Xiaomi MiMo Service for Lele AI Tour Guide:
- Speech Synthesis (MiMo-v2.5-TTS)
- Speech Recognition (MiMo-v2.5-ASR)
- Intelligent Tour Guide Proposal Generator
"""

import os
import json
import base64
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("MiMoService")

API_KEY = "sk-cogl4le0fr7gcnkzl4ydioufw4ufelmf21k1oxbnwijpfn50"
BASE_URL = "https://api.xiaomimimo.com/v1"

class MiMoService:
    def __init__(self, api_key=API_KEY, base_url=BASE_URL):
        self.api_key = api_key
        self.base_url = base_url

    def synthesize_speech(self, text: str, voice: str = "冰糖") -> bytes:
        """
        Synthesize natural Chinese speech using Xiaomi MiMo-v2.5-TTS.
        """
        payload = {
            "model": "mimo-v2.5-tts",
            "messages": [
                {"role": "user", "content": "用亲切生动、活泼自然的小导游语气。"},
                {"role": "assistant", "content": text}
            ],
            "audio": {
                "format": "wav",
                "voice": voice
            }
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": self.api_key
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                audio_b64 = data["choices"][0]["message"]["audio"]["data"]
                return base64.b64decode(audio_b64)
        except Exception as e:
            logger.error(f"MiMo TTS error: {e}")
            return None

    def recognize_speech(self, audio_bytes: bytes) -> str:
        """
        Transcribe voice audio using Xiaomi MiMo-v2.5-ASR.
        """
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {
            "model": "mimo-v2.5-asr",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_b64}"
                            }
                        }
                    ]
                }
            ],
            "asr_options": {"language": "zh"}
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "api-key": self.api_key
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            logger.warning(f"MiMo ASR HTTP status {e.code}: {e.reason}")
            return ""
        except Exception as e:
            logger.error(f"MiMo ASR error: {e}")
            return ""

    def generate_tour_proposal(self, user_text: str, current_city: str = "开封", current_spot: str = "鼓楼夜市") -> dict:
        """
        Given the recognized user speech, creates a structured tour guide proposal.
        """
        # Intelligent contextual matching
        text = user_text.strip()
        
        if "包公" in text or "开封" in text or "铜铡" in text or "铡刀" in text:
            return {
                "user_text": text if text else "我想给开封加一个包公断案的故事！",
                "title": "开封府 · 包公断案与三口铜铡",
                "desc": "铁面无私包青天断奇案，设计考考爸妈三口铡刀名字！",
                "quiz": "龙头铡、虎头铡、狗头铡分别铡谁？",
                "poem": "《示儿》· 陆游"
            }
        elif "华山" in text or "沉香" in text or "救母" in text or "劈山" in text:
            return {
                "user_text": text if text else "我想了解华山沉香救母的神话！",
                "title": "华山西峰 · 沉香劈山救母巨石",
                "desc": "寻找西峰神石，背诵北宋神童寇准7岁咏华山名诗！",
                "quiz": "沉香一斧劈开两半的巨石在哪个峰？",
                "poem": "《咏华山》· 寇准"
            }
        elif "大雁塔" in text or "玄奘" in text or "唐僧" in text or "西安" in text:
            return {
                "user_text": text if text else "我想知道大雁塔唐僧玄奘的故事！",
                "title": "大雁塔 · 玄奘西行五万里传奇",
                "desc": "玄奘法师独自西行17年取回657部真经建塔故事！",
                "quiz": "大雁塔是哪位唐代高僧主持修建的？",
                "poem": "《登科后》· 孟郊"
            }
        elif "龙门" in text or "石窟" in text or "洛阳" in text or "大佛" in text or "武则天" in text:
            return {
                "user_text": text if text else "我想在洛阳龙门石窟加一个寻宝任务！",
                "title": "龙门石窟 · 寻找卢舍那大佛微笑",
                "desc": "打卡东方蒙娜丽莎与大诗人白居易琵琶峰墓园！",
                "quiz": "卢舍那大佛的面容是按哪位皇帝雕刻的？",
                "poem": "《春夜洛城闻笛》· 李白"
            }
        elif "地坑院" in text or "三门峡" in text or "地下" in text:
            return {
                "user_text": text if text else "我想探索三门峡地坑院的美食！",
                "title": "陕州地坑院 · 地平线下的民居奇观",
                "desc": "见树不见村，进村不见人，探索地下四合院十大碗！",
                "quiz": "地坑院暴雨天为什么不会被水淹？",
                "poem": "民俗谚语"
            }
        else:
            return {
                "user_text": text if text else f"我想了解{current_city}{current_spot}的好玩故事！",
                "title": f"{current_spot} · 乐乐亲子探秘",
                "desc": f"和小导游乐乐一起打卡{current_city}文化名胜！",
                "quiz": f"你知道{current_spot}背后有什么历史故事吗？",
                "poem": "经典诗词"
            }

if __name__ == "__main__":
    service = MiMoService()
    print("Testing MiMo TTS...")
    audio = service.synthesize_speech("小导游乐乐，你好！我是小米 MIMO AI 助手！")
    if audio:
        out_path = "/vol1/1000/esp32_passport_workspace/family-trip/audio/mimo_welcome.wav"
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(audio)
        print(f"[+] Successfully generated MiMo TTS audio to: {out_path} ({len(audio)} bytes)")
