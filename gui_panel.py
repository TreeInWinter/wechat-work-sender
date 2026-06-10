#!/usr/bin/env python3
"""
企业微信话术快捷发送面板 (macOS GUI)

依赖:
- customtkinter
- sender.py (同目录)
"""

import json
import math
import os
import subprocess
import threading
import re
import copy
import sys
from datetime import datetime

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, simpledialog
from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXValueGetValue,
    kAXWindowsAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    AXIsProcessTrusted,
)

from sender import NoChatWindowError
from im_clients.base import UnsupportedClientAction
from im_clients.registry import choose_default_client, discover_clients
from im_clients import probes
from ai_reply import (
    AICancelledError,
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
    CancelToken,
    REFINE_PRESETS,
    generate_reply,
    generate_reply_stream,
    refine_reply,
    extract_kb_entry,
)
from kb_writer import KBEntry, save_to_vault
from config import load_config, save_config
from draft_log import log_draft_diff

try:
    from kb_search import rebuild_index as _kb_rebuild, get_db_path as _kb_get_db_path
    import sqlite3 as _sqlite3
except ImportError:
    _kb_rebuild = None
    _kb_get_db_path = None
    _sqlite3 = None


# ── 系统权限探测 ────────────────────────────────────────────────
# 本工具依赖两类 macOS 隐私权限：
#   - 辅助功能（Accessibility）：所有 AX 客户端（企业微信/大象）发送、读取的根本依赖
#     → AXIsProcessTrusted()（已从 ApplicationServices 导入）
#   - 屏幕录制（Screen Recording）：微信 Qt 不透 AX，读取走截图 + Vision OCR，必需此权限
#     → Quartz.CGPreflightScreenCaptureAccess()（macOS 10.15+）
# 深链直跳系统设置对应面板，避免用户自己翻菜单。

# 系统设置深链（open x-apple.systempreferences:）
PREF_ACCESSIBILITY = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
PREF_SCREEN_CAPTURE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

try:
    from Quartz import (
        CGPreflightScreenCaptureAccess as _cg_preflight_screen,
        CGRequestScreenCaptureAccess as _cg_request_screen,
    )
except Exception:  # pragma: no cover - 旧系统或非 macOS
    _cg_preflight_screen = None
    _cg_request_screen = None


def has_accessibility_permission() -> bool:
    """辅助功能权限是否已授予。"""
    try:
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def has_screen_recording_permission() -> bool:
    """屏幕录制权限是否已授予。无法探测（旧系统）时乐观返回 True，不挡用户。"""
    if _cg_preflight_screen is None:
        return True
    try:
        return bool(_cg_preflight_screen())
    except Exception:
        return True


def request_screen_recording_permission() -> None:
    """触发系统屏幕录制授权弹窗（首次调用才会弹，已授予则无副作用）。"""
    if _cg_request_screen is not None:
        try:
            _cg_request_screen()
        except Exception:
            pass


def open_privacy_pane(deeplink: str) -> None:
    """打开系统设置的指定隐私面板。"""
    subprocess.run(["open", deeplink], check=False)


def _vault_is_indexed(vault_path: str) -> bool:
    """返回 True 当且仅当索引中已有属于 vault_path 的记录。"""
    if not _kb_get_db_path or not _sqlite3:
        return False
    try:
        db = _kb_get_db_path()
        if not os.path.exists(db):
            return False
        conn = _sqlite3.connect(db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM kb_meta WHERE path LIKE ?",
                (vault_path.rstrip("/") + "/%",),
            ).fetchone()[0]
            return n > 0
        finally:
            conn.close()
    except Exception:
        return False

# ── 配色令牌（轻量中性 + 靛蓝 Indigo）─────────────────────────────
# 设计方向：去高饱和蓝标题栏，改近白/浅灰表面 + 1px 细边框，强调色只用在
# 主操作；IM 选择器等控件降为低调中性，标题栏不再与白色控件打架。

# 强调色（收敛蓝，对齐交互稿 v2 视觉 token）
PRIMARY    = "#2B5CE6"   # 主按钮 / 选中态 / 链接
PRIMARY_H  = "#1E47C0"   # hover / 按下
ACCENT_SOFT = "#EAF0FD"  # 极浅蓝底（选中卡片 / 浅强调 hover）

# 中性表面 / 边框
APP_BG     = "#F7F8FA"   # 应用背景
SURFACE    = "#FFFFFF"   # 卡片 / 输入面
HEADER_BG  = "#FFFFFF"   # 标题栏（近白，不再用强调色）
BORDER     = "#E5E7EB"   # 细边框 / 分隔线
PILL_BG    = "#F0F1F4"   # IM 选择器等胶囊底
PILL_HOVER = "#E6E8EC"

# 兼容旧引用（全局散落）：选中卡片底 / 面板底
CARD_BG   = ACCENT_SOFT  # 选中卡片背景（旧名保留）
PANEL_BG  = "#F7F8FA"    # 面板背景

# 状态色（spec v2：检测中=中性灰，不是警告）
DOT_OK    = "#34C759"
DOT_ERR   = "#FF3B30"
DOT_WAIT  = "#8F959E"

# 文字三级（对齐交互稿 v2 视觉 token）
TEXT_MAIN = "#1F2329"   # 主文字
TEXT_SUB  = "#646A73"   # 次文字
TEXT_WEAK = "#8F959E"   # 弱文字

ctk.set_appearance_mode("light")    # 轻量中性方向：锁定浅色，不跟随系统深色
ctk.set_default_color_theme("blue")

# ============================================================
# 话术数据管理
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/WechatWorkSender")
DEFAULT_DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")
DATA_FILE = os.path.join(APP_SUPPORT_DIR, "phrases.json") if getattr(sys, "frozen", False) else DEFAULT_DATA_FILE

VARIABLE_PATTERN = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")
SYSTEM_VARIABLES = {
    "日期": lambda: datetime.now().strftime("%Y-%m-%d"),
    "时间": lambda: datetime.now().strftime("%H:%M"),
    "星期": lambda: "一二三四五六日"[datetime.now().weekday()],
}

# 默认话术库
DEFAULT_PHRASES = {
    "问候语": [
        "您好，我是您的专属客服，请问有什么可以帮您？",
        "您好，感谢您的耐心等待，现在为您处理。",
        "早上好！有什么需要帮助的吗？",
    ],
    "常用回复": [
        "好的，我这边帮您查一下，请稍等。",
        "已收到您的反馈，我们会尽快处理。",
        "非常抱歉给您带来不便，我们马上为您解决。",
        "感谢您的理解与支持！",
    ],
    "结束语": [
        "还有其他问题吗？如果没有的话，祝您生活愉快！",
        "问题已解决，如有其他需要随时联系我们。",
        "感谢咨询，再见！",
    ],
}


_wechat_ax = None  # 缓存 AXUIElement，避免每次重新查 PID


def get_wechat_window_bounds() -> tuple | None:
    """通过 Accessibility API 直接读取企业微信窗口坐标，无 subprocess 开销"""
    global _wechat_ax
    try:
        if _wechat_ax is None:
            apps = NSWorkspace.sharedWorkspace().runningApplications()
            pid = next((a.processIdentifier() for a in apps if a.localizedName() == "企业微信"), None)
            if pid is None:
                return None
            _wechat_ax = AXUIElementCreateApplication(pid)

        _, windows = AXUIElementCopyAttributeValue(_wechat_ax, kAXWindowsAttribute, None)
        if not windows:
            return None
        win = windows[0]
        _, pos_ref  = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
        _, size_ref = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
        _, pt = AXValueGetValue(pos_ref,  kAXValueCGPointType, None)
        _, sz = AXValueGetValue(size_ref, kAXValueCGSizeType,  None)
        return (int(pt.x), int(pt.y), int(sz.width), int(sz.height))
    except Exception:
        _wechat_ax = None  # 进程重启后重新获取
        return None


def load_phrases() -> dict:
    """加载话术库"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    if DATA_FILE != DEFAULT_DATA_FILE and os.path.exists(DEFAULT_DATA_FILE):
        try:
            with open(DEFAULT_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_PHRASES.copy()


def save_phrases(phrases: dict):
    """保存话术库"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(phrases, f, ensure_ascii=False, indent=2)


def normalize_phrase(phrase) -> list:
    """将话术值统一转换为 Block 列表（兼容旧纯字符串）。
    str  → [{"type": "text", "content": str}]
    list → list (原样返回，跳过非 dict 项)
    """
    if phrase is None:
        return []
    if isinstance(phrase, str):
        return [{"type": "text", "content": phrase}]
    return [b for b in phrase if isinstance(b, dict)]


def phrase_preview_text(phrase) -> str:
    """返回用于卡片展示的纯文本摘要（去换行，图片块替换为 🖼）。"""
    parts = []
    for block in normalize_phrase(phrase):
        if block.get("type") == "text" and block.get("content", "").strip():
            parts.append(block["content"].replace("\n", " ").strip())
        elif block.get("type") == "image":
            parts.append("🖼")
    return "  ".join(p for p in parts if p)


def has_images(phrase) -> bool:
    """话术中是否含有图片块。"""
    return any(b.get("type") == "image" for b in normalize_phrase(phrase))


def phrase_full_text(phrase) -> str:
    """返回话术的完整文本（多个文本块按换行拼接，忽略图片块）。

    用于「插入草稿台」：保留原始换行（区别于 phrase_preview_text 的去换行摘要）。
    """
    parts = []
    for block in normalize_phrase(phrase):
        if block.get("type") == "text" and block.get("content", "").strip():
            parts.append(block["content"].rstrip())
    return "\n".join(parts)


def extract_variables(blocks: list) -> list[str]:
    """按出现顺序提取 {{变量名}} 占位符，内置日期/时间变量不要求用户填写。"""
    seen = set()
    names = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        for name in VARIABLE_PATTERN.findall(block.get("content", "")):
            if name in SYSTEM_VARIABLES or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def render_template_text(text: str, values: dict[str, str]) -> str:
    """替换文本中的 {{变量名}}。未填写的变量保留原样，避免误删内容。"""
    def repl(match):
        name = match.group(1).strip()
        if name in SYSTEM_VARIABLES:
            return SYSTEM_VARIABLES[name]()
        value = values.get(name, "")
        return value if value else match.group(0)

    return VARIABLE_PATTERN.sub(repl, text)


def render_template_blocks(blocks: list, values: dict[str, str]) -> list:
    """返回替换变量后的 blocks 副本。"""
    rendered = copy.deepcopy(blocks)
    for block in rendered:
        if block.get("type") == "text":
            block["content"] = render_template_text(block.get("content", ""), values)
    return rendered


def prepare_direct_send_blocks(blocks: list) -> list:
    """主界面直接发送前渲染内置变量，不弹出发送预览。"""
    return render_template_blocks(blocks, {})


def send_blocks_with_client(client, blocks: list) -> bool:
    """通过当前接管对象发送话术块。"""
    if client is None:
        raise UnsupportedClientAction("请先选择接管对象")
    return client.adapter.send_blocks(blocks)


def read_chat_with_client(client, max_messages: int = 20) -> list[dict]:
    """通过当前接管对象读取聊天内容。"""
    if client is None:
        raise UnsupportedClientAction("请先选择接管对象")
    return client.adapter.read_chat_messages(max_messages=max_messages)


