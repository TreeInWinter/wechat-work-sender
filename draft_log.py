# draft_log.py
"""草稿沉淀：记录「AI 原稿 → 实际发送」的差异（数据飞轮）。

坐席在发送前对 AI 草稿的编辑，是质量最高的风格训练信号：它直接告诉我们
「AI 这样写、人最终改成了那样」。把这些 diff 静默落到本地 jsonl，未来可用于
个性化话术风格、评估 AI 草稿采纳率，也是产品的数据护城河。

设计要点：
- **静默 + 尽力而为**：任何异常都不得影响发送主流程（调用方已 try/except，
  本模块内部也兜底）。
- **纯本地**：只写到与 config.json 同目录（打包后 ~/Library/Application Support），
  不上传、不联网。
- 仅记录「有 AI 原稿」的发送；纯手输（无原稿）不构成风格信号，跳过。
"""
from __future__ import annotations

import difflib
import json
import os
import sys
from datetime import datetime

try:
    from config import APP_SUPPORT_DIR, SCRIPT_DIR
except Exception:  # pragma: no cover - 极端情况下的兜底
    APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/WechatWorkSender")
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 与 config.json 一致：打包后写用户数据目录，开发期写源码目录
DRAFT_LOG_FILE = (
    os.path.join(APP_SUPPORT_DIR, "draft_diffs.jsonl")
    if getattr(sys, "frozen", False)
    else os.path.join(SCRIPT_DIR, "draft_diffs.jsonl")
)


def compute_diff(original: str, sent: str) -> dict:
    """计算原稿与实发文本的差异指标（纯函数，便于单测）。"""
    original = original or ""
    sent = sent or ""
    edited = original.strip() != sent.strip()
    ratio = difflib.SequenceMatcher(None, original, sent).ratio()
    return {
        "edited": edited,
        "similarity": round(ratio, 4),        # 1.0=未改动；越低改动越大
        "orig_len": len(original),
        "sent_len": len(sent),
        "len_delta": len(sent) - len(original),
    }


def log_draft_diff(
    original: str,
    sent: str,
    *,
    client_id: str = "",
    context_msgs: int = 0,
    source: str = "ai_reply",
) -> bool:
    """追加一条「原稿→实发」记录到本地 jsonl。返回是否写入成功（失败静默）。

    original 为空（无 AI 原稿）时跳过——纯手输不构成风格信号。
    """
    try:
        if not (original and original.strip()):
            return False
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "client_id": client_id,
            "context_msgs": context_msgs,
            "source": source,
            "original": original,
            "sent": sent,
            **compute_diff(original, sent),
        }
        os.makedirs(os.path.dirname(DRAFT_LOG_FILE), exist_ok=True)
        with open(DRAFT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False  # 绝不影响发送主流程
