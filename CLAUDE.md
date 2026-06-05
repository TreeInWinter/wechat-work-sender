# 企业微信快捷发送面板 — CLAUDE.md

> 此文件记录关键技术决策与背景，防止上下文压缩后遗失。每次会话结束后更新。

---

## 项目定位

macOS 辅助工具，通过 Accessibility API（AX API）自动化企业微信，提供话术快捷发送和聊天内容读取。**不修改企业微信进程，不走网络接口**，纯系统级 API。

---

## 技术栈

- **GUI**：CustomTkinter 5.2.x（不是原生 tkinter）
- **macOS 集成**：pyobjc-framework-{Cocoa, Quartz, ApplicationServices}
- **图片处理**：Pillow（缩略图，`uv pip install Pillow`）
- **Python**：3.10+ 且带 Tk 支持，当前推荐 Miniconda 3.13，venv 用 `uv` 管理（`.venv/bin/python`）
- **远端仓库**：`ssh://git@git.sankuai.com/~baijinshan/wechat_work_sender.git`（美团内部）

---

## 关键技术决策（必读）

### 1. Enter 键用 AppleScript，不用 CGEvent（纯文字消息）

```python
# 正确做法（send_message 内部用法）
script = 'tell application "System Events" to keystroke return'
subprocess.run(["osascript", "-e", script])

# 错误做法（已验证无效）
press_key(KEY_RETURN)  # CGEvent kCGHIDEventTap
```

**原因**：企业微信基于 Electron/Chromium，Chromium 渲染进程有独立事件处理层，会丢弃 `CGEvent kCGHIDEventTap` 的裸 Return 键。AppleScript `keystroke return` 走 `System Events` 通道可靠。

**⚠️ 重要**：此方式只对**纯文字** `send_message()` 有效。图文混排场景见第 6 条。

---

### 2. 窗口激活用 PyObjC，不用 AppleScript

```python
# 正确做法（~10ms）
app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

# 旧做法（~600ms，已废弃）
subprocess.run(["osascript", "-e", 'tell application "企业微信" to activate'])
```

---

### 3. 查找聊天输入框用 BFS，不用 DFS

BFS 优先找最浅的 AXTextArea（depth=6，空，可写）。DFS 会先深入消息历史区找到 depth=9 的只读 AXTextArea。

**企业微信 AX 树关键节点**：
- `depth=4`：左侧会话列表 AXTable（跳过）
- `depth=6`：聊天输入框 AXTextArea（`value=None`，可写）★
- `depth=6`：消息历史 AXTable
- `depth=9`：消息历史中的 AXTextArea（内容有值，只读）

---

### 4. 弹出框必须临时关闭 topmost

```python
def _ask_input(self, title, prompt):
    self.root.attributes("-topmost", False)
    dialog = ctk.CTkInputDialog(text=prompt, title=title)
    result = dialog.get_input()
    self.root.attributes("-topmost", True)
    return result
```

**原因**：`-topmost True` 使窗口处于 `NSFloatingWindowLevel`（层级 3），所有弹窗默认在 `NSNormalWindowLevel`（层级 0），永远被遮。三个辅助方法：`_ask_input()`、`_show_warning()`、`_ask_yesno()`。

---

### 5. 图片必须写 public.png 格式到剪贴板

```python
# 正确做法
tiff_data = image.TIFFRepresentation()
bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
png_data = bitmap.representationUsingType_properties_(4, None)  # 4 = NSPNGFileType
pb.setData_forType_(png_data, "public.png")

# 错误做法（只写 TIFF，企业微信 Electron 不识别）
pb.writeObjects_([image])   # 只写 public.tiff，Cmd+V 无反应
```

**原因**：`writeObjects_([NSImage])` 只写 TIFF 格式。企业微信（Electron/Chromium）Web 层只识别 `public.png`（与 macOS 截图工具写入格式一致）。

---

### 6. 图文混排发送：单条消息只能可靠降级为合成图片

```python
# 保证只出现一条消息：把文字和图片渲染成一张 PNG，再 send_image()
send_blocks_single(blocks)

# 实验路径：一次性粘贴 public.html，成败取决于企业微信 Electron/Web 编辑器
send_blocks_html_once(blocks)
```

**踩坑记录（不要再尝试）**：

| 尝试 | 失败原因 |
|------|---------|
| `type_text()` AppleScript 逐字输入后统一 Enter | Enter 无法触发 WebKit send handler |
| 统一粘贴所有内容再 Enter | 企业微信把 clipboard 粘贴文字当独立消息先发，变两条 |
| `click_send_button()` AX 点击 | 找不到正确按钮，不可靠 |
| `press_enter()` 各种变体（CGEvent/AppleScript/key code 36）| 均无法触发 WebKit 子进程的 send handler |

