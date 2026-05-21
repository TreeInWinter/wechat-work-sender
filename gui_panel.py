#!/usr/bin/env python3
"""
企业微信话术快捷发送面板 (macOS GUI)

依赖:
- customtkinter
- sender.py (同目录)
"""

import json
import os
import subprocess
import threading
import re
import copy

import customtkinter as ctk
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
)

from sender import send_message, is_daxiang_running, NoChatWindowError, read_chat_messages

# 颜色常量
PRIMARY   = "#1677FF"
PRIMARY_H = "#0958d9"   # hover
CARD_BG   = "#e6f0ff"   # 选中卡片背景
PANEL_BG  = "#f0f5ff"   # 面板背景
DOT_OK    = "#52c41a"
DOT_ERR   = "#ff4d4f"
DOT_WAIT  = "#faad14"

ctk.set_appearance_mode("system")   # 跟随 macOS 深色/浅色
ctk.set_default_color_theme("blue")

# ============================================================
# 话术数据管理
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")

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
    return DEFAULT_PHRASES.copy()


def save_phrases(phrases: dict):
    """保存话术库"""
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


# ============================================================
# 块编辑器
# ============================================================

class BlockEditor(ctk.CTkToplevel):
    """话术块编辑器：支持文字块和图片块的混排编辑。"""

    def __init__(self, parent, initial_phrase=None):
        super().__init__(parent)
        self.title("编辑话术")
        self.geometry("480x420")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._result = None
        self._text_widgets: dict = {}

        if initial_phrase is None:
            self.blocks = [{"type": "text", "content": ""}]
        elif isinstance(initial_phrase, str):
            self.blocks = [{"type": "text", "content": initial_phrase}]
        else:
            self.blocks = copy.deepcopy(initial_phrase)

        self._build()
        self.grab_set()

    def _build(self):
        self.blocks_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0
        )
        self.blocks_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        toolbar = ctk.CTkFrame(self, fg_color="transparent", height=48)
        toolbar.pack(fill="x", padx=10, pady=8)
        toolbar.pack_propagate(False)

        ctk.CTkButton(
            toolbar, text="＋文字", width=80, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=PRIMARY,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12),
            command=self._add_text_block,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            toolbar, text="＋图片", width=80, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=PRIMARY,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12),
            command=self._add_image_block,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="取消", width=64, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666",
            command=self.destroy,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            toolbar, text="确认", width=64, height=32, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H, text_color="white",
            command=self._confirm,
        ).pack(side="right")

        self._refresh_blocks()

    def _refresh_blocks(self):
        self._sync_text_widgets()
        for w in self.blocks_frame.winfo_children():
            w.destroy()
        self._text_widgets = {}
        for i, block in enumerate(self.blocks):
            self._render_block(i, block)

    def _render_block(self, i: int, block: dict):
        row = ctk.CTkFrame(self.blocks_frame, fg_color="#f8f8f8", corner_radius=8)
        row.pack(fill="x", pady=(0, 6))

        ctrl = ctk.CTkFrame(row, fg_color="transparent", width=76)
        ctrl.pack(side="right", padx=4, pady=4)
        ctrl.pack_propagate(False)

        ctk.CTkButton(
            ctrl, text="🗑", width=28, height=26, corner_radius=6,
            fg_color="transparent", text_color="#ff4d4f",
            command=lambda idx=i: self._delete_block(idx),
        ).pack(pady=(0, 2))
        if i > 0:
            ctk.CTkButton(
                ctrl, text="↑", width=28, height=26, corner_radius=6,
                fg_color="transparent", text_color="#666",
                command=lambda idx=i: self._move_block(idx, -1),
            ).pack(pady=1)
        if i < len(self.blocks) - 1:
            ctk.CTkButton(
                ctrl, text="↓", width=28, height=26, corner_radius=6,
                fg_color="transparent", text_color="#666",
                command=lambda idx=i: self._move_block(idx, 1),
            ).pack(pady=1)

        if block["type"] == "text":
            tb = ctk.CTkTextbox(
                row, height=80, corner_radius=6,
                font=ctk.CTkFont(family="PingFang SC", size=12),
                border_width=1, border_color="#e0e0e0",
            )
            tb.pack(fill="x", padx=(8, 4), pady=8)
            tb.insert("end", block.get("content", ""))
            self._text_widgets[i] = tb
        elif block["type"] == "image":
            name = os.path.basename(block.get("path", "")) or "（未选择）"
            ctk.CTkLabel(
                row, text=f"🖼  {name}", anchor="w",
                font=ctk.CTkFont(family="PingFang SC", size=12),
                text_color="#555",
            ).pack(fill="x", padx=(10, 4), pady=12)

    def _sync_text_widgets(self):
        for i, tb in self._text_widgets.items():
            if i < len(self.blocks) and self.blocks[i]["type"] == "text":
                try:
                    self.blocks[i]["content"] = tb.get("1.0", "end").strip()
                except Exception:
                    pass

    def _add_text_block(self):
        self._sync_text_widgets()
        self.blocks.append({"type": "text", "content": ""})
        self._refresh_blocks()

    def _add_image_block(self):
        from tkinter import filedialog
        self._sync_text_widgets()
        path = filedialog.askopenfilename(
            parent=self,
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks.append({"type": "image", "path": path})
            self._refresh_blocks()

    def _delete_block(self, i: int):
        self._sync_text_widgets()
        self.blocks.pop(i)
        self._refresh_blocks()

    def _move_block(self, i: int, direction: int):
        self._sync_text_widgets()
        j = i + direction
        if 0 <= j < len(self.blocks):
            self.blocks[i], self.blocks[j] = self.blocks[j], self.blocks[i]
        self._refresh_blocks()

    def _confirm(self):
        self._sync_text_widgets()
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
    SELECTED_BG    = "#e6f0ff"
    SELECTED_BORDER = "#bbd6ff"

    def __init__(self, parent, text: str, on_send, on_select, **kwargs):
        super().__init__(parent, corner_radius=10, fg_color=self.NORMAL_BG,
                         border_width=1, border_color="#e8e8e8", **kwargs)
        self._text = text
        self._on_send = on_send
        self._on_select = on_select
        self._selected = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        self._label = ctk.CTkLabel(
            self, text=self._text, wraplength=240,
            justify="left", anchor="w",
            text_color="#333",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        self._label.grid(row=0, column=0, padx=(10, 6), pady=8, sticky="ew")

        self._send_btn = ctk.CTkButton(
            self, text="发送", width=44, height=26,
            corner_radius=6, fg_color=CARD_BG,
            text_color=PRIMARY, hover_color="#bbd6ff",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_send,
        )
        self._send_btn.grid(row=0, column=1, padx=(0, 8), pady=8)

        self._label.bind("<Button-1>", lambda e: self._on_select(self))
        self.bind("<Button-1>", lambda e: self._on_select(self))

    @property
    def text(self) -> str:
        return self._text

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
                                      hover_color="#bbd6ff")


# ============================================================
# GUI 应用
# ============================================================

class DaxiangSenderApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("企业微信快捷发送")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        self.phrases = load_phrases()
        self.current_group = list(self.phrases.keys())[0] if self.phrases else ""
        self._selected_card = None  # 当前选中的卡片

        bounds = get_wechat_window_bounds()
        if bounds:
            wx, wy, ww, wh = bounds
            self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
        else:
            self.root.geometry("420x600")
        self._last_bounds = bounds

        self._build_ui()
        self.root.after(100, self._poll_snap)

    def _build_ui(self):
        # ── 状态栏 ──
        status_frame = ctk.CTkFrame(self.root, height=48, corner_radius=0, fg_color=PRIMARY)
        status_frame.pack(fill="x")
        status_frame.pack_propagate(False)

        left = ctk.CTkFrame(status_frame, fg_color="transparent")
        left.pack(side="left", padx=12, pady=12)

        self.status_dot = ctk.CTkLabel(left, text="●", text_color=DOT_WAIT,
                                        font=ctk.CTkFont(size=10), width=14)
        self.status_dot.pack(side="left")

        self.status_label = ctk.CTkLabel(left, text="检测中...",
                                          text_color="white",
                                          font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"))
        self.status_label.pack(side="left", padx=(4, 0))

        ctk.CTkButton(status_frame, text="↻", width=32, height=32,
                       corner_radius=8, fg_color="transparent",
                       hover_color=PRIMARY_H, text_color="white",
                       font=ctk.CTkFont(size=16),
                       command=self._check_status).pack(side="right", padx=8)

        # ── 分组选择 ──
        group_frame = ctk.CTkFrame(self.root, fg_color="transparent")
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

        ctk.CTkButton(group_frame, text="+ 新分组", width=64, height=28,
                       corner_radius=8, fg_color="transparent",
                       border_width=1, border_color=PRIMARY,
                       text_color=PRIMARY, hover_color=CARD_BG,
                       font=ctk.CTkFont(size=11),
                       command=self._add_group).pack(side="right")

        # ── 话术卡片列表 ──
        self.cards_frame = ctk.CTkScrollableFrame(
            self.root, fg_color=PANEL_BG, corner_radius=0,
            scrollbar_button_color=PRIMARY,
            scrollbar_button_hover_color=PRIMARY_H,
        )
        self.cards_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.cards_frame.grid_columnconfigure(0, weight=1)

        # ── 操作按钮 ──
        btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
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
        ctk.CTkFrame(self.root, height=1, fg_color="#dce8ff", corner_radius=0).pack(
            fill="x", padx=12, pady=(2, 8))

        # ── 自定义消息 ──
        bottom_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=12, pady=(0, 10))

        self.custom_input = ctk.CTkTextbox(
            bottom_frame, height=60, corner_radius=10,
            border_width=1, border_color="#dce8ff",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        self.custom_input.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            bottom_frame, text="发送自定义消息", height=36, corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=self._send_custom,
        ).pack(fill="x", pady=(0, 5))

        ctk.CTkButton(
            bottom_frame, text="📋 读取聊天内容", height=34, corner_radius=10,
            fg_color="transparent", border_width=1, border_color="#dce8ff",
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=self._read_chat,
        ).pack(fill="x")

        # ── 初始化 ──
        self._refresh_cards()
        self._check_status()

    def _refresh_cards(self):
        for widget in self.cards_frame.winfo_children():
            widget.destroy()
        self._selected_card = None
        group = self.group_var.get()
        for phrase in self.phrases.get(group, []):
            card = PhraseCard(
                self.cards_frame,
                text=phrase,
                on_send=lambda p=phrase: self._do_send(p),
                on_select=self._select_card,
            )
            card.pack(fill="x", pady=(0, 5))

    def _select_card(self, card: "PhraseCard"):
        if self._selected_card and self._selected_card != card:
            self._selected_card.set_selected(False)
        self._selected_card = card
        card.set_selected(True)

    def _on_group_change(self, value=None):
        self.current_group = self.group_var.get()
        self._refresh_cards()

    def _poll_snap(self):
        """每 100ms 直接在主线程读取窗口坐标（AX API 调用 <5ms，无需后台线程）"""
        bounds = get_wechat_window_bounds()
        if bounds and bounds != self._last_bounds:
            self._last_bounds = bounds
            wx, wy, ww, wh = bounds
            self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
        self.root.after(100, self._poll_snap)

    def _check_status(self):
        """检查企业微信状态"""
        def check():
            running = is_daxiang_running()
            self.root.after(0, lambda: self._update_status(running))

        threading.Thread(target=check, daemon=True).start()

    def _update_status(self, running: bool):
        if running:
            self.status_dot.configure(text_color=DOT_OK)
            self.status_label.configure(text="企业微信已连接")
        else:
            self.status_dot.configure(text_color=DOT_ERR)
            self.status_label.configure(text="企业微信未运行")

    # ── 辅助：对话框在 topmost 窗口下的兼容方法 ──────────────────
    # macOS 上 CTk -topmost 窗口处于 NSFloatingWindowLevel，
    # tkinter 原生 simpledialog/messagebox 是 NSNormalWindowLevel，
    # 会被 CTk 窗口遮挡。修复方式：
    #   - 文本输入 → ctk.CTkInputDialog（CTk 层级，可见）
    #   - 警告/确认 → 弹出前临时关闭 topmost，结束后恢复

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

    def _ask_yesno(self, title: str, message: str) -> bool:
        """弹出确认框，临时关闭 topmost 确保可见"""
        self.root.attributes("-topmost", False)
        result = messagebox.askyesno(title, message)
        self.root.attributes("-topmost", True)
        return result

    # ── 话术管理 ─────────────────────────────────────────────────

    def _add_phrase(self):
        text = self._ask_input("添加话术", "请输入话术内容：")
        if text and text.strip():
            group = self.group_var.get()
            self.phrases.setdefault(group, []).append(text.strip())
            save_phrases(self.phrases)
            self._refresh_cards()

    def _delete_phrase(self):
        if not self._selected_card:
            self._show_warning("请先选中要删除的话术")
            return
        if self._ask_yesno("确认", "确定要删除这条话术吗？"):
            group = self.group_var.get()
            phrase = self._selected_card.text
            if phrase in self.phrases.get(group, []):
                self.phrases[group].remove(phrase)
                save_phrases(self.phrases)
                self._refresh_cards()

    def _send_custom(self):
        text = self.custom_input.get("1.0", "end").strip()
        if not text:
            self._show_warning("请输入消息内容")
            return
        self._do_send(text)
        self.custom_input.delete("1.0", "end")

    def _do_send(self, text: str):
        def send_task():
            try:
                send_message(text)
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_OK))
                self.root.after(0, lambda: self.status_label.configure(text="✅ 发送成功"))
            except NoChatWindowError as e:
                msg = str(e)
                self.root.after(0, lambda: self._show_warning(msg))
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_WAIT))
                self.root.after(0, lambda: self.status_label.configure(text="未选中聊天窗口"))
            except Exception:
                self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
                self.root.after(0, lambda: self.status_label.configure(text="❌ 发送失败"))
            self.root.after(3000, self._check_status)
        threading.Thread(target=send_task, daemon=True).start()

    def _read_chat(self):
        """读取企业微信当前聊天内容并弹窗展示"""
        self.status_label.configure(text="⏳ 读取中...")

        def fetch():
            msgs = read_chat_messages(max_messages=30)
            self.root.after(0, lambda: self._show_chat_popup(msgs))

        threading.Thread(target=fetch, daemon=True).start()

    def _show_chat_popup(self, msgs: list):
        self._check_status()
        win = ctk.CTkToplevel(self.root)
        win.title("聊天内容")
        win.geometry("500x480")
        win.attributes("-topmost", True)

        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=f"共 {len(msgs)} 条消息",
                      text_color="white",
                      font=ctk.CTkFont(family="PingFang SC", size=12)).pack(
            side="left", padx=12, pady=12)
        ctk.CTkButton(header, text="✕", width=32, height=32, corner_radius=8,
                       fg_color="transparent", hover_color=PRIMARY_H,
                       text_color="white", font=ctk.CTkFont(size=14),
                       command=win.destroy).pack(side="right", padx=8)

        text_widget = ctk.CTkTextbox(
            win, corner_radius=0, border_width=0,
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
        text_widget.pack(fill="both", expand=True, padx=10, pady=10)

        if not msgs:
            text_widget.insert("end", "未读取到消息，请先在企业微信中选中聊天窗口。")
        else:
            for m in msgs:
                time_str = f"[{m['time']}]  " if m['time'] else ""
                text_widget.insert("end", f"{time_str}{m['content']}\n\n")
        text_widget.configure(state="disabled")

    def _add_group(self):
        name = self._ask_input("新分组", "请输入分组名称：")
        if name and name.strip():
            name = name.strip()
            if name not in self.phrases:
                self.phrases[name] = []
                save_phrases(self.phrases)
                self.group_menu.configure(values=list(self.phrases.keys()))
                self.group_var.set(name)
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
    app = DaxiangSenderApp()
    app.run()
