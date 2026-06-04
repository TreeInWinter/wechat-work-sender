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
from collections import deque

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
    queue = deque([(ax_root, 0)])
    while queue:
        el, depth = queue.popleft()
        if depth > max_depth:
            continue
        try:
            _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            if role == "AXTextArea":
                _, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
                if not val:   # value=None 表示空可写输入框
                    return el
            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, depth + 1))
        except Exception:
            pass  # AX 元素可能在遍历中失效，静默跳过
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
            pass  # AX 元素可能在遍历中失效，静默跳过
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
        raise ValueError(f"无法将图片转换为 PNG 格式：{image_path}")


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
        pass  # AXTable 或 rows 迭代失效时静默返回已收集的消息
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
