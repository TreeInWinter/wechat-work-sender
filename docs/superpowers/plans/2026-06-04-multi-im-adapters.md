# 多 IM 客户端适配器实现计划（微信 + 大象）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为微信（个人版）和大象（美团内部 IM）实现与企业微信同等级别的 AX API 自动化（发文字、发图片、读聊天消息）。

**Architecture:** 新增 `im_clients/ax_helpers.py` 提取通用 AX 工具函数（参数化 app_name），修改 `im_clients/wechat.py` 和 `im_clients/daxiang.py` 实现完整 `send_blocks` + `read_chat_messages`，新增 `tools/explore_ax.py` 用于真机 AX 树探测。`sender.py` 和 `gui_panel.py` 不改动。

**Tech Stack:** pyobjc-framework-{AppKit, ApplicationServices, Quartz}，Python 3.10+，unittest + unittest.mock

---

## Task 1：Fork 分支

**Files:**
- 无代码变更，仅 git 操作

- [ ] **Step 1: 从 master 创建新分支**

```bash
git checkout master
git pull
git checkout -b feature/multi-im-adapters
```

Expected: `Switched to a new branch 'feature/multi-im-adapters'`

- [ ] **Step 2: 确认分支状态**

```bash
git status
git log --oneline -3
```

Expected: `On branch feature/multi-im-adapters`，最近三条 commit 与 master 一致。

---

## Task 2：新增 `tools/explore_ax.py` AX 树探测脚本

**Files:**
- Create: `tools/explore_ax.py`

这是纯只读工具，不发任何消息，用于探测微信/大象的 AX 树结构，确认聊天输入框和消息历史的 depth 和 role。

- [ ] **Step 1: 创建 tools/ 目录并写探测脚本**

```python
# tools/explore_ax.py
#!/usr/bin/env python3
"""
AX 树探测工具 — 打印指定 app 的 Accessibility 元素树

用法:
  .venv/bin/python tools/explore_ax.py <app_name> [max_depth]

示例:
  .venv/bin/python tools/explore_ax.py 微信 12
  .venv/bin/python tools/explore_ax.py 大象 12
  .venv/bin/python tools/explore_ax.py 企业微信 10
"""

import sys
from collections import deque

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    kAXRoleAttribute,
    kAXChildrenAttribute,
    kAXValueAttribute,
    kAXWindowsAttribute,
)


def get_running_pid(app_name: str) -> int | None:
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    for app in apps:
        if app.localizedName() == app_name:
            return app.processIdentifier()
    return None


def explore(app_name: str, max_depth: int = 12):
    pid = get_running_pid(app_name)
    if pid is None:
        print(f"[错误] 应用「{app_name}」未运行，请先打开它并进入一个聊天窗口。")
        sys.exit(1)

    ax = AXUIElementCreateApplication(pid)
    _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
    if not windows:
        print(f"[错误] 未找到「{app_name}」的窗口，请确保主窗口已打开。")
        sys.exit(1)

    print(f"\n=== AX 树：{app_name}（PID={pid}，max_depth={max_depth}）===\n")
    print(f"{'depth':<8} {'role':<24} {'value (前60字符)'}")
    print("-" * 70)

    queue = deque([(windows[0], 0)])
    total = 0
    while queue:
        el, d = queue.popleft()
        if d > max_depth:
            continue
        total += 1
        try:
            _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            _, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
            role_str = str(role) if role else "?"
            val_preview = repr(str(val)[:60]) if val else "None"

            # 高亮候选输入框（AXTextArea + value 为 None）
            marker = ""
            if role_str == "AXTextArea":
                if val is None:
                    marker = "  ← ★ 候选输入框（空，可写）"
                else:
                    marker = "  ← 消息历史（有值，只读）"
            elif role_str == "AXTable":
                marker = "  ← 候选消息历史容器"

            print(f"depth={d:<4} {role_str:<24} {val_preview}{marker}")

            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, d + 1))
        except Exception:
            pass

    print(f"\n共遍历 {total} 个节点（max_depth={max_depth}）")
    print("\n提示：")
    print("  ★ 候选输入框 = BFS 最浅的 AXTextArea（value=None）")
    print("  候选消息历史容器 = AXTable，其子节点含消息 cells")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    app_name = sys.argv[1]
    max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    explore(app_name, max_depth)
```

- [ ] **Step 2: 语法检查**

```bash
.venv/bin/python -m py_compile tools/explore_ax.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/explore_ax.py
git commit -m "feat: add AX tree explorer tool for multi-IM adapter development"
```

