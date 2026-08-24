"""
tmux Monitor & State Parser with Chinese Localization.
"""

import subprocess
import re
import time
import logging
from typing import Dict, Any, Tuple, Optional
from protocol import Protocol

logger = logging.getLogger("TmuxMonitor")

SHELL_NAMES = {"bash", "zsh", "sh", "fish", "ash", "csh", "tcsh"}

class TmuxMonitor:
    def __init__(self, session_name: str = "agy_workspace"):
        self.session_name = session_name
        self.last_output = ""
        self.last_status = Protocol.STATUS_IDLE
        self.last_progress = 0
        self.last_task = "等待新任务开始..."
        self.last_detail = "系统已就绪，随时可以工作"
        self.is_paused = False
        self.last_status_change_time = time.time()

    def session_exists(self) -> bool:
        try:
            res = subprocess.run(
                ["tmux", "has-session", "-t", self.session_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return res.returncode == 0
        except FileNotFoundError:
            return False

    def get_current_command(self) -> str:
        if not self.session_exists():
            return ""
        try:
            res = subprocess.run(
                ["tmux", "display-message", "-p", "-t", self.session_name, "#{pane_current_command}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    def capture_pane(self, lines: int = 35) -> str:
        if not self.session_exists():
            return ""
        try:
            res = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", self.session_name, "-S", f"-{lines}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace"
            )
            if res.returncode == 0:
                return res.stdout
        except Exception as e:
            logger.warning(f"Failed to capture tmux pane: {e}")
        return ""

    def parse_progress(self, text: str) -> Optional[int]:
        matches = re.findall(r'(?:progress|step|pct)?\s*[:=]?\s*\[?\s*(\d{1,3})\s*%\s*\]?', text, re.IGNORECASE)
        if matches:
            try:
                pct = int(matches[-1])
                if 0 <= pct <= 100:
                    return pct
            except ValueError:
                pass

        frac_matches = re.findall(r'(?:step|item|task)?\s*\[?\s*(\d+)\s*/\s*(\d+)\s*\]?', text, re.IGNORECASE)
        if frac_matches:
            try:
                curr, total = int(frac_matches[-1][0]), int(frac_matches[-1][1])
                if total > 0 and curr <= total:
                    return int((curr / total) * 100)
            except ValueError:
                pass
        return None

    def parse_state(self) -> Dict[str, Any]:
        if not self.session_exists():
            return {
                "session": self.session_name,
                "status": Protocol.STATUS_IDLE,
                "task": f"未连接会话：{self.session_name}",
                "progress": 0,
                "detail": "请在主机开启 tmux 会话"
            }

        output = self.capture_pane(lines=30)
        lines = [line.strip() for line in output.splitlines() if line.strip()]

        if not lines:
            return {
                "session": self.session_name,
                "status": Protocol.STATUS_IDLE,
                "task": "等待新任务开始...",
                "progress": 0,
                "detail": "系统待命中，准备就绪"
            }

        curr_cmd = self.get_current_command()
        is_cmd_running = bool(curr_cmd and curr_cmd.lower() not in SHELL_NAMES)

        recent_text = "\n".join(lines[-15:])
        last_line = lines[-1] if lines else ""
        prev_line = lines[-2] if len(lines) > 1 else ""

        if self.is_paused:
            return {
                "session": self.session_name,
                "status": Protocol.STATUS_PAUSED,
                "task": self.last_task or "任务已暂停休息中",
                "progress": self.last_progress,
                "detail": "按 OK 键随时继续任务"
            }

        fail_patterns = [
            r'error\b', r'failed\b', r'exception\b', r'traceback',
            r'fatal\b', r'abort\b', r'build failed', r'exit code [1-9]'
        ]
        is_failed = any(re.search(p, recent_text, re.IGNORECASE) for p in fail_patterns)

        success_patterns = [
            r'successfully\b', r'build finished', r'completed\b',
            r'all tests passed', r'success\b', r'finished successfully'
        ]
        is_success = any(re.search(p, recent_text, re.IGNORECASE) for p in success_patterns)

        is_shell_prompt = bool(re.search(r'[\$#>\?]\s*$', last_line))
        pct = self.parse_progress(recent_text)

        if is_cmd_running:
            status = Protocol.STATUS_RUNNING
        elif is_failed and (not is_shell_prompt or (time.time() - self.last_status_change_time < 8.0 and self.last_status == Protocol.STATUS_FAILED)):
            status = Protocol.STATUS_FAILED
        elif is_success:
            status = Protocol.STATUS_SUCCESS
        elif is_shell_prompt:
            if is_success:
                status = Protocol.STATUS_SUCCESS
            elif is_failed:
                status = Protocol.STATUS_FAILED
            else:
                status = Protocol.STATUS_IDLE
        else:
            status = Protocol.STATUS_RUNNING

        if status == Protocol.STATUS_RUNNING:
            progress = pct if pct is not None else min(95, max(5, self.last_progress + 2))
            task = f"正在运行：{curr_cmd}" if curr_cmd and curr_cmd not in SHELL_NAMES else self._extract_task_name(lines)
            detail = last_line[:80]
        elif status == Protocol.STATUS_SUCCESS:
            progress = 100
            task = "太棒啦！任务已顺利完成"
            detail = (prev_line if is_shell_prompt and prev_line else last_line)[:80]
        elif status == Protocol.STATUS_FAILED:
            progress = pct if pct is not None else self.last_progress
            task = "哎呀，任务遇到一点问题"
            detail = self._extract_error_detail(lines)[:80]
        else:
            progress = 0
            task = "等待新任务开始..."
            detail = last_line[:80] if last_line else "随时准备开始新任务"

        if status != self.last_status:
            self.last_status_change_time = time.time()

        self.last_status = status
        self.last_progress = progress
        self.last_task = task
        self.last_detail = detail

        return {
            "session": self.session_name,
            "status": status,
            "task": task,
            "progress": progress,
            "detail": detail
        }

    def _extract_task_name(self, lines) -> str:
        for line in reversed(lines[-8:]):
            clean = re.sub(r'[\$#>]', '', line).strip()
            if clean and len(clean) > 3:
                return clean[:24]
        return "执行代码任务中..."

    def _extract_error_detail(self, lines) -> str:
        for line in reversed(lines[-6:]):
            if re.search(r'error|failed|exception|fatal', line, re.IGNORECASE):
                return line[:80]
        return lines[-1][:80] if lines else "未知错误"

    def pause_session(self) -> Tuple[bool, str]:
        if not self.session_exists():
            return False, "会话不存在"
        try:
            subprocess.run(["tmux", "send-keys", "-t", self.session_name, "C-z"], check=True)
            self.is_paused = True
            return True, "已暂停"
        except Exception as e:
            return False, str(e)

    def resume_session(self) -> Tuple[bool, str]:
        if not self.session_exists():
            return False, "会话不存在"
        try:
            subprocess.run(["tmux", "send-keys", "-t", self.session_name, "fg", "Enter"], check=True)
            self.is_paused = False
            return True, "已恢复"
        except Exception as e:
            return False, str(e)

    def next_step(self) -> Tuple[bool, str]:
        if not self.session_exists():
            return False, "会话不存在"
        try:
            subprocess.run(["tmux", "send-keys", "-t", self.session_name, "Enter"], check=True)
            return True, "已确认下一步"
        except Exception as e:
            return False, str(e)

    def send_keys(self, keys: str) -> Tuple[bool, str]:
        if not self.session_exists():
            return False, "会话不存在"
        try:
            subprocess.run(["tmux", "send-keys", "-t", self.session_name, keys], check=True)
            return True, f"已发送：{keys}"
        except Exception as e:
            return False, str(e)
