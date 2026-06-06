# KB Capture 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 视图新增「💾 存入知识库」按钮，通过 AI 提炼聊天回复的结构化字段，经可编辑弹窗确认后写入 Obsidian vault 的 `IM回复记录/` 目录，形成"生成 → 存档 → 复用"闭环。

**Architecture:** 新增 `kb_writer.py` 负责文件写入；`ai_reply.py` 新增 `extract_kb_entry()` 进行结构提炼（独立于 generate_reply，失败时静默返回 None）；`gui_panel.py` 添加按钮、后台提炼线程、可编辑弹窗三件套。

**Tech Stack:** Python 3.10+, CustomTkinter 5.2.x, subprocess（复用现有 mc --code 调用模式），标准库 json / re / datetime / os。

---

## 文件清单

| 操作 | 路径 | 职责 |
|------|------|------|
| **新建** | `kb_writer.py` | KBEntry dataclass + save_to_vault() |
| **新建** | `tests/test_kb_writer.py` | kb_writer 单元测试 |
| **修改** | `ai_reply.py` | 新增 extract_kb_entry() + _build_extraction_prompt() |
| **修改** | `tests/test_ai_reply.py` | 新增 ExtractKBEntryTests |
| **修改** | `gui_panel.py` | 新增按钮、_ai_kb_capture_async()、_show_kb_save_dialog()、_ai_set_reply() 联动 |

---

## Task 1: kb_writer.py — KBEntry 与文件写入

**Files:**
- Create: `kb_writer.py`
- Create: `tests/test_kb_writer.py`

- [ ] **Step 1: 写失败测试（文件写入 + 内容）**

新建 `tests/test_kb_writer.py`：

```python
# tests/test_kb_writer.py
import os
import tempfile
import unittest

from kb_writer import KBEntry, save_to_vault


class SaveToVaultTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        self.entry = KBEntry(
            title="订单查询",
            scenario="用户询问订单处理进度",
            tags=["订单", "客服", "SOP"],
            reply="您好，我帮您查一下。",
            source="企业微信",
            date="2026-06-06",
        )

    def test_creates_im_records_directory(self):
        save_to_vault(self.entry, self.vault)
        self.assertTrue(os.path.isdir(os.path.join(self.vault, "IM回复记录")))

    def test_filename_starts_with_date_and_title(self):
        path = save_to_vault(self.entry, self.vault)
        filename = os.path.basename(path)
        self.assertTrue(filename.startswith("2026-06-06-订单查询"))
        self.assertTrue(filename.endswith(".md"))

    def test_file_contains_yaml_frontmatter(self):
        path = save_to_vault(self.entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn("title: 订单查询", content)
        self.assertIn("date: 2026-06-06", content)
        self.assertIn("tags: [订单, 客服, SOP]", content)
        self.assertIn("source: 企业微信", content)

    def test_file_contains_body_sections(self):
        path = save_to_vault(self.entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn("## 适用场景", content)
        self.assertIn("用户询问订单处理进度", content)
        self.assertIn("## 标准回复", content)
        self.assertIn("您好，我帮您查一下。", content)

    def test_collision_creates_unique_filename(self):
        path1 = save_to_vault(self.entry, self.vault)
        path2 = save_to_vault(self.entry, self.vault)
        self.assertNotEqual(path1, path2)
        self.assertTrue(os.path.exists(path2))

    def test_returns_absolute_path(self):
        path = save_to_vault(self.entry, self.vault)
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(os.path.exists(path))

    def test_empty_tags_writes_empty_list(self):
        entry = KBEntry(
            title="测试", scenario="测试场景", tags=[],
            reply="回复", source="微信", date="2026-06-06",
        )
        path = save_to_vault(entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn("tags: []", content)

    def test_unsafe_filename_chars_stripped(self):
        entry = KBEntry(
            title="订单/查询:测试",
            scenario="s", tags=[], reply="r", source="微信", date="2026-06-06",
        )
        path = save_to_vault(entry, self.vault)
        filename = os.path.basename(path)
        self.assertNotIn("/", filename)
        self.assertNotIn(":", filename)
```