**根本原因**：企业微信的"发送"逻辑在 **WebKit 子进程**（`"企业微信"网页内容`）中。外部发给主进程的键盘 Enter 无法可靠转发到 WebKit。只有 `send_message()` 内置流程（剪贴板 Cmd+V → AppleScript Enter）才可靠。

**图文混排协议限制**：企业微信 regular chat 是否支持原生单条图文混排，取决于客户端/协议，外部自动化不能保证。当前可保证的是"单条图片消息"：`send_blocks_single()` 将文字像素化并合成 PNG。若需要继续验证原生图文，使用 `send_blocks_html_once()` 做 HTML 剪贴板实验。

---

### 7. 顺序发送时 auto_activate=False

```python
# 第一个 block 激活，后续 block 跳过激活，避免重复激活打断焦点
send_message(content, auto_activate=first)
send_image(path, auto_activate=first)
first = False
```

---

### 8. 窗口位置轮询在主线程，100ms 间隔

AX API 每次调用 < 5ms，直接在主线程 `root.after(100, _poll_snap)` 即可，不需要后台线程。

---

### 9. 聊天消息读取去重

```python
half = len(raw) // 2
content = raw[:half] if half and raw[:half] == raw[half:] else raw
```

部分消息 `kAXValueAttribute` 会重复两次（AX 渲染层 bug）。

### 10. AI 回复助手调用 `mc --code`，但必须人工确认发送

AI 回复第一版使用 `mc --code -p --tools "" --no-session-persistence` 作为可配置命令入口。GUI 只展示候选回复并要求人工确认，不做自动发送。AI 调用封装在 `ai_reply.py`，便于未来替换为 Ollama、HTTP 接口或其他公司内部 CLI。

---

### 11. 微信（个人版）使用 Qt 渲染，AX 无法穿透，改用坐标点击

```python
# 微信 macOS 版 AX 树只有 6 个顶层节点，无法用 BFS 找到输入框
# 正确做法：激活窗口后，点击窗口底部中央（距底 50px）
def _click_input_area(self) -> bool:
    from Quartz import CGEventCreateMouseEvent, CGEventPost, kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGHIDEventTap, CGPointMake
    bounds = self._get_window_bounds()  # (x, y, w, h)
    click_x = bounds[0] + bounds[2] / 2
    click_y = bounds[1] + bounds[3] - 50  # 距底 50px
    # ... CGEventCreateMouseEvent + CGEventPost
```

**根本原因**：微信 macOS 版使用 **Qt 渲染 UI**（非 Electron/Chromium），Qt 渲染层不向 macOS AX API 暴露内部 UI 元素（AX 树仅 6 个节点）。因此：
- BFS 找输入框 → **失败**（树太浅）
- 消息历史 AXTable → **不存在**（`can_read_chat=False`）
- 坐标点击输入框区域 → **可靠**（真机验证通过）

**进程名**：AppleScript `tell process "WeChat"`（不是 "微信"）

**与大象的区别**：大象使用 WebView 渲染（AXWebArea），AX 可穿透，输入框在 depth=23，走 BFS 路径（`allow_with_value=True`），无需坐标点击。

---

### 12. 大象（`cn.neixin.pc`）WebView 渲染，输入框在 depth=23

```python
# 大象 AX 树探测结论（2026-06-05）：
# - bundle ID: cn.neixin.pc（不是 com.sankuai.daxiang）
# - AXWebArea 在 depth=5，聊天输入框 AXTextArea 在 depth=23（从 window 算）
# - 输入框有占位符文本 '说点什么...'，需 allow_with_value=True
# - 正确调用：
focus_input(ax, max_depth=26, allow_with_value=True)
```

**与企业微信的区别**：企业微信输入框在 depth=6 且 value=None；大象在 depth=23 且有占位符。`bfs_find_input` 加了 `allow_with_value` 参数支持这两种情况。

**消息读取**：大象消息历史没有 AXTable，是 `AXStaticText` 散布在 depth=22-25，与侧边栏联系人列表混合。`read_chat_messages()` 目前返回 `[]`，待后续单独实现解析器。

---

## 项目文件结构

