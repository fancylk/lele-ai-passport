#!/bin/bash
# ============================================================
# lele-coder worker - 常驻 tmux 会话中的 AI 编码任务执行器
# AI 工具: omp (oh-my-pi), 用 -c/--continue 维持同一会话
# 任务协议 (/home/ubuntu/lele-bridge/tasks/):
#   *.task               : JSON {"id","title","desc","quiz","prompt"}
#   done/<id>.result.json: {"id","changed","commit","exit","duration","summary","error"}
# ============================================================
BASE=/home/ubuntu/lele-bridge
TASK_DIR=$BASE/tasks
DONE_DIR=$TASK_DIR/done
LOG_DIR=$BASE/coder_logs
REPO=/home/ubuntu/trip-repo
OMP=/home/ubuntu/.npm-global/bin/omp
export PATH="$HOME/.npm-global/bin:$PATH"
export ZHIPU_API_KEY="sk-f155d9569c5845e998df8861b880297a.uqua7IxQP9GgOvGH"
export ZHIPUAI_API_KEY="$ZHIPU_API_KEY"
CODER_BIN="${LELE_CODER_BIN:-$OMP}"
MODEL="${LELE_CODER_MODEL:-openai-codex/gpt-5.6-luna}"
TASK_TIMEOUT="${LELE_TASK_TIMEOUT:-1500}"

mkdir -p "$TASK_DIR" "$DONE_DIR" "$LOG_DIR"

"$CODER_BIN" --version >/dev/null 2>&1 || { echo "[worker] FATAL: coder cli not found"; sleep 3600; }
echo "[worker] ready. waiting for tasks..."

while true; do
  TASK_FILE=$(ls "$TASK_DIR"/*.task 2>/dev/null | head -n1)
  if [ -z "$TASK_FILE" ]; then
    sleep 3
    continue
  fi

  TASK_ID=$(basename "$TASK_FILE" .task)
  META=$(cat "$TASK_FILE")
  rm -f "$TASK_FILE"
  echo "[worker] ========================================"
  echo "[worker] picked task $TASK_ID at $(date '+%F %T')"

  PROMPT=$(python3 -c "import json,sys;print(json.load(open('/dev/stdin'))['prompt'])" <<< "$META")
  echo "[worker] prompt: $PROMPT"

  LOG_FILE="$LOG_DIR/${TASK_ID}.log"
  START_TS=$(date +%s)

  cd "$REPO"
  timeout "$TASK_TIMEOUT" "$CODER_BIN" -p --mode json -c --auto-approve --model "$MODEL" \
      --max-time 20m "$PROMPT" > "$LOG_FILE" 2>&1
  EXIT_CODE=$?
  END_TS=$(date +%s)
  DUR=$((END_TS-START_TS))
  echo "[worker] omp exit=$EXIT_CODE duration=${DUR}s log=$LOG_FILE"

  # 从 JSON 事件流提取最终回复/错误
  SUMMARY=$(python3 - "$LOG_FILE" << 'PYEOF'
import json, sys, re
path = sys.argv[1]
final_text, err, stop = "", "", ""
try:
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            t = evt.get("type", "")
            if t == "message_update":
                c = (evt.get("message") or {}).get("content") or []
                parts = []
                for seg in c:
                    if isinstance(seg, dict) and seg.get("type") == "text":
                        parts.append(seg.get("text", ""))
                if parts:
                    final_text = "\n".join(parts)
            elif t == "turn_end":
                m = evt.get("message") or {}
                sr = m.get("stopReason", "")
                if m.get("errorMessage"):
                    err = str(m["errorMessage"])[:300]
                if sr:
                    stop = sr
                c = m.get("content") or []
                txts = [seg.get("text", "") for seg in c if isinstance(seg, dict) and seg.get("type") == "text"]
                if txts:
                    final_text = "\n".join(txts)
except Exception as e:
    err = "log parse error: %s" % e
out = (final_text or err or "").strip()
out = re.sub(r"\s+", " ", out)[:400]
print(json.dumps({"summary": out, "stop": stop, "error": err}, ensure_ascii=False))
PYEOF
)
  STOP_REASON=$(python3 -c "import json,sys;print(json.loads(sys.argv[1]).get('stop',''))" <<< "$SUMMARY" 2>/dev/null)
  ERR_TEXT=$(python3 -c "import json,sys;print(json.loads(sys.argv[1]).get('error',''))" <<< "$SUMMARY" 2>/dev/null)
  SUMMARY_TEXT=$(python3 -c "import json,sys;print(json.loads(sys.argv[1]).get('summary',''))" <<< "$SUMMARY" 2>/dev/null)
  echo "[worker] stop=$STOP_REASON err=$ERR_TEXT"

  # 失败判定: 非0退出 或 stop=error
  FAILED=0
  [ "$EXIT_CODE" != "0" ] && FAILED=1
  [ "$STOP_REASON" = "error" ] && FAILED=1

  # 检查仓库变更
  cd "$REPO"
  git add -A >/dev/null 2>&1
  CHANGED=0
  COMMIT=""
  if ! git diff --cached --quiet; then
    if [ "$FAILED" = "0" ]; then
      CHANGED=1
      COMMIT_MSG=$(python3 -c "import json;m=json.loads('''$META''');print('feat(lele): '+m.get('title','乐乐的新需求')[:60])")
      git commit -m "$COMMIT_MSG" >/dev/null 2>&1
      COMMIT=$(git rev-parse --short HEAD)
      if git push origin main >/dev/null 2>&1; then
        echo "[worker] pushed $COMMIT"
      else
        echo "[worker] PUSH FAILED"
        git reset --soft HEAD~1 >/dev/null 2>&1
        CHANGED=0
        ERR_TEXT="git push failed"
        FAILED=1
      fi
    else
      git reset >/dev/null 2>&1
      echo "[worker] task failed, staged changes reverted"
    fi
  fi

  RESULT_FILE="$DONE_DIR/${TASK_ID}.result.json"
  python3 - "$RESULT_FILE" << PYEOF
import json, sys
res = {
    "id": "$TASK_ID",
    "changed": "$CHANGED" == "1",
    "commit": "$COMMIT",
    "exit": $EXIT_CODE,
    "duration": $DUR,
    "failed": "$FAILED" == "1",
    "summary": """$SUMMARY_TEXT""",
    "error": """$ERR_TEXT"""
}
json.dump(res, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PYEOF
  echo "[worker] result written for $TASK_ID"
done
