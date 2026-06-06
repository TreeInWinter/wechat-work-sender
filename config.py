# config.py
"""应用配置读写（config.json）。"""
from __future__ import annotations

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/WechatWorkSender")

CONFIG_FILE = (
    os.path.join(APP_SUPPORT_DIR, "config.json")
    if getattr(sys, "frozen", False)
    else os.path.join(SCRIPT_DIR, "config.json")
)

_DEFAULTS: dict = {
    "kb_enabled": False,
    "kb_vault_path": "",
}


def load_config() -> dict:
    """读取 config.json；文件不存在或损坏时返回默认值。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULTS)


def save_config(data: dict) -> None:
    """将 data 合并写入 config.json。"""
    current = load_config()
    current.update(data)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
