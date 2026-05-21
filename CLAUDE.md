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
- **Python**：3.13，venv 用 `uv` 管理（`.venv/bin/python`）
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

### 6. 图文混排发送：用 send_message + send_image 串联，不要尝试合并

```python
# 正确做法（简单可靠）
def send_blocks(blocks):
    first = True
    for block in blocks:
        if block["type"] == "text":
            send_message(content, auto_activate=first)
        elif block["type"] == "image":
            send_image(path, auto_activate=first)
        first = False
        time.sleep(0.3)
```

**踩坑记录（不要再尝试）**：

| 尝试 | 失败原因 |
|------|---------|
| `type_text()` AppleScript 逐字输入后统一 Enter | Enter 无法触发 WebKit send handler |
| 统一粘贴所有内容再 Enter | 企业微信把 clipboard 粘贴文字当独立消息先发，变两条 |
| `click_send_button()` AX 点击 | 找不到正确按钮，不可靠 |
| `press_enter()` 各种变体（CGEvent/AppleScript/key code 36）| 均无法触发 WebKit 子进程的 send handler |

**根本原因**：企业微信的"发送"逻辑在 **WebKit 子进程**（`"企业微信"网页内容`）中。外部发给主进程的键盘 Enter 无法可靠转发到 WebKit。只有 `send_message()` 内置流程（剪贴板 Cmd+V → AppleScript Enter）才可靠。

**图文混排协议限制**：企业微信 regular chat 不支持单条图文混排消息，text + image 必然是两条连续消息。这是企业微信协议层设计，无法突破。

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

---

## 项目文件结构

```
gui_panel.py      # CustomTkinter GUI（BlockEditor、PhraseCard、发送逻辑）
sender.py         # 核心：send_message/send_image/send_blocks/AX API/read_chat
phrases.json      # 话术数据（用户数据）
build.spec        # PyInstaller 打包配置（arm64）
build.sh          # 一键打包脚本（输出 dist/wechat-sender.dmg ~31MB）
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
| `feature/rich-text` | 活跃 | 图文混排全功能（BlockEditor、send_blocks）|
| `feature/macos-installer` | 未合并 | macOS .dmg 安装包 |
| `feature/sync-minimize` | 未合并 | 同步最小化（已 revert，含文档）|

---

## 已知坑

1. **AX depth 依赖**：聊天输入框 depth=6，消息历史 depth=9。企业微信 UI 更新后需重新探测。

2. **topmost 遮挡所有弹窗**：包括 `CTkInputDialog`，全部需要临时关闭 topmost 后再弹。

3. **AX 只读**：`kAXValueAttribute` 可读不可写（Electron WebView）。发送只能走剪贴板 + Cmd+V。

4. **图片格式**：必须用 `public.png`，`writeObjects_([NSImage])` 只写 TIFF 无效。

5. **图文混排 Enter 失效**：企业微信发送在 WebKit 子进程，外部键盘 Enter 不触发。用 `send_message()` + `send_image()` 串联是唯一可靠方案。

6. **`type_text()` 不用于发送流程**：AppleScript keystroke 打字后 Enter 无法触发 WebKit send，已在代码中保留但不在 send_blocks 中使用。

7. **resizable(False, False)**：主窗口禁止手动拖拽，`geometry()` 程序化调用不受影响。

8. **macOS 安装包**：`build.spec` 必须 `collect_all('customtkinter')` + `collect_all('tkinter')`，否则启动崩溃。`DATA_FILE` 必须在 `~/Library/Application Support/`，bundle 内只读。

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

# 打包（Apple Silicon .dmg）
./build.sh   # 输出 dist/wechat-sender.dmg
```
