# 本地知识库集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 回复生成时，可选地把 Obsidian vault 目录通过 `--add-dir` 传给 `mc --code`，让模型自主读取相关知识文档。

**Architecture:** 新建 `config.py` 统一管理持久化配置（kb_enabled / kb_vault_path）。`ai_reply.py` 根据 KB 开关切换命令行参数。`gui_panel.py` 在 Header 增加 ⚙ 设置入口，在 AI 视图增加知识库状态行。

**Tech Stack:** Python 3.10+, CustomTkinter 5.2.x, tkinter.filedialog, subprocess, json, unittest

---

## 文件改动总览

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `config.py` | 配置读写（kb_enabled, kb_vault_path） |
| 新建 | `tests/test_config.py` | config.py 单元测试 |
| 修改 | `ai_reply.py` | AIReplyConfig 加 KB 字段；generate_reply 切换 args；build_reply_prompt 加 KB 引导 |
| 修改 | `tests/test_ai_reply.py` | 补充 KB 相关测试用例 |
| 修改 | `gui_panel.py` | 引入 config；加载配置；KB 状态行；⚙ 按钮；settings 弹窗；_ai_generate_async 传 config |

---

## Task 1：config.py — 配置读写模块

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1：写失败测试**

```python
# tests/test_config.py
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config as cfg


class LoadConfigTests(unittest.TestCase):
    def test_returns_defaults_when_file_missing(self):
        with patch.object(cfg, "CONFIG_FILE", "/nonexistent/path/config.json"):
            result = cfg.load_config()
        self.assertFalse(result["kb_enabled"])
        self.assertEqual(result["kb_vault_path"], "")

    def test_loads_saved_values(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"kb_enabled": True, "kb_vault_path": "/tmp/vault"}, f)
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertTrue(result["kb_enabled"])
            self.assertEqual(result["kb_vault_path"], "/tmp/vault")
        finally:
            os.unlink(fname)

    def test_returns_defaults_on_corrupt_json(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("not json {{{")
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertFalse(result["kb_enabled"])
        finally:
            os.unlink(fname)

    def test_missing_keys_filled_with_defaults(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"kb_enabled": True}, f)   # kb_vault_path 缺失
            fname = f.name
        try:
            with patch.object(cfg, "CONFIG_FILE", fname):
                result = cfg.load_config()
            self.assertEqual(result["kb_vault_path"], "")  # 补默认值
        finally:
            os.unlink(fname)


class SaveConfigTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "config.json")
            with patch.object(cfg, "CONFIG_FILE", fpath):
                cfg.save_config({"kb_enabled": True, "kb_vault_path": "/my/vault"})
                result = cfg.load_config()
            self.assertTrue(result["kb_enabled"])
            self.assertEqual(result["kb_vault_path"], "/my/vault")

    def test_partial_update_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "config.json")
            with patch.object(cfg, "CONFIG_FILE", fpath):
                cfg.save_config({"kb_vault_path": "/v"})
                cfg.save_config({"kb_enabled": True})
                result = cfg.load_config()
            self.assertEqual(result["kb_vault_path"], "/v")
            self.assertTrue(result["kb_enabled"])
```

- [ ] **Step 2：运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_config.py -v
```
预期：`ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3：实现 config.py**

```python
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
```

- [ ] **Step 4：运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_config.py -v
```
预期：`8 passed`

- [ ] **Step 5：提交**

```bash
git add config.py tests/test_config.py
git commit -m "feat: config.py — KB 配置读写模块"
```

---

## Task 2：ai_reply.py — KB 字段与参数切换

**Files:**
- Modify: `ai_reply.py`
- Modify: `tests/test_ai_reply.py`

- [ ] **Step 1：写失败测试（在 tests/test_ai_reply.py 末尾追加）**

```python
# 在文件末尾追加：
class BuildReplyPromptKBTests(unittest.TestCase):
    def test_no_kb_preamble_when_disabled(self):
        prompt = build_reply_prompt([{"content": "你好"}], kb_enabled=False)
        self.assertNotIn("知识库", prompt)

    def test_kb_preamble_present_when_enabled(self):
        prompt = build_reply_prompt([{"content": "你好"}], kb_enabled=True)
        self.assertIn("知识库", prompt)
        self.assertIn("检索相关文档", prompt)


class GenerateReplyKBTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_kb_enabled_uses_add_dir_and_no_tools_flag(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="回复内容", stderr=""
        )
        config = AIReplyConfig(
            command="mc", timeout=5,
            kb_enabled=True, kb_vault_path="/tmp",
        )
        generate_reply([{"content": "问题"}], config)
        cmd = run_mock.call_args.args[0]
        self.assertIn("--add-dir", cmd)
        self.assertIn("/tmp", cmd)
        self.assertNotIn("--tools", cmd)

    @patch("ai_reply.subprocess.run")
    def test_kb_disabled_uses_tools_empty_arg(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="回复内容", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5, kb_enabled=False)
        generate_reply([{"content": "问题"}], config)
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--add-dir", cmd)
        self.assertIn("--tools", cmd)

    def test_kb_enabled_with_empty_path_raises(self):
        config = AIReplyConfig(command="mc", timeout=5, kb_enabled=True, kb_vault_path="")
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "问题"}], config)

    def test_kb_enabled_with_nonexistent_path_raises(self):
        config = AIReplyConfig(
            command="mc", timeout=5,
            kb_enabled=True, kb_vault_path="/nonexistent/vault/xyz",
        )
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "问题"}], config)
```

- [ ] **Step 2：运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py::BuildReplyPromptKBTests tests/test_ai_reply.py::GenerateReplyKBTests -v
```
预期：`TypeError: build_reply_prompt() got an unexpected keyword argument 'kb_enabled'`

- [ ] **Step 3：修改 AIReplyConfig（在 ai_reply.py 的 AIReplyConfig dataclass 中追加两个字段）**

找到：
```python
    timeout: int = 60
    max_messages: int = 20
```
替换为：
```python
    timeout: int = 60
    max_messages: int = 20
    kb_enabled: bool = False
    kb_vault_path: str = ""
```

- [ ] **Step 4：修改 build_reply_prompt（加 kb_enabled 参数与 KB 引导段）**

找到：
```python
def build_reply_prompt(messages: list[dict], max_messages: int = 20) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    return (
        "你是 IM 聊天回复助手。请根据下面最近的聊天记录，生成一段可以直接发送的中文回复。\n\n"
```
替换为：
```python
def build_reply_prompt(
    messages: list[dict], max_messages: int = 20, kb_enabled: bool = False
) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    kb_preamble = (
        "你可以访问本地知识库目录中的文档。请先根据聊天内容在知识库中检索相关文档，"
        "结合检索结果和聊天上下文，生成一段可以直接发送的中文回复。\n\n"
        if kb_enabled
        else ""
    )
    return (
        f"{kb_preamble}"
        "你是 IM 聊天回复助手。请根据下面最近的聊天记录，生成一段可以直接发送的中文回复。\n\n"
```

- [ ] **Step 5：修改 generate_reply（KB 校验 + 条件 args）**

找到：
```python
    prompt = build_reply_prompt(messages, max_messages=config.max_messages)
    cmd = [config.command, *config.args, prompt]
```
替换为：
```python
    if config.kb_enabled:
        if not config.kb_vault_path:
            raise AICommandFailedError(
                "知识库已启用但未配置路径，请在设置中选择 Obsidian vault 文件夹"
            )
        if not os.path.isdir(config.kb_vault_path):
            raise AICommandFailedError(
                f"知识库路径不存在或不是目录：{config.kb_vault_path}"
            )

    prompt = build_reply_prompt(
        messages, max_messages=config.max_messages, kb_enabled=config.kb_enabled
    )
    if config.kb_enabled:
        cmd = [
            config.command, "--code", "-p",
            "--add-dir", config.kb_vault_path,
            "--no-session-persistence",
            prompt,
        ]
    else:
        cmd = [config.command, *config.args, prompt]
```

