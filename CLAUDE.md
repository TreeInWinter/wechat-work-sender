# 企业微信快捷发送面板 — CLAUDE.md

> 此文件记录关键技术决策与背景，防止上下文压缩后遗失。

---

## 项目定位

macOS 辅助工具，通过 Accessibility API（AX API）自动化企业微信，提供话术快捷发送和聊天内容读取。**不修改企业微信进程，不走网络接口**，纯系统级 API。

---

## 技术栈

- **GUI**：CustomTkinter 5.2.x（不是原生 tkinter）
- **macOS 集成**：pyobjc-framework-{Cocoa, Quartz, ApplicationServices}
- **Python**：3.13，venv 用 `uv` 管理（`.venv/bin/python`）
- **远端仓库**：`ssh://git@git.sankuai.com/~baijinshan/wechat_work_sender.git`（美团内部）

---

## 关键技术决策（必读）

### 1. Enter 键用 AppleScript，不用 CGEvent

```python
# 正确做法
script = 'tell application "System Events" to keystroke return'
subprocess.run(["osascript", "-e", script])

# 错误做法（已验证无效）
press_key(KEY_RETURN)  # CGEvent kCGHIDEventTap
```

**原因**：企业微信基于 Electron/Chromium，Chromium 渲染进程有独立事件处理层，会丢弃 `CGEvent kCGHIDEventTap` 的裸 Return 键。AppleScript 走 `System Events` 通道，绕过这层，对 Electron 应用可靠。

---

### 2. 窗口激活用 PyObjC，不用 AppleScript

```python
# 正确做法（~10ms）
app = NSWorkspace.sharedWorkspace().runningApplications()
app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

# 旧做法（~600ms，已废弃）
subprocess.run(["osascript", "-e", 'tell application "企业微信" to activate'])
```

**原因**：AppleScript 每次启动新子进程，有固定 80ms+ 开销，加上 `delay 0.3` 总计 600ms。PyObjC 直接调用系统 API，< 10ms。

---

### 3. 查找聊天输入框用 BFS，不用 DFS

```python
# 正确做法（BFS - 优先最浅层）
queue = deque([(root, 0)])
while queue:
    el, depth = queue.popleft()  # ← 广度优先，先找浅层

# 错误做法（DFS - 先深入）
# 会找到 depth=9 的消息历史 AXTextArea（只读），而非 depth=6 的输入框
```

**企业微信 AX 树关键节点**：
- `depth=4`：左侧会话列表的 AXTable（跳过）
- `depth=6`：聊天输入框 AXTextArea（`value=None`，可写）★
- `depth=6`：当前聊天消息历史的 AXTable（读取用）
- `depth=9`：消息历史中的 AXTextArea（内容有值，只读镜像）

DFS 先深入左侧会话列表 → 找到 depth=9 的消息历史 AXTextArea → 聚焦后粘贴失败。BFS 优先找 depth=6 的输入框 → 正确。

---

### 4. 弹出框必须临时关闭 topmost

```python
# 所有 dialog/messagebox 调用前后都要这样做
def _ask_input(self, title, prompt):
    self.root.attributes("-topmost", False)   # ← 必须关
    dialog = ctk.CTkInputDialog(text=prompt, title=title)
    result = dialog.get_input()
    self.root.attributes("-topmost", True)    # ← 恢复
    return result
```

**原因**：macOS 上 `attributes("-topmost", True)` 把窗口提升到 `NSFloatingWindowLevel`（层级 3）。所有弹窗（`messagebox`、`simpledialog`、`CTkInputDialog`）默认在 `NSNormalWindowLevel`（层级 0），永远被主窗口遮盖，用户看不到。

三个辅助方法封装了这个逻辑：`_ask_input()`、`_show_warning()`、`_ask_yesno()`。

---

### 5. 窗口位置轮询在主线程，不用后台线程

```python
def _poll_snap(self):
    bounds = get_wechat_window_bounds()  # AX API，< 5ms
    if bounds != self._last_bounds:
        self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
    self.root.after(100, self._poll_snap)  # 主线程，100ms 轮询
```

**原因**：AX API 调用 < 5ms，无需后台线程减少开销。后台线程反而增加复杂度（需要 `root.after(0, lambda: ...)` 回主线程）。直接在主线程每 100ms 调用，简单可靠。

---

### 6. 聊天消息读取的去重逻辑

```python
half = len(raw) // 2
content = raw[:half] if half and raw[:half] == raw[half:] else raw
```

**原因**：企业微信 AX 树中，部分消息的 `kAXValueAttribute` 会把内容重复两次（AX 渲染层的 bug）。需要检测 "X+X" 模式并去重。

---

## 项目文件结构

```
gui_panel.py   # CustomTkinter GUI，所有 UI 逻辑
sender.py      # 核心逻辑：发送、AX 查找、聊天读取
phrases.json   # 话术数据（用户数据，不提交敏感内容）
docs/
  design.md       # 技术设计文档
  product.md      # 产品文档
  user-manual.md  # 使用手册
  superpowers/
    specs/        # 设计稿
    plans/        # 实现计划
```

---

## 分支状态

| 分支 | 状态 | 说明 |
|------|------|------|
| `master` | 主干 | 包含 CustomTkinter UI 现代化 |
| `feature/sync-minimize` | 活跃 | 文档沉淀分支，待合并 |
| `feature/ui-modernization` | 已合并 | CustomTkinter 迁移 |
| `feature/read-chat-content` | 已合并 | 聊天内容读取 |
| `wechat_for_enter` | 已合并 | 企业微信适配 + Enter 修复 |

---

## 已知坑

1. **`_find_text_area` depth 依赖**：当前聊天输入框在 depth=6，消息历史在 depth=9。如果企业微信更新了 UI 布局，depth 可能变化，需要重新探测。

2. **`simpledialog` 在 CTk 中完全失效**：不要用 `simpledialog.askstring(parent=ctk_window)`，即使加 parent 也会被遮挡。统一用 `_ask_input()` 封装。

3. **AX 只读限制**：`kAXValueAttribute` 可读不可写（Electron WebView）。发送消息只能走「剪贴板 + Cmd+V」路线，不能直接 `AXUIElementSetAttributeValue` 写入文本。

4. **`NoChatWindowError`**：在 `send_message()` 中由 `focus_chat_input()` 返回 False 时抛出。GUI 的 `_do_send()` 捕获后调用 `_show_warning()`（注意用辅助方法，不能直接 `messagebox.showwarning`）。

5. **`resizable(False, False)`**：主窗口禁止手动拖拽，尺寸由 `_poll_snap` 控制。不影响 `geometry()` 的程序化调用。

---

## 常用命令

```bash
# 运行
.venv/bin/python gui_panel.py

# 语法检查
.venv/bin/python -m py_compile gui_panel.py sender.py

# 探测企业微信 AX 树（调试用）
.venv/bin/python -c "
from sender import _get_ax_app
from ApplicationServices import *
from collections import deque
ax = _get_ax_app()
_, wins = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
# BFS 打印所有 AXTextArea
queue = deque([(wins[0], 0)])
while queue:
    el, d = queue.popleft()
    if d > 12: continue
    _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
    if role == 'AXTextArea':
        _, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
        print(f'depth={d} val={repr(str(val)[:40] if val else None)}')
    _, ch = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
    if ch:
        for c in ch: queue.append((c, d+1))
"
```
