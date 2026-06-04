# 设计文档：多 IM 客户端适配器（微信 + 大象）

**日期：** 2026-06-04  
**分支：** `feature/multi-im-adapters`（从 master fork）  
**目标：** 为微信（个人版）和大象（美团内部 IM）实现与企业微信同等级别的 AX API 自动化功能

---

## 1. 背景

项目已有完整的企业微信自动化实现（`sender.py` + `im_clients/wechat_work.py`），并预留了微信和大象的 adapter 框架（`im_clients/wechat.py`、`im_clients/daxiang.py`），但两者的 `can_send`、`can_read_chat` 均为 `False`，`verified=False`。

本次工作目标：基于方案 A（直接实现，探测 + 硬编码 depth），补全两个 adapter 的完整实现。

---

## 2. 不动的文件

| 文件 | 原因 |
|------|------|
| `sender.py` | 企业微信专用，保持原样，不引入破坏性修改 |
| `gui_panel.py` | 已通过 `im_clients` 抽象调用 adapter，无需改动 |

---

## 3. 新增 / 修改文件

```
im_clients/
  ax_helpers.py      # 新增：通用 AX 工具函数（从 sender.py 提取，参数化 app name）
  wechat.py          # 修改：实现 send_blocks + read_chat_messages
  daxiang.py         # 修改：实现 send_blocks + read_chat_messages
tools/
  explore_ax.py      # 新增：AX 树探测脚本
```

---

## 4. ax_helpers.py 接口

从 `sender.py` 提取已验证的工具函数，以 `app_name: str` 参数化，供微信和大象 adapter 复用。

```python
def get_running_app(app_name: str)
    """从 NSWorkspace 找到指定 app 的 NSRunningApplication"""

def is_app_running(app_name: str) -> bool
    """检查 app 是否在运行"""

def activate_app(app_name: str) -> bool
    """激活 app 窗口（PyObjC NSApplicationActivateIgnoringOtherApps，~10ms）"""

def get_ax_element(app_name: str)
    """返回 AXUIElement（application level）"""

def bfs_find_input(ax_root) -> object | None
    """BFS 找最浅的空 AXTextArea（聊天输入框）"""

def bfs_find_msg_table(ax_root) -> object | None
    """BFS 找消息历史 AXTable"""

def set_clipboard_text(text: str)
    """写纯文本到剪贴板"""

def set_clipboard_png(image_path: str)
    """写 public.png 格式图片到剪贴板（企业微信已验证必须用此格式）"""

def paste_and_send(delay: float = 0.1)
    """Cmd+V 粘贴，AppleScript keystroke return 发送"""

def read_messages_from_table(table_element, max_messages: int = 20) -> list[dict]
    """从 AXTable 读取消息列表，含去重逻辑（kAXValueAttribute 重复两次的 bug）"""
```

**继承自企业微信的关键约束：**
- Enter 键走 AppleScript `keystroke return`，不走 CGEvent（Electron/WebKit 子进程丢弃裸 Return）
- 图片必须写 `public.png` 格式，`writeObjects_([NSImage])` 只写 TIFF 无效
- 微信和大象若也是 Electron/WebKit 架构，同样约束适用；若是原生 macOS app，Enter 机制可能不同——先用同一套，失败时再单独处理

---

## 5. Adapter 实现结构

`wechat.py` 和 `daxiang.py` 结构完全对称，只有 `client_id`、`display_name`、`app_names`、`bundle_ids` 不同。

```python
class WechatAdapter(IMClientAdapter):
    client_id = "wechat"
    display_name = "微信"
    app_names = ("微信", "WeChat")
    bundle_ids = ("com.tencent.xinWeChat", "com.tencent.xinwechat")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=False,      # 真机测试通过后改为 True
    )
```

### 发送流程

| 消息类型 | 流程 |
|---------|------|
| 纯文字 | `activate` → `bfs_find_input` → `set_clipboard_text` → `Cmd+V` → `AppleScript Enter` |
| 纯图片 | `activate` → `bfs_find_input` → `set_clipboard_png` → `Cmd+V` → `AppleScript Enter` |
| 图文混排 | `render_blocks_to_image`（复用 `sender.py`）→ 作为单张图片发送 |

图文混排直接复用 `sender.py` 中的 `render_blocks_to_image()`，不重新实现。

### verified 标志策略

- 初始 `verified=False`，GUI 状态栏显示「待验证」
- 在真机测试发送和读取功能通过后，各自改为 `True`
- 不影响现有企业微信功能，不误导用户

---

## 6. tools/explore_ax.py 探测脚本

```
用法: .venv/bin/python tools/explore_ax.py <app_name> [max_depth]

示例:
  .venv/bin/python tools/explore_ax.py 微信 12
  .venv/bin/python tools/explore_ax.py 大象 12
```

**输出格式：**
```
depth=0  AXApplication  val=None
depth=1  AXWindow       val=None
...
depth=6  AXTextArea     val=None          ← 候选输入框（value=None 且 depth 较浅）
depth=9  AXTextArea     val='你好，今天...' ← 消息历史（只读）
```

- 打印所有 `AXTextArea`（高亮候选输入框）
- 打印所有 `AXTable`（候选消息历史容器）
- 打印完整树前 `max_depth` 层（默认 12）
- 纯只读，不发送任何消息

---

## 7. 已知风险

| 风险 | 处理 |
|------|------|
| 微信/大象 AX 树结构未知 | 通过 `explore_ax.py` 探测后确认 depth，以常量注释标注 |
| 微信/大象可能是原生 macOS app，Enter 机制不同 | 先用 AppleScript `keystroke return`，失败时在 adapter 中单独处理，不影响其他 adapter |
| 微信/大象没有开放 AX 权限 | `is_app_running` 检查失败时 adapter 返回 `UnsupportedClientAction`，GUI 显示「待验证」 |
| `render_blocks_to_image` 依赖 sender.py | 直接 `import sender`，与 `wechat_work.py` 保持一致 |

---

## 8. 交付清单

- [ ] 创建分支 `feature/multi-im-adapters`
- [ ] 新增 `im_clients/ax_helpers.py`
- [ ] 修改 `im_clients/wechat.py`（实现 send_blocks + read_chat_messages）
- [ ] 修改 `im_clients/daxiang.py`（实现 send_blocks + read_chat_messages）
- [ ] 新增 `tools/explore_ax.py`
- [ ] 语法检查（`py_compile`）
- [ ] 真机测试微信发送/读取 → 如通过，`verified=True`
- [ ] 真机测试大象发送/读取 → 如通过，`verified=True`
