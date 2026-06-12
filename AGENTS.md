# 秒回SideKick（IM 快捷回复助手）— AGENTS.md

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
im_clients/       # 即时通讯客户端适配器（企业微信/微信/大象隔离）
phrases.json      # 话术数据（用户数据）
build.spec        # PyInstaller 打包配置（arm64）
build.sh          # 一键打包脚本（输出 dist/miaohui-sidekick.dmg ~31MB）
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
| `codex/im-target-selection` | 活跃 | 发现 macOS 已安装 IM 客户端，选择当前接管对象 |

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

9. **个人版基础体验（2026-05-28）**：`codex-personal-basics-weeks-1-2` 分支补齐搜索、快捷键、变量模板、发送预览、权限引导和安装包。
   - 搜索只过滤当前分组，`⌘1` 到 `⌘9` 发送当前可见结果。
   - 主界面发送直接执行，不再弹出发送预览；自定义消息触发发送后清空输入框。
   - 模板变量格式为 `{{变量名}}`；`{{日期}}`、`{{时间}}`、`{{星期}}` 为内置变量，主界面发送时自动替换；未填写的自定义变量保留原占位符。
   - 打包脚本优先使用 `uv pip install`，找不到 `uv` 时降级为 `.venv/bin/python -m pip install`。
   - `build/` 与 `dist/` 是本地构建产物，已加入 `.gitignore`；验证产物为 `dist/miaohui-sidekick.dmg`。

10. **多 IM 接管对象（2026-06-04）**：`codex/im-target-selection` 分支新增 `im_clients/` 适配器层。
   - 注册表只展示有适配器的对象，第一批为企业微信、微信、大象。
   - 企业微信适配器复用现有 `sender.py` 可靠发送/读取链路，仍是默认目标。
   - 微信和大象第一版只做安装/运行发现、激活和窗口边界读取；发送/读取聊天标记为待验证，不能误发。
   - GUI 顶部“接管对象”下拉决定状态检测、窗口吸附、读取聊天和发送路由。
   - 不同 IM 的 AX 树、进程名、bundle id 必须留在各自适配器文件中，不要写回 `gui_panel.py`。

11. **当前工作区观测（2026-06-06）**：本次会话仅熟悉项目并跑测试，无业务代码修改。
   - 当前本地分支为 `master`，`git status` 显示落后 `origin/master` 28 个提交；HEAD 同时指向 `origin/feature/multi-im-adapters`。
   - 当前 `origin` 实际为 `git@github.com:TreeInWinter/wechat-work-sender.git`，与上方历史记录中的美团内部远端信息不一致，后续推送前需先确认目标远端。
   - 未跟踪文件 `config.json` 视为本地配置/用户数据，本次未读取、未修改。
   - 现有测试命令 `.venv/bin/python -m pytest -q` 通过，结果为 `64 passed`。
   - 代码现状中 `WechatWorkAdapter.send_blocks()` 对含图片 blocks 会走 `sender.send_blocks_single()`（合成单张图片/单条消息路径），与第 6 条“图文混排用 send_message + send_image 串联”的历史决策存在漂移；涉及企业微信图文发送前需优先核对真实期望。

12. **AI 草稿台与话术页 iOS 风格收敛（2026-06-12）**：`codex/ios-polish-marked-area` 分支整理 AI 草稿台顶部与话术页管理区的凌乱区域。
   - 顶部两颗「读取并生成 / 重新生成」按钮移除，顶部只保留一张摘要卡（状态 + 上下文折叠入口），降低视觉噪音。
   - 底部主按钮变为唯一主操作：空草稿为「读取并生成」，有草稿为「发送」，读取中为「读取中…」，生成中为红色「取消生成」，发送中为「发送中…」。
   - 「重新生成」移入底部 `⋯` 菜单，仅已有上下文且非读取/生成中时可用。
   - 话术页分组新增/改名/删除和「删除选中话术」收进 `⋯` 管理菜单；底部只保留「添加话术」，搜索清空压缩为小型 `×`。
   - 话术卡片右侧红框按钮墙继续收敛：每条卡片只保留一个轻量 `⋯`，单条「发送 / 插入草稿 / 编辑」进入卡片菜单；`⌘1-9` 继续保留快速发送。
   - 验证：`.venv/bin/python -m py_compile gui_panel.py sender.py`、`.venv/bin/python -m pytest -q` 通过，结果为 `182 passed, 1 skipped`；窗口实例化 smoke 验证主按钮状态切换与话术页控件存在；`screencapture` 对 AI 草稿台与话术页完成图片级视觉验收。

13. **支持作者 / 微信收款码（2026-06-12）**：右上 `⋯` 菜单新增「支持作者…」，弹出 iOS 风格二维码面板。
   - 收款码资产固定复制到 `assets/donation-wechat.jpg`，不要依赖微信临时文件路径。
   - `app_resource_path()` 兼容源码运行和 PyInstaller `_MEIPASS`；`make_contained_image()` 用于完整等比展示二维码，不裁剪。
   - `build.spec` 必须包含 `("assets/donation-wechat.jpg", "assets")`，否则打包后的 `.app` 找不到收款码。
   - 验证：新增 `ResourcePathTests` 覆盖资源路径和二维码存在；`.venv/bin/python -m pytest -q` 结果为 `184 passed, 1 skipped`；`screencapture` 视觉验收确认「支持作者」面板里二维码真实可见。
   - 发送触发策略：`donation_send_count` 记录成功发送次数，每成功发送 10 次后延迟弹出一次「支持作者」面板；失败发送不计数、不弹窗。`next_donation_send_count()` 有单测覆盖 10/20 次触发。

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
./build.sh   # 输出 dist/miaohui-sidekick.dmg
```
