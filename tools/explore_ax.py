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
    err, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
    if err != 0:
        print(f"[错误] 无法读取「{app_name}」窗口（AX错误码={err}），请检查辅助功能权限。")
        sys.exit(1)
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
                marker = "  ← AXTable（可能是消息历史容器或会话列表）"

            print(f"depth={d:<4} {role_str:<24} {val_preview}{marker}")

            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, d + 1))
        except Exception as e:
            pass  # AX 元素可能在遍历中失效，静默跳过

    print(f"\n共遍历 {total} 个节点（max_depth={max_depth}）")
    print("\n提示：")
    print("  ★ 候选输入框 = BFS 最浅的 AXTextArea（value=None）")
    print("  候选消息历史容器 = AXTable，其子节点含消息 cells")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    app_name = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            max_depth = int(sys.argv[2])
        except ValueError:
            print(f"[错误] max_depth 必须是整数，收到：{sys.argv[2]!r}")
            sys.exit(1)
    else:
        max_depth = 12
    explore(app_name, max_depth)
