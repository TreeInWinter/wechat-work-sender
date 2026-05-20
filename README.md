# 企业微信快捷发送面板 (macOS)

一个贴合企业微信右侧边缘运行的快捷发送工具，支持话术一键发送、聊天内容读取，基于 macOS Accessibility API 实现，无需模拟点击。

---

## 功能

| 功能 | 说明 |
|------|------|
| **话术卡片发送** | 维护分组话术库，点击卡片右侧「发送」直接发出 |
| **自定义消息** | 底部输入框随时发送临时消息 |
| **读取聊天内容** | 读取企业微信当前聊天窗口最近 30 条消息，弹窗展示 |
| **窗口贴合** | 启动即自动贴合企业微信右侧，高度与企业微信同步 |
| **窗口跟随** | 每 100ms 通过 AX API 读取窗口坐标，企业微信移动时自动跟随 |
| **深色模式** | 跟随 macOS 系统外观自动切换 |

---

## 技术原理

### 发送消息

```
1. NSRunningApplication.activateWithOptions_()  →  激活企业微信（无子进程开销）
2. AXUIElement BFS 遍历         →  找到聊天输入框（AXTextArea, depth=6）
3. AXUIElementSetAttributeValue →  聚焦输入框
4. NSPasteboard                 →  写入消息到剪贴板
5. CGEvent Cmd+V                →  模拟粘贴
6. AppleScript keystroke return →  发送（Electron 应用用 AppleScript 更可靠）
```

### 读取聊天内容

```
AX 树结构（企业微信）：
AXWindow
└─ AXSplitGroup
   └─ AXSplitGroup
      ├─ AXScrollArea/AXTable (depth=4)  ← 左侧会话列表（跳过）
      └─ AXSplitGroup
         └─ AXSplitGroup
            └─ AXScrollArea/AXTable (depth=6)  ← 当前聊天消息 ✓
               └─ AXRow → AXCell
                  ├─ AXStaticText  →  时间戳
                  └─ AXTextArea   →  消息正文
```

用 BFS（广度优先）优先找 depth=6 的消息历史 AXTable，避免误读 depth=4 的会话列表。

### 窗口贴合

```python
# 每 100ms，主线程直接调用（AX API < 5ms，无需后台线程）
bounds = AXUIElementCopyAttributeValue(win, kAXPositionAttribute/kAXSizeAttribute)
self.root.geometry(f"420x{wh}+{wx + ww}+{wy}")
```

---

## 系统要求

- macOS 10.15+
- Python 3.9+
- 在「系统设置 → 隐私与安全性 → 辅助功能」中授权终端 / IDE

---

## 安装

```bash
# 依赖安装（使用 uv）
uv pip install pyobjc-framework-Cocoa \
               pyobjc-framework-Quartz \
               pyobjc-framework-ApplicationServices \
               customtkinter
```

---

## 使用

```bash
# GUI 面板（推荐）
python gui_panel.py

# CLI 单条发送
python sender.py "您好，请问有什么可以帮您？"

# CLI 批量发送（| 分隔）
python sender.py "消息1|消息2|消息3"
```

---

## 项目结构

```
wechat_work_sender/
├── gui_panel.py          # CustomTkinter GUI 面板（主入口）
├── sender.py             # 核心发送逻辑 + AX API 工具函数
├── phrases.json          # 话术数据（自动持久化）
├── start.sh              # 快捷启动脚本
└── docs/
    └── superpowers/
        ├── specs/        # 设计文档
        └── plans/        # 实现计划
```

### 主要 API（sender.py）

| 函数 | 说明 |
|------|------|
| `send_message(text)` | 向当前聊天窗口发送消息 |
| `read_chat_messages(max_messages=20)` | 读取当前聊天消息，返回 `[{"content", "time"}]` |
| `focus_chat_input()` | BFS 找到聊天输入框并聚焦 |
| `get_wechat_window_bounds()` | 读取企业微信窗口坐标 `(x, y, w, h)` |
| `is_daxiang_running()` | 检查企业微信是否运行 |

---

## 已知问题 & 注意事项

- **辅助功能权限**：首次运行需在系统设置中授权，否则 AX API 返回空
- **企业微信更新**：如 AX 树结构变更，`_find_msg_table` 中的 `depth==6` 可能需要调整
- **topmost 对话框**：所有弹窗（添加话术、删除确认）在弹出前会临时关闭主窗口置顶，结束后恢复

---

## 安全提醒

本工具仅供内部提效使用，请勿用于骚扰或违规群发。企业微信可能检测异常发送行为，请控制频率。
