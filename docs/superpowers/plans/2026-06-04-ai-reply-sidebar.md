# AI Reply Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full working AI assistant mode to the existing WeCom sidebar: read current chat messages, call `mc --code`, show an editable candidate reply, and send after confirmation.

**Architecture:** Keep WeCom automation in `sender.py`, add AI generation in a new `ai_reply.py`, and keep GUI orchestration in `gui_panel.py`. The AI module exposes small pure functions for prompt building and one subprocess wrapper for command execution, so the GUI can remain focused on state, threading, and user confirmation.

**Tech Stack:** Python 3.13, CustomTkinter 5.2.x, PyObjC Accessibility APIs, `subprocess`, stdlib `unittest`/`unittest.mock`.

---

## File Structure

- Create `ai_reply.py`
  - Owns AI command configuration, prompt construction, subprocess invocation, and AI-specific exceptions.
  - Must not import CustomTkinter or sender GUI modules.

- Create `tests/test_ai_reply.py`
  - Unit tests for prompt building and subprocess error handling.
  - Use stdlib `unittest` to avoid adding dependencies.

- Modify `gui_panel.py`
  - Import `generate_reply` and AI exceptions.
  - Add a mode switch for `话术` and `AI 助手`.
  - Wrap the existing status-below UI into `self.phrase_view`.
  - Add `self.ai_view` with read/generate, editable reply, copy, clear, and confirm send controls.
  - Reuse existing `_do_send(text)` for final send preview and dispatch.

- Keep `sender.py` unchanged unless implementation reveals a chat-reading bug.

---

## Task 1: Add AI Reply Core Module

**Files:**
- Create: `ai_reply.py`
- Create: `tests/test_ai_reply.py`

- [ ] **Step 1: Write failing prompt tests**

Create `tests/test_ai_reply.py` with:

```python
import unittest

from ai_reply import build_reply_prompt


class BuildReplyPromptTests(unittest.TestCase):
    def test_includes_recent_messages_and_reply_constraints(self):
        messages = [
            {"time": "10:01", "content": "客户：我这个订单怎么还没发货？"},
            {"time": "10:02", "content": "客服：我帮您查一下。"},
        ]

        prompt = build_reply_prompt(messages)

        self.assertIn("客户：我这个订单怎么还没发货？", prompt)
        self.assertIn("客服：我帮您查一下。", prompt)
        self.assertIn("只输出", prompt)
        self.assertIn("中文回复", prompt)

    def test_limits_messages_to_max_messages(self):
        messages = [{"content": f"消息{i}", "time": None} for i in range(25)]

        prompt = build_reply_prompt(messages, max_messages=3)

        self.assertNotIn("消息21", prompt)
        self.assertIn("消息22", prompt)
        self.assertIn("消息23", prompt)
        self.assertIn("消息24", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run prompt tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
```

Expected: FAIL because `ai_reply.py` does not exist yet.

- [ ] **Step 3: Implement prompt builder and config skeleton**

Create `ai_reply.py`:

```python
#!/usr/bin/env python3
"""AI reply generation helpers for the WeCom sidebar."""

from __future__ import annotations

from dataclasses import dataclass, field
import subprocess


class AIReplyError(Exception):
    """Base class for AI reply generation failures."""


class AICommandNotFoundError(AIReplyError):
    """AI command is not installed or not visible in PATH."""


class AICommandTimeoutError(AIReplyError):
    """AI command exceeded the configured timeout."""


class AICommandFailedError(AIReplyError):
    """AI command exited with a non-zero status."""


class AIEmptyResponseError(AIReplyError):
    """AI command returned no usable reply."""


@dataclass
class AIReplyConfig:
    command: str = "mc"
    args: list[str] = field(
        default_factory=lambda: ["--code", "-p", "--tools", "", "--no-session-persistence"]
    )
    timeout: int = 60
    max_messages: int = 20


def _format_message(message: dict) -> str:
    content = str(message.get("content", "")).strip()
    time_str = message.get("time")
    if time_str:
        return f"[{time_str}] {content}"
    return content


def build_reply_prompt(messages: list[dict], max_messages: int = 20) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    return (
        "你是企业微信客服回复助手。请根据下面最近的聊天记录，生成一段可以直接发给客户的中文回复。\n\n"
        "要求：\n"
        "1. 只输出最终回复正文，不要标题、解释、Markdown 或代码块。\n"
        "2. 语气礼貌、简洁、专业。\n"
        "3. 不要承诺无法从聊天记录确认的事实。\n"
        "4. 如果信息不足，先表达已收到，并说明需要进一步确认。\n\n"
        "最近聊天记录：\n"
        f"{transcript}\n\n"
        "请输出回复："
    )
```