---

## Task 3：新增 `im_clients/ax_helpers.py` 通用 AX 工具

**Files:**
- Create: `im_clients/ax_helpers.py`

提取 sender.py 中已验证的核心逻辑，参数化 app_name，供微信和大象 adapter 复用。关键约束继承自企业微信：Enter 走 AppleScript（不走 CGEvent），图片写 `public.png`。

- [ ] **Step 1: 先写失败测试**

在 `tests/test_ax_helpers.py` 中写 mock 测试（macOS 真机 AX 调用用 mock 隔离）：

```python
# tests/test_ax_helpers.py
import unittest
from unittest.mock import MagicMock, patch, call
import subprocess


class GetRunningAppTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.NSWorkspace")
    def test_returns_app_when_found(self, ws_mock):
        app = MagicMock()
        app.localizedName.return_value = "微信"
        ws_mock.sharedWorkspace.return_value.runningApplications.return_value = [app]

        from im_clients.ax_helpers import get_running_app
        result = get_running_app("微信")

        self.assertIs(result, app)

    @patch("im_clients.ax_helpers.NSWorkspace")
    def test_returns_none_when_not_found(self, ws_mock):
        ws_mock.sharedWorkspace.return_value.runningApplications.return_value = []

        from im_clients.ax_helpers import get_running_app
        result = get_running_app("微信")

        self.assertIsNone(result)


class IsAppRunningTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.get_running_app", return_value=MagicMock())
    def test_returns_true_when_app_found(self, _):
        from im_clients.ax_helpers import is_app_running
        self.assertTrue(is_app_running("微信"))

    @patch("im_clients.ax_helpers.get_running_app", return_value=None)
    def test_returns_false_when_app_not_found(self, _):
        from im_clients.ax_helpers import is_app_running
        self.assertFalse(is_app_running("微信"))


class ActivateAppTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.get_running_app")
    def test_activates_app_and_returns_true(self, get_app_mock):
        app = MagicMock()
        get_app_mock.return_value = app

        from im_clients.ax_helpers import activate_app
        result = activate_app("微信")

        self.assertTrue(result)
        app.activateWithOptions_.assert_called_once()

    @patch("im_clients.ax_helpers.get_running_app", return_value=None)
    def test_returns_false_when_not_running(self, _):
        from im_clients.ax_helpers import activate_app
        self.assertFalse(activate_app("微信"))


class SetClipboardTextTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.NSPasteboard")
    def test_writes_string_to_pasteboard(self, pb_mock):
        pb = MagicMock()
        pb_mock.generalPasteboard.return_value = pb

        from im_clients.ax_helpers import set_clipboard_text
        set_clipboard_text("hello")

        pb.clearContents.assert_called_once()
        pb.setString_forType_.assert_called_once()
        args = pb.setString_forType_.call_args.args
        self.assertEqual(args[0], "hello")


class PasteAndSendTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.subprocess.run")
    @patch("im_clients.ax_helpers.CGEventPost")
    @patch("im_clients.ax_helpers.CGEventCreateKeyboardEvent")
    @patch("im_clients.ax_helpers.CGEventSetFlags")
    def test_paste_triggers_cmd_v_and_applescript_enter(
        self, _flags, _create, post_mock, run_mock
    ):
        run_mock.return_value = subprocess.CompletedProcess([], 0)

        from im_clients.ax_helpers import paste_and_send
        paste_and_send(app_name="微信", delay=0)

        # Cmd+V 触发了 CGEventPost（至少 2 次：key down + key up）
        self.assertGreaterEqual(post_mock.call_count, 2)
        # AppleScript Enter 被调用
        run_mock.assert_called_once()
        script_arg = run_mock.call_args.args[0]
        self.assertIn("osascript", script_arg)


class ReadMessagesFromTableTests(unittest.TestCase):
    def _make_cell(self, content: str, time_val: str | None = None):
        """构造一个 mock AX cell，包含 AXTextArea（content）和 AXStaticText（time）"""
        from ApplicationServices import kAXRoleAttribute, kAXValueAttribute, kAXChildrenAttribute

        def ax_attr(el, attr, _):
            return (None, el._attrs.get(attr))

        text_area = MagicMock()
        text_area._attrs = {
            kAXRoleAttribute: "AXTextArea",
            kAXValueAttribute: content,
            kAXChildrenAttribute: None,
        }

        children = [text_area]
        if time_val:
            time_el = MagicMock()
            time_el._attrs = {
                kAXRoleAttribute: "AXStaticText",
                kAXValueAttribute: time_val,
                kAXChildrenAttribute: None,
            }
            children.append(time_el)

        cell = MagicMock()
        cell._attrs = {
            kAXChildrenAttribute: children,
        }
        return cell

    @patch("im_clients.ax_helpers.AXUIElementCopyAttributeValue")
    def test_extracts_content_and_time_from_table(self, ax_mock):
        # 该测试集成度较高，用 WechatWorkAdapter 的 read_chat_messages 集成测试代替
        # 此处仅验证去重逻辑
        from im_clients.ax_helpers import _dedup_ax_value
        duplicated = "你好你好"
        self.assertEqual(_dedup_ax_value(duplicated), "你好")
        normal = "你好"
        self.assertEqual(_dedup_ax_value(normal), "你好")
        empty = ""
        self.assertEqual(_dedup_ax_value(empty), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认全部失败（模块尚未存在）**

```bash
.venv/bin/python -m pytest tests/test_ax_helpers.py -v 2>&1 | head -30
```

Expected: `ImportError` 或 `ModuleNotFoundError: No module named 'im_clients.ax_helpers'`

- [ ] **Step 3: 实现 `im_clients/ax_helpers.py`**

```python
# im_clients/ax_helpers.py
"""
通用 macOS Accessibility API 工具函数。

参数化 app_name，供微信、大象等 IM 适配器复用。
关键约束（继承自企业微信验证结论）：
  - Enter 键走 AppleScript keystroke return，不走 CGEvent
  - 图片必须写 public.png 格式到剪贴板
"""
from __future__ import annotations

