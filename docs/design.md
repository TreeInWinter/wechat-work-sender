# 技术设计文档

**项目：** 企业微信快捷发送面板  
**版本：** 1.0  
**日期：** 2026-05-20  
**平台：** macOS 10.15+

---

## 1. 系统概述

本系统是一个 macOS 原生辅助工具，通过 Accessibility API（AX API）与企业微信进行自动化交互，提供话术快捷发送和聊天内容读取能力，无需侵入企业微信进程、无需网络接口。

### 1.1 核心设计原则

- **零侵入**：不修改企业微信，只通过 macOS 系统级 API 操作
- **低延迟**：所有操作在主线程完成，AX API 调用 < 5ms
- **健壮性**：每个异常场景都有明确的用户提示而非崩溃

---

## 2. 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| GUI 框架 | CustomTkinter 5.2.x | 现代化 UI，自动深色/浅色模式 |
| macOS 集成 | pyobjc-framework-Cocoa | NSPasteboard、NSWorkspace、NSRunningApplication |
| macOS 集成 | pyobjc-framework-Quartz | CGEvent 键盘事件模拟 |
| macOS 集成 | pyobjc-framework-ApplicationServices | AXUIElement 辅助功能 API |
| 自动化脚本 | osascript（AppleScript） | Enter 键发送（Electron 专项）|
| 数据持久化 | JSON 文件（phrases.json）| 话术库 |

---

## 3. 核心模块

### 3.1 发送流程（sender.py）

```
用户点击「发送」
    │
    ▼
activate_daxiang()
    NSRunningApplication.activateWithOptions_()
    sleep(0.1)  # 等待窗口激活
    │
    ▼
focus_chat_input()  ← BFS 遍历 AX 树
    AXUIElementCopyAttributeValue(win, kAXWindowsAttribute)
    BFS 队列遍历，优先找最浅 AXTextArea (depth=6)
    AXUIElementSetAttributeValue(ta, kAXFocusedAttribute, True)
    │
    ▼
set_clipboard(text)
    NSPasteboard.generalPasteboard().clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    │
    ▼
paste()  ← CGEvent
    CGEventCreateKeyboardEvent(None, KEY_V, True)
    CGEventSetFlags(event, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event)
    sleep(0.1)
    │
    ▼
press_enter()  ← AppleScript（CGEvent 对 Electron 不可靠）
    osascript: tell System Events to keystroke return
    │
    ▼
restore_clipboard()
```

**为什么 Enter 用 AppleScript 而非 CGEvent？**

企业微信基于 Electron（Chromium 渲染进程），`CGEvent + kCGHIDEventTap` 的 Return 键会被 Chromium 事件层丢弃。AppleScript `keystroke return` 走 `System Events` 通道，直接注入键盘事件，对 Electron 应用可靠。

### 3.2 AX 树遍历（聊天输入框定位）

企业微信 AX 树结构：

```
AXWindow (depth=0)
└─ AXSplitGroup (depth=1)
   └─ AXSplitGroup (depth=2)
      ├─ AXScrollArea/AXTable (depth=4)   ← 左侧会话列表（AXTextArea 在 depth=7）
      └─ AXSplitGroup
         └─ AXSplitGroup
            └─ AXScrollArea
               ├─ AXTable (depth=6)       ← 当前聊天消息历史
               │  └─ AXRow → AXCell
               │     ├─ AXStaticText      → 时间戳
               │     └─ AXTextArea        → 消息正文（depth=9，只读镜像）
               └─ [输入区]
                  └─ AXTextArea (depth=6) ← 聊天输入框（空，可写）★
```

**BFS vs DFS：**
- DFS（深度优先）：先深入左侧会话列表，找到 depth=9 的消息历史 AXTextArea（只读），返回错误目标
- BFS（广度优先）：按层级遍历，优先找 depth=6 的聊天输入框（空，可写），命中正确目标

### 3.3 聊天消息读取

```python
def read_chat_messages(max_messages=20):
    # 1. BFS 找 AXTable at depth=6（消息历史，区别于 depth=4 的会话列表）
    table = _find_msg_table(windows[0])
    
    # 2. 遍历 AXRow → AXCell
    for row in children(table):
        cell = children(row)[0]
        content = AXTextArea.kAXValueAttribute   # 消息正文
        time    = AXStaticText.kAXValueAttribute  # 时间戳（可能为 None）
    
    # 3. 去重：部分消息 AX 值重复两次（AX 渲染层 bug）
    half = len(raw) // 2
    content = raw[:half] if raw[:half] == raw[half:] else raw
```

### 3.4 窗口贴合与跟随

```python
def _poll_snap(self):
    # 每 100ms 轮询，主线程直接调用（< 5ms，无需后台线程）
    bounds = get_wechat_window_bounds()   # AX API 读坐标
    if bounds != self._last_bounds:
        wx, wy, ww, wh = bounds
        self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
        self._last_bounds = bounds
    self.root.after(100, self._poll_snap)
```

`get_wechat_window_bounds()` 通过 `kAXPositionAttribute` + `kAXSizeAttribute` 读取，配合 `AXValueGetValue` 解包 `CGPoint`/`CGSize`。

---

## 4. 数据模型

### 4.1 话术库（phrases.json）

```json
{
  "问候语": [
    "您好，我是您的专属客服，请问有什么可以帮您？",
    "早上好！有什么需要帮助的吗？"
  ],
  "常用回复": [
    "好的，我这边帮您查一下，请稍等。"
  ]
}
```

分组名为键，话术列表为值，支持动态增删分组和话术，实时持久化。

---

## 5. 错误处理

| 场景 | 检测方式 | 处理 |
|------|----------|------|
| 企业微信未运行 | `NSWorkspace.runningApplications()` | 返回 False，状态栏红点 |
| 无聊天窗口 | BFS 找不到 AXTextArea | 抛出 `NoChatWindowError`，弹窗提示 |
| AX API 失败 | try/except，重置 `_ax_app_cache` | 下次重新初始化 |
| 对话框被遮挡 | macOS NSFloatingWindowLevel 问题 | 弹出前 `attributes("-topmost", False)`，结束后恢复 |

---

## 6. 线程模型

```
主线程（Tkinter 事件循环）
    ├─ _poll_snap()           每 100ms，AX API 读坐标，更新 geometry
    ├─ _check_status()        触发后台线程检测企业微信状态
    └─ UI 事件处理

后台线程（daemon=True）
    ├─ send_task()            发送消息，完成后 root.after(0, ...) 更新 UI
    ├─ fetch()                读取聊天，完成后 root.after(0, ...) 弹窗
    └─ check()                检测运行状态，完成后 root.after(0, ...) 更新圆点
```

所有 UI 操作通过 `root.after(0, lambda: ...)` 回到主线程，保证线程安全。

---

## 7. 已知限制

- **AX API 只读**：企业微信文本框是 Electron WebView 只读镜像，消息内容只能读取不能写入（写入走剪贴板路线）
- **消息历史有限**：AX 树只暴露当前屏幕可见的消息，滚动区域外的消息无法读取
- **macOS 版本依赖**：AX API 在 macOS 系统升级后可能行为变化
- **辅助功能授权**：需要用户手动授权，企业安全策略可能限制