- [ ] **Step 4: Run prompt tests and verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
```

Expected: PASS for the prompt tests.

- [ ] **Step 5: Write failing subprocess tests**

Append to `tests/test_ai_reply.py`:

```python
from unittest.mock import patch

from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
    generate_reply,
)


class GenerateReplyTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_generate_reply_returns_stdout(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=0, stdout="您好，我来帮您确认。\\n", stderr=""
        )

        result = generate_reply([{"content": "客户：请帮我看一下"}], AIReplyConfig(timeout=5))

        self.assertEqual(result, "您好，我来帮您确认。")
        self.assertEqual(run_mock.call_args.args[0][0], "mc")

    @patch("ai_reply.subprocess.run", side_effect=FileNotFoundError)
    def test_command_not_found(self, _run_mock):
        with self.assertRaises(AICommandNotFoundError):
            generate_reply([{"content": "客户：在吗"}])

    @patch("ai_reply.subprocess.run", side_effect=subprocess.TimeoutExpired(["mc"], timeout=1))
    def test_command_timeout(self, _run_mock):
        with self.assertRaises(AICommandTimeoutError):
            generate_reply([{"content": "客户：在吗"}], AIReplyConfig(timeout=1))

    @patch("ai_reply.subprocess.run")
    def test_nonzero_exit(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=2, stdout="", stderr="auth failed"
        )
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "客户：在吗"}])

    @patch("ai_reply.subprocess.run")
    def test_empty_stdout(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=0, stdout="\\n", stderr=""
        )
        with self.assertRaises(AIEmptyResponseError):
            generate_reply([{"content": "客户：在吗"}])
```

Also add `import subprocess` near the top of the test file.

- [ ] **Step 6: Run subprocess tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
```

Expected: FAIL because `generate_reply()` is not implemented.

- [ ] **Step 7: Implement `generate_reply()`**

Add to `ai_reply.py`:

```python
def generate_reply(messages: list[dict], config: AIReplyConfig | None = None) -> str:
    config = config or AIReplyConfig()
    prompt = build_reply_prompt(messages, max_messages=config.max_messages)
    if not prompt.strip() or not any(str(m.get("content", "")).strip() for m in messages):
        raise AIEmptyResponseError("没有可用于生成回复的聊天内容")

    cmd = [config.command, *config.args, prompt]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AICommandNotFoundError(f"未找到 AI 命令: {config.command}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AICommandTimeoutError("AI 生成超时，请稍后重试") from exc

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise AICommandFailedError(err or f"AI 命令退出码: {result.returncode}")

    reply = (result.stdout or "").strip()
    if not reply:
        raise AIEmptyResponseError("AI 返回内容为空")
    return reply
```

