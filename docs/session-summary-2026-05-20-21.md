# 会话摘要 2026-05-20 ~ 05-21

本文记录两天会话的主要工作、关键决策和踩坑，供后续上下文恢复使用。

---

## 项目状态概览

| 分支 | 状态 | 说明 |
|------|------|------|
| `master` | 主干 | 含 UI 现代化、图文混排基础 |
| `feature/rich-text` | 活跃 | 图文混排全功能（当前工作分支）|
| `feature/macos-installer` | 已推送 | macOS .dmg 安装包（未合并）|
| `feature/sync-minimize` | 已推送 | 同步最小化（已回退，含文档）|

---

## 本次会话完成的主要工作

### 1. UI 现代化（已合并 master）

**问题**：原生 tkinter 控件在 macOS 上无圆角、无深色模式、多色混乱。

**方案**：迁移到 CustomTkinter 5.2.x。
- 主色统一为企业微信品牌蓝 `#1677FF`
- 话术列表改为卡片式（右侧直接有「发送」按钮）
- 深色/浅色跟随系统

**关键 bug 修复**：
- **topmost 遮挡对话框**：macOS 上 `-topmost True` 使窗口处于 `NSFloatingWindowLevel`，所有 `messagebox`/`simpledialog`/`CTkInputDialog` 都被遮挡。修复：弹出前临时 `attributes("-topmost", False)`，结束后恢复。三个辅助方法：`_ask_input()`、`_show_warning()`、`_ask_yesno()`。
- **BFS vs DFS 查找输入框**：DFS 先找到消息历史区（depth=9，只读），BFS 优先命中聊天输入框（depth=6）。

### 2. 图文混排话术（feature/rich-text）

**功能**：话术支持文字块 + 图片块混排，点击发送按块发出。

**存储格式**：
```json
[
  {"type": "text", "content": "您好！以下是操作步骤："},
  {"type": "image", "path": "/path/to/step1.png"},
  {"type": "text", "content": "如有问题随时联系。"}
]
```
旧纯字符串话术向后兼容（normalize_phrase 自动处理）。

**BlockEditor（所见即所得）**：
- 内联画布风格：文字块直接编辑，图片块显示 Pillow 缩略图
- 活跃块蓝色边框高亮
- 工具栏：＋文字、＋图片、↑↓排序、🗑删除
- 依赖：Pillow（`uv pip install Pillow`）

**发送逻辑演进（踩坑记录）**：

| 尝试 | 问题 |
|------|------|
| `writeObjects_([NSImage])` 写剪贴板 | 只写 TIFF，企业微信（Electron）不识别，需要 `public.png` |
| clipboard 粘贴文字 + clipboard 粘贴图片 | 企业微信把 clipboard 粘贴文字作为独立消息先发，结果两条消息 |
| AppleScript `type_text()` 模拟打字 + 最后 Enter | Enter 无法发送（企业微信发送逻辑在 WebKit 子进程，主进程 keystroke 不触发）|
| CGEvent Enter / AppleScript key code 36 / click_send_button() | 均失败 |
| **最终方案**：回归 send_message() + send_image() 串联 | ✅ 可靠，多条消息但每条准确发出 |

**最终 send_blocks() 实现**（简单可靠）：
```python
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

**关键技术决策**：
- **图片格式**：NSImage.writeObjects_ 只写 TIFF，需用 `NSBitmapImageRep.representationUsingType_(NSPNGFileType)` 写 `public.png`，企业微信才能识别
- **text auto_activate**：第一个 block 激活企业微信，后续 `auto_activate=False` 避免重复激活打断焦点

### 3. macOS 安装包（feature/macos-installer，未合并）

**功能**：PyInstaller + hdiutil 打包为 arm64 .dmg。

**关键点**：
- `DATA_FILE` 必须迁移到 `~/Library/Application Support/`（.app bundle 内部只读）
- `build.spec` 必须包含 `collect_all('customtkinter')` 和 `collect_all('tkinter')`（漏掉启动崩溃）
- pyobjc 的 hidden imports 需要 `pyinstaller-hooks-contrib`
- DMG 文件名用 ASCII（`wechat-sender.dmg`），避免中文路径问题
- 运行：`./build.sh` → 生成 `dist/wechat-sender.dmg`（约 31MB）

### 4. 文档沉淀

新增文档：
- `docs/design.md` — 技术设计文档（AX API 原理、发送流程、AX 树结构）
- `docs/product.md` — 产品文档（目标用户、功能清单、使用场景）
- `docs/user-manual.md` — 使用手册（安装、操作步骤、常见问题）
- `CHANGELOG.md` — 版本记录
- `CLAUDE.md` — 关键技术决策（防上下文压缩丢失）

---

## 重要技术决策汇总

### AX API 层面

| 决策 | 原因 |
|------|------|
| BFS 查找 AXTextArea（depth=6）| DFS 先深入消息历史区（depth=9，只读），找错目标 |
| 图片写 public.png | 企业微信 Electron/Chromium 不识别纯 TIFF |
| send_image auto_activate 参数 | 顺序发送时重复激活会打断输入框焦点 |
| `type_text()` 不用于发送 | AppleScript keystroke 后 Enter 无法触发 WebKit send handler |

### UI 层面

| 决策 | 原因 |
|------|------|
| topmost 弹窗前关闭 | NSFloatingWindowLevel 遮挡所有弹窗 |
| 话术改卡片式 | 原 listbox 需要「选中→点按钮」两步，卡片直接点发送 |
| BlockEditor 用 Pillow 缩略图 | CTkLabel 不支持富文本，Pillow 渲染图片预览 |

---

## 当前已知问题 / TODO

- `feature/macos-installer` 未合并到 master（需要用户手动冒烟测试后决定是否合并）
- `feature/sync-minimize`（企业微信最小化时同步最小化面板）已实现但已 revert，有需要可以从该分支重新合并
- 图文混排话术是多条消息（企业微信协议层不支持单条图文混排消息）
- 图文混排发送速度：每条消息内部约 0.5-1s，block 间隔 0.3s，整体较慢

---

## 快速恢复上下文

当前工作在 `feature/rich-text`，所有图文混排相关代码在此分支。

主要文件：
- `gui_panel.py` — CustomTkinter GUI（BlockEditor + PhraseCard + 发送逻辑）
- `sender.py` — 核心发送（send_message / send_image / send_blocks / AX API）
- `CLAUDE.md` — 项目技术决策速查

运行：
```bash
.venv/bin/python gui_panel.py
```
