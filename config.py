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
    # kb_mode: "none" | "local" | "cloud"
    # "local"  — 使用本地 Obsidian vault（FTS5 两级检索，需配置 kb_vault_path）
    # "cloud"  — 使用 hss-kb-serve-entry 云端知识库（需安装 hss-kb CLI）
    # "none"   — 不使用知识库
    "kb_mode": "none",
    "kb_scope": "",     # 云端模式的查询范围（服务名/模块名），可选
    # UI 密度："comfortable"（默认，间距宽松）| "compact"（紧凑，一屏多塞话术）
    "density": "comfortable",
    # 成功发送计数：免费用户每 10 次成功发送后提示一次「支持作者」
    "donation_send_count": 0,
    # 历史本机支持状态：保留兼容旧配置，但不再作为可信支付状态。
    "donation_profile": None,
    # 支付服务配置：客户端只保存服务地址、provider 偏好、安装标识和权益缓存。
    "payment_server_url": "http://127.0.0.1:8787",
    "payment_provider": "mock",
    "payment_default_amount_cents": 1000,
    "payment_install_id": "",
    "payment_entitlement_cache": None,
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
    """将 data 合并写入 config.json（原子写入，防止崩溃损坏文件）。"""
    current = load_config()
    current.update(data)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