- [ ] **Step 6：运行全部 ai_reply 测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py -v
```
预期：全部 pass（原有测试 + 新增 6 个）

- [ ] **Step 7：提交**

```bash
git add ai_reply.py tests/test_ai_reply.py
git commit -m "feat: ai_reply 支持 KB --add-dir 模式"
```

---

## Task 3：gui_panel.py — 引入配置 + KB 状态行

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1：在 gui_panel.py 顶部 import 区添加 config 和 AIReplyConfig**

找到：
```python
from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    generate_reply,
)
```
替换为：
```python
from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
    generate_reply,
)
from config import load_config, save_config
```

- [ ] **Step 2：在 App.__init__ 里加载配置**

找到（约第 704 行）：
```python
        self._ai_messages = []
        self._ai_generating = False
```
替换为：
```python
        self._ai_messages = []
        self._ai_generating = False
        self._app_config = load_config()
```

- [ ] **Step 3：在 _build_ai_view 里动作按钮之后插入 KB 状态行**

找到：
```python
        self.ai_status_label = ctk.CTkLabel(
            self.ai_view, text="选中当前接管对象聊天后，读取会话并生成回复。",
```
在其**之前**插入：
```python
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

```

- [ ] **Step 4：添加 _update_kb_row 方法（紧接 _build_ai_view 之后）**

找到：
```python
    def _ai_set_status(self, text: str):
```
在其**之前**插入：
```python
    def _update_kb_row(self):
        """根据当前配置刷新知识库状态行外观。"""
        cfg = self._app_config
        if cfg.get("kb_enabled") and cfg.get("kb_vault_path"):
            vault_name = os.path.basename(cfg["kb_vault_path"]) or cfg["kb_vault_path"]
            self.kb_row.configure(fg_color="#f6ffed", border_color="#b7eb8f")
            self.kb_row_label.configure(
                text=f"📗 知识库已启用 · {vault_name}", text_color="#389e0d"
            )
        else:
            self.kb_row.configure(fg_color="#fafafa", border_color="#e8e8e8")
            self.kb_row_label.configure(
                text="📂 知识库未启用 — 点击设置", text_color="#aaa"
            )

```

- [ ] **Step 5：修改 _ai_generate_async 使用 AIReplyConfig 传入 KB 参数**

找到：
```python
        def generate_task():
            try:
                reply = generate_reply(msgs)
```
替换为：
```python
        ai_config = AIReplyConfig(
            kb_enabled=self._app_config.get("kb_enabled", False),
            kb_vault_path=self._app_config.get("kb_vault_path", ""),
        )

        def generate_task():
            try:
                reply = generate_reply(msgs, ai_config)
```

- [ ] **Step 6：语法检查**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```
预期：`OK`

- [ ] **Step 7：提交**

```bash
git add gui_panel.py
git commit -m "feat: gui — 引入 config，KB 状态行，_ai_generate_async 传 KB 参数"
```

---

## Task 4：gui_panel.py — ⚙ 按钮 + 设置弹窗

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1：在 Header 最右侧（`↻` 刷新按钮左边）加 ⚙ 按钮**

找到：
```python
        ctk.CTkButton(status_frame, text="↻", width=32, height=32,
                       corner_radius=8, fg_color="transparent",
                       hover_color=PRIMARY_H, text_color="white",
                       font=ctk.CTkFont(size=16),
                       command=self._refresh_targets_and_status).pack(side="right", padx=8)
```
替换为：
```python
        ctk.CTkButton(status_frame, text="↻", width=32, height=32,
                       corner_radius=8, fg_color="transparent",
                       hover_color=PRIMARY_H, text_color="white",
                       font=ctk.CTkFont(size=16),
                       command=self._refresh_targets_and_status).pack(side="right", padx=8)

        ctk.CTkButton(status_frame, text="⚙", width=32, height=32,
                       corner_radius=8, fg_color="transparent",
                       hover_color=PRIMARY_H, text_color="white",
                       font=ctk.CTkFont(size=15),
                       command=self._show_ai_settings).pack(side="right", padx=(0, 2))
```

- [ ] **Step 2：添加 _show_ai_settings 方法**

在 `_update_kb_row` 之后插入：

```python
    def _show_ai_settings(self):
        """弹出 AI 知识库设置窗口。"""
        self.root.attributes("-topmost", False)
        win = ctk.CTkToplevel(self.root)
        win.title("AI 知识库设置")
        win.geometry("400x210")
        win.resizable(False, False)
        win.lift()
        win.focus_force()
        win.grab_set()

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

        # 启用开关
        row1 = ctk.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            row1, text="启用知识库",
            font=ctk.CTkFont(family="PingFang SC", size=12),
        ).pack(side="left")
        kb_var = ctk.BooleanVar(value=bool(self._app_config.get("kb_enabled")))
        ctk.CTkSwitch(
            row1, text="", variable=kb_var,
            onvalue=True, offvalue=False, width=44,
        ).pack(side="right")

        # Vault 路径
        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkLabel(
            row2, text="Vault 路径",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            width=72, anchor="w",
        ).pack(side="left")
        path_var = ctk.StringVar(value=self._app_config.get("kb_vault_path", ""))
        path_entry = ctk.CTkEntry(
            row2, textvariable=path_var,
            height=30, corner_radius=6, border_width=1,
            border_color="#dce8ff",
            font=ctk.CTkFont(family="PingFang SC", size=11),
            state="disabled",
        )
        path_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))

        def browse():
            from tkinter import filedialog
            chosen = filedialog.askdirectory(
                title="选择 Obsidian Vault 文件夹",
                parent=win,
            )
            if chosen:
                path_var.set(chosen)

        ctk.CTkButton(
            row2, text="浏览…", width=60, height=30, corner_radius=6,
            fg_color="transparent", border_width=1, border_color="#dce8ff",
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=11),
            command=browse,
        ).pack(side="right")

        # ── Footer ──
        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(4, 14))
        footer.grid_columnconfigure((0, 1), weight=1)

        def on_save():
            if kb_var.get() and not path_var.get():
                self._show_warning("请先选择 Obsidian Vault 路径")
                return
            self._app_config["kb_enabled"] = kb_var.get()
            self._app_config["kb_vault_path"] = path_var.get()
            save_config(self._app_config)
            self._update_kb_row()
            win.destroy()
            self.root.attributes("-topmost", True)

        def on_cancel():
            win.destroy()
            self.root.attributes("-topmost", True)

        win.protocol("WM_DELETE_WINDOW", on_cancel)

        ctk.CTkButton(
            footer, text="取消", height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666", hover_color="#f0f0f0",
            font=ctk.CTkFont(family="PingFang SC", size=12),
            command=on_cancel,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")

        ctk.CTkButton(
            footer, text="保存", height=32, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=on_save,
        ).grid(row=0, column=1, padx=(5, 0), sticky="ew")

```

- [ ] **Step 3：语法检查**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```
预期：`OK`

- [ ] **Step 4：运行全部测试确认无回归**

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_ai_reply.py -v
```
预期：全部 pass

- [ ] **Step 5：提交**

```bash
git add gui_panel.py
git commit -m "feat: gui — ⚙ 按钮 + 知识库设置弹窗"
```

---

## 验证清单（实现完成后手动测试）

- [ ] 启动应用，Header 右侧出现 ⚙ 按钮
- [ ] 点击 ⚙，弹窗正常出现（不被 topmost 遮挡）
- [ ] 点击"浏览…"，弹出文件夹选择对话框
- [ ] 选择一个目录，路径显示在输入框中
- [ ] 保存后状态行变绿（`📗 知识库已启用 · <vault名>`）
- [ ] 重启应用，配置持久化（路径和开关保持）
- [ ] 开启 KB 后点击"读取并生成"，`config.json` 中 `kb_enabled=true`
- [ ] 关闭 KB 后再次生成，行为与原来一致
- [ ] 路径填非法路径时，状态栏显示友好错误信息
