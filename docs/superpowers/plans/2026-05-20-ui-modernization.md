# UI 现代化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 gui_panel.py 从原生 tkinter 迁移到 CustomTkinter，实现品牌蓝配色 + 话术卡片式一键发送。

**Architecture:** 保留 sender.py 及所有非 UI 逻辑（snap/poll、phrases 管理）不变。只重写 gui_panel.py 的 UI 部分，用 CustomTkinter 控件替换所有 tkinter 控件，新增 `PhraseCard` 组件类封装单条话术卡片。

**Tech Stack:** Python 3.13, customtkinter, pyobjc-framework-ApplicationServices, AppKit

---

## 文件结构

| 文件 | 变更 | 说明 |
|------|------|------|
| `gui_panel.py` | 重写 | 全部控件换成 CTk，新增 PhraseCard 类 |
| `sender.py` | 不变 | 发送逻辑与 UI 完全解耦 |

---

## Task 1：创建分支 + 安装 CustomTkinter

**Files:**
- 无代码变更，环境准备

- [ ] **Step 1: 从 master 创建新分支**

```bash
git checkout master
git checkout -b feature/ui-modernization
git push -u origin feature/ui-modernization
```

- [ ] **Step 2: 安装 customtkinter**

```bash
cd /Users/baijinshan/Desktop/coffe_hours/wechat_work_sender
uv pip install customtkinter --python .venv/bin/python
```

- [ ] **Step 3: 验证安装**

```bash
.venv/bin/python -c "import customtkinter as ctk; print(ctk.__version__)"
```

Expected: 打印版本号，无报错（如 `5.2.x`）

- [ ] **Step 4: 提交环境记录**

```bash
git commit --allow-empty -m "chore: add customtkinter dependency"
```

---

## Task 2：重建主窗口与常量

**Files:**
- Modify: `gui_panel.py`（头部 import、常量、`__init__`）

- [ ] **Step 1: 替换 import 区**

将 `gui_panel.py` 顶部替换为：

```python
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
```

- [ ] **Step 2: 保留 phrases 管理函数不变**

`SCRIPT_DIR`、`DATA_FILE`、`DEFAULT_PHRASES`、`get_wechat_window_bounds()`、`load_phrases()`、`save_phrases()` 这些函数无需修改，保持原样。

- [ ] **Step 3: 更新 `DaxiangSenderApp.__init__`**

```python
class DaxiangSenderApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("企业微信快捷发送")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        self.phrases = load_phrases()
        self.current_group = list(self.phrases.keys())[0] if self.phrases else ""
        self._selected_card: "PhraseCard | None" = None  # 当前选中的卡片

        bounds = get_wechat_window_bounds()
        if bounds:
            wx, wy, ww, wh = bounds
            self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
        else:
            self.root.geometry("420x600")
        self._last_bounds = bounds

        self._build_ui()
        self.root.after(100, self._poll_snap)

    def run(self):
        self.root.mainloop()
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: replace tkinter imports with customtkinter, add color constants"
```

---

## Task 3：重建状态栏

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 状态栏部分、`_update_status`）

- [ ] **Step 1: 用 CTkFrame 重建状态栏**

在 `_build_ui` 方法开头写入：

```python
def _build_ui(self):
    # ── 状态栏 ──
    status_frame = ctk.CTkFrame(self.root, height=48, corner_radius=0, fg_color=PRIMARY)
    status_frame.pack(fill="x")
    status_frame.pack_propagate(False)

    # 左侧：状态圆点 + 标题
    left = ctk.CTkFrame(status_frame, fg_color="transparent")
    left.pack(side="left", padx=12, pady=12)

    self.status_dot = ctk.CTkLabel(left, text="●", text_color=DOT_WAIT,
                                    font=ctk.CTkFont(size=10), width=14)
    self.status_dot.pack(side="left")

    self.status_label = ctk.CTkLabel(left, text="检测中...",
                                      text_color="white",
                                      font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"))
    self.status_label.pack(side="left", padx=(4, 0))

    # 右侧：刷新按钮
    ctk.CTkButton(status_frame, text="↻", width=32, height=32,
                   corner_radius=8, fg_color="transparent",
                   hover_color=PRIMARY_H, text_color="white",
                   font=ctk.CTkFont(size=16),
                   command=self._check_status).pack(side="right", padx=8)
```

- [ ] **Step 2: 更新 `_update_status` 方法**