import subprocess
import time

from AppKit import (
    NSApplicationActivateIgnoringOtherApps,
    NSBitmapImageRep,
    NSImage,
    NSPasteboard,
    NSPasteboardTypeString,
    NSWorkspace,
)
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    kAXChildrenAttribute,
    kAXFocusedAttribute,
    kAXRoleAttribute,
    kAXValueAttribute,
    kAXWindowsAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

# Cmd+V 的虚拟键码
_KEY_V = 0x09


# ── 应用查找与激活 ──────────────────────────────────────────────


def get_running_app(app_name: str):
    """从 NSWorkspace 找到指定 app 的 NSRunningApplication，未找到返回 None。"""
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    return next((a for a in apps if a.localizedName() == app_name), None)


def is_app_running(app_name: str) -> bool:
    """检查指定 app 是否正在运行。"""
    return get_running_app(app_name) is not None


def activate_app(app_name: str) -> bool:
    """激活指定 app 窗口（PyObjC，~10ms）。未运行返回 False。"""
    app = get_running_app(app_name)
    if app is None:
        return False
    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.1)
    return True


def get_ax_element(app_name: str):
    """返回指定 app 的 AXUIElement（application level）。未运行返回 None。"""
    app = get_running_app(app_name)
    if app is None:
        return None
    return AXUIElementCreateApplication(app.processIdentifier())


# ── AX 树查找 ──────────────────────────────────────────────────


def bfs_find_input(ax_root, max_depth: int = 10):
    """
    BFS 找最浅的空 AXTextArea（聊天输入框）。

    BFS 优先命中最浅节点，避免先深入消息历史区找到只读的 AXTextArea。
    返回找到的 AX 元素，未找到返回 None。
    """
    from collections import deque

    queue = deque([(ax_root, 0)])
    while queue:
        el, depth = queue.popleft()
        if depth > max_depth:
            continue
        try:
            _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            if role == "AXTextArea":
                return el
            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, depth + 1))
        except Exception:
            pass
    return None


def focus_input(ax_root, max_depth: int = 10) -> bool:
    """找到聊天输入框并聚焦，成功返回 True。"""
    text_area = bfs_find_input(ax_root, max_depth)
    if text_area is None:
        return False
    try:
        AXUIElementSetAttributeValue(text_area, kAXFocusedAttribute, True)
        return True
    except Exception:
        return False


def bfs_find_msg_table(ax_root, max_depth: int = 8):
    """
    BFS 找消息历史的 AXTable。

    注意：不同 app 的 AXTable depth 可能不同（企业微信为 depth=6）。
    本函数找到第一个 depth >= 4 的 AXTable 即返回，适配不同 app。
    若探测后发现 depth 固定，可在 adapter 中传入更精确的 max_depth。
    """
    from collections import deque

    queue = deque([(ax_root, 0)])
    while queue:
        el, d = queue.popleft()
        if d > max_depth:
            continue
        try:
            _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            if role == "AXTable" and d >= 4:
                return el
            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, d + 1))
        except Exception:
            pass
    return None


