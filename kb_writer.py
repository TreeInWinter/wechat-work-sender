# kb_writer.py
"""将结构化回复条目写入 Obsidian vault。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class KBEntry:
    title: str
    scenario: str
    tags: list[str]
    reply: str
    source: str
    date: str  # YYYY-MM-DD


def _sanitize_filename(name: str) -> str:
    """移除文件名中不安全的字符。"""
    return re.sub(r'[\\/:*?"<>|\n\r]', "", name).strip() or "untitled"


def save_to_vault(entry: KBEntry, vault_path: str) -> str:
    """
    将 entry 写入 <vault_path>/IM回复记录/ 目录。
    文件名：YYYY-MM-DD-<title>.md
    同名冲突时自动追加 -HHmmss 后缀，不覆盖。
    返回最终写入文件的绝对路径。
    """
    folder = os.path.join(vault_path, "IM回复记录")
    os.makedirs(folder, exist_ok=True)

    safe_title = _sanitize_filename(entry.title)
    base = f"{entry.date}-{safe_title}"
    dest = os.path.join(folder, f"{base}.md")

    if os.path.exists(dest):
        suffix = datetime.now().strftime("%H%M%S")
        dest = os.path.join(folder, f"{base}-{suffix}.md")

    tags_str = "[" + ", ".join(entry.tags) + "]"
    content = (
        f"---\n"
        f"title: {entry.title}\n"
        f"date: {entry.date}\n"
        f"tags: {tags_str}\n"
        f"source: {entry.source}\n"
        f"---\n\n"
        f"## 适用场景\n"
        f"{entry.scenario}\n\n"
        f"## 标准回复\n"
        f"{entry.reply}\n"
    )

    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    return os.path.abspath(dest)