```python
def _update_status(self, running: bool):
    if running:
        self.status_dot.configure(text_color=DOT_OK)
        self.status_label.configure(text="企业微信已连接")
    else:
        self.status_dot.configure(text_color=DOT_ERR)
        self.status_label.configure(text="企业微信未运行")
```

- [ ] **Step 3: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 4: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: rebuild status bar with CTkFrame and dot indicator"
```

---

## Task 4：重建分组选择器

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 分组区、`_on_group_change`、`_add_group`、`_refresh_cards`）

- [ ] **Step 1: 用 CTkOptionMenu 重建分组选择区**

在状态栏代码之后，继续写入 `_build_ui`：

```python
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
```

- [ ] **Step 2: 更新 `_on_group_change`**

```python
def _on_group_change(self, value=None):
    self.current_group = self.group_var.get()
    self._refresh_cards()
```

- [ ] **Step 3: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 4: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: rebuild group selector with CTkOptionMenu"
```

---

## Task 5：PhraseCard 组件

**Files:**
- Modify: `gui_panel.py`（新增 `PhraseCard` 类，在 `DaxiangSenderApp` 之前）

- [ ] **Step 1: 新增 PhraseCard 类**

在 `DaxiangSenderApp` 类定义之前插入：

```python
class PhraseCard(ctk.CTkFrame):
    """单条话术卡片：左侧文本 + 右侧发送按钮"""

    NORMAL_BG   = "white"
    SELECTED_BG = "#e6f0ff"
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

        # 点击卡片本体 → 选中
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
```

- [ ] **Step 2: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 3: 提交**

```bash
git add gui_panel.py
git commit -m "feat: add PhraseCard component with select/send state"
```

---

## Task 6：话术卡片列表

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 列表区、`_refresh_cards`、`_select_card`）

- [ ] **Step 1: 用 CTkScrollableFrame 重建列表区**

在分组选择代码之后，继续写入 `_build_ui`：

```python
    # ── 话术卡片列表 ──
    self.cards_frame = ctk.CTkScrollableFrame(
        self.root, fg_color=PANEL_BG, corner_radius=0,
        scrollbar_button_color=PRIMARY,
        scrollbar_button_hover_color=PRIMARY_H,
    )
    self.cards_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
    self.cards_frame.grid_columnconfigure(0, weight=1)
```

- [ ] **Step 2: 新增 `_refresh_cards` 方法**

```python
def _refresh_cards(self):
    """清空并重建当前分组的话术卡片"""
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
```

- [ ] **Step 3: 新增 `_select_card` 方法**

```python
def _select_card(self, card: PhraseCard):
    """切换卡片选中状态"""
    if self._selected_card and self._selected_card != card:
        self._selected_card.set_selected(False)
    self._selected_card = card
    card.set_selected(True)
```

- [ ] **Step 4: 在 `_build_ui` 末尾初始化卡片**

```python
    # 初始化
    self._refresh_cards()
    self._check_status()
```

- [ ] **Step 5: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 6: 提交**

```bash
git add gui_panel.py
git commit -m "feat: rebuild phrase list as scrollable card layout"
```

---

## Task 7：操作按钮区

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 按钮区、`_add_phrase`、`_delete_phrase`）

- [ ] **Step 1: 用 CTkButton 重建操作按钮**

在卡片列表代码之后，继续写入 `_build_ui`：

```python
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
```

- [ ] **Step 2: 更新 `_add_phrase`**

```python
def _add_phrase(self):
    text = simpledialog.askstring("添加话术", "请输入话术内容：", parent=self.root)
    if text and text.strip():
        group = self.group_var.get()
        self.phrases.setdefault(group, []).append(text.strip())
        save_phrases(self.phrases)
        self._refresh_cards()
```

- [ ] **Step 3: 更新 `_delete_phrase`**

```python
def _delete_phrase(self):
    if not self._selected_card:
        messagebox.showwarning("提示", "请先选中要删除的话术", parent=self.root)
        return
    if messagebox.askyesno("确认", "确定要删除这条话术吗？", parent=self.root):
        group = self.group_var.get()
        phrase = self._selected_card.text
        if phrase in self.phrases.get(group, []):
            self.phrases[group].remove(phrase)
            save_phrases(self.phrases)
            self._refresh_cards()
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: rebuild action buttons with CTkButton"
```

---