# ── 剪贴板操作 ─────────────────────────────────────────────────


def set_clipboard_text(text: str):
    """将纯文本写入系统剪贴板。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def get_clipboard_text() -> str:
    """读取系统剪贴板纯文本内容。"""
    pb = NSPasteboard.generalPasteboard()
    return pb.stringForType_(NSPasteboardTypeString) or ""


def set_clipboard_png(image_path: str):
    """
    将图片以 public.png 格式写入剪贴板。

    必须用 public.png，writeObjects_([NSImage]) 只写 TIFF，
    Electron/Chromium 类 app（企业微信、微信）不识别 TIFF。
    """
    image = NSImage.alloc().initWithContentsOfFile_(image_path)
    if image is None:
        raise ValueError(f"无法加载图片: {image_path}")
    tiff_data = image.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
    png_data = bitmap.representationUsingType_properties_(4, None)  # 4 = NSPNGFileType
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    if png_data:
        pb.setData_forType_(png_data, "public.png")
    else:
        pb.writeObjects_([image])  # 兜底：写 TIFF


# ── 键盘操作 ───────────────────────────────────────────────────


def _cmd_v():
    """模拟 Cmd+V 粘贴（CGEvent）。"""
    down = CGEventCreateKeyboardEvent(None, _KEY_V, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.05)
    up = CGEventCreateKeyboardEvent(None, _KEY_V, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.05)


def paste_and_send(app_name: str, delay: float = 0.1):
    """
    Cmd+V 粘贴剪贴板内容，AppleScript keystroke return 发送。

    app_name 用于 AppleScript tell process 定向，确保 Enter 发给正确进程。
    Enter 必须走 AppleScript（不走 CGEvent），原因：Electron/WebKit 子进程
    会丢弃 CGEvent 的裸 Return 键。
    """
    _cmd_v()
    time.sleep(delay)
    script = f'''
    tell application "System Events"
        tell process "{app_name}"
            key code 36
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ── 消息读取 ───────────────────────────────────────────────────


def _dedup_ax_value(raw: str) -> str:
    """
    部分 app 的 kAXValueAttribute 会将内容重复两次（AX 渲染层 bug），去重。

    "你好你好" → "你好"
    "你好"     → "你好"
    """
    half = len(raw) // 2
    if half and raw[:half] == raw[half:]:
        return raw[:half]
    return raw


def read_messages_from_table(table_element, max_messages: int = 20) -> list[dict]:
    """
    从消息历史 AXTable 读取消息列表。

    每条消息格式：{"content": str, "time": str | None}
    按显示顺序返回，最多 max_messages 条。
    """
    messages = []
    try:
        _, rows = AXUIElementCopyAttributeValue(table_element, kAXChildrenAttribute, None)
        if not rows:
            return []
        for row in rows:
            _, cells = AXUIElementCopyAttributeValue(row, kAXChildrenAttribute, None)
            if not cells:
                continue
            content, time_str = _extract_cell_fields(cells[0])
            if content:
                messages.append({"content": content, "time": time_str})
    except Exception:
        pass
    return messages[-max_messages:]


def _extract_cell_fields(cell) -> tuple[str | None, str | None]:
    """从消息 Cell 中提取内容文本和时间字符串。"""
    content = None
    time_str = None
    try:
        _, children = AXUIElementCopyAttributeValue(cell, kAXChildrenAttribute, None)
        if not children:
            return None, None
        for child in children:
            _, role = AXUIElementCopyAttributeValue(child, kAXRoleAttribute, None)
            _, val = AXUIElementCopyAttributeValue(child, kAXValueAttribute, None)
            if role == "AXTextArea" and val and content is None:
                content = _dedup_ax_value(str(val))
            elif role == "AXStaticText" and val:
                time_str = str(val)
    except Exception:
        pass
    return content, time_str
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/bin/python -m pytest tests/test_ax_helpers.py -v
```

Expected: 全部 PASS（mock 隔离 NSWorkspace / CGEvent，不需要真机）

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile im_clients/ax_helpers.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add im_clients/ax_helpers.py tests/test_ax_helpers.py
git commit -m "feat: add ax_helpers with parameterized AX utilities for multi-IM adapters"
```

---

## Task 4：实现 `im_clients/wechat.py`（微信 adapter）

**Files:**
- Modify: `im_clients/wechat.py`
- Modify: `tests/test_im_clients.py`（新增微信 adapter 测试）

- [ ] **Step 1: 在 test_im_clients.py 中新增微信 adapter 测试**

在 `tests/test_im_clients.py` 末尾添加：

```python
class WechatAdapterSendTests(unittest.TestCase):
    @patch("im_clients.wechat.is_app_running", return_value=False)
    def test_send_blocks_returns_false_when_not_running(self, _):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "hello"}])
        self.assertFalse(result)

    @patch("im_clients.wechat.activate_app", return_value=True)
    @patch("im_clients.wechat.is_app_running", return_value=True)
    @patch("im_clients.wechat.get_ax_element")
    @patch("im_clients.wechat.focus_input", return_value=True)
    @patch("im_clients.wechat.get_clipboard_text", return_value="")
    @patch("im_clients.wechat.paste_and_send")
    @patch("im_clients.wechat.set_clipboard_text")
    def test_send_text_calls_clipboard_and_paste(
        self, set_clip, paste_mock, get_clip, focus, ax_el, running, activate
    ):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "你好"}])
        self.assertTrue(result)
        set_clip.assert_any_call("你好")
        paste_mock.assert_called_once()

    @patch("im_clients.wechat.activate_app", return_value=True)
    @patch("im_clients.wechat.is_app_running", return_value=True)
    @patch("im_clients.wechat.get_ax_element")
    @patch("im_clients.wechat.focus_input", return_value=False)
    def test_send_raises_when_no_chat_window(self, focus, ax_el, running, activate):
        from im_clients.base import UnsupportedClientAction
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        with self.assertRaises(UnsupportedClientAction):
            adapter.send_blocks([{"type": "text", "content": "你好"}])

    @patch("im_clients.wechat.is_app_running", return_value=False)
    def test_read_chat_returns_empty_when_not_running(self, _):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])

    @patch("im_clients.wechat.activate_app", return_value=True)
    @patch("im_clients.wechat.is_app_running", return_value=True)
    @patch("im_clients.wechat.get_ax_element")
    @patch("im_clients.wechat.bfs_find_msg_table", return_value=None)
    def test_read_chat_returns_empty_when_no_table(self, table, ax_el, running, activate):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])
```

- [ ] **Step 2: 运行新增测试，确认失败**

```bash
.venv/bin/python -m pytest tests/test_im_clients.py::WechatAdapterSendTests -v 2>&1 | head -20
```

Expected: 各种 ImportError 或 AttributeError（`send_blocks` / `read_chat_messages` 未实现）

- [ ] **Step 3: 实现 `im_clients/wechat.py`**

完整替换文件内容：

```python
# im_clients/wechat.py
from __future__ import annotations

import os
import tempfile

from .ax_helpers import (
    activate_app,
    bfs_find_msg_table,
    focus_input,
    get_ax_element,
    get_clipboard_text,
    is_app_running,
    paste_and_send,
    read_messages_from_table,
    set_clipboard_png,
    set_clipboard_text,
)
from .base import IMClientAdapter, TakeoverCapabilities, UnsupportedClientAction


class WechatAdapter(IMClientAdapter):
    """
    微信（个人版）IM 适配器。

    AX 树结构待真机探测（运行 tools/explore_ax.py 微信）后确认。
    发送流程与企业微信一致：剪贴板 Cmd+V + AppleScript Enter。
    verified=False：真机测试通过后改为 True。
    """

    client_id = "wechat"
    display_name = "微信"
    app_names = ("微信", "WeChat")
    bundle_ids = ("com.tencent.xinWeChat", "com.tencent.xinwechat")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=False,  # 真机测试通过后改为 True
    )

    # 进程名（AppleScript tell process 用）
    # 微信实际进程名可能为 "微信" 或 "WeChat"，真机探测后确认
    _PROCESS_NAME = "微信"

    def is_running(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return True
        return False

    def activate(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return activate_app(name)
        return False

    def _get_app_name(self) -> str | None:
        """返回当前正在运行的 app_name（用于 AX 查找）。"""
        for name in self.app_names:
            if is_app_running(name):
                return name
        return None

    def send_blocks(self, blocks: list) -> bool:
        """
        发送 blocks 到当前微信聊天窗口。

        纯文字：set_clipboard_text + paste_and_send
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png + paste_and_send
        图文混排：合成单张图片发送（保证只出现一条消息）
        """
        app_name = self._get_app_name()
        if app_name is None:
            return False

        if not activate_app(app_name):
            return False

        ax = get_ax_element(app_name)
        if ax is None:
            return False

        from ApplicationServices import AXUIElementCopyAttributeValue, kAXWindowsAttribute
        try:
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                raise UnsupportedClientAction("微信未找到聊天窗口，请先选中一个聊天")
            if not focus_input(windows[0]):
                raise UnsupportedClientAction("微信未找到聊天输入框，请先选中一个聊天")
        except UnsupportedClientAction:
            raise
        except Exception:
            raise UnsupportedClientAction("微信 AX 访问失败，请检查辅助功能权限")

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks, app_name)
        else:
            return self._send_text_blocks(blocks, app_name)

    def _send_text_blocks(self, blocks: list, app_name: str) -> bool:
        """纯文字 blocks：拼接后写剪贴板，paste_and_send。"""
        text = "\n".join(
            b.get("content", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            return False
        original = get_clipboard_text()
        set_clipboard_text(text)
        paste_and_send(app_name=app_name)
        set_clipboard_text(original)
        return True

    def _send_as_image(self, blocks: list, app_name: str) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        import sender  # 复用企业微信已验证的图片合成逻辑

        tmp = tempfile.mktemp(suffix=".png")
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=app_name)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"微信图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """读取当前微信聊天窗口的消息记录。"""
        app_name = self._get_app_name()
        if app_name is None:
            return []

        ax = get_ax_element(app_name)
        if ax is None:
            return []

        try:
            from ApplicationServices import AXUIElementCopyAttributeValue, kAXWindowsAttribute
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                return []
            table = bfs_find_msg_table(windows[0])
            if table is None:
                return []
            return read_messages_from_table(table, max_messages)
        except Exception:
            return []
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
.venv/bin/python -m pytest tests/test_im_clients.py -v
```

Expected: 全部 PASS（包括新增的 WechatAdapterSendTests 和原有测试）

注意：原有测试 `test_unverified_adapter_blocks_send` 断言微信 adapter 抛 `UnsupportedClientAction`，但现在微信已经实现了 `send_blocks`（不再抛异常）。需要更新该测试：

```python
# 将 tests/test_im_clients.py 中的 test_unverified_adapter_blocks_send 改为：
def test_unverified_adapter_blocks_send_daxiang_still_raises(self):
    clients = discover_clients(
        [
            ApplicationInfo(name="大象", bundle_id="com.sankuai.daxiang", running=True, pid=1234),
        ]
    )
    daxiang = next(client for client in clients if client.client_id == "daxiang")

    with self.assertRaises(UnsupportedClientAction):
        daxiang.adapter.send_blocks([{"type": "text", "content": "hello"}])
```

（大象 adapter 在 Task 5 完成前仍用默认的 `raise UnsupportedClientAction`，此测试继续有效。）

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile im_clients/wechat.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add im_clients/wechat.py tests/test_im_clients.py
git commit -m "feat: implement WechatAdapter send_blocks and read_chat_messages"
```

---

## Task 5：实现 `im_clients/daxiang.py`（大象 adapter）

**Files:**
- Modify: `im_clients/daxiang.py`
- Modify: `tests/test_im_clients.py`（新增大象 adapter 测试）

- [ ] **Step 1: 在 test_im_clients.py 中新增大象 adapter 测试**

在 `tests/test_im_clients.py` 末尾追加：

```python
class DaxiangAdapterSendTests(unittest.TestCase):
    @patch("im_clients.daxiang.is_app_running", return_value=False)
    def test_send_blocks_returns_false_when_not_running(self, _):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "hello"}])
        self.assertFalse(result)

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.focus_input", return_value=True)
    @patch("im_clients.daxiang.get_clipboard_text", return_value="")
    @patch("im_clients.daxiang.paste_and_send")
    @patch("im_clients.daxiang.set_clipboard_text")
    def test_send_text_calls_clipboard_and_paste(
        self, set_clip, paste_mock, get_clip, focus, ax_el, running, activate
    ):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "你好"}])
        self.assertTrue(result)
        set_clip.assert_any_call("你好")
        paste_mock.assert_called_once()

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.focus_input", return_value=False)
    def test_send_raises_when_no_chat_window(self, focus, ax_el, running, activate):
        from im_clients.base import UnsupportedClientAction
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        with self.assertRaises(UnsupportedClientAction):
            adapter.send_blocks([{"type": "text", "content": "你好"}])

    @patch("im_clients.daxiang.is_app_running", return_value=False)
    def test_read_chat_returns_empty_when_not_running(self, _):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.bfs_find_msg_table", return_value=None)
    def test_read_chat_returns_empty_when_no_table(self, table, ax_el, running, activate):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])
```

- [ ] **Step 2: 运行新增测试，确认失败**

```bash
.venv/bin/python -m pytest tests/test_im_clients.py::DaxiangAdapterSendTests -v 2>&1 | head -20
```

Expected: 各种 AttributeError（`send_blocks` / `read_chat_messages` 未实现）

- [ ] **Step 3: 实现 `im_clients/daxiang.py`**

完整替换文件内容（与 wechat.py 结构对称，只有 id/名字/进程名不同）：

```python
# im_clients/daxiang.py
from __future__ import annotations

import os
import tempfile

from .ax_helpers import (
    activate_app,
    bfs_find_msg_table,
    focus_input,
    get_ax_element,
    get_clipboard_text,
    is_app_running,
    paste_and_send,
    read_messages_from_table,
    set_clipboard_png,
    set_clipboard_text,
)
from .base import IMClientAdapter, TakeoverCapabilities, UnsupportedClientAction


class DaxiangAdapter(IMClientAdapter):
    """
    大象（美团内部 IM）适配器。

    AX 树结构待真机探测（运行 tools/explore_ax.py 大象）后确认。
    发送流程与企业微信一致：剪贴板 Cmd+V + AppleScript Enter。
    verified=False：真机测试通过后改为 True。
    """

    client_id = "daxiang"
    display_name = "大象"
    app_names = ("大象", "Daxiang", "DaXiang")
    bundle_ids = ("com.sankuai.daxiang", "com.meituan.daxiang")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=False,  # 真机测试通过后改为 True
    )

    # 进程名（AppleScript tell process 用）
    # 大象实际进程名需真机探测确认
    _PROCESS_NAME = "大象"

    def is_running(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return True
        return False

    def activate(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return activate_app(name)
        return False

    def _get_app_name(self) -> str | None:
        """返回当前正在运行的 app_name（用于 AX 查找）。"""
        for name in self.app_names:
            if is_app_running(name):
                return name
        return None

    def send_blocks(self, blocks: list) -> bool:
        """
        发送 blocks 到当前大象聊天窗口。

        纯文字：set_clipboard_text + paste_and_send
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png + paste_and_send
        图文混排：合成单张图片发送（保证只出现一条消息）
        """
        app_name = self._get_app_name()
        if app_name is None:
            return False

        if not activate_app(app_name):
            return False

        ax = get_ax_element(app_name)
        if ax is None:
            return False

        from ApplicationServices import AXUIElementCopyAttributeValue, kAXWindowsAttribute
        try:
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                raise UnsupportedClientAction("大象未找到聊天窗口，请先选中一个聊天")
            if not focus_input(windows[0]):
                raise UnsupportedClientAction("大象未找到聊天输入框，请先选中一个聊天")
        except UnsupportedClientAction:
            raise
        except Exception:
            raise UnsupportedClientAction("大象 AX 访问失败，请检查辅助功能权限")

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks, app_name)
        else:
            return self._send_text_blocks(blocks, app_name)

    def _send_text_blocks(self, blocks: list, app_name: str) -> bool:
        """纯文字 blocks：拼接后写剪贴板，paste_and_send。"""
        text = "\n".join(
            b.get("content", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            return False
        original = get_clipboard_text()
        set_clipboard_text(text)
        paste_and_send(app_name=app_name)
        set_clipboard_text(original)
        return True

    def _send_as_image(self, blocks: list, app_name: str) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        import sender  # 复用企业微信已验证的图片合成逻辑

        tmp = tempfile.mktemp(suffix=".png")
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=app_name)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"大象图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """读取当前大象聊天窗口的消息记录。"""
        app_name = self._get_app_name()
        if app_name is None:
            return []

        ax = get_ax_element(app_name)
        if ax is None:
            return []

        try:
            from ApplicationServices import AXUIElementCopyAttributeValue, kAXWindowsAttribute
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                return []
            table = bfs_find_msg_table(windows[0])
            if table is None:
                return []
            return read_messages_from_table(table, max_messages)
        except Exception:
            return []
```

- [ ] **Step 4: 运行全部测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 5: 语法检查所有修改文件**

```bash
.venv/bin/python -m py_compile im_clients/daxiang.py im_clients/wechat.py im_clients/ax_helpers.py tools/explore_ax.py && echo "ALL OK"
```

Expected: `ALL OK`

- [ ] **Step 6: Commit**

```bash
git add im_clients/daxiang.py tests/test_im_clients.py
git commit -m "feat: implement DaxiangAdapter send_blocks and read_chat_messages"
```

---

## Task 6：最终验收

**Files:**
- 无新增文件

- [ ] **Step 1: 运行全部测试套件**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: 全部 PASS，无 FAIL / ERROR

- [ ] **Step 2: 确认 sender.py 和 gui_panel.py 未被修改**

```bash
git diff master -- sender.py gui_panel.py
```

Expected: 无输出（未改动）

- [ ] **Step 3: 查看完整 diff**

```bash
git diff master --stat
```

Expected 新增/修改文件：
```
 im_clients/ax_helpers.py          | (新增)
 im_clients/daxiang.py             | (修改)
 im_clients/wechat.py              | (修改)
 tests/test_ax_helpers.py          | (新增)
 tests/test_im_clients.py          | (修改)
 tools/explore_ax.py               | (新增)
 docs/superpowers/specs/2026-06-04-multi-im-adapters-design.md | (新增)
```

- [ ] **Step 4: 真机探测微信 AX 树（需要微信运行）**

打开微信并选中任意聊天窗口后运行：
```bash
.venv/bin/python tools/explore_ax.py 微信 12
```

根据输出确认：
1. 候选输入框的 depth 值 → 如与企业微信不同（≠6），在 `wechat.py` 的 `focus_input` 调用中传入 `max_depth` 参数
2. 候选消息历史 AXTable 的 depth 值 → 如与企业微信不同（≠6），在 `wechat.py` 的 `bfs_find_msg_table` 调用中传入 `max_depth` 参数

- [ ] **Step 5: 真机探测大象 AX 树（需要大象运行）**

打开大象并选中任意聊天窗口后运行：
```bash
.venv/bin/python tools/explore_ax.py 大象 12
```

同上，根据输出调整 `daxiang.py` 中的 `max_depth` 参数（如需要）。

- [ ] **Step 6: 真机测试微信发送（需要微信运行并选中聊天）**

```bash
.venv/bin/python -c "
from im_clients.wechat import WechatAdapter
adapter = WechatAdapter()
print('running:', adapter.is_running())
result = adapter.send_blocks([{'type': 'text', 'content': '测试消息 [自动化测试]'}])
print('send result:', result)
"
```

Expected: 微信聊天窗口出现「测试消息 [自动化测试]」，`send result: True`

- [ ] **Step 7: 真机测试微信读取（需要微信运行并有聊天消息）**

```bash
.venv/bin/python -c "
from im_clients.wechat import WechatAdapter
adapter = WechatAdapter()
msgs = adapter.read_chat_messages(max_messages=5)
for m in msgs:
    print(m)
"
```

Expected: 打印最近 5 条消息，格式 `{'content': '...', 'time': '...'}`

- [ ] **Step 8: 真机测试通过后设置 verified=True**

如微信测试通过，在 `im_clients/wechat.py` 中：
```python
# 将：
verified=False,  # 真机测试通过后改为 True
# 改为：
verified=True,
```

如大象测试通过，在 `im_clients/daxiang.py` 中同样修改。

- [ ] **Step 9: 最终 commit**

```bash
git add -A
git commit -m "feat: multi-IM adapters - wechat and daxiang fully implemented

- 新增 im_clients/ax_helpers.py：通用 AX 工具函数（参数化 app_name）
- 实现 WechatAdapter：send_blocks + read_chat_messages
- 实现 DaxiangAdapter：send_blocks + read_chat_messages
- 新增 tools/explore_ax.py：AX 树探测工具
- sender.py / gui_panel.py 未改动"
```

---

## 真机调试参考

如果探测后发现微信/大象的输入框在更深的 depth，在对应 adapter 中调整调用参数：

```python
# wechat.py 或 daxiang.py 中的 send_blocks：
# 默认 max_depth=10，足够覆盖大多数 app
if not focus_input(windows[0], max_depth=12):   # 如探测结果 > 10，调大
    raise UnsupportedClientAction(...)

# read_chat_messages 中：
table = bfs_find_msg_table(windows[0], max_depth=10)  # 如探测结果 > 8，调大
```

如果微信/大象是原生 macOS app（非 Electron），AppleScript Enter 可能多发一次消息。调试方法：先发一条消息，确认只出现一条；若出现两条，说明原生 app 粘贴后自动发送，去掉 `paste_and_send` 里的 AppleScript Enter（仅 `_cmd_v()`）。