def make_thumbnail(path: str, size: tuple = (72, 54)):
    """用 Pillow 生成 CTkImage 缩略图。加载失败返回 None。"""
    try:
        if not path or not isinstance(path, str):
            return None
        from PIL import Image as PILImage
        expanded = os.path.expanduser(path)
        if not os.path.exists(expanded):
            return None
        img = PILImage.open(expanded)
        img.thumbnail((size[0] * 3, size[1] * 3), PILImage.LANCZOS)
        w, h = img.size
        tw, th = size
        left = max(0, (w - tw) // 2)
        top  = max(0, (h - th) // 2)
        img = img.crop((left, top, left + min(w, tw), top + min(h, th)))
        new = PILImage.new("RGBA", size, (240, 244, 255, 255))
        img_rgba = img.convert("RGBA") if img.mode != "RGBA" else img
        new.paste(img_rgba, ((tw - img_rgba.width) // 2, (th - img_rgba.height) // 2))
        return ctk.CTkImage(light_image=new, dark_image=new, size=size)
    except Exception:
        return None


# ============================================================
# 块编辑器
# ============================================================

class BlockEditor(ctk.CTkToplevel):
    """WYSIWYG 内联画布话术编辑器：文字块直接编辑，图片块显示缩略图。"""

    TEXT_LABEL_BG     = ACCENT_SOFT
    IMAGE_LABEL_BG    = "#fff8f0"
    INACTIVE_LABEL_BG = "#f8f8f8"

    def __init__(self, parent, initial_phrase=None):
        super().__init__(parent)
        self.title("编辑话术")
        self.geometry("520x500")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._result      = None
        self._active_idx  = 0
        self._text_widgets: dict = {}   # {block_index: CTkTextbox}

        if initial_phrase is None:
            self.blocks = [{"type": "text", "content": ""}]
        elif isinstance(initial_phrase, str):
            self.blocks = [{"type": "text", "content": initial_phrase}]
        else:
            self.blocks = copy.deepcopy(initial_phrase)

        self._build()
        self.grab_set()
        self.after(120, self._focus_active_textbox)

    # ── 构建固定框架 ─────────────────────────────────────────

    def _build(self):
        # 标题栏
        header = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="编辑话术", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            header, text="确认", width=60, height=28, corner_radius=6,
            fg_color="white", text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._confirm,
        ).pack(side="right", padx=(4, 10))

        ctk.CTkButton(
            header, text="取消", width=60, height=28, corner_radius=6,
            fg_color="transparent", text_color="white", hover_color=PRIMARY_H,
            border_width=1, border_color="#4a9eff",
            font=ctk.CTkFont(size=12),
            command=self.destroy,
        ).pack(side="right")

        # 可滚动画布
        self._canvas = ctk.CTkScrollableFrame(
            self, fg_color=APP_BG, corner_radius=0
        )
        self._canvas.pack(fill="both", expand=True)

        # 底部添加按钮栏
        add_bar = ctk.CTkFrame(self, fg_color="white", height=52, corner_radius=0)
        add_bar.pack(fill="x")
        add_bar.pack_propagate(False)

        inner = ctk.CTkFrame(add_bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=8)
        inner.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            inner, text="＋ 添加文字", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#C7D7F8",
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=11),
            command=self._add_text,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        ctk.CTkButton(
            inner, text="＋ 添加图片", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#ffd591",
            text_color="#fa8c16", hover_color="#fff8f0",
            font=ctk.CTkFont(size=11),
            command=self._add_image,
        ).grid(row=0, column=1, padx=4, sticky="ew")

        ctk.CTkButton(
            inner, text="{{变量}}", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#555", hover_color="#f0f0f0",
            font=ctk.CTkFont(size=11),
            command=self._insert_variable,
        ).grid(row=0, column=2, padx=(4, 0), sticky="ew")

        self._render_all()

    # ── 渲染 ─────────────────────────────────────────────────

    def _render_all(self):
        self._sync_all_texts()
        for w in self._canvas.winfo_children():
            w.destroy()
        self._text_widgets = {}
        for i, block in enumerate(self.blocks):
            self._render_block(i, block)

    def _render_block(self, i: int, block: dict):
        active  = (i == self._active_idx)
        b_color = PRIMARY if active else "#e8e8e8"
        b_width = 2 if active else 1

        outer = ctk.CTkFrame(
            self._canvas, corner_radius=10, fg_color="white",
            border_color=b_color, border_width=b_width,
        )
        outer.pack(fill="x", padx=12, pady=(0, 7))

        # 标签条
        if block["type"] == "text":
            lbg    = self.TEXT_LABEL_BG if active else self.INACTIVE_LABEL_BG
            lcolor = PRIMARY if active else "#999"
            ltxt   = "文字"
        else:
            lbg    = self.IMAGE_LABEL_BG
            lcolor = "#fa8c16"
            ltxt   = "图片"

        label_bar = ctk.CTkFrame(outer, fg_color=lbg, corner_radius=0, height=24)
        label_bar.pack(fill="x")
        label_bar.pack_propagate(False)

        ctk.CTkLabel(
            label_bar, text=ltxt, text_color=lcolor,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=8)

        # 控制按钮
        btn_area = ctk.CTkFrame(label_bar, fg_color="transparent")
        btn_area.pack(side="right", padx=4)

        if i > 0:
            ctk.CTkButton(
                btn_area, text="↑", width=20, height=18, corner_radius=4,
                fg_color="transparent", text_color="#aaa", hover_color="#f0f0f0",
                font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._move(idx, -1),
            ).pack(side="left", padx=1)

        if i < len(self.blocks) - 1:
            ctk.CTkButton(
                btn_area, text="↓", width=20, height=18, corner_radius=4,
                fg_color="transparent", text_color="#aaa", hover_color="#f0f0f0",
                font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._move(idx, 1),
            ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_area, text="🗑", width=20, height=18, corner_radius=4,
            fg_color="transparent", text_color="#ff4d4f", hover_color="#fff0f0",
            font=ctk.CTkFont(size=11),
            command=lambda idx=i: self._delete(idx),
        ).pack(side="left", padx=(1, 4))

        # 内容区
        if block["type"] == "text":
            tb = ctk.CTkTextbox(
                outer, height=72, corner_radius=0, border_width=0,
                font=ctk.CTkFont(family="PingFang SC", size=12),
            )
            tb.pack(fill="x", padx=10, pady=(6, 10))
            tb.insert("end", block.get("content", ""))
            tb.bind("<FocusIn>",  lambda e, idx=i: self._on_focus_in(idx))
            tb.bind("<FocusOut>", lambda e, idx=i, w=tb: self._on_focus_out(idx, w))
            self._text_widgets[i] = tb
        else:
            self._render_image_content(outer, i, block)

    def _render_image_content(self, parent, i: int, block: dict):
        path = block.get("path", "")
        row  = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)

        # 缩略图
        thumb = make_thumbnail(path) if path else None
        if thumb:
            ctk.CTkLabel(row, image=thumb, text="", width=72, height=54).pack(
                side="left", padx=(0, 10)
            )
        else:
            ctk.CTkLabel(
                row, text="🖼", font=ctk.CTkFont(size=24),
                width=72, height=54, fg_color="#e0eeff", corner_radius=6,
                text_color="#7ba8e0",
            ).pack(side="left", padx=(0, 10))

        # 信息列
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        name = os.path.basename(path) if path else "（未选择）"
        ctk.CTkLabel(
            info, text=name, anchor="w",
            font=ctk.CTkFont(family="PingFang SC", size=11, weight="bold"),
            text_color="#333",
        ).pack(anchor="w")

        expanded = os.path.expanduser(path) if path else ""
        if expanded and os.path.exists(expanded):
            try:
                sz = os.path.getsize(expanded)
                size_str = f"{sz // 1024} KB" if sz >= 1024 else f"{sz} B"
                ctk.CTkLabel(
                    info, text=size_str, anchor="w",
                    font=ctk.CTkFont(size=10), text_color="#999",
                ).pack(anchor="w")
            except Exception:
                pass

        ctk.CTkButton(
            info, text="替换图片", width=60, height=20, corner_radius=4,
            fg_color="transparent", text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=10),
            command=lambda idx=i: self._replace_image(idx),
        ).pack(anchor="w", pady=(4, 0))

    # ── 事件处理 ─────────────────────────────────────────────

    def _focus_active_textbox(self):
        tb = self._text_widgets.get(self._active_idx)
        if tb:
            tb.focus_set()

    def _sync_all_texts(self):
        """将所有 CTkTextbox 内容同步回 self.blocks。"""
        for i, tb in self._text_widgets.items():
            if i < len(self.blocks) and self.blocks[i]["type"] == "text":
                try:
                    self.blocks[i]["content"] = tb.get("1.0", "end").strip()
                except Exception:
                    pass

    def _on_focus_in(self, idx: int):
        if self._active_idx != idx:
            self._active_idx = idx
            self._render_all()
            self.after(50, self._focus_active_textbox)  # 重建后恢复焦点

    def _on_focus_out(self, idx: int, tb: ctk.CTkTextbox):
        if idx < len(self.blocks) and self.blocks[idx]["type"] == "text":
            try:
                self.blocks[idx]["content"] = tb.get("1.0", "end").strip()
            except Exception:
                pass

    def _move(self, i: int, direction: int):
        self._sync_all_texts()
        j = i + direction
        if 0 <= j < len(self.blocks):
            self.blocks[i], self.blocks[j] = self.blocks[j], self.blocks[i]
            self._active_idx = j
        self._render_all()

    def _delete(self, i: int):
        self._sync_all_texts()
        self.blocks.pop(i)
        self._active_idx = min(self._active_idx, max(0, len(self.blocks) - 1))
        self._render_all()

    def _add_text(self):
        self._sync_all_texts()
        self.blocks.append({"type": "text", "content": ""})
        self._active_idx = len(self.blocks) - 1
        self._render_all()
        self.after(80, self._focus_active_textbox)

    def _add_image(self):
        from tkinter import filedialog
        self._sync_all_texts()
        path = filedialog.askopenfilename(
            parent=self,
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks.append({"type": "image", "path": path})
            self._active_idx = len(self.blocks) - 1
            self._render_all()

    def _insert_variable(self):
        dialog = ctk.CTkInputDialog(
            text="输入变量名，例如：客户名、订单号、日期、时间、星期",
            title="插入变量",
        )
        name = dialog.get_input()
        if not name or not name.strip():
            return
        token = "{{" + name.strip() + "}}"
        tb = self._text_widgets.get(self._active_idx)
        if not tb:
            self._sync_all_texts()
            self.blocks.append({"type": "text", "content": token})
            self._active_idx = len(self.blocks) - 1
            self._render_all()
            return
        try:
            tb.insert("insert", token)
            self.blocks[self._active_idx]["content"] = tb.get("1.0", "end").strip()
        except Exception:
            pass

    def _replace_image(self, i: int):
        from tkinter import filedialog
        self._sync_all_texts()
        path = filedialog.askopenfilename(
            parent=self,
            title="替换图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks[i]["path"] = path
            self._active_idx = i
            self._render_all()

    def _confirm(self):
        self._sync_all_texts()
        result = [
            b for b in self.blocks
            if (b["type"] == "text" and b.get("content", "").strip())
            or b["type"] == "image"
        ]
        if not result:
            return
        self._result = result
        self.destroy()

    def get_result(self):
        """等待对话框关闭，返回 blocks 列表或 None（取消时）。"""
        self.wait_window()
        return self._result


# ============================================================
# 话术卡片组件
# ============================================================

class PhraseCard(ctk.CTkFrame):
    """单条话术卡片：左侧文本 + 右侧发送按钮"""

    NORMAL_BG      = "white"
    SELECTED_BG    = ACCENT_SOFT
    SELECTED_BORDER = "#C7D7F8"

    def __init__(self, parent, phrase, on_send, on_select, on_edit=None, index: int | None = None,
                 density: str = "comfortable", on_insert=None, **kwargs):
        super().__init__(parent, corner_radius=10, fg_color=self.NORMAL_BG,
                         border_width=1, border_color="#e8e8e8", **kwargs)
        self._phrase = phrase
        self._on_send = on_send
        self._on_select = on_select
        self._on_edit = on_edit
        self._on_insert = on_insert
        self._index = index
        self._density = density
        self._selected = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        # 密度：紧凑模式缩小卡片内边距，一屏多塞 2-3 条话术
        pad_y = 4 if self._density == "compact" else 8

        preview = phrase_preview_text(self._phrase)
        has_img = has_images(self._phrase)

        prefix = f"{self._index}. " if self._index is not None else ""
        self._label = ctk.CTkLabel(
            self,
            text=prefix + ("🖼 " if has_img else "") + preview,
            wraplength=200,
            justify="left", anchor="w",
            text_color="#333",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        self._label.grid(row=0, column=0, padx=(10, 4), pady=pad_y, sticky="ew")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=(0, 6), pady=pad_y)

        if self._on_edit:
            ctk.CTkButton(
                btn_frame, text="编辑", width=36, height=22,
                corner_radius=4, fg_color="transparent",
                border_width=1, border_color="#d9d9d9",
                text_color="#888", hover_color="#f0f0f0",
                font=ctk.CTkFont(size=10),
                command=self._on_edit,
            ).pack(side="top", pady=(0, 3))

        if self._on_insert:
            ctk.CTkButton(
                btn_frame, text="插入", width=44, height=22,
                corner_radius=4, fg_color="transparent",
                border_width=1, border_color=BORDER,
                text_color=PRIMARY, hover_color=CARD_BG,
                font=ctk.CTkFont(size=10),
                command=self._on_insert,
            ).pack(side="top", pady=(0, 3))

        self._send_btn = ctk.CTkButton(
            btn_frame, text="发送", width=44, height=26,
            corner_radius=6, fg_color=CARD_BG,
            text_color=PRIMARY, hover_color="#C7D7F8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_send,
        )
        self._send_btn.pack(side="top")

        self._label.bind("<Button-1>", lambda e: self._on_select(self))
        self.bind("<Button-1>", lambda e: self._on_select(self))

    @property
    def text(self) -> str:
        """纯文本摘要（向后兼容）。"""
        return phrase_preview_text(self._phrase)

    @property
    def phrase(self):
        """原始话术值（str 或 list of blocks）。"""
        return self._phrase

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.configure(fg_color=self.SELECTED_BG, border_color=self.SELECTED_BORDER)
            self._label.configure(text_color=PRIMARY)
            self._send_btn.configure(fg_color=PRIMARY, text_color="white",
                                      hover_color=PRIMARY_H)
        else:
            self.configure(fg_color=self.NORMAL_BG, border_color="#e8e8e8")
            self._label.configure(text_color="#333")
            self._send_btn.configure(fg_color=CARD_BG, text_color=PRIMARY,
                                      hover_color="#C7D7F8")


# ============================================================
# GUI 应用
# ============================================================

class WXSenderApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("企业微信快捷发送")
        self.root.configure(fg_color=APP_BG)   # 中性表面背景
        self.root.attributes("-topmost", True)
        # 宽度锁死（保持贴靠对齐），高度允许用户自由拉伸——解决 420×600 固定高度长期紧张。
        self.root.resizable(False, True)
        # 吸附开关：True=跟随目标窗口右缘（默认）；False=脱离吸附，可拖到第二屏常驻。
        self._snap_enabled = True

        self.phrases = load_phrases()
        self.current_group = list(self.phrases.keys())[0] if self.phrases else ""
        self._selected_card = None  # 当前选中的卡片
        self._visible_phrases = []
        self._search_after_id = None
        self.mode_var = ctk.StringVar(value="phrases")
        self._ai_messages = []
        self._ai_origin_draft = ""   # 本轮 AI 首次生成的原稿，用于发送时对比沉淀 diff
        self._ai_generating = False
        self._ai_kb_capturing = False
        self._ai_anim_running = False
        self._ai_anim_tick = 0
        self._app_config = load_config()
        self._density = self._app_config.get("density", "comfortable")  # UI 密度
        self.clients = discover_clients()
        self.current_client = choose_default_client(self.clients)
        self._client_label_to_id = {}
        self.target_var = ctk.StringVar(value="")

        bounds = self._current_window_bounds()
        if bounds:
            wx, wy, ww, wh = bounds
            self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
        else:
            self.root.geometry("420x600")
        self._last_bounds = bounds
        self._snap_threshold = 4      # 位置变化小于此值时不触发 geometry()（防 IME 抖动）
        self._snap_max_delta = 300    # 单次跳变超过此值则认为 AX 数据异常，直接丢弃

        self._build_ui()
        self._bind_shortcuts()
        self.root.after(100, self._poll_snap)
        # 启动后延迟做一次被动自检（不抢焦点），提示权限/窗口类问题
        self.root.after(1200, self._startup_self_check)

    def _build_ui(self):
        # ── 状态栏（近白表面 + 底部 1px 细边框，不再用强调色铺底）──
        status_frame = ctk.CTkFrame(self.root, height=50, corner_radius=0, fg_color=HEADER_BG)
        status_frame.pack(fill="x")
        status_frame.pack_propagate(False)

        left = ctk.CTkFrame(status_frame, fg_color="transparent")
        left.pack(side="left", padx=14, pady=12)

        self.status_dot = ctk.CTkLabel(left, text="●", text_color=DOT_WAIT,
                                        font=ctk.CTkFont(size=11), width=14)
        self.status_dot.pack(side="left")

        self.status_label = ctk.CTkLabel(left, text="检测中...",
                                          text_color=TEXT_MAIN,
                                          font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"))
        self.status_label.pack(side="left", padx=(5, 0))

        # ── 右侧：折叠菜单 + 吸附开关 + IM 选择器 ──
        # 标题栏改近白后，按钮/控件全部降为中性灰，不再白字幽灵。
        self.menu_btn = ctk.CTkButton(
            status_frame, text="⋯", width=34, height=30,
            corner_radius=8, fg_color="transparent",
            hover_color=PILL_HOVER, text_color=TEXT_SUB,
            font=ctk.CTkFont(size=20, weight="bold"),
            command=self._show_overflow_menu,
        )
        self.menu_btn.pack(side="right", padx=(2, 10))

        # 吸附/脱离开关：按钮文字即「下一步动作」——吸附时显示「脱离」，脱离时显示「吸附」
        self.snap_btn = ctk.CTkButton(
            status_frame, text="脱离", width=44, height=30,
            corner_radius=8, fg_color="transparent",
            hover_color=PILL_HOVER, text_color=TEXT_SUB,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._toggle_snap,
        )
        self.snap_btn.pack(side="right", padx=(0, 2))

        # IM 选择器：低调浅灰胶囊，融入近白标题栏（不再是白盒压饱和蓝）
        self.target_menu = ctk.CTkOptionMenu(
            status_frame,
            values=["检测中"],
            variable=self.target_var,
            width=130,
            height=30,
            corner_radius=8,
            fg_color=PILL_BG,
            button_color=PILL_BG,
            button_hover_color=PILL_HOVER,
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            dropdown_fg_color=SURFACE,
            dropdown_text_color=TEXT_MAIN,
            dropdown_hover_color=ACCENT_SOFT,
            dropdown_font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._on_target_change,
        )
        self.target_menu.pack(side="right", padx=(0, 4))
        self._refresh_client_menu()

        # 标题栏底部 1px 细分隔线
        ctk.CTkFrame(self.root, height=1, corner_radius=0, fg_color=BORDER).pack(fill="x")

        # ── 模式切换 ──
        self.mode_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.mode_frame.pack(fill="x", padx=12, pady=(10, 4))
        self.mode_frame.grid_columnconfigure((0, 1), weight=1)

        self.phrase_mode_btn = ctk.CTkButton(
            self.mode_frame, text="话术", height=30, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=lambda: self._switch_mode("phrases"),
        )
        self.phrase_mode_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.ai_mode_btn = ctk.CTkButton(
            self.mode_frame, text="AI 助手", height=30, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(family="PingFang SC", size=12),
            command=lambda: self._switch_mode("ai"),
        )
        self.ai_mode_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.phrase_view = ctk.CTkFrame(self.root, fg_color="transparent")
        self.phrase_view.pack(fill="both", expand=True)

        # ── 分组选择 ──
        group_frame = ctk.CTkFrame(self.phrase_view, fg_color="transparent")
        group_frame.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(group_frame, text="分组",
                      text_color="gray", font=ctk.CTkFont(size=11)).pack(side="left")

        self.group_var = ctk.StringVar(value=self.current_group)
        self.group_menu = ctk.CTkOptionMenu(
            group_frame,
            values=list(self.phrases.keys()),
            variable=self.group_var,
            width=120, height=28, corner_radius=8,
            fg_color="white", button_color=PRIMARY,
            text_color="#333",
            command=self._on_group_change,
        )
        self.group_menu.pack(side="left", padx=(6, 0))

        # 分组管理：新增 / 改名 / 删除（side=right 先 pack 者靠最右）
        ctk.CTkButton(group_frame, text="＋", width=32, height=28,
                       corner_radius=8, fg_color="transparent",
                       border_width=1, border_color=PRIMARY,
                       text_color=PRIMARY, hover_color=CARD_BG,
                       font=ctk.CTkFont(size=13),
                       command=self._add_group).pack(side="right", padx=(4, 0))

        ctk.CTkButton(group_frame, text="改名", width=44, height=28,
                       corner_radius=8, fg_color="transparent",
                       border_width=1, border_color="#d9d9d9",
                       text_color="#666", hover_color="#f0f0f0",
                       font=ctk.CTkFont(size=11),
                       command=self._rename_group).pack(side="right", padx=(4, 0))

        ctk.CTkButton(group_frame, text="删除", width=44, height=28,
                       corner_radius=8, fg_color="transparent",
                       border_width=1, border_color="#ffe0e0",
                       text_color="#ff4d4f", hover_color="#fff0f0",
                       font=ctk.CTkFont(size=11),
                       command=self._delete_group).pack(side="right", padx=(4, 0))

        # ── 搜索 ──
        search_frame = ctk.CTkFrame(self.phrase_view, fg_color="transparent")
        search_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.search_var,
            height=30,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
            placeholder_text="搜索当前分组话术",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_var.trace_add("write", self._on_search_change)
        ctk.CTkButton(
            search_frame, text="清空", width=48, height=30, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666", hover_color="#f0f0f0",
            font=ctk.CTkFont(size=11),
            command=self._clear_search,
        ).pack(side="right", padx=(6, 0))

        # ── 话术卡片列表 ──
        self.cards_frame = ctk.CTkScrollableFrame(
            self.phrase_view, fg_color=PANEL_BG, corner_radius=0,
            scrollbar_button_color=PRIMARY,
            scrollbar_button_hover_color=PRIMARY_H,
        )
        self.cards_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.cards_frame.grid_columnconfigure(0, weight=1)

        # ── 操作按钮 ──
        btn_frame = ctk.CTkFrame(self.phrase_view, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 6))
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_frame, text="➕ 添加话术", height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#555", hover_color="#f0f0f0",
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._add_phrase,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        ctk.CTkButton(
            btn_frame, text="🗑️ 删除选中", height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#ffe0e0",
            text_color="#ff4d4f", hover_color="#fff0f0",
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._delete_phrase,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # ── 分隔线 ──
        ctk.CTkFrame(self.phrase_view, height=1, fg_color=BORDER, corner_radius=0).pack(
            fill="x", padx=12, pady=(2, 8))

        # ── 自定义消息 ──
        bottom_frame = ctk.CTkFrame(self.phrase_view, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=12, pady=(0, 10))

        self.custom_input = ctk.CTkTextbox(
            bottom_frame, height=60, corner_radius=10,
            border_width=1, border_color=BORDER,
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        self.custom_input.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            bottom_frame, text="发送自定义消息", height=36, corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=self._send_custom,
        ).pack(fill="x")

        # 读取聊天内容统一走「AI 助手 → 读取并生成」入口（话术页不再单设读取按钮）

        self.ai_view = ctk.CTkFrame(self.root, fg_color="transparent")
        self._build_ai_view()

        # ── 初始化 ──
        self._refresh_cards()
        self._check_status()
        # 草稿台升为默认主界面（spec v2：草稿台即主界面）。
        # 话术仍可经顶部「话术」切换进入（话术抽屉化为独立任务，暂保留切换入口）。
        self._switch_mode("ai")

    def _refresh_client_menu(self):
        selected_id = self.current_client.client_id if self.current_client else None
        self.clients = discover_clients()
        if selected_id:
            self.current_client = next(
                (client for client in self.clients if client.client_id == selected_id),
                None,
            )
        if self.current_client is None:
            self.current_client = choose_default_client(self.clients)

        self._client_label_to_id = {client.menu_label: client.client_id for client in self.clients}
        labels = list(self._client_label_to_id.keys()) or ["无可用对象"]
        self.target_menu.configure(values=labels)
        if self.current_client:
            self.target_var.set(self.current_client.menu_label)
        elif labels:
            self.target_var.set(labels[0])

    def _on_target_change(self, label: str):
        client_id = self._client_label_to_id.get(label)
        if not client_id:
            return
        self.current_client = next(
            (client for client in self.clients if client.client_id == client_id),
            self.current_client,
        )
        self._last_bounds = None
        self._check_status()

    def _refresh_targets_and_status(self):
        self._refresh_client_menu()
        self._check_status()

    def _show_overflow_menu(self):
        """折叠菜单：把刷新/设置/权限/自检等低频操作收进下拉，给状态栏腾空间。"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="刷新状态与接管对象", command=self._refresh_targets_and_status)
        menu.add_separator()
        menu.add_command(label="AI / 知识库设置…", command=self._show_ai_settings)
        density_label = "切换为紧凑布局" if self._density == "comfortable" else "切换为舒适布局"
        menu.add_command(label=density_label, command=self._toggle_density)
        menu.add_command(label="权限引导…", command=self._show_permission_guide)
        menu.add_command(label="AX 结构自检", command=self._run_self_check_async)
        menu.add_separator()
        menu.add_command(
            label="快捷键：⌘F 搜索 · ⌘↩ 发送自定义 · ⌘1-9 发送话术 · Esc 清空",
            state="disabled",
        )
        try:
            x = self.menu_btn.winfo_rootx()
            y = self.menu_btn.winfo_rooty() + self.menu_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _toggle_density(self):
        """在舒适 / 紧凑布局间切换，持久化到 config 并立即重排话术卡片。"""
        self._density = "compact" if self._density == "comfortable" else "comfortable"
        self._app_config["density"] = self._density
        try:
            save_config(self._app_config)
        except Exception:
            pass
        self._refresh_cards()

    def _current_window_bounds(self) -> tuple | None:
        if not self.current_client:
            return None
        return self.current_client.adapter.window_bounds()

    def _current_client_name(self) -> str:
        return self.current_client.display_name if self.current_client else "当前接管对象"

    def _switch_mode(self, mode: str):
        self.mode_var.set(mode)
        if mode == "ai":
            self.phrase_view.pack_forget()
            self.ai_view.pack(fill="both", expand=True)
            self.phrase_mode_btn.configure(
                fg_color="transparent", border_width=1, border_color=BORDER,
                text_color=PRIMARY, hover_color=CARD_BG,
                font=ctk.CTkFont(family="PingFang SC", size=12),
            )
            self.ai_mode_btn.configure(
                fg_color=PRIMARY, border_width=0, text_color="white",
                hover_color=PRIMARY_H,
                font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            )
        else:
            self.ai_view.pack_forget()
            self.phrase_view.pack(fill="both", expand=True)
            self.phrase_mode_btn.configure(
                fg_color=PRIMARY, border_width=0, text_color="white",
                hover_color=PRIMARY_H,
                font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            )
            self.ai_mode_btn.configure(
                fg_color="transparent", border_width=1, border_color=BORDER,
                text_color=PRIMARY, hover_color=CARD_BG,
                font=ctk.CTkFont(family="PingFang SC", size=12),
            )

    def _ai_overflow_menu(self):
        """草稿台底部 ⋯ 溢出菜单：低频项（复制 / 存入知识库 / 清空）。"""
        has_draft = bool(self.ai_reply_box.get("1.0", "end").strip())
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="复制草稿", command=self._ai_copy_reply,
                         state=("normal" if has_draft else "disabled"))
        menu.add_command(label="存入知识库…", command=self._ai_kb_capture_async,
                         state=("normal" if has_draft else "disabled"))
        menu.add_separator()
        menu.add_command(label="清空草稿", command=self._ai_clear_reply,
                         state=("normal" if has_draft else "disabled"))
        try:
            x = self.ai_overflow_btn.winfo_rootx()
            y = self.ai_overflow_btn.winfo_rooty() + self.ai_overflow_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _build_ai_view(self):
        action_frame = ctk.CTkFrame(self.ai_view, fg_color="transparent")
        action_frame.pack(fill="x", padx=12, pady=(8, 6))
        action_frame.grid_columnconfigure((0, 1), weight=1)

        self.ai_generate_btn = ctk.CTkButton(
            action_frame, text="读取并生成", height=34, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=self._ai_read_and_generate,
        )
        self.ai_generate_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.ai_regenerate_btn = ctk.CTkButton(
            action_frame, text="重新生成", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(family="PingFang SC", size=12),
            command=self._ai_regenerate,
        )
        self.ai_regenerate_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # ── 知识库状态行 ──
        self.kb_row = ctk.CTkFrame(
            self.ai_view, corner_radius=6, border_width=1,
            fg_color="#fafafa", border_color="#e8e8e8",
        )
        self.kb_row.pack(fill="x", padx=12, pady=(0, 4))
        self.kb_row.pack_propagate(False)
        self.kb_row.configure(height=26)

        self.kb_row_label = ctk.CTkLabel(
            self.kb_row, text="📂 知识库未启用 — 点击设置",
            text_color="#aaa", anchor="w",
            font=ctk.CTkFont(family="PingFang SC", size=11),
        )
        self.kb_row_label.pack(side="left", padx=8)

        self.kb_row.bind("<Button-1>", lambda e: self._show_ai_settings())
        self.kb_row_label.bind("<Button-1>", lambda e: self._show_ai_settings())
        self._update_kb_row()

        self.ai_status_label = ctk.CTkLabel(
            self.ai_view, text="选中当前接管对象聊天后，读取会话并生成回复。",
            text_color="#8c8c8c", anchor="w",
            font=ctk.CTkFont(family="PingFang SC", size=11),
        )
        self.ai_status_label.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(
            self.ai_view, text="聊天上下文", anchor="w",
            text_color="#333", font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
        ).pack(fill="x", padx=14, pady=(4, 4))

        self.ai_context_box = ctk.CTkTextbox(
            self.ai_view, height=100, corner_radius=8, border_width=1,
            border_color=BORDER, font=ctk.CTkFont(family="PingFang SC", size=11),
        )
        self.ai_context_box.pack(fill="x", padx=12, pady=(0, 6))
        self.ai_context_box.configure(state="disabled")

        ctk.CTkLabel(
            self.ai_view, text="候选回复", anchor="w",
            text_color="#333", font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
        ).pack(fill="x", padx=14, pady=(4, 4))

        # 回复框 + 改写栏 + 工具/发送行。
        # 关键：底部的工具行、发送行用 side="bottom" 且 **先于** 回复框 pack，
        # 这样它们优先占据底部空间；回复框最后 pack（expand）吸收剩余高度。
        # Tk 在空间不足时优先压缩最后 pack 的控件，因此回复框会先被压缩，
        # 而发送/工具行始终完整可见，无论窗口多矮。
        self.ai_reply_box = ctk.CTkTextbox(
            self.ai_view, height=88, corner_radius=8, border_width=1,
            border_color=BORDER, font=ctk.CTkFont(family="PingFang SC", size=12),
        )

        # ── 发送行（最先 pin 到最底部）──
        # ── 底部减负：1 主操作（确认发送）+ 1 溢出（⋯）──
        # 原 4 个按钮（确认发送 / 存知识库 / 复制 / 清空）压成一行：
        # 主操作 确认发送 撑满，低频项（复制 / 存入知识库 / 清空）收进 ⋯ 菜单。
        send_row = ctk.CTkFrame(self.ai_view, fg_color="transparent")
        send_row.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            send_row, text="确认发送", height=38, corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
            command=self._ai_send_reply,
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.ai_overflow_btn = ctk.CTkButton(
            send_row, text="⋯", width=44, height=38, corner_radius=10,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=TEXT_SUB, hover_color=CARD_BG,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._ai_overflow_menu,
        )
        self.ai_overflow_btn.grid(row=0, column=1, sticky="e")

        # 兼容：KB 提炼流程仍引用 ai_save_btn 做进度反馈（不进入布局，隐藏存在）
        self.ai_save_btn = ctk.CTkButton(self.ai_view, text="💾 存入知识库")

        # ── 一键改写（对话式微调）：预设 + 自定义 ──
        self.ai_refine_btns: list = []
        refine_frame = ctk.CTkFrame(self.ai_view, fg_color="transparent")
        refine_frame.grid_columnconfigure((0, 1, 2), weight=1)
        for col, (key, label) in enumerate(
            (("formal", "更正式"), ("shorter", "更简短"), ("rephrase", "换个说法"))
        ):
            btn = ctk.CTkButton(
                refine_frame, text=label, height=28, corner_radius=8,
                fg_color="transparent", border_width=1, border_color=BORDER,
                text_color=PRIMARY, hover_color=CARD_BG,
                font=ctk.CTkFont(family="PingFang SC", size=11),
                command=lambda k=key: self._ai_refine(REFINE_PRESETS[k]),
            )
            pad = (0, 3) if col == 0 else (3, 0) if col == 2 else (3, 3)
            btn.grid(row=0, column=col, padx=pad, sticky="ew")
            self.ai_refine_btns.append(btn)

        custom_frame = ctk.CTkFrame(self.ai_view, fg_color="transparent")
        custom_frame.grid_columnconfigure(0, weight=1)
        self.ai_refine_entry = ctk.CTkEntry(
            custom_frame, height=28, corner_radius=8, border_width=1,
            border_color=BORDER, placeholder_text="自定义修改要求，如：加上歉意、更口语化…",
            font=ctk.CTkFont(family="PingFang SC", size=11),
        )
        self.ai_refine_entry.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.ai_refine_entry.bind("<Return>", lambda e: self._ai_refine_custom())
        self.ai_refine_apply_btn = ctk.CTkButton(
            custom_frame, text="应用", width=52, height=28, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._ai_refine_custom,
        )
        self.ai_refine_apply_btn.grid(row=0, column=1, sticky="e")
        self.ai_refine_btns.append(self.ai_refine_apply_btn)

        # ── pack 顺序：底部控件先占位，回复框最后 expand 吸收余量 ──
        send_row.pack(side="bottom", fill="x", padx=12, pady=(2, 10))
        custom_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        refine_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 4))
        self.ai_reply_box.pack(fill="both", expand=True, padx=12, pady=(0, 6))

    def _update_kb_row(self):
        """根据当前配置刷新知识库状态行外观。"""
        cfg = self._app_config
        # 向后兼容：旧配置只有 kb_enabled=True 时视为 local 模式
        kb_mode = cfg.get("kb_mode", "none")
        if kb_mode == "none" and cfg.get("kb_enabled"):
            kb_mode = "local"

        if kb_mode == "cloud":
            scope = cfg.get("kb_scope", "")
            scope_str = f" · {scope}" if scope else ""
            self.kb_row.configure(fg_color=SURFACE, border_color=BORDER)
            self.kb_row_label.configure(
                text=f"✓ 云端知识库已启用{scope_str}", text_color=PRIMARY
            )
        elif kb_mode == "local" and cfg.get("kb_vault_path"):
            vault_name = os.path.basename(cfg["kb_vault_path"]) or cfg["kb_vault_path"]
            count_str = ""
            if _kb_get_db_path and _sqlite3:
                try:
                    db = _kb_get_db_path()
                    if os.path.exists(db):
                        conn = _sqlite3.connect(db)
                        try:
                            vault = cfg["kb_vault_path"].rstrip("/")
                            n = conn.execute(
                                "SELECT COUNT(*) FROM kb_meta WHERE path LIKE ?",
                                (vault + "/%",),
                            ).fetchone()[0]
                            count_str = f"  ({n} 条)"
                        finally:
                            conn.close()
                except Exception:
                    pass
            self.kb_row.configure(fg_color=SURFACE, border_color=BORDER)
            self.kb_row_label.configure(
                text=f"✓ 知识库已启用 · {vault_name}{count_str}", text_color="#389e0d"
            )
        else:
            self.kb_row.configure(fg_color=SURFACE, border_color=BORDER)
            self.kb_row_label.configure(
                text="知识库未启用 · 点击设置", text_color=TEXT_WEAK
            )

    def _show_ai_settings(self):
        """弹出 AI 知识库设置窗口。"""
        self.root.attributes("-topmost", False)
        win = ctk.CTkToplevel(self.root)
        win.withdraw()   # 先隐藏，定位后再显示，防止闪烁
        win.title("AI 知识库设置")
        win.resizable(False, False)
        self._center_on_root(win, 420, 310)   # 内部调用 deiconify()
        win.lift()
        win.focus_force()
        win.grab_set()
        win.attributes("-topmost", True)

        # ── Header ──
        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="⚙  AI 知识库设置", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=14, pady=12)

        # ── Body ──
        body = ctk.CTkFrame(win, fg_color="white", corner_radius=0)
        body.pack(fill="both", expand=True)

        # ── 知识库模式选择 ──
        _MODE_LABELS = ["关闭", "本地知识库", "云端知识库"]
        _MODE_VALUES = ["none", "local", "cloud"]

        # 向后兼容：旧配置只有 kb_enabled=True 时视为 local
        _saved_mode = self._app_config.get("kb_mode", "none")
        if _saved_mode == "none" and self._app_config.get("kb_enabled"):
            _saved_mode = "local"
        _init_label = _MODE_LABELS[_MODE_VALUES.index(_saved_mode)] if _saved_mode in _MODE_VALUES else "关闭"

        row0 = ctk.CTkFrame(body, fg_color="transparent")
        row0.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            row0, text="知识库模式",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            width=72, anchor="w",
        ).pack(side="left")
        mode_var = ctk.StringVar(value=_init_label)
        seg_btn = ctk.CTkSegmentedButton(
            row0, values=_MODE_LABELS,
            variable=mode_var,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            width=250,
        )
        seg_btn.pack(side="right")

        # ── 本地知识库：Vault 路径行 ──
        row_local = ctk.CTkFrame(body, fg_color="transparent")
        ctk.CTkLabel(
            row_local, text="Vault 路径",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            width=72, anchor="w",
        ).pack(side="left")
        path_var = ctk.StringVar(value=self._app_config.get("kb_vault_path", ""))
        path_entry = ctk.CTkEntry(
            row_local, textvariable=path_var,
            height=30, corner_radius=6, border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            state="disabled",
        )
        path_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

        def browse():
            from tkinter import filedialog
            win.grab_release()
            chosen = filedialog.askdirectory(
                title="选择 Obsidian Vault 文件夹",
                parent=win,
            )
            win.grab_set()
            if chosen:
                path_var.set(chosen)

        ctk.CTkButton(
            row_local, text="浏览…", width=60, height=30, corner_radius=6,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=11),
            command=browse,
        ).pack(side="right")

        # ── 云端知识库：查询范围行 ──
        row_cloud = ctk.CTkFrame(body, fg_color="transparent")
        ctk.CTkLabel(
            row_cloud, text="查询范围",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            width=72, anchor="w",
        ).pack(side="left")
        scope_var = ctk.StringVar(value=self._app_config.get("kb_scope", ""))
        ctk.CTkEntry(
            row_cloud, textvariable=scope_var,
            height=30, corner_radius=6, border_width=1,
            border_color=BORDER,
            placeholder_text="可选：服务名/模块名，提升查询精度",
            font=ctk.CTkFont(family="PingFang SC", size=11),
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

        def _refresh_rows(label: str):
            """根据所选模式显示/隐藏对应行。"""
            if label == "本地知识库":
                row_local.pack(fill="x", padx=16, pady=(0, 6))
                row_cloud.pack_forget()
            elif label == "云端知识库":
                row_local.pack_forget()
                row_cloud.pack(fill="x", padx=16, pady=(0, 6))
            else:
                row_local.pack_forget()
                row_cloud.pack_forget()

        # 初始显示
        _refresh_rows(_init_label)
        mode_var.trace_add("write", lambda *_: _refresh_rows(mode_var.get()))

        # ── Footer ──
        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(4, 14), side="bottom")
        footer.grid_columnconfigure((0, 1, 2), weight=1)

        def _start_rebuild_ui(target_path: str) -> None:
            """关闭设置窗口，弹出进度提示，后台重建索引。"""
            win.destroy()
            self.root.attributes("-topmost", False)
            progress_win = ctk.CTkToplevel(self.root)
            progress_win.withdraw()
            progress_win.title("建立索引")
            progress_win.resizable(False, False)
            self._center_on_root(progress_win, 320, 80)
            progress_win.attributes("-topmost", True)
            progress_win.grab_set()
            prog_lbl = ctk.CTkLabel(progress_win, text="正在建立知识库索引…")
            prog_lbl.pack(expand=True)

            def do_rebuild():
                err = None
                try:
                    _kb_rebuild(target_path)
                except Exception as e:
                    err = str(e)

                def on_done():
                    self._update_kb_row()
                    if err:
                        prog_lbl.configure(
                            text=f"❌ 重建失败：{err[:50]}", text_color="#cf1322"
                        )
                        # 3s 后自动关闭
                        self.root.after(3000, lambda: (
                            progress_win.destroy(),
                            self.root.attributes("-topmost", True),
                        ))
                    else:
                        progress_win.destroy()
                        self.root.attributes("-topmost", True)

                self.root.after(0, on_done)

            threading.Thread(target=do_rebuild, daemon=True).start()

        def on_save():
            cur_label = mode_var.get()
            cur_mode = _MODE_VALUES[_MODE_LABELS.index(cur_label)] if cur_label in _MODE_LABELS else "none"
            new_path = path_var.get().strip()
            new_scope = scope_var.get().strip()

            if cur_mode == "local" and not new_path:
                self._show_warning("请先选择 Obsidian Vault 路径")
                return

            old_path = self._app_config.get("kb_vault_path", "")
            self._app_config["kb_mode"] = cur_mode
            self._app_config["kb_scope"] = new_scope
            # 向后兼容字段同步更新
            self._app_config["kb_enabled"] = (cur_mode == "local")
            self._app_config["kb_vault_path"] = new_path
            try:
                save_config(self._app_config)
            except OSError as e:
                self._show_warning(f"保存失败：{e}")
                return
            self._app_config = load_config()
            self._update_kb_row()

            # 本地模式路径变更 或 vault 从未被索引时，重建索引
            needs_rebuild = (
                cur_mode == "local" and new_path and _kb_rebuild
                and (new_path != old_path or not _vault_is_indexed(new_path))
            )
            if needs_rebuild:
                _start_rebuild_ui(new_path)
            else:
                win.destroy()
                self.root.attributes("-topmost", True)

        # 状态标签（重建进度反馈，默认隐藏）
        status_lbl = ctk.CTkLabel(
            body, text="", height=18,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            text_color="#888",
        )
        status_lbl.pack(fill="x", padx=16, pady=(0, 2))

        def on_cancel():
            win.destroy()
            self.root.attributes("-topmost", True)

        win.protocol("WM_DELETE_WINDOW", on_cancel)

        # 先建按钮，存引用；回调用 configure(command=) 补绑，避免前向引用
        btn_rebuild = ctk.CTkButton(
            footer, text="重建索引", height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#555", hover_color="#f0f0f0",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        btn_rebuild.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        btn_cancel = ctk.CTkButton(
            footer, text="取消", height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666", hover_color="#f0f0f0",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            command=on_cancel,
        )
        btn_cancel.grid(row=0, column=1, padx=(4, 4), sticky="ew")

        btn_save = ctk.CTkButton(
            footer, text="保存", height=32, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=on_save,
        )
        btn_save.grid(row=0, column=2, padx=(4, 0), sticky="ew")

        def on_rebuild():
            """手动重建索引：保持窗口打开，原地显示进度（仅本地模式有效）。"""
            cur_path = path_var.get().strip()
            if not cur_path:
                self._show_warning("请先选择 Obsidian Vault 路径")
                return
            if not _kb_rebuild:
                return
            # 先保存当前设置
            cur_label = mode_var.get()
            cur_mode = _MODE_VALUES[_MODE_LABELS.index(cur_label)] if cur_label in _MODE_LABELS else "none"
            self._app_config["kb_mode"] = cur_mode
            self._app_config["kb_scope"] = scope_var.get().strip()
            self._app_config["kb_enabled"] = (cur_mode == "local")
            self._app_config["kb_vault_path"] = cur_path
            try:
                save_config(self._app_config)
            except OSError:
                pass
            self._app_config = load_config()

            # 禁用所有按钮，显示进度
            for btn in (btn_rebuild, btn_cancel, btn_save):
                btn.configure(state="disabled")
            btn_rebuild.configure(text="重建中…")
            status_lbl.configure(text="正在建立知识库索引…", text_color="#888")

            def do_inline_rebuild():
                count = 0
                err = None
                try:
                    count = _kb_rebuild(cur_path)
                except Exception as e:
                    err = str(e)

                def on_done():
                    for btn in (btn_rebuild, btn_cancel, btn_save):
                        btn.configure(state="normal")
                    btn_rebuild.configure(text="重建索引")
                    if err:
                        status_lbl.configure(
                            text=f"❌ 重建失败：{err[:40]}", text_color="#cf1322"
                        )
                    else:
                        status_lbl.configure(
                            text=f"✅ 完成，已索引 {count} 个文件", text_color="#389e0d"
                        )
                    self._update_kb_row()

                self.root.after(0, on_done)

            threading.Thread(target=do_inline_rebuild, daemon=True).start()

        btn_rebuild.configure(command=on_rebuild)

    # ── 生成中动效 ───────────────────────────────────────────

    @staticmethod
    def _lerp_color(c1: str, c2: str, t: float) -> str:
        """在两个 #rrggbb 颜色间线性插值。"""
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        return "#{:02x}{:02x}{:02x}".format(
            round(r1 + (r2 - r1) * t),
            round(g1 + (g2 - g1) * t),
            round(b1 + (b2 - b1) * t),
        )

    def _ai_start_loading_anim(self):
        """启动候选回复文本框的 AI 生成动效（边框呼吸 + 框内光标闪烁）。"""
        self._ai_anim_running = True
        self._ai_anim_tick = 0
        tb = self.ai_reply_box._textbox
        tb.tag_configure("anim_dot",  foreground=PRIMARY)
        tb.tag_configure("anim_msg",  foreground=TEXT_WEAK)
        tb.tag_configure("anim_cur",  foreground=PRIMARY)
        self._ai_anim_step()

    def _ai_stop_loading_anim(self):
        """停止动效，恢复边框颜色，清空占位文字，恢复文本框可编辑。"""
        self._ai_anim_running = False
        self.ai_reply_box.configure(border_color=BORDER)
        # 恢复底层 tk.Text 为可编辑（_ai_anim_step 最后一次 tick 可能将其设为 disabled）
        self.ai_reply_box._textbox.configure(state="normal")
        self.ai_reply_box.delete("1.0", "end")

    def _ai_anim_step(self):
        if not self._ai_anim_running:
            return
        n = self._ai_anim_tick

        # 边框呼吸：正弦波，周期 28 tick = 1.4s（50ms/tick）
        t_border = (math.sin(n * math.pi / 14) + 1) / 2
        self.ai_reply_box.configure(
            border_color=self._lerp_color(BORDER, PRIMARY, t_border)
        )

        # 框内占位文字：彩色点 + 提示文字 + 闪烁光标
        t_dot = (math.sin(n * math.pi / 10) + 1) / 2
        dot_color = self._lerp_color("#a0c4ff", PRIMARY, t_dot)
        cursor_char = "▋" if (n // 9) % 2 == 0 else " "

        tb = self.ai_reply_box._textbox
        tb.configure(state="normal")
        tb.delete("1.0", "end")
        tb.tag_configure("anim_dot", foreground=dot_color)
        tb.insert("end", "⬤ ", "anim_dot")
        tb.insert("end", "AI 正在生成回复", "anim_msg")
        tb.insert("end", cursor_char, "anim_cur")
        tb.configure(state="disabled")

        self._ai_anim_tick += 1
        self.root.after(50, self._ai_anim_step)

    # ─────────────────────────────────────────────────────────

    def _ai_set_status(self, text: str):
        self.ai_status_label.configure(text=text)

    def _ai_set_context(self, text: str):
        self.ai_context_box.configure(state="normal")
        self.ai_context_box.delete("1.0", "end")
        self.ai_context_box.insert("end", text)
        self.ai_context_box.configure(state="disabled")

    def _ai_set_reply(self, text: str):
        self.ai_reply_box.delete("1.0", "end")
        self.ai_reply_box.insert("end", text)
        if hasattr(self, "ai_save_btn"):
            capturing = getattr(self, "_ai_kb_capturing", False)
            self.ai_save_btn.configure(
                state="normal" if (text.strip() and not capturing) else "disabled"
            )

    def _ai_get_reply(self) -> str:
        return self.ai_reply_box.get("1.0", "end").strip()

    def _format_ai_messages(self, msgs: list) -> str:
        lines = []
        for msg in msgs:
            time_str = f"[{msg['time']}] " if msg.get("time") else ""
            lines.append(f"{time_str}{msg.get('content', '')}")
        return "\n\n".join(lines)

    def _ai_read_and_generate(self):
        if self._ai_generating:
            return
        self.ai_reply_box.delete("1.0", "end")
        self._ai_origin_draft = ""  # 新一轮读取，清空上一轮原稿基准
        self._ai_set_status("正在读取聊天内容...")
        self.ai_generate_btn.configure(state="disabled")
        client = self.current_client

        def fetch():
            try:
                msgs = read_chat_with_client(client, max_messages=30)
                self.root.after(0, lambda: self._ai_after_read(msgs))
            except UnsupportedClientAction as exc:
                msg = str(exc)
                self.root.after(0, lambda: self._ai_read_failed(msg))
            except Exception as exc:
                msg = f"读取失败: {exc}"
                self.root.after(0, lambda: self._ai_read_failed(msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _ai_after_read(self, msgs: list):
        self._ai_messages = msgs
        self.ai_generate_btn.configure(state="normal")
        if not msgs:
            self._ai_set_context(f"未读取到消息，请先在{self._current_client_name()}中选中聊天窗口。")
            self._ai_set_status("未读取到聊天内容")
            return
        self._ai_set_context(self._format_ai_messages(msgs))
        self._ai_generate_async(msgs)

    def _ai_read_failed(self, message: str):
        self.ai_generate_btn.configure(state="normal")
        self._ai_set_context(message)
        self._ai_set_status(message)

    def _ai_regenerate(self):
        if self._ai_generating:
            return
        if not self._ai_messages:
            self._ai_read_and_generate()
            return
        self.ai_reply_box.delete("1.0", "end")
        self._ai_generate_async(self._ai_messages)

    def _ai_set_generating_ui(self, on: bool):
        """生成中：把「读取并生成」主按钮变为红色「取消生成」；结束后恢复。"""
        if on:
            self.ai_generate_btn.configure(
                text="取消生成", fg_color=DOT_ERR, hover_color="#d9363e",
                state="normal", command=self._ai_cancel_generation,
            )
            self.ai_regenerate_btn.configure(state="disabled")
        else:
            self.ai_generate_btn.configure(
                text="读取并生成", fg_color=PRIMARY, hover_color=PRIMARY_H,
                state="normal", command=self._ai_read_and_generate,
            )
            self.ai_regenerate_btn.configure(state="normal")

    def _ai_cancel_generation(self):
        """用户点「取消生成」：置位取消标志，流式循环会杀掉子进程。"""
        token = getattr(self, "_ai_cancel", None)
        if token is not None:
            token.cancel()
        self._ai_set_status("正在取消…")

    def _ai_stream_append(self, text: str):
        """流式回调：把新到的文本块追加进草稿框并滚动到底。"""
        if not self._ai_generating:
            return
        # 第一个流式块到达：停掉生成动效（它会清空占位文字并恢复可编辑），
        # 之后才开始真正写入内容。
        if not getattr(self, "_ai_stream_started", False):
            self._ai_stop_loading_anim()
            self._ai_stream_started = True
        box = self.ai_reply_box
        box._textbox.configure(state="normal")
        box.insert("end", text)
        box.see("end")

    def _ai_generate_async(self, msgs: list):
        self._ai_generating = True
        self._ai_cancel = CancelToken()
        self._ai_set_generating_ui(True)
        self._ai_set_refine_enabled(False)
        self._ai_set_status("正在调用 AI 生成回复…")
        # 先放生成动效（呼吸边框 + 「AI 正在生成」占位）；第一个流式块到达时
        # 再停掉动效、切换为逐块写入。等待期有反馈，有内容了就实时涌出。
        self._ai_stream_started = False
        self._ai_start_loading_anim()

        ai_config = AIReplyConfig(
            kb_enabled=self._app_config.get("kb_enabled", False),
            kb_vault_path=self._app_config.get("kb_vault_path", ""),
            kb_mode=self._app_config.get("kb_mode", "none"),
            kb_scope=self._app_config.get("kb_scope", ""),
        )
        cancel = self._ai_cancel

        def on_chunk(text: str):
            self.root.after(0, lambda t=text: self._ai_stream_append(t))

        def generate_task():
            try:
                reply = generate_reply_stream(msgs, ai_config, on_chunk=on_chunk, cancel=cancel)
                self.root.after(0, lambda: self._ai_generation_done(reply))
            except AICancelledError:
                self.root.after(0, self._ai_generation_cancelled)
            except (
                AICommandNotFoundError,
                AICommandTimeoutError,
                AICommandFailedError,
                AIEmptyResponseError,
            ) as exc:
                msg = str(exc)
                self.root.after(0, lambda: self._ai_generation_failed(msg))
            except Exception as exc:
                msg = f"AI 生成失败: {exc}"
                self.root.after(0, lambda: self._ai_generation_failed(msg))

        threading.Thread(target=generate_task, daemon=True).start()

    def _ai_generation_done(self, reply: str):
        self._ai_generating = False
        self._ai_stop_loading_anim()
        self._ai_set_generating_ui(False)
        self._ai_set_refine_enabled(True)
        # 用规范化后的完整文本替换流式累积内容（去重 / 启用「存入知识库」）
        self._ai_set_reply(reply)
        # 记录本轮 AI 原稿（首次生成），发送时与实发文本对比沉淀风格信号
        self._ai_origin_draft = (reply or "").strip()
        self._ai_set_status("AI 回复已生成，可改写或编辑后发送")

    def _ai_generation_cancelled(self):
        self._ai_generating = False
        self._ai_stop_loading_anim()
        self._ai_set_generating_ui(False)
        self._ai_set_refine_enabled(True)
        self._ai_set_status("已取消生成")

    def _ai_generation_failed(self, message: str):
        self._ai_generating = False
        self._ai_stop_loading_anim()
        self._ai_set_generating_ui(False)
        self._ai_set_refine_enabled(True)
        self._ai_set_status(message)

    # ── 草稿改写（对话式微调）─────────────────────────────────

    def _ai_set_refine_enabled(self, enabled: bool):
        """统一启用/禁用所有改写按钮。"""
        state = "normal" if enabled else "disabled"
        for btn in getattr(self, "ai_refine_btns", []):
            btn.configure(state=state)

    def _ai_refine_custom(self):
        """读取自定义输入框中的修改要求并应用。"""
        instruction = self.ai_refine_entry.get().strip()
        if not instruction:
            self._ai_set_status("请先输入自定义修改要求")
            return
        self._ai_refine(instruction)

    def _ai_refine(self, instruction: str):
        """按修改要求改写当前草稿（以当前文本框内容为基准，支持多轮链式微调）。"""
        if self._ai_generating:
            return
        draft = self._ai_get_reply()
        if not draft:
            self._ai_set_status("没有可改写的草稿，请先生成或输入回复")
            return

        self._ai_generating = True
        self.ai_generate_btn.configure(state="disabled")
        self.ai_regenerate_btn.configure(state="disabled")
        self._ai_set_refine_enabled(False)
        self._ai_set_status(f"正在改写：{instruction}")
        self._ai_start_loading_anim()

        ai_config = AIReplyConfig(
            kb_enabled=self._app_config.get("kb_enabled", False),
            kb_vault_path=self._app_config.get("kb_vault_path", ""),
            kb_mode=self._app_config.get("kb_mode", "none"),
            kb_scope=self._app_config.get("kb_scope", ""),
        )
        msgs = self._ai_messages

        def refine_task():
            try:
                reply = refine_reply(msgs, draft, instruction, ai_config)
                self.root.after(0, lambda: self._ai_refine_done(reply))
            except (
                AICommandNotFoundError,
                AICommandTimeoutError,
                AICommandFailedError,
                AIEmptyResponseError,
            ) as exc:
                msg = str(exc)
                self.root.after(0, lambda: self._ai_refine_failed(msg))
            except Exception as exc:
                msg = f"改写失败: {exc}"
                self.root.after(0, lambda: self._ai_refine_failed(msg))

        threading.Thread(target=refine_task, daemon=True).start()

    def _ai_refine_done(self, reply: str):
        self._ai_generating = False
        self._ai_stop_loading_anim()
        self.ai_generate_btn.configure(state="normal")
        self.ai_regenerate_btn.configure(state="normal")
        self._ai_set_refine_enabled(True)
        self._ai_set_reply(reply)
        self._ai_set_status("已改写，可继续微调或发送")

    def _ai_refine_failed(self, message: str):
        self._ai_generating = False
        self._ai_stop_loading_anim()
        self.ai_generate_btn.configure(state="normal")
        self.ai_regenerate_btn.configure(state="normal")
        self._ai_set_refine_enabled(True)
        self._ai_set_status(message)

    def _ai_copy_reply(self):
        reply = self._ai_get_reply()
        if not reply:
            self._show_warning("暂无可复制的回复")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(reply)
        self._ai_set_status("候选回复已复制")

    def _ai_clear_reply(self):
        self._ai_set_reply("")
        self._ai_set_status("候选回复已清空")

    def _insert_phrase_to_draft(self, phrase):
        """把话术文本插入草稿台（切到草稿视图，追加到草稿框末尾，供编辑后发送）。

        spec §4「每卡两动作：插入 / 发送」——插入打通「话术 → 草稿台」动线。
        图片块不进文本草稿，仅插入文本部分并在状态栏提示。
        """
        text = phrase_full_text(phrase)
        if not text:
            self._switch_mode("ai")
            self._ai_set_status("该话术无可插入的文本内容")
            return
        self._switch_mode("ai")
        box = self.ai_reply_box
        box._textbox.configure(state="normal")
        existing = box.get("1.0", "end").strip()
        if existing:
            box.insert("end", "\n" + text)
        else:
            box.delete("1.0", "end")
            box.insert("end", text)
        box.see("end")
        if hasattr(self, "ai_save_btn"):
            self.ai_save_btn.configure(state="normal")
        note = "；图片块未插入（草稿台仅支持文本）" if has_images(phrase) else ""
        self._ai_set_status("已插入话术到草稿台，可编辑后发送" + note)

    def _ai_send_reply(self):
        reply = self._ai_get_reply()
        if not reply:
            self._show_warning("请先生成或输入回复内容")
            return
        # 数据飞轮：静默沉淀「AI 原稿 → 实际发送」diff（绝不影响发送主流程）
        try:
            log_draft_diff(
                self._ai_origin_draft,
                reply,
                client_id=(self.current_client.client_id if self.current_client else ""),
                context_msgs=len(self._ai_messages),
            )
        except Exception:
            pass
        self._ai_origin_draft = ""  # 本轮已发送，清空原稿基准，避免下次重复记账
        self._do_send(reply)

    # ── KB 存储 ──────────────────────────────────────────────────────────────

    def _ai_kb_capture_async(self):
        """点击「存入知识库」后：校验配置，启动后台提炼线程。"""
        vault_path = self._app_config.get("kb_vault_path", "")
        if not vault_path:
            self._show_warning("请先在 ⚙ 设置中配置知识库路径")
            return

        reply = self._ai_get_reply()
        if not reply:
            return  # 按钮本应 disabled，防御性检查

        if self._ai_kb_capturing:
            return  # 防止重入
        self._ai_kb_capturing = True
        self.ai_save_btn.configure(state="disabled", text="提炼中…")
        msgs = list(self._ai_messages)  # 快照，防止线程读写竞争

        ai_config = AIReplyConfig(
            kb_enabled=False,  # 提炼任务不需要读 vault
            kb_vault_path="",
        )

        def extract_task():
            entry_dict = extract_kb_entry(msgs, reply, ai_config)
            self.root.after(0, lambda: self._ai_kb_capture_done(entry_dict, reply))

        threading.Thread(target=extract_task, daemon=True).start()

    def _ai_kb_capture_done(self, entry_dict: dict | None, reply: str):
        """提炼完成（或失败）后恢复按钮并弹出编辑弹窗。"""
        self._ai_kb_capturing = False
        self.ai_save_btn.configure(state="normal", text="💾 存入知识库")
        source_name = (
            self.current_client.display_name if self.current_client else "未知来源"
        )
        self._show_kb_save_dialog(entry_dict or {}, reply, source_name)

    def _show_kb_save_dialog(
        self, entry_dict: dict, reply: str, source_name: str
    ):
        """
        弹出 KB 条目编辑弹窗。
        entry_dict: AI 提炼结果（可能为空 {}），含 title/scenario/tags 键。
        reply: 候选回复原文（预填回复内容字段）。
        source_name: IM 客户端名称（只读展示）。
        """
        self.root.attributes("-topmost", False)
        win = ctk.CTkToplevel(self.root)
        win.title("存入知识库")
        win.geometry("420x400")
        win.resizable(False, False)
        win.lift()
        win.focus_force()
        win.grab_set()
        win.attributes("-topmost", True)

        # ── Header ──────────────────────────────────────────────────────────
        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="💾  存入知识库", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=14, pady=10)

        # ── Body ─────────────────────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(win, fg_color="white", corner_radius=0)
        body.pack(fill="both", expand=True)

        LABEL_FONT = ctk.CTkFont(family="PingFang SC", size=11)
        ENTRY_FONT = ctk.CTkFont(family="PingFang SC", size=12)

        def labeled_row(parent, label_text):
            """返回 row_frame，便于后续 pack 子控件。"""
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(8, 0))
            ctk.CTkLabel(
                row, text=label_text, font=LABEL_FONT,
                text_color="#555", anchor="w",
            ).pack(fill="x")
            return row

        # 标题
        labeled_row(body, "标题")
        title_var = ctk.StringVar(value=entry_dict.get("title", ""))
        ctk.CTkEntry(
            body, textvariable=title_var, height=32, corner_radius=6,
            border_width=1, border_color=BORDER, font=ENTRY_FONT,
        ).pack(fill="x", padx=16, pady=(3, 0))

        # 适用场景
        labeled_row(body, "适用场景")
        scenario_box = ctk.CTkTextbox(
            body, height=52, corner_radius=6, border_width=1,
            border_color=BORDER, font=ENTRY_FONT,
        )
        scenario_box.pack(fill="x", padx=16, pady=(3, 0))
        scenario_box.insert("end", entry_dict.get("scenario", ""))

        # 标签（逗号分隔）
        labeled_row(body, "标签（逗号分隔）")
        tags_raw = ", ".join(entry_dict.get("tags", []))
        tags_var = ctk.StringVar(value=tags_raw)
        ctk.CTkEntry(
            body, textvariable=tags_var, height=32, corner_radius=6,
            border_width=1, border_color=BORDER, font=ENTRY_FONT,
        ).pack(fill="x", padx=16, pady=(3, 0))

        # 回复内容
        labeled_row(body, "回复内容")
        reply_box = ctk.CTkTextbox(
            body, height=80, corner_radius=6, border_width=1,
            border_color=BORDER, font=ENTRY_FONT,
        )
        reply_box.pack(fill="x", padx=16, pady=(3, 0))
        reply_box.insert("end", reply)

        # 来源（只读）
        labeled_row(body, "来源")
        ctk.CTkLabel(
            body, text=source_name, font=ENTRY_FONT,
            text_color="#888", anchor="w",
        ).pack(fill="x", padx=20, pady=(3, 0))

        # ── Footer ───────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(win, fg_color="white", height=56, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        footer.grid_columnconfigure((0, 1), weight=1)

        def on_cancel():
            win.destroy()
            self.root.attributes("-topmost", True)

        def on_save():
            title_val = title_var.get().strip()
            if not title_val:
                win.grab_release()
                self._show_warning("标题不能为空")
                win.grab_set()
                return

            scenario_val = scenario_box.get("1.0", "end").strip()
            tags_val = [t.strip() for t in tags_var.get().split(",") if t.strip()]
            reply_val = reply_box.get("1.0", "end").strip()
            vault_path = self._app_config.get("kb_vault_path", "")

            from datetime import date
            entry = KBEntry(
                title=title_val,
                scenario=scenario_val,
                tags=tags_val,
                reply=reply_val,
                source=source_name,
                date=date.today().isoformat(),
            )
            try:
                saved_path = save_to_vault(entry, vault_path)
                filename = os.path.basename(saved_path)
                win.destroy()
                self.root.attributes("-topmost", True)
                self._ai_set_status(f"✅ 已存入知识库：{filename}")
            except OSError as exc:
                win.grab_release()
                self._show_warning(f"写入失败：{exc}")
                win.grab_set()
            except Exception as exc:
                self._show_warning(f"保存异常：{exc}")
                win.destroy()
                self.root.attributes("-topmost", True)

        win.protocol("WM_DELETE_WINDOW", on_cancel)

        ctk.CTkButton(
            footer, text="取消", height=36, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666", hover_color="#f0f0f0",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            command=on_cancel,
        ).grid(row=0, column=0, padx=(12, 4), pady=10, sticky="ew")

        ctk.CTkButton(
            footer, text="保存到 Vault", height=36, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=on_save,
        ).grid(row=0, column=1, padx=(4, 12), pady=10, sticky="ew")

    def _refresh_cards(self):
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        self._selected_card = None
        group = self.group_var.get()
        all_phrases = self.phrases.get(group, [])
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        indexed_phrases = [
            (i, phrase) for i, phrase in enumerate(all_phrases)
            if not query or query in phrase_preview_text(phrase).lower()
        ]
        self._visible_phrases = [phrase for _, phrase in indexed_phrases]

        if not indexed_phrases:
            empty_text = "当前分组暂无话术" if not query else "没有匹配的话术"
            ctk.CTkLabel(
                self.cards_frame, text=empty_text, text_color="#8c8c8c",
                font=ctk.CTkFont(family="PingFang SC", size=12),
            ).pack(pady=24)
            return

        card_gap = (0, 2) if self._density == "compact" else (0, 5)
        for visible_i, (i, phrase) in enumerate(indexed_phrases, 1):
            card = PhraseCard(
                self.cards_frame,
                phrase=phrase,
                on_send=lambda p=phrase: self._do_send(p),
                on_select=self._select_card,
                on_edit=lambda idx=i: self._edit_phrase(idx),
                on_insert=lambda p=phrase: self._insert_phrase_to_draft(p),
                index=visible_i if visible_i <= 9 else None,
                density=self._density,
            )
            card.pack(fill="x", pady=card_gap)

    def _select_card(self, card: "PhraseCard"):
        if self._selected_card and self._selected_card != card:
            self._selected_card.set_selected(False)
        self._selected_card = card
        card.set_selected(True)

    def _on_group_change(self, value=None):
        self.current_group = self.group_var.get()
        self._refresh_cards()

    def _on_search_change(self, *_):
        if self._search_after_id:
            self.root.after_cancel(self._search_after_id)
        self._search_after_id = self.root.after(120, self._refresh_cards)

    def _clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _bind_shortcuts(self):
        self.root.bind("<Command-f>", lambda e: self._focus_search())
        self.root.bind("<Command-F>", lambda e: self._focus_search())
        self.root.bind("<Command-Return>", lambda e: self._send_custom())
        self.root.bind("<Command-KP_Enter>", lambda e: self._send_custom())
        self.root.bind("<Escape>", lambda e: self._clear_search())
        for i in range(1, 10):
            self.root.bind(f"<Command-Key-{i}>", lambda e, idx=i: self._send_visible_phrase(idx))

    def _focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _send_visible_phrase(self, idx: int):
        if 1 <= idx <= len(self._visible_phrases):
            self._do_send(self._visible_phrases[idx - 1])
        return "break"

    def _toggle_snap(self):
        """切换吸附 / 脱离。脱离后面板停在原地、用户可拖到任意屏；重新吸附立即回贴。"""
        self._snap_enabled = not self._snap_enabled
        if self._snap_enabled:
            self.snap_btn.configure(text="脱离")
            self._last_bounds = None  # 强制下一次轮询立即重新定位
        else:
            self.snap_btn.configure(text="吸附")

    def _poll_snap(self):
        """
        每 100ms 读取目标窗口坐标，贴靠到目标窗口右侧（仅位置，不改高度）。

        - 脱离吸附（_snap_enabled=False）时只重排下一次轮询，不动窗口，
          让用户能把面板拖到第二屏常驻。
        - 只更新位置（geometry "+x+y"），不写死高度——保留用户手动拉伸的高度。

        过滤策略（防闪烁 + 防消失）：
        - 小变化（< 4px）忽略：防止 IME 弹框引起的 1-2px 抖动触发重绘
        - 大跳变（> 300px）丢弃：AX 数据异常保护，防止面板被送到屏幕外
        """
        if not self._snap_enabled:
            self.root.after(100, self._poll_snap)
            return

        bounds = self._current_window_bounds()
        if not bounds:
            self.root.after(100, self._poll_snap)
            return

        if self._last_bounds is not None:
            delta = max(abs(n - o) for n, o in zip(bounds, self._last_bounds))
            if delta < self._snap_threshold:
                # 微抖动，忽略
                self.root.after(100, self._poll_snap)
                return
            if delta > self._snap_max_delta:
                # 异常跳变（AX 返回错误数据），丢弃本次读数
                self.root.after(100, self._poll_snap)
                return

        # 确认更新：仅贴靠位置到目标窗口右缘，高度由用户掌控
        self._last_bounds = bounds
        wx, wy, ww, wh = bounds
        self.root.geometry(f"+{wx + ww}+{wy}")
        self.root.after(100, self._poll_snap)

    def _check_status(self):
        """检查当前接管对象状态"""
        client = self.current_client

        def check():
            running = client.adapter.is_running() if client else False
            self.root.after(0, lambda: self._update_status(client, running))

        threading.Thread(target=check, daemon=True).start()

    def _update_status(self, client, running: bool):
        if not AXIsProcessTrusted():
            self.status_dot.configure(text_color=DOT_WAIT)
            self.status_label.configure(text="需要辅助功能权限")
        elif client is None:
            self.status_dot.configure(text_color=DOT_ERR)
            self.status_label.configure(text="未选择接管对象")
        elif running and client.capabilities.verified:
            self.status_dot.configure(text_color=DOT_OK)
            self.status_label.configure(text=f"{client.display_name}已连接")
        elif running:
            self.status_dot.configure(text_color=DOT_WAIT)
            self.status_label.configure(text=f"{client.display_name}待验证")
        elif client.installed:
            self.status_dot.configure(text_color=DOT_ERR)
            self.status_label.configure(text=f"{client.display_name}未运行")
        else:
            self.status_dot.configure(text_color=DOT_ERR)
            self.status_label.configure(text=f"{client.display_name}未安装")

    def _open_accessibility_settings(self):
        open_privacy_pane(PREF_ACCESSIBILITY)

    # ── 首启权限向导（实时探测 + 自动前进）──────────────────────────
    # 单页静态说明 → 活的权限清单：两项权限各一行，实时显示 ✓/待开启，
    # 「去开启」深链直跳对应系统设置面板；后台 800ms 轮询，授予后自动
    # 打勾、核心权限齐备后底部按钮转为「开始使用」。
    #
    # 权限清单（required=核心，缺失则功能不可用；可选=仅特定客户端需要）：
    #   - 辅助功能：企业微信/大象 发送+读取的根本依赖（required）
    #   - 屏幕录制：微信 OCR 读取所需（可选，缺失只影响微信读取）

    def _perm_steps(self):
        """返回权限清单 [(key, 标题, 一句话原因, 检测函数, 深链, 打开前回调)]。"""
        return [
            (
                "accessibility", "辅助功能", "企业微信 / 大象 发送与读取的根本依赖",
                has_accessibility_permission, PREF_ACCESSIBILITY, None, True,
            ),
            (
                "screen", "屏幕录制", "微信消息读取（OCR）所需；不用微信可跳过",
                has_screen_recording_permission, PREF_SCREEN_CAPTURE,
                request_screen_recording_permission, False,
            ),
        ]

    def _show_permission_guide(self):
        # 已有向导则前置，不重复开
        existing = getattr(self, "_perm_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return

        win = ctk.CTkToplevel(self.root)
        self._perm_win = win
        win.withdraw()
        win.title("权限引导")
        win.attributes("-topmost", True)

        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="权限设置", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=14)
        ctk.CTkButton(
            header, text="✕", width=32, height=32, corner_radius=8,
            fg_color="transparent", hover_color=PRIMARY_H,
            text_color="white", font=ctk.CTkFont(size=14),
            command=win.destroy,
        ).pack(side="right", padx=8)

        content = ctk.CTkFrame(win, fg_color=APP_BG, corner_radius=0)
        content.pack(fill="both", expand=True)

        ctk.CTkLabel(
            content,
            text="开启以下权限即可使用。授予后会自动打勾，无需重启。",
            text_color=TEXT_SUB, font=ctk.CTkFont(family="PingFang SC", size=11),
            wraplength=440, justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 12))

        # 逐项权限卡片，保存可刷新的控件引用
        self._perm_rows = {}
        for key, title, why, check, deeplink, on_open, required in self._perm_steps():
            card = ctk.CTkFrame(content, fg_color="white", corner_radius=10,
                                border_width=1, border_color="#e5e8ee")
            card.pack(fill="x", padx=18, pady=(0, 10))

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(12, 2))

            dot = ctk.CTkLabel(top, text="○", text_color=DOT_WAIT, width=18,
                               font=ctk.CTkFont(size=15, weight="bold"))
            dot.pack(side="left")
            ctk.CTkLabel(
                top, text=title + ("" if required else "（可选）"),
                text_color=TEXT_MAIN,
                font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
            ).pack(side="left", padx=(6, 0))

            def _do_open(dl=deeplink, cb=on_open):
                if cb is not None:
                    cb()
                open_privacy_pane(dl)

            btn = ctk.CTkButton(
                top, text="去开启", width=72, height=28, corner_radius=8,
                fg_color=PRIMARY, hover_color=PRIMARY_H,
                font=ctk.CTkFont(family="PingFang SC", size=11, weight="bold"),
                command=_do_open,
            )
            btn.pack(side="right")

            ctk.CTkLabel(
                card, text=why, text_color=TEXT_SUB, anchor="w",
                font=ctk.CTkFont(family="PingFang SC", size=11),
                wraplength=420, justify="left",
            ).pack(fill="x", padx=(38, 14), pady=(0, 12))

            self._perm_rows[key] = (dot, btn, check)

        # 底部：核心权限齐备前=进度提示，齐备后=开始使用
        self._perm_footer = ctk.CTkButton(
            content, text="完成", height=36, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=win.destroy,
        )
        self._perm_footer.pack(fill="x", padx=18, pady=(4, 16))

        # 关闭时停止轮询
        def _on_close():
            pid = getattr(self, "_perm_poll_id", None)
            if pid is not None:
                try:
                    self.root.after_cancel(pid)
                except Exception:
                    pass
                self._perm_poll_id = None
            self._perm_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

        self._center_on_root(win, 480, 360)
        win.grab_set()
        self._perm_wizard_poll()

    def _perm_wizard_poll(self):
        """800ms 轮询：实时刷新各权限状态，核心权限齐备后切换底部按钮。"""
        win = getattr(self, "_perm_win", None)
        if win is None or not win.winfo_exists():
            self._perm_poll_id = None
            return

        accessibility_ok = True
        for key, (dot, btn, check) in self._perm_rows.items():
            try:
                granted = bool(check())
            except Exception:
                granted = False
            if key == "accessibility":
                accessibility_ok = granted
            if granted:
                dot.configure(text="✓", text_color=DOT_OK)
                btn.configure(text="已开启", state="disabled",
                              fg_color="transparent", border_width=1,
                              border_color="#cfd4dc", text_color=TEXT_WEAK)
            else:
                dot.configure(text="○", text_color=DOT_WAIT)
                btn.configure(text="去开启", state="normal",
                              fg_color=PRIMARY, border_width=0, text_color="white")

        if accessibility_ok:
            self._perm_footer.configure(text="开始使用 ✓", fg_color=DOT_OK,
                                        hover_color="#28a745")
        else:
            self._perm_footer.configure(text="完成", fg_color=PRIMARY,
                                        hover_color=PRIMARY_H)

        # 顺带刷新主面板状态点
        self._check_status()
        self._perm_poll_id = self.root.after(800, self._perm_wizard_poll)

    # ── 辅助：对话框在 topmost 窗口下的兼容方法 ──────────────────
    # macOS 上 CTk -topmost 窗口处于 NSFloatingWindowLevel，
    # tkinter 原生 simpledialog/messagebox 是 NSNormalWindowLevel，
    # 会被 CTk 窗口遮挡。修复方式：
    #   - 文本输入 → ctk.CTkInputDialog（CTk 层级，可见）
    #   - 警告/确认 → 弹出前临时关闭 topmost，结束后恢复

    def _center_on_root(self, win: ctk.CTkToplevel, w: int, h: int) -> None:
        """将 Toplevel 窗口居中叠放在主窗口上，防止先在默认位置闪烁。
        调用方须在 CTkToplevel() 创建后立即调用 win.withdraw()，
        本方法定位完成后调用 win.deiconify() 一次性显示在正确位置。
        """
        self.root.update_idletasks()
        rx, ry = self.root.winfo_x(), self.root.winfo_y()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        x = rx + (rw - w) // 2
        y = ry + (rh - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.deiconify()

    def _ask_input(self, title: str, prompt: str) -> str | None:
        """弹出文本输入框，临时关闭 topmost 确保对话框可见且可输入"""
        self.root.attributes("-topmost", False)
        dialog = ctk.CTkInputDialog(text=prompt, title=title)
        result = dialog.get_input()
        self.root.attributes("-topmost", True)
        return result

    def _show_warning(self, message: str):
        """弹出警告框，临时关闭 topmost 确保可见"""
        self.root.attributes("-topmost", False)
        messagebox.showwarning("提示", message)
        self.root.attributes("-topmost", True)

    def _show_info(self, title: str, message: str):
        """弹出信息框，临时关闭 topmost 确保可见"""
        self.root.attributes("-topmost", False)
        messagebox.showinfo(title, message)
        self.root.attributes("-topmost", True)

    # ── 稳健性自检 ───────────────────────────────────────────────

    def _run_self_check_async(self):
        """手动触发：对所有客户端做 AX 结构自检，在后台线程运行，完成后弹窗汇总。"""
        if getattr(self, "_selfcheck_running", False):
            return
        self._selfcheck_running = True
        self.menu_btn.configure(state="disabled")
        clients = self.clients

        def task():
            try:
                results = probes.run_self_check(clients, activate=True)
            except Exception as exc:
                results = None
                err = str(exc)
            else:
                err = None
            self.root.after(0, lambda: self._self_check_done(results, err))

        threading.Thread(target=task, daemon=True).start()

    def _self_check_done(self, results, err):
        self._selfcheck_running = False
        self.menu_btn.configure(state="normal")
        if err is not None:
            self._show_warning(f"自检执行失败：{err}")
            return

        icon = {
            probes.STATUS_OK: "✅",
            probes.STATUS_DEGRADED: "⚠️",
            probes.STATUS_NO_WINDOW: "⚠️",
            probes.STATUS_NO_PERMISSION: "🔒",
            probes.STATUS_NOT_RUNNING: "·",
            probes.STATUS_SKIPPED: "·",
        }
        lines = [
            f"{icon.get(r.status, '·')} {r.display_name}：{r.detail}"
            for r in results
        ]
        problems = [r for r in results if r.is_problem]
        body = "\n".join(lines) if lines else "没有可检查的客户端。"
        if problems:
            self._show_warning(
                "AX 结构自检发现问题（客户端可能已更新）：\n\n" + body +
                "\n\n若发送/读取失效，请用 tools/explore_ax.py 重新探测对应客户端的 AX 树。"
            )
        else:
            self._show_info("AX 结构自检", "全部正常：\n\n" + body)

    def _startup_self_check(self):
        """
        启动时被动自检（不激活窗口、不抢焦点）：检查「当前默认客户端」。

        被动模式下不激活窗口，AX 客户端非前台时本就读不到窗口（no_window），
        这属正常，不告警；只对「与激活无关、确实需要用户处理」的问题提示：
          - 辅助功能权限缺失（no_permission）：持续性问题，必报
          - 非 AX 客户端（微信）窗口不可达（no_window）：CGWindow 不依赖激活，可靠
        深层 AX 结构异常需激活才能判定，留给手动 🩺 自检。
        """
        client = self.current_client
        if client is None:
            return

        def task():
            try:
                result = probes.run_probe(client.adapter, activate=False)
            except Exception:
                return
            probe = probes.get_probe(client.adapter.client_id)
            worthy = result.status == probes.STATUS_NO_PERMISSION or (
                probe is not None and not probe.uses_ax
                and result.status == probes.STATUS_NO_WINDOW
            )
            if worthy:
                self.root.after(0, lambda: self._show_startup_warning(result))

        threading.Thread(target=task, daemon=True).start()

    def _show_startup_warning(self, result):
        """在状态栏标题追加自检告警提示（不弹窗）。"""
        hint = {
            probes.STATUS_NO_PERMISSION: "需授予辅助功能权限",
            probes.STATUS_NO_WINDOW: "未检测到窗口",
            probes.STATUS_DEGRADED: "AX 结构异常，点 🩺 自检",
        }.get(result.status, "自检异常")
        try:
            self.status_label.configure(text=f"{result.display_name}·{hint}")
            self.status_dot.configure(text_color=DOT_WAIT)
        except Exception:
            pass

    def _ask_yesno(self, title: str, message: str) -> bool:
        """弹出确认框，临时关闭 topmost 确保可见"""
        self.root.attributes("-topmost", False)
        result = messagebox.askyesno(title, message)
        self.root.attributes("-topmost", True)
        return result

    # ── 话术管理 ─────────────────────────────────────────────────

    def _add_phrase(self):
        self.root.attributes("-topmost", False)
        editor = BlockEditor(self.root)
        result = editor.get_result()
        self.root.attributes("-topmost", True)

        if not result:
            return
        group = self.group_var.get()
        phrase = result[0]["content"] if len(result) == 1 and result[0]["type"] == "text" else result
        self.phrases.setdefault(group, []).append(phrase)
        save_phrases(self.phrases)
        self._refresh_cards()

    def _delete_phrase(self):
        if not self._selected_card:
            self._show_warning("请先选中要删除的话术")
            return
        if self._ask_yesno("确认", "确定要删除这条话术吗？"):
            group = self.group_var.get()
            target = self._selected_card.phrase
            phrases_list = self.phrases.get(group, [])
            for i, p in enumerate(phrases_list):
                if p == target:
                    phrases_list.pop(i)
                    break
            save_phrases(self.phrases)
            self._refresh_cards()

    def _edit_phrase(self, idx: int):
        """打开 BlockEditor 编辑第 idx 条话术并保存。"""
        group = self.group_var.get()
        phrases_list = self.phrases.get(group, [])
        if idx >= len(phrases_list):
            return

        self.root.attributes("-topmost", False)
        editor = BlockEditor(self.root, initial_phrase=phrases_list[idx])
        result = editor.get_result()
        self.root.attributes("-topmost", True)

        if result is None:
            return
        if len(result) == 1 and result[0]["type"] == "text":
            phrases_list[idx] = result[0]["content"]
        else:
            phrases_list[idx] = result
        save_phrases(self.phrases)
        self._refresh_cards()

    def _send_custom(self):
        text = self.custom_input.get("1.0", "end").strip()
        if not text:
            self._show_warning("请输入消息内容")
            return
        self._do_send(text, on_confirm=lambda: self.custom_input.delete("1.0", "end"))

    def _do_send(self, phrase, on_confirm=None):
        """主界面发送不再弹出预览，直接执行发送。"""
        blocks = normalize_phrase(phrase)
        if on_confirm:
            on_confirm()
        self._send_blocks_async(prepare_direct_send_blocks(blocks))

    def _open_send_preview(self, blocks: list, on_confirm=None):
        variables = extract_variables(blocks)
        values = {}

        win = ctk.CTkToplevel(self.root)
        win.title("发送预览")
        win.geometry("520x560")
        win.attributes("-topmost", True)
        win.grab_set()

        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="发送预览", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=12)
        ctk.CTkButton(
            header, text="✕", width=32, height=32, corner_radius=8,
            fg_color="transparent", hover_color=PRIMARY_H,
            text_color="white", font=ctk.CTkFont(size=14),
            command=win.destroy,
        ).pack(side="right", padx=8)

        body = ctk.CTkFrame(win, fg_color=APP_BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        entry_vars = {}
        if variables:
            var_frame = ctk.CTkFrame(body, fg_color="white", corner_radius=8)
            var_frame.pack(fill="x", padx=12, pady=(12, 8))
            var_frame.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                var_frame, text="变量", anchor="w",
                font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
                text_color="#333",
            ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 4), sticky="w")
            for row, name in enumerate(variables, 1):
                ctk.CTkLabel(
                    var_frame, text=name, anchor="w",
                    font=ctk.CTkFont(family="PingFang SC", size=11),
                    text_color="#666",
                ).grid(row=row, column=0, padx=(10, 8), pady=5, sticky="w")
                sv = ctk.StringVar(value="")
                entry_vars[name] = sv
                entry = ctk.CTkEntry(
                    var_frame, textvariable=sv, height=28, corner_radius=7,
                    border_color=BORDER, placeholder_text=f"填写{name}",
                    font=ctk.CTkFont(family="PingFang SC", size=12),
                )
                entry.grid(row=row, column=1, padx=(0, 10), pady=5, sticky="ew")
                sv.trace_add("write", lambda *_: refresh_preview())
            first_entry = var_frame.grid_slaves(row=1, column=1)
            if first_entry:
                win.after(80, first_entry[0].focus_set)

        ctk.CTkLabel(
            body, text="预览内容", anchor="w",
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            text_color="#333",
        ).pack(fill="x", padx=16, pady=(6, 4))

        preview = ctk.CTkTextbox(
            body, height=230, corner_radius=8, border_width=1,
            border_color=BORDER,
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        preview.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        hint = ctk.CTkLabel(
            body,
            text="内置变量：{{日期}}、{{时间}}、{{星期}} 会自动替换。",
            text_color="#8c8c8c",
            font=ctk.CTkFont(family="PingFang SC", size=10),
        )
        hint.pack(fill="x", padx=12, pady=(0, 8))

        error_label = ctk.CTkLabel(
            body, text="", text_color=DOT_ERR,
            font=ctk.CTkFont(family="PingFang SC", size=11),
        )
        error_label.pack(fill="x", padx=12, pady=(0, 6))

        footer = ctk.CTkFrame(win, fg_color="white", height=52, corner_radius=0)
        footer.pack(fill="x")
        footer.pack_propagate(False)

        def current_values():
            return {name: var.get().strip() for name, var in entry_vars.items()}

        def preview_text(rendered_blocks):
            lines = []
            for block in rendered_blocks:
                if block.get("type") == "text":
                    content = block.get("content", "").strip()
                    if content:
                        lines.append(content)
                elif block.get("type") == "image":
                    lines.append(f"[图片] {os.path.basename(block.get('path', ''))}")
            return "\n\n".join(lines)

        def refresh_preview():
            rendered = render_template_blocks(blocks, current_values())
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("end", preview_text(rendered))
            preview.configure(state="disabled")

        def confirm_send():
            missing = [name for name, var in entry_vars.items() if not var.get().strip()]
            if missing:
                error_label.configure(text=f"请填写变量：{', '.join(missing)}")
                return
            error_label.configure(text="")
            rendered = render_template_blocks(blocks, current_values())
            win.destroy()
            if on_confirm:
                on_confirm()
            self._send_blocks_async(rendered)

        ctk.CTkButton(
            footer, text="取消", width=80, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666", hover_color="#f0f0f0",
            font=ctk.CTkFont(size=11),
            command=win.destroy,
        ).pack(side="right", padx=(4, 12), pady=10)

        ctk.CTkButton(
            footer, text="确认发送", width=96, height=32, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=confirm_send,
        ).pack(side="right", padx=4, pady=10)

        refresh_preview()

    def _send_blocks_async(self, blocks: list):
        """确认后实际发送。纯文本沿用原链路；含图片渲染为一张图片保证单条消息。"""
        client = self.current_client

        def send_task():
            try:
                send_blocks_with_client(client, blocks)
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_OK))
                self.root.after(0, lambda: self.status_label.configure(text="✅ 发送成功"))
            except UnsupportedClientAction as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_warning(msg))
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_WAIT))
                self.root.after(0, lambda: self.status_label.configure(text="接管能力待验证"))
            except NoChatWindowError as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_warning(msg))
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_WAIT))
                self.root.after(0, lambda: self.status_label.configure(text="未选中聊天窗口"))
            except FileNotFoundError as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_warning(msg))
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
                self.root.after(0, lambda: self.status_label.configure(text="❌ 图片文件不存在"))
            except Exception:
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
                self.root.after(0, lambda: self.status_label.configure(text="❌ 发送失败"))
            self.root.after(3000, self._check_status)

        threading.Thread(target=send_task, daemon=True).start()

    def _add_group(self):
        name = self._ask_input("新分组", "请输入分组名称：")
        if name and name.strip():
            name = name.strip()
            if name not in self.phrases:
                self.phrases[name] = []
                save_phrases(self.phrases)
                self.group_menu.configure(values=list(self.phrases.keys()))
                self.group_var.set(name)
                self.current_group = name
                self._refresh_cards()
            else:
                self._show_warning(f"分组「{name}」已存在")

    def _rename_group(self):
        """重命名当前分组（保持原有顺序）。"""
        old = self.group_var.get()
        if not old or old not in self.phrases:
            return
        new = self._ask_input("重命名分组", f"将「{old}」重命名为：")
        if not new or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if new in self.phrases:
            self._show_warning(f"分组「{new}」已存在")
            return
        # 重建 dict 以保持分组顺序不变
        self.phrases = {(new if k == old else k): v for k, v in self.phrases.items()}
        save_phrases(self.phrases)
        self.current_group = new
        self.group_menu.configure(values=list(self.phrases.keys()))
        self.group_var.set(new)
        self._refresh_cards()

    def _delete_group(self):
        """删除当前分组及其全部话术（至少保留一个分组）。"""
        group = self.group_var.get()
        if not group or group not in self.phrases:
            return
        if len(self.phrases) <= 1:
            self._show_warning("至少保留一个分组，无法删除最后一个分组")
            return
        count = len(self.phrases.get(group, []))
        if not self._ask_yesno(
            "确认删除分组",
            f"确定删除分组「{group}」及其 {count} 条话术吗？\n此操作不可撤销。",
        ):
            return
        self.phrases.pop(group, None)
        save_phrases(self.phrases)
        self.current_group = next(iter(self.phrases.keys()))
        self.group_menu.configure(values=list(self.phrases.keys()))
        self.group_var.set(self.current_group)
        self._refresh_cards()

    def run(self):
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  企业微信快捷发送面板")
    print("  请确保已授予辅助功能权限")
    print("=" * 50)
    app = WXSenderApp()
    app.run()
