# Changelog

## [Unreleased] — feature/sync-minimize

### Docs
- 新增 UI 现代化设计文档与实现计划（`docs/superpowers/`）

---

## [master] — UI 现代化 + 功能完善

### 新功能
- **UI 现代化**：从原生 tkinter 迁移至 CustomTkinter，品牌蓝 `#1677FF` 配色，全面圆角设计
- **话术卡片**：列表改为卡片式，每条右侧有「发送」按钮，一键发出无需二次操作
- **读取聊天内容**：通过 AX API 读取企业微信当前聊天窗口最近 30 条消息，弹窗展示
- **深色模式**：跟随 macOS 系统外观自动切换（CustomTkinter 原生支持）

### Bug 修复
- **对话框被遮挡**：macOS 上 `-topmost True` 窗口处于 `NSFloatingWindowLevel`，导致所有弹窗（输入框、警告框、确认框）被遮盖。修复：弹出前临时关闭 topmost，使用 `CTkInputDialog` 替代 `simpledialog`
- **发送目标错误**：原 DFS 遍历 AX 树时先找到消息历史区（depth=9），改为 BFS 后优先命中聊天输入框（depth=6）
- **Enter 键无效**：企业微信基于 Electron，`CGEvent kCGHIDEventTap` 的裸 Return 键不可靠，改用 AppleScript `keystroke return`
- **lambda 闭包**：`except X as e` 后 `e` 被 Python 3 自动删除，改为提前 `msg = str(e)` 捕获

### 性能优化
- **窗口激活**：用 `NSRunningApplication.activateWithOptions_()` 替换 AppleScript，激活耗时从 600ms 降至 10ms
- **位置轮询**：用 AX API 直接读取坐标（< 5ms），替代 `subprocess + osascript`（80ms），轮询间隔从 1000ms 降至 100ms

---

## [wechat_for_enter] — 企业微信适配

### 变更
- **品牌替换**：所有「大象」改为「企业微信」，AppleScript tell target 改为 `"企业微信"`
- **窗口贴合**：面板启动即贴合企业微信右侧，高度与企业微信同步，拖动时 100ms 内跟随
- **健壮性**：无聊天窗口时不再崩溃，改为弹窗提示「请先在企业微信中选中聊天窗口」（`NoChatWindowError`）

---

## [feature/read-chat-content] — 聊天内容读取

### 新功能
- `read_chat_messages(max_messages)` — 通过 AX API 读取当前聊天消息
- AX 树结构分析：消息历史在 `AXWindow/.../AXTable (depth=6)`，每行 `AXRow → AXCell → AXTextArea`（正文）+ `AXStaticText`（时间戳）
- 自动去重：部分消息 AX 值会重复，检测并去除

---

## [Initial] — 项目初始化

- 基于 macOS Accessibility API 的企业微信自动发送工具
- `sender.py`：核心发送引擎（NSPasteboard + CGEvent + AppleScript）
- `gui_panel.py`：tkinter 话术快捷面板
- `phrases.json`：话术数据持久化
