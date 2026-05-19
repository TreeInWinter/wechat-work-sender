#!/usr/bin/env python3
"""
向企业微信发送消息 Demo (macOS)

原理：
1. AppleScript 激活企业微信窗口
2. NSPasteboard 写入要发送的文本到系统剪贴板
3. CGEvent 模拟 Cmd+V 粘贴
4. CGEvent 模拟 Enter 发送

使用前提：
- 企业微信桌面端已打开且已进入某个聊天窗口
- 终端/Python 已在「系统设置 → 隐私与安全性 → 辅助功能」中获得授权
"""

import sys
import time
import subprocess

# macOS 原生框架
from AppKit import (
    NSPasteboard, NSStringPboardType, NSPasteboardTypeString,
    NSWorkspace, NSApplicationActivateIgnoringOtherApps,
)
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXRoleAttribute,
    kAXChildrenAttribute,
    kAXFocusedAttribute,
    kAXWindowsAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
    kCGEventKeyDown,
    kCGEventKeyUp,
)


class NoChatWindowError(Exception):
    """企业微信未选中聊天窗口时抛出"""
    pass


# ============================================================
# 模块一：窗口识别与激活
# ============================================================

DAXIANG_APP_NAME = "企业微信"


def _get_wechat_app():
    """从 NSWorkspace 找到企业微信的 NSRunningApplication 对象"""
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    return next((a for a in apps if a.localizedName() == DAXIANG_APP_NAME), None)


def is_daxiang_running() -> bool:
    """检查企业微信是否正在运行"""
    return _get_wechat_app() is not None


def activate_daxiang() -> bool:
    """激活企业微信窗口，用 PyObjC 直接调用，无 subprocess 开销"""
    app = _get_wechat_app()
    if app is None:
        print("[错误] 企业微信未运行")
        return False
    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.1)  # 等待窗口完成激活
    return True


_ax_app_cache = None  # 缓存 AXUIElement，避免重复查 PID


def _get_ax_app():
    global _ax_app_cache
    if _ax_app_cache is None:
        app = _get_wechat_app()
        if app is None:
            return None
        _ax_app_cache = AXUIElementCreateApplication(app.processIdentifier())
    return _ax_app_cache


def _find_text_area(element, depth=0):
    """DFS 查找 AXTextArea，最大深度 10"""
    if depth > 10:
        return None
    try:
        _, role = AXUIElementCopyAttributeValue(element, kAXRoleAttribute, None)
        if role == "AXTextArea":
            return element
        _, children = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, None)
        if not children:
            return None
        for child in children:
            result = _find_text_area(child, depth + 1)
            if result is not None:
                return result
    except Exception:
        pass
    return None


def focus_chat_input() -> bool:
    """在 AX 树中找到聊天输入框并主动聚焦。找到返回 True，否则返回 False。"""
    ax = _get_ax_app()
    if ax is None:
        return False
    try:
        _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
        if not windows:
            return False
        text_area = _find_text_area(windows[0])
        if text_area is None:
            return False
        AXUIElementSetAttributeValue(text_area, kAXFocusedAttribute, True)
        return True
    except Exception:
        return False


# ============================================================
# 模块二：剪贴板操作
# ============================================================

def set_clipboard(text: str):
    """将文本写入系统剪贴板"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def get_clipboard() -> str:
    """读取系统剪贴板内容"""
    pb = NSPasteboard.generalPasteboard()
    return pb.stringForType_(NSPasteboardTypeString) or ""


# ============================================================
# 模块三：模拟按键
# ============================================================

# macOS 虚拟键码
KEY_V = 0x09        # V 键
KEY_RETURN = 0x24   # Enter/Return 键
KEY_A = 0x00        # A 键


def press_key(keycode: int, flags: int = 0):
    """
    模拟按下并释放一个按键。
    keycode: macOS 虚拟键码
    flags: 修饰键标记 (如 kCGEventFlagMaskCommand)
    """
    # Key Down
    event_down = CGEventCreateKeyboardEvent(None, keycode, True)
    if flags:
        CGEventSetFlags(event_down, flags)
    CGEventPost(kCGHIDEventTap, event_down)

    time.sleep(0.05)

    # Key Up
    event_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        CGEventSetFlags(event_up, flags)
    CGEventPost(kCGHIDEventTap, event_up)

    time.sleep(0.05)


def paste():
    """模拟 Cmd+V 粘贴"""
    press_key(KEY_V, kCGEventFlagMaskCommand)


def press_enter():
    """用 AppleScript 发送 Return 键，对 Electron 类应用（如企业微信）更可靠"""
    script = '''
    tell application "System Events"
        keystroke return
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def select_all():
    """模拟 Cmd+A 全选"""
    press_key(KEY_A, kCGEventFlagMaskCommand)


# ============================================================
# 模块四：核心发送逻辑
# ============================================================

def send_message(text: str, auto_activate: bool = True, delay_before_send: float = 0.1) -> bool:
    """
    向企业微信当前聊天窗口发送一条文本消息。

    参数：
        text: 要发送的消息文本
        auto_activate: 是否自动激活企业微信窗口（如果已经是前台则不需要）
        delay_before_send: 粘贴后等待多久再按回车（秒），防止粘贴未完成就发送

    返回：
        是否发送成功（基本判断，无法100%确认消息已送达）
    """
    if not text.strip():
        print("[警告] 消息内容为空，跳过发送")
        return False

    # Step 1: 激活企业微信（内含运行检查）
    if auto_activate:
        if not activate_daxiang():
            return False

    # Step 2: 找到聊天输入框并聚焦（同时验证是否有聊天窗口）
    if not focus_chat_input():
        raise NoChatWindowError("请先在企业微信中选中聊天窗口")

    # Step 3: 保存原始剪贴板内容
    original_clipboard = get_clipboard()

    # Step 3: 写入消息到剪贴板并粘贴
    set_clipboard(text)
    paste()
    time.sleep(delay_before_send)

    # Step 4: 模拟 Enter 发送
    press_enter()

    # Step 5: 恢复原始剪贴板
    if original_clipboard:
        set_clipboard(original_clipboard)

    print(f"[成功] 消息已发送: {text[:50]}{'...' if len(text) > 50 else ''}")
    return True


def send_messages_batch(messages: list, interval: float = 1.0):
    """
    批量发送多条消息。

    参数：
        messages: 消息列表
        interval: 每条消息之间的间隔（秒）
    """
    print(f"[信息] 准备批量发送 {len(messages)} 条消息，间隔 {interval} 秒")

    for i, msg in enumerate(messages, 1):
        print(f"[{i}/{len(messages)}] 发送中...")
        success = send_message(msg, auto_activate=(i == 1))
        if not success:
            print(f"[错误] 第 {i} 条消息发送失败，终止批量发送")
            return
        if i < len(messages):
            time.sleep(interval)

    print(f"[完成] 批量发送 {len(messages)} 条消息完毕")


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python sender.py <消息内容>")
        print("示例: python sender.py '你好，这是自动发送的消息'")
        print("")
        print("批量发送（用 | 分隔）:")
        print("  python sender.py '消息1|消息2|消息3'")
        sys.exit(1)

    text = " ".join(sys.argv[1:])

    # 支持用 | 分隔批量发送
    if "|" in text:
        messages = [m.strip() for m in text.split("|") if m.strip()]
        send_messages_batch(messages)
    else:
        send_message(text)


if __name__ == "__main__":
    main()