- [ ] **Step 2: 运行测试，确认全部失败**

```bash
.venv/bin/python -m pytest tests/test_kb_writer.py -v
```

预期：`ModuleNotFoundError: No module named 'kb_writer'`

- [ ] **Step 3: 实现 kb_writer.py**

新建 `kb_writer.py`：

```python
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
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
.venv/bin/python -m pytest tests/test_kb_writer.py -v
```

预期：全部 PASS

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile kb_writer.py && echo "OK"
```

预期：`OK`

- [ ] **Step 6: 提交**

```bash
git add kb_writer.py tests/test_kb_writer.py
git commit -m "feat: kb_writer — KBEntry dataclass + save_to_vault()"
```

---

## Task 2: ai_reply.py — extract_kb_entry()

**Files:**
- Modify: `ai_reply.py`
- Modify: `tests/test_ai_reply.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_ai_reply.py` 末尾，`if __name__ == "__main__":` 之前添加：

```python
# ── extract_kb_entry ─────────────────────────────────────────────────────────

from ai_reply import extract_kb_entry


class ExtractKBEntryTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_returns_parsed_dict_on_success(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"title": "订单查询", "scenario": "用户询问进度", "tags": ["订单", "客服"]}',
            stderr="",
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "订单查询")
        self.assertEqual(result["tags"], ["订单", "客服"])

    @patch("ai_reply.subprocess.run")
    def test_returns_none_on_invalid_json(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="不是 JSON 内容", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run", side_effect=subprocess.TimeoutExpired(["mc"], timeout=10))
    def test_returns_none_on_timeout(self, _run_mock):
        config = AIReplyConfig(command="mc", timeout=10)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run")
    def test_returns_none_on_nonzero_exit(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run")
    def test_command_never_uses_add_dir(self, run_mock):
        """提炼任务不需要访问 vault，确保命令中没有 --add-dir。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"title": "t", "scenario": "s", "tags": []}',
            stderr="",
        )
        config = AIReplyConfig(
            command="mc", timeout=5, kb_enabled=True, kb_vault_path="/tmp"
        )
        extract_kb_entry([{"content": "test"}], "reply", config)
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--add-dir", cmd)
        self.assertIn("--tools", cmd)

    @patch("ai_reply.subprocess.run")
    def test_strips_markdown_code_fence(self, run_mock):
        """mc 有时会把 JSON 包在 ```json ... ``` 里，应能正常解析。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='```json\n{"title": "t", "scenario": "s", "tags": []}\n```',
            stderr="",
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "test"}], "reply", config)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "t")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py::ExtractKBEntryTests -v
```

预期：`ImportError: cannot import name 'extract_kb_entry'`

- [ ] **Step 3: 在 ai_reply.py 中实现 _build_extraction_prompt 和 extract_kb_entry**

在 `ai_reply.py` 的 `build_reply_prompt` 函数定义之后添加（`generate_reply` 函数之前）：

```python
def _build_extraction_prompt(
    messages: list[dict], reply: str, max_messages: int = 20
) -> str:
    """构造提炼知识库条目的 prompt，要求模型只输出 JSON。"""
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    return (
        "你是知识库整理助手。请根据下面的聊天记录和候选回复，提炼出结构化的知识库条目。\n\n"
        "严格只输出一个 JSON 对象，不输出任何其他文字，格式：\n"
        '{"title": "简短标题（10字以内）", '
        '"scenario": "适用场景描述（20字以内）", '
        '"tags": ["标签1", "标签2"]}\n\n'
        f"聊天记录：\n{transcript}\n\n"
        f"候选回复：\n{reply}\n\n"
        "输出 JSON："
    )