## Task 8：自定义消息区 + 读取聊天按钮

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 底部区域、`_send_custom`、`_read_chat`、`_show_chat_popup`）

- [ ] **Step 1: 用 CTkTextbox + CTkButton 重建底部区域**

在操作按钮代码之后，继续写入 `_build_ui`：

```python
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
```

- [ ] **Step 2: 更新 `_send_custom`**

```python
def _send_custom(self):
    text = self.custom_input.get("1.0", "end").strip()
    if not text:
        messagebox.showwarning("提示", "请输入消息内容", parent=self.root)
        return
    self._do_send(text)
    self.custom_input.delete("1.0", "end")
```

- [ ] **Step 3: 更新 `_show_chat_popup`（用 CTkToplevel）**

```python
def _show_chat_popup(self, msgs: list):
    self._check_status()
    win = ctk.CTkToplevel(self.root)
    win.title("聊天内容")
    win.geometry("500x480")
    win.attributes("-topmost", True)

    # 标题栏
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

    # 消息文本区
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
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: rebuild custom message area and chat popup with CTk"
```

---

## Task 9：保留 snap/poll 与 _do_send 逻辑

**Files:**
- Modify: `gui_panel.py`（`_poll_snap`、`_do_send`、`_check_status`、`_add_group`）

这些方法逻辑不变，只需确认它们不依赖被移除的 tkinter 控件。

- [ ] **Step 1: 确认 `_poll_snap` 无需改动**

`_poll_snap` 调用 `get_wechat_window_bounds()` 和 `self.root.geometry()`，两者在 CTk 中完全兼容，无需修改。

- [ ] **Step 2: 更新 `_do_send` 状态反馈（用 status_dot）**

```python
def _do_send(self, text: str):
    def send_task():
        try:
            send_message(text)
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_OK))
            self.root.after(0, lambda: self.status_label.configure(text="✅ 发送成功"))
        except NoChatWindowError as e:
            msg = str(e)
            self.root.after(0, lambda: messagebox.showwarning("提示", msg))
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_WAIT))
            self.root.after(0, lambda: self.status_label.configure(text="未选中聊天窗口"))
        except Exception:
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
            self.root.after(0, lambda: self.status_label.configure(text="❌ 发送失败"))
        self.root.after(3000, self._check_status)

    threading.Thread(target=send_task, daemon=True).start()
```

- [ ] **Step 3: 更新 `_add_group`**

```python
def _add_group(self):
    name = simpledialog.askstring("新分组", "请输入分组名称：", parent=self.root)
    if name and name.strip():
        name = name.strip()
        if name not in self.phrases:
            self.phrases[name] = []
            save_phrases(self.phrases)
            self.group_menu.configure(values=list(self.phrases.keys()))
            self.group_var.set(name)
            self._refresh_cards()
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "refactor: update _do_send and _add_group for CTk compatibility"
```

---

## Task 10：入口函数 + 端到端手动验证

**Files:**
- Modify: `gui_panel.py`（`__main__` 入口）

- [ ] **Step 1: 更新入口**

```python
if __name__ == "__main__":
    print("=" * 50)
    print("  企业微信快捷发送面板")
    print("  请确保已授予辅助功能权限")
    print("=" * 50)
    app = DaxiangSenderApp()
    app.run()
```

- [ ] **Step 2: 启动应用验证**

```bash
.venv/bin/python gui_panel.py
```

逐项检查：
- [ ] 面板贴合企业微信右侧，高度与企业微信一致
- [ ] 状态栏蓝色背景、绿色圆点、白色标题
- [ ] 分组下拉列表正常显示所有分组
- [ ] 话术以卡片形式显示，右侧有「发送」按钮
- [ ] 点击卡片本体 → 选中（蓝色高亮）
- [ ] 点击卡片「发送」→ 消息发到企业微信
- [ ] 无聊天窗口时点发送 → 弹窗提示「请先在企业微信中选中聊天窗口」
- [ ] 添加话术 → 新卡片出现
- [ ] 删除话术 → 选中后删除成功
- [ ] 自定义消息输入后点发送 → 消息发出，输入框清空
- [ ] 读取聊天内容 → 弹窗显示消息列表
- [ ] macOS 切换深色模式 → 面板自动适配

- [ ] **Step 3: 提交**

```bash
git add gui_panel.py
git commit -m "feat: complete CustomTkinter migration, modern UI"
```

- [ ] **Step 4: 推送**

```bash
git push
```