```
gui_panel.py      # CustomTkinter GUI（BlockEditor、PhraseCard、发送逻辑）
sender.py         # 核心：send_message/send_image/send_blocks/AX API/read_chat（企业微信）
phrases.json      # 话术数据（用户数据）
build.spec        # PyInstaller 打包配置（arm64）
build.sh          # 一键打包脚本（输出 dist/wechat-sender.dmg ~31MB）
im_clients/
  base.py           # IMClientAdapter 基类、TakeoverCapabilities、UnsupportedClientAction
  registry.py       # discover_clients()、choose_default_client()
  ax_helpers.py     # 通用 AX 工具（参数化 app_name）
  wechat_work.py    # 企业微信 adapter（委托 sender.py，verified=True）
  wechat.py         # 微信个人版 adapter（Qt 渲染，坐标点击，verified=True）
  daxiang.py        # 大象 adapter（发送 verified=True，读取 TODO）
tools/
  explore_ax.py     # AX 树探测工具（探测新 IM app 时用）
docs/
  design.md           # 技术设计文档
  product.md          # 产品文档
  user-manual.md      # 使用手册
  install-guide.md    # macOS 安装说明（含 Gatekeeper 步骤）
  session-summary-2026-05-20-21.md  # 会话摘要
  superpowers/
    specs/        # 设计稿
    plans/        # 实现计划
```

---

## 分支状态

| 分支 | 状态 | 说明 |
|------|------|------|
| `master` | 主干 | CustomTkinter UI + 图文混排基础 |
| `feature/multi-im-adapters` | **活跃，待合并** | 微信 verified=True，大象 verified=True（发送），大象读取 TODO |
| `feature/rich-text` | 活跃 | 图文混排全功能（BlockEditor、send_blocks）|
| `feature/macos-installer` | 未合并 | macOS .dmg 安装包 |
| `feature/sync-minimize` | 未合并 | 同步最小化（已 revert，含文档）|

---

## 已知坑

1. **AX depth 依赖**：聊天输入框 depth=6，消息历史 depth=9。企业微信 UI 更新后需重新探测。

2. **topmost 遮挡所有弹窗**：包括 `CTkInputDialog`，全部需要临时关闭 topmost 后再弹。

3. **AX 只读**：`kAXValueAttribute` 可读不可写（Electron WebView）。发送只能走剪贴板 + Cmd+V。

4. **图片格式**：必须用 `public.png`，`writeObjects_([NSImage])` 只写 TIFF 无效。

5. **图文混排 Enter 失效**：企业微信发送在 WebKit 子进程，外部键盘 Enter 不触发。要保证单条消息时用 `send_blocks_single()` 合成图片；要保留原生文字只能接受 text/image 分开发送或继续实验 HTML 剪贴板。

6. **`type_text()` 不用于发送流程**：AppleScript keystroke 打字后 Enter 无法触发 WebKit send，已在代码中保留但不在 send_blocks 中使用。

7. **resizable(False, False)**：主窗口禁止手动拖拽，`geometry()` 程序化调用不受影响。

8. **macOS 安装包**：`build.spec` 必须 `collect_all('customtkinter')` + `collect_all('tkinter')`，否则启动崩溃。`DATA_FILE` 必须在 `~/Library/Application Support/`，bundle 内只读。

9. **微信 Qt 渲染 AX 不透过**：微信个人版 macOS 使用 Qt 渲染，AX 树只有 6 个节点，BFS 找不到输入框。改用坐标点击（窗口底部中央距底 50px）。`can_read_chat=False`（Qt 不暴露消息历史）。AppleScript 进程名为 `"WeChat"` 不是 `"微信"`。

10. **新增 IM adapter 流程**：先用 `tools/explore_ax.py <app名> 12` 探测 AX 树（需先激活 app，否则 kAXWindowsAttribute 返回 0）。若 AX 树能暴露 AXTextArea，走 BFS 路径；若树浅（≤10节点），改用坐标点击路径（参考 wechat.py）。

11. **大象 bundle ID**：实际为 `cn.neixin.pc`（非 `com.sankuai.daxiang`）。输入框在 depth=23，有占位符文本，需 `allow_with_value=True`。`kAXWindowsAttribute` 在未激活时返回空，activate 后才有窗口。**AppleScript 进程名 `"大象"` 已真机验证可用**（发送 verified=True）。

12. **大象消息读取 TODO**：大象无 AXTable，消息以 `AXStaticText` 散布 depth=22-25，与侧边栏联系人列表混合，无法简单用 `bfs_find_msg_table` 读取。需实现专门的解析器。

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

# 探测任意 IM app 的 AX 树（新增 adapter 时用）
.venv/bin/python tools/explore_ax.py 微信 12
.venv/bin/python tools/explore_ax.py 大象 12
.venv/bin/python tools/explore_ax.py 企业微信 10

# 打包（Apple Silicon .dmg）
./build.sh   # 输出 dist/wechat-sender.dmg
```