def extract_kb_entry(
    messages: list[dict],
    reply: str,
    config: AIReplyConfig | None = None,
) -> dict | None:
    """
    根据聊天记录和候选回复提炼结构化知识库条目。
    返回 {"title": ..., "scenario": ..., "tags": [...]}。
    任何错误（超时、解析失败、命令不存在）均返回 None，由调用方降级处理。
    注意：此调用始终使用 --tools ""（不读 vault），与 generate_reply 的 KB 模式不同。
    """
    import json

    config = config or AIReplyConfig()
    prompt = _build_extraction_prompt(messages, reply, max_messages=config.max_messages)
    cmd = [
        config.command, "--code", "-p",
        "--tools", "",
        "--no-session-persistence",
        prompt,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    text = (result.stdout or "").strip()
    # 去除可能的 Markdown 代码块包装（```json ... ```）
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py -v
```

预期：全部 PASS（含原有测试）

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile ai_reply.py && echo "OK"
```

预期：`OK`

- [ ] **Step 6: 提交**

```bash
git add ai_reply.py tests/test_ai_reply.py
git commit -m "feat: ai_reply — extract_kb_entry() KB 条目提炼"
```

---

## Task 3: gui_panel.py — 「💾 存入知识库」按钮 + 后台提炼线程

**Files:**
- Modify: `gui_panel.py:1098-1103`（替换单按钮为双按钮行）
- Modify: `gui_panel.py:1307-1309`（_ai_set_reply 联动按钮状态）
- Modify: `gui_panel.py`（新增 _ai_kb_capture_async 和两个回调方法）

- [ ] **Step 1: 在 gui_panel.py 中更新 import，引入 extract_kb_entry 和 kb_writer**

找到现有 import 块（`gui_panel.py` 第 38 行）：

```python
from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
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
    extract_kb_entry,
)
from kb_writer import KBEntry, save_to_vault
```

- [ ] **Step 2: 将单个「确认发送」按钮替换为双按钮行**

找到 `gui_panel.py` 中这段代码（约第 1098-1103 行）：

```python
        ctk.CTkButton(
            self.ai_view, text="确认发送", height=36, corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=self._ai_send_reply,
        ).pack(fill="x", padx=12, pady=(0, 10))
```

替换为：

```python
        send_row = ctk.CTkFrame(self.ai_view, fg_color="transparent")
        send_row.pack(fill="x", padx=12, pady=(0, 10))
        send_row.grid_columnconfigure(0, weight=3)
        send_row.grid_columnconfigure(1, weight=2)

        ctk.CTkButton(
            send_row, text="确认发送", height=36, corner_radius=10,
            fg_color=PRIMARY, hover_color=PRIMARY_H,
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=self._ai_send_reply,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.ai_save_btn = ctk.CTkButton(
            send_row, text="💾 存入知识库", height=36, corner_radius=10,
            fg_color="transparent", border_width=1, border_color="#7c3aed",
            text_color="#7c3aed", hover_color="#f5f0ff",
            font=ctk.CTkFont(family="PingFang SC", size=11),
            state="disabled",
            command=self._ai_kb_capture_async,
        )
        self.ai_save_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")
```

- [ ] **Step 3: 在 _ai_set_reply 中联动按钮状态**

找到 `_ai_set_reply` 方法（约第 1307 行）：

```python
    def _ai_set_reply(self, text: str):
        self.ai_reply_box.delete("1.0", "end")
        self.ai_reply_box.insert("end", text)
```

替换为：

```python
    def _ai_set_reply(self, text: str):
        self.ai_reply_box.delete("1.0", "end")
        self.ai_reply_box.insert("end", text)
        if hasattr(self, "ai_save_btn"):
            self.ai_save_btn.configure(
                state="normal" if text.strip() else "disabled"
            )
```

- [ ] **Step 4: 新增 _ai_kb_capture_async 和回调方法**

在 `_ai_send_reply` 方法之后（约第 1485 行后）添加：

```python
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
        self.ai_save_btn.configure(state="normal", text="💾 存入知识库")
        source_name = (
            self.current_client.display_name if self.current_client else "未知来源"
        )
        self._show_kb_save_dialog(entry_dict or {}, reply, source_name)
```

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

预期：`OK`

- [ ] **Step 6: 提交**

```bash
git add gui_panel.py
git commit -m "feat: gui — 存入知识库按钮 + 后台提炼线程"
```

---

## Task 4: gui_panel.py — _show_kb_save_dialog() 弹窗

**Files:**
- Modify: `gui_panel.py`（新增 _show_kb_save_dialog 方法）

- [ ] **Step 1: 在 _ai_kb_capture_done 之后添加 _show_kb_save_dialog**

紧接 Task 3 Step 4 添加的 `_ai_kb_capture_done` 方法之后，添加：

```python
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
        header = ctk.CTkFrame(win, height=44, corner_radius=0, fg_color="#7c3aed")
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
            """返回 (row_frame, label) 便于后续 pack 子控件。"""
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
            border_width=1, border_color="#dce8ff", font=ENTRY_FONT,
        ).pack(fill="x", padx=16, pady=(3, 0))

        # 适用场景
        labeled_row(body, "适用场景")
        scenario_box = ctk.CTkTextbox(
            body, height=52, corner_radius=6, border_width=1,
            border_color="#dce8ff", font=ENTRY_FONT,
        )
        scenario_box.pack(fill="x", padx=16, pady=(3, 0))
        scenario_box.insert("end", entry_dict.get("scenario", ""))

        # 标签（逗号分隔）
        labeled_row(body, "标签（逗号分隔）")
        tags_raw = ", ".join(entry_dict.get("tags", []))
        tags_var = ctk.StringVar(value=tags_raw)
        ctk.CTkEntry(
            body, textvariable=tags_var, height=32, corner_radius=6,
            border_width=1, border_color="#dce8ff", font=ENTRY_FONT,
        ).pack(fill="x", padx=16, pady=(3, 0))

        # 回复内容
        labeled_row(body, "回复内容")
        reply_box = ctk.CTkTextbox(
            body, height=80, corner_radius=6, border_width=1,
            border_color="#dce8ff", font=ENTRY_FONT,
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
                self._show_warning("标题不能为空")
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
                self._show_warning(f"写入失败：{exc}")

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
            fg_color="#7c3aed", hover_color="#6d28d9",
            font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
            command=on_save,
        ).grid(row=0, column=1, padx=(4, 12), pady=10, sticky="ew")
```

- [ ] **Step 2: 语法检查**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

预期：`OK`

- [ ] **Step 3: 运行全部测试确认无回归**

```bash
.venv/bin/python -m pytest tests/ -v --ignore=tests/test_gui_send.py --ignore=tests/test_ax_helpers.py --ignore=tests/test_im_clients.py --ignore=tests/test_wechat_ocr.py
```

预期：全部 PASS（`test_config.py`、`test_ai_reply.py`、`test_kb_writer.py`）

- [ ] **Step 4: 提交**

```bash
git add gui_panel.py
git commit -m "feat: gui — _show_kb_save_dialog() KB 存储编辑弹窗"
```

---

## 验证清单（手动测试）

- [ ] 候选回复为空时，「💾 存入知识库」呈 disabled 灰色状态
- [ ] 有候选回复时，按钮可点击
- [ ] vault 未配置时点击按钮，弹出提示"请先在 ⚙ 设置中配置知识库路径"
- [ ] 正常点击后按钮变为「提炼中…」，约 5s 后弹出编辑弹窗
- [ ] 弹窗字段已预填（标题/场景/标签），来源字段只读
- [ ] 修改标题后点"保存到 Vault"，在 `<vault>/IM回复记录/` 下出现 `.md` 文件
- [ ] 打开该文件，确认 YAML frontmatter 包含正确的 source、tags、date
- [ ] 标题留空点保存，弹窗内显示"标题不能为空"
- [ ] 连续保存同名两次，第二个文件自动加时间戳后缀，两个文件均存在
- [ ] mc 不可用时点击按钮，弹窗仍然出现（字段为空，可手填后保存）
- [ ] 保存成功后状态栏显示「✅ 已存入知识库：<文件名>」