- [ ] **Step 8: Run all AI module tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
```

Expected: PASS.

- [ ] **Step 9: Commit AI module**

Run:

```bash
git add ai_reply.py tests/test_ai_reply.py
git commit -m "feat: add AI reply generator"
```

---

## Task 2: Add Mode Switch Container in GUI

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: Identify the existing status bar boundary**

Read `WXSenderApp._build_ui()` and locate the point immediately after the status bar buttons are added. Everything below status bar should move into a phrase-mode container without changing behavior.

- [ ] **Step 2: Add mode state in `__init__`**

After existing search state fields, add:

```python
self.mode_var = ctk.StringVar(value="phrases")
```

- [ ] **Step 3: Add a mode switch after the status bar**

In `_build_ui()`, after the status bar section, create:

```python
self.mode_frame = ctk.CTkFrame(self.root, fg_color="white", corner_radius=0)
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
    fg_color="transparent", border_width=1, border_color="#dce8ff",
    text_color=PRIMARY, hover_color=CARD_BG,
    font=ctk.CTkFont(family="PingFang SC", size=12),
    command=lambda: self._switch_mode("ai"),
)
self.ai_mode_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")
```

- [ ] **Step 4: Wrap existing phrase UI**

Create `self.phrase_view = ctk.CTkFrame(self.root, fg_color="transparent")` after the mode switch and pack it. Move existing group/search/cards/buttons/custom-message widgets to use `self.phrase_view` as their root parent instead of `self.root`.

Example:

```python
group_frame = ctk.CTkFrame(self.phrase_view, fg_color="transparent")
```

- [ ] **Step 5: Add empty AI view placeholder**

After phrase view setup, add:

```python
self.ai_view = ctk.CTkFrame(self.root, fg_color="transparent")
self._build_ai_view()
```

Do not pack `self.ai_view` initially; phrase mode remains default.

- [ ] **Step 6: Implement `_switch_mode()`**

Add method:

```python
def _switch_mode(self, mode: str):
    self.mode_var.set(mode)
    if mode == "ai":
        self.phrase_view.pack_forget()
        self.ai_view.pack(fill="both", expand=True)
        self.phrase_mode_btn.configure(
            fg_color="transparent", border_width=1, border_color="#dce8ff",
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
            fg_color="transparent", border_width=1, border_color="#dce8ff",
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(family="PingFang SC", size=12),
        )
