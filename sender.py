#!/usr/bin/env python3
"""
大象自动发送 Demo (macOS)

原理：
1. AppleScript 激活大象窗口
2. NSPasteboard 写入要发送的文本到系统剪贴板
3. CGEvent 模拟 Cmd+V 粘贴
4. CGEvent 模拟 Enter 发送

使用前提：
- 大象桌面端已打开且已进入某个聊天窗口
- 终端/Python 已在「系统设置 → 隐私与安全性 → 辅助功能」中获得授权
"""

import sys
import time
import subprocess

# macOS 原生框架
from AppKit import NSPasteboard, NSStringPboardType, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
    kCGEventKeyDown,
    kCGEventKeyUp,
)


# ============================================================
# 模块一：窗口识别与激活
# ============================================================

DAXIANG_APP_NAME = "大象"


def is_daxiang_running() -> bool:
    """检查大象是否正在运行"""
    script = f'''
    tell application "System Events"
        set appList to name of every process
        return appList contains "大象"
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    return "true" in result.stdout.lower()


def activate_daxiang() -> bool:
    """
    激活大象窗口并将焦点放到最前面的聊天输入框。
    返回是否成功激活。
    """
    script = '''
    tell application "大象"
        activate
    end tell
    delay 0.3
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[错误] 激活大象失败: {result.stderr}")
        return False
    # 给窗口一点时间完成激活
    time.sleep(0.3)
    return True


def get_frontmost_app() -> str:
    """获取当前最前台应用名称"""
    script = '''
    tell application "System Events"
        return name of first application process whose frontmost is true
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    return result.stdout.strip()


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
    """模拟按下 Enter 键"""
    press_key(KEY_RETURN)


def select_all():
    """模拟 Cmd+A 全选"""
    press_key(KEY_A, kCGEventFlagMaskCommand)


# ============================================================
# 模块四：核心发送逻辑
# ============================================================

def send_message(text: str, auto_activate: bool = True, delay_before_send: float = 0.5) -> bool:
    """
    向大象当前聊天窗口发送一条文本消息。

    参数：
        text: 要发送的消息文本
        auto_activate: 是否自动激活大象窗口（如果已经是前台则不需要）
        delay_before_send: 粘贴后等待多久再按回车（秒），防止粘贴未完成就发送

    返回：
        是否发送成功（基本判断，无法100%确认消息已送达）
    """
    if not text.strip():
        print("[警告] 消息内容为空，跳过发送")
        return False

    # Step 1: 检查大象是否运行
    if not is_daxiang_running():
        print("[错误] 大象未运行，请先打开大象并进入聊天窗口")
        return False

    # Step 2: 激活大象
    if auto_activate:
        if not activate_daxiang():
            return False

    # 确认当前前台是大象
    frontmost = get_frontmost_app()
    if "大象" not in frontmost:
        print(f"[警告] 当前前台应用是 '{frontmost}'，不是大象，尝试继续...")

    # Step 3: 保存原始剪贴板内容
    original_clipboard = get_clipboard()

    # Step 4: 写入消息到剪贴板
    set_clipboard(text)
    time.sleep(0.1)

    # Step 5: 模拟 Cmd+V 粘贴
    paste()
    time.sleep(delay_before_send)

    # Step 6: 再等一下确保粘贴内容渲染完成
    time.sleep(0.3)

    # Step 7: 模拟 Enter 发送
    press_enter()
    time.sleep(0.2)

    # Step 7: 恢复原始剪贴板（可选，防止覆盖用户剪贴板）
    if original_clipboard:
        time.sleep(0.3)
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