```

- [ ] **Step 7: Run syntax check**

Run:

```bash
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
```

Expected: exit 0.

- [ ] **Step 8: Manual smoke check**

Run:

```bash
.venv/bin/python gui_panel.py
```

Expected: UI opens, phrase mode looks and behaves like before, AI mode switch shows an empty/placeholder panel.

- [ ] **Step 9: Commit mode switch**

Run:

```bash
git add gui_panel.py
git commit -m "feat: add sidebar mode switch"
```

---

## Task 3: Build AI Assistant View

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: Add imports**

Add near existing sender import:

```python
from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    generate_reply,
)
```

- [ ] **Step 2: Add AI state in `__init__`**

Add:

```python
self._ai_messages = []
self._ai_generating = False
```

- [ ] **Step 3: Implement `_build_ai_view()` layout**

Create:

```python
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
        fg_color="transparent", border_width=1, border_color="#dce8ff",
        text_color=PRIMARY, hover_color=CARD_BG,
        font=ctk.CTkFont(family="PingFang SC", size=12),
        command=self._ai_regenerate,
    )
    self.ai_regenerate_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

    self.ai_status_label = ctk.CTkLabel(
        self.ai_view, text="选中企业微信聊天后，读取会话并生成回复。",
        text_color="#8c8c8c", anchor="w",
        font=ctk.CTkFont(family="PingFang SC", size=11),
    )
    self.ai_status_label.pack(fill="x", padx=14, pady=(0, 6))

    ctk.CTkLabel(
        self.ai_view, text="聊天上下文", anchor="w",
        text_color="#333", font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
    ).pack(fill="x", padx=14, pady=(4, 4))

    self.ai_context_box = ctk.CTkTextbox(
        self.ai_view, height=140, corner_radius=8, border_width=1,
        border_color="#dce8ff", font=ctk.CTkFont(family="PingFang SC", size=11),
    )
    self.ai_context_box.pack(fill="x", padx=12, pady=(0, 8))
    self.ai_context_box.configure(state="disabled")

    ctk.CTkLabel(
        self.ai_view, text="候选回复", anchor="w",
        text_color="#333", font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
    ).pack(fill="x", padx=14, pady=(4, 4))

    self.ai_reply_box = ctk.CTkTextbox(
        self.ai_view, height=160, corner_radius=8, border_width=1,
        border_color="#dce8ff", font=ctk.CTkFont(family="PingFang SC", size=12),
    )
    self.ai_reply_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    utility_frame = ctk.CTkFrame(self.ai_view, fg_color="transparent")
    utility_frame.pack(fill="x", padx=12, pady=(0, 6))
    utility_frame.grid_columnconfigure((0, 1), weight=1)

    ctk.CTkButton(
        utility_frame, text="复制", height=30, corner_radius=8,
        fg_color="transparent", border_width=1, border_color="#d9d9d9",
        text_color="#666", hover_color="#f0f0f0",
        font=ctk.CTkFont(size=11),
        command=self._ai_copy_reply,
    ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

    ctk.CTkButton(
        utility_frame, text="清空", height=30, corner_radius=8,
        fg_color="transparent", border_width=1, border_color="#d9d9d9",
        text_color="#666", hover_color="#f0f0f0",
        font=ctk.CTkFont(size=11),
        command=self._ai_clear_reply,
    ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

    ctk.CTkButton(
        self.ai_view, text="确认发送", height=36, corner_radius=10,
        fg_color=PRIMARY, hover_color=PRIMARY_H,
        font=ctk.CTkFont(family="PingFang SC", size=12, weight="bold"),
        command=self._ai_send_reply,
    ).pack(fill="x", padx=12, pady=(0, 10))
```

- [ ] **Step 4: Add helper methods for AI text boxes**

Add:

```python
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

def _ai_get_reply(self) -> str:
    return self.ai_reply_box.get("1.0", "end").strip()
```

- [ ] **Step 5: Run syntax check**

Run:

```bash
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
```

Expected: exit 0.

- [ ] **Step 6: Manual UI check**

Run:

```bash
.venv/bin/python gui_panel.py
```

Expected: AI mode displays all controls without overlap in the 420px sidebar.

- [ ] **Step 7: Commit AI view**

Run:

```bash
git add gui_panel.py
git commit -m "feat: add AI assistant view"
```

---

## Task 4: Wire Chat Reading and AI Generation

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: Implement context formatting**

Add:

```python
def _format_ai_messages(self, msgs: list) -> str:
    lines = []
    for m in msgs:
        time_str = f"[{m['time']}] " if m.get("time") else ""
        lines.append(f"{time_str}{m.get('content', '')}")
    return "\n\n".join(lines)
```

- [ ] **Step 2: Implement `_ai_read_and_generate()`**

Add:

```python
def _ai_read_and_generate(self):
    if self._ai_generating:
        return
    self._ai_set_status("正在读取聊天内容...")
    self.ai_generate_btn.configure(state="disabled")

    def fetch():
        msgs = read_chat_messages(max_messages=30)
        self.root.after(0, lambda: self._ai_after_read(msgs))

    threading.Thread(target=fetch, daemon=True).start()
```

- [ ] **Step 3: Implement `_ai_after_read()`**

Add:

```python
def _ai_after_read(self, msgs: list):
    self._ai_messages = msgs
    self.ai_generate_btn.configure(state="normal")
    if not msgs:
        self._ai_set_context("未读取到消息，请先在企业微信中选中聊天窗口。")
        self._ai_set_status("未读取到聊天内容")
        return
    self._ai_set_context(self._format_ai_messages(msgs))
    self._ai_generate_async(msgs)
```

- [ ] **Step 4: Implement `_ai_regenerate()`**

Add:

```python
def _ai_regenerate(self):
    if self._ai_generating:
        return
    if not self._ai_messages:
        self._ai_read_and_generate()
        return
    self._ai_generate_async(self._ai_messages)
```

- [ ] **Step 5: Implement `_ai_generate_async()`**

Add:

```python
def _ai_generate_async(self, msgs: list):
    self._ai_generating = True
    self.ai_generate_btn.configure(state="disabled")
    self.ai_regenerate_btn.configure(state="disabled")
    self._ai_set_status("正在调用 AI 生成回复...")

    def generate_task():
        try:
            reply = generate_reply(msgs)
            self.root.after(0, lambda: self._ai_generation_done(reply))
        except (AICommandNotFoundError, AICommandTimeoutError, AICommandFailedError, AIEmptyResponseError) as e:
            msg = str(e)
            self.root.after(0, lambda: self._ai_generation_failed(msg))
        except Exception as e:
            msg = f"AI 生成失败: {e}"
            self.root.after(0, lambda: self._ai_generation_failed(msg))

    threading.Thread(target=generate_task, daemon=True).start()
```

- [ ] **Step 6: Implement completion handlers**

Add:

```python
def _ai_generation_done(self, reply: str):
    self._ai_generating = False
    self.ai_generate_btn.configure(state="normal")
    self.ai_regenerate_btn.configure(state="normal")
    self._ai_set_reply(reply)
    self._ai_set_status("AI 回复已生成，可编辑后发送")

def _ai_generation_failed(self, message: str):
    self._ai_generating = False
    self.ai_generate_btn.configure(state="normal")
    self.ai_regenerate_btn.configure(state="normal")
    self._ai_set_status(message)
```

- [ ] **Step 7: Run unit and syntax checks**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
```

Expected: both exit 0.

- [ ] **Step 8: Manual generation check**

Run:

```bash
.venv/bin/python gui_panel.py
```

Expected: With a WeCom chat selected, clicking `读取并生成` fills context and then fills candidate reply.

- [ ] **Step 9: Commit generation wiring**

Run:

```bash
git add gui_panel.py
git commit -m "feat: generate AI replies from chat"
```

---

## Task 5: Wire Copy, Clear, and Confirm Send

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: Implement copy and clear**

Add:

```python
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
```

- [ ] **Step 2: Implement confirm send**

Add:

```python
def _ai_send_reply(self):
    reply = self._ai_get_reply()
    if not reply:
        self._show_warning("请先生成或输入回复内容")
        return
    self._do_send(reply)
```

- [ ] **Step 3: Run checks**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
```

Expected: both exit 0.

- [ ] **Step 4: Manual full-flow check**

Run:

```bash
.venv/bin/python gui_panel.py
```

Expected:

1. Switch to `AI 助手`.
2. Click `读取并生成`.
3. Edit the generated reply.
4. Click `确认发送`.
5. Existing send preview opens.
6. Confirm sends the edited text to current WeCom chat.

- [ ] **Step 5: Commit send controls**

Run:

```bash
git add gui_panel.py
git commit -m "feat: send AI reply candidates"
```

---

## Task 6: Final Verification and Documentation Update

**Files:**
- Modify: `README.md`
- Optional Modify: `CLAUDE.md`

- [ ] **Step 1: Add README usage note**

In `README.md`, add a short `AI 助手` section:

```markdown
## AI 助手

- 切换到「AI 助手」后，可读取当前企业微信聊天内容并调用 `mc --code` 生成候选回复。
- 候选回复会先展示在面板中，支持编辑、复制、清空和重新生成。
- 点击「确认发送」后直接发送到企业微信，不再弹出发送预览。
```

- [ ] **Step 2: Add CLAUDE.md decision note**

If this feature is implemented, append a short decision to `CLAUDE.md`:

```markdown
### AI 回复助手

AI 回复第一版使用 `mc --code -p --tools "" --no-session-persistence` 作为可配置命令入口。GUI 只展示候选回复并要求人工确认，不做自动发送。AI 调用封装在 `ai_reply.py`，便于未来替换为 Ollama、HTTP 接口或其他公司内部 CLI。
```

- [ ] **Step 3: Run final automated checks**

Run:

```bash
.venv/bin/python -m unittest tests.test_ai_reply -v
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
mc --code -p --tools "" --no-session-persistence "只输出两个字：可以"
```

Expected:

- Unit tests PASS.
- Syntax check exits 0.
- AI command outputs `可以`.

- [ ] **Step 4: Manual acceptance check**

Run:

```bash
.venv/bin/python gui_panel.py
```

Acceptance criteria:

- `话术` mode keeps existing phrase search/send/edit behavior.
- `AI 助手` mode reads current chat.
- `AI 助手` mode calls `mc --code` and shows a candidate reply.
- Candidate reply can be edited before sending.
- `确认发送` opens existing send preview.
- Confirming preview sends the edited text to WeCom.
- Errors for empty chat, missing command, timeout, and empty reply are visible to the user.

- [ ] **Step 5: Commit docs**

Run:

```bash
git add README.md CLAUDE.md
git commit -m "docs: document AI reply assistant"
```

---

## Notes for Implementation

- Do not change the proven Enter behavior in `sender.py`.
- Do not use CGEvent Return for text sending.
- Do not bypass the existing send preview.
- Keep AI generation in a background thread so the CustomTkinter UI does not freeze.
- Use `self.root.after(0, ...)` for all UI updates from worker threads.
- Prefer minimal restructuring of `gui_panel.py`; this file is already large, so new AI logic should be grouped and named clearly.
- If git write permission is unavailable in the current sandbox, still produce the file changes and report that commits could not be created.
