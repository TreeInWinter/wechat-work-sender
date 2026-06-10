# 秒回SideKick（IM 快捷回复助手）— CLAUDE.md

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

### 8. 窗口贴合 = 拖拽事件驱动（丝滑）+ 100ms 轮询（兜底）

**拖拽跟随（`window_follow.py`，2026-06-10）**：100ms 轮询有半帧到一帧拖影，
做不到原生丝滑。拖动期间完全不查 AX：

- `NSEvent.addGlobalMonitorForEventsMatchingMask_handler_` 监听全局
  leftMouseDown/Dragged/Up（辅助功能权限即可，Tk Aqua 跑在 Cocoa 运行循环上，
  handler 在主线程回调，真机验证通过）；
- mouseDown 落在目标窗口顶部 80px 拖拽带内且 `owner_at_point`（CGWindowList
  前→后第一个 layer-0 窗口，无需屏幕录制权限）确认是目标 app → 记录
  「鼠标-窗口」偏移开启会话；
- 每个 dragged 事件：预测位置 = 鼠标 + 偏移（零 AX 调用，60-120Hz），handler
  **只把预测位置存进 `_pending_drag_pos`**（传感器角色，不执行任何动作）；
- `_poll_snap` 检测到拖拽会话后自动切 **8ms 高频泵**（~120Hz），在 Tk 回调
  上下文里消费最新位置，用 `root.geometry()` 移动面板——geometry 的移动在泵
  返回主循环后的 idle 阶段立即生效，亚毫秒级，不是丝滑瓶颈；
- mouseUp：handler 置 `_drag_end_pending`，泵执行 `_snap_now()` 做一次 AX
  真值校正（屏幕边缘吸附会让预测偏离实际），然后退回 100ms 慢轮询。

**⚠️ GIL 致命坑（踩过两次，机制要记牢）**：`_tkinter` 的线程状态是配对管理
的——只有经 `_tkinter` 进入 Tcl（`ENTER_TCL` 把线程状态存进 `tcl_tstate`），
Tcl 回调 Python 时（`ENTER_PYTHON` = `PyEval_RestoreThread(tcl_tstate)`）才
合法。由此两条铁律：

1. **NSEvent handler 里不能调 Tk**（root.after/geometry 都不行）：handler
   发生在 Tcl_DoOneEvent 泵 Cocoa 事件途中（Tcl 已释放 GIL，PyObjC 经
   PyGILState 临时拿回），重入 _tkinter 会破坏 tcl_tstate 配对。
2. **任何上下文都不能用 PyObjC `setFrameOrigin_` 移动 Tk 自己的 NSWindow**
   （第二次崩溃就是把它挪进 Tk after 回调后仍然崩）：PyObjC 释放 GIL 时不设
   `tcl_tstate`，窗口移动同步触发 TkMacOSX `windowDidMove` → CTk 的
   `<Configure>` 回调 → `ENTER_PYTHON` 拿到 NULL 线程状态 → fatal。
   面板移动**只能走 `root.geometry()`**。

AX 读取、CGWindowList、`NSEvent.mouseLocation` 等只读、不碰 Tk 的 PyObjC
调用在 handler 里已验证安全。回调 handler-safe 性由
`tests/test_gui_panel_ui.py::DragFollowCallbackTests` 守护。

**坐标系**：全程 AX 顶左坐标，只在 `setFrameOrigin_` 瞬间经
`appkit_frame_origin()` 翻转 y（AppKit 底左原点）。纯逻辑
（DragSession/in_drag_band/appkit_frame_origin）无 AppKit 依赖，单测在
`tests/test_window_follow.py`。

**轮询兜底**：`_poll_snap` 100ms 保留，覆盖非拖拽位移（最大化、AppleScript
移窗等）；拖拽会话进行中暂停轮询防两路打架。监听安装失败时静默回退纯轮询。
AX API 每次调用 < 5ms，主线程 `root.after(100, _poll_snap)`，不需要后台线程。

**自愈式贴靠 + `SnapFilter` 读数把关**（gui_panel 模块级纯逻辑，有单测）：
- **每 tick 对比「期望位置（目标右缘）vs 面板实际位置（parse_geometry_pos
  解析 root.geometry()）」，偏离 ≥4px 才移动**。不能只跟踪目标窗口变化来决定
  动不动（已踩坑）：面板最小化期间目标移动，filter 接受了新位置，面板恢复后
  delta=0 永远跳过、从此不跟。自愈对比让面板任何形式的失同步（最小化恢复被
  macOS 放回旧位、被用户误拖）都在下一 tick 归位，顺带防 IME 抖动；
- `SnapFilter.validate()` 只管读数可信性：大跳变（>300px）**不永久丢弃**——
  旧实现丢弃时不更新基准导致每 tick 同样大 delta、永远拒绝（已踩坑），现为
  连续 2 tick 一致 → 可信真实位移；单 tick AX 毛刺仍被拒；目标窗口消失
  （最小化/退出，bounds=None）→ 重现的首个读数无条件可信；
- 面板自身最小化（`root.state() != "normal"`）时不调 geometry（iconic 下行为
  未定义），恢复可见后靠自愈对比自动归位。

---

### 9. 聊天消息读取去重

```python
half = len(raw) // 2
content = raw[:half] if half and raw[:half] == raw[half:] else raw
```

部分消息 `kAXValueAttribute` 会重复两次（AX 渲染层 bug）。

### 10. AI 回复助手调用 `mc --code`，但必须人工确认发送

AI 回复第一版使用 `mc --code -p --tools "" --no-session-persistence` 作为可配置命令入口。GUI 只展示候选回复并要求人工确认，不做自动发送。AI 调用封装在 `ai_reply.py`，便于未来替换为 Ollama、HTTP 接口或其他公司内部 CLI。

消息格式（`_format_message`）：`发送者 [时间]: 内容`，其中 `发送者=我` 表示自己发的消息。提示词为通用 IM 助手（不写死"企业微信客服"），支持多 IM（大象/微信/企业微信）。

**草稿对话式微调（refine）**：`refine_reply(messages, current_draft, instruction, config)` 以当前草稿为基准按要求改写，GUI 提供「更正式/更简短/换个说法」预设（`REFINE_PRESETS`）+ 自定义输入。改写**故意走纯文本模式**（`config.args`，不注入 `--add-dir/--add-file`）以保证低延迟、可多轮链式调用——KB 检索只在首次 `generate_reply` 时做。`_invoke_ai()` 为 generate/refine 共用的命令执行+错误处理。

---

### 10.1 云端知识库查询必须用 mc，不能用 claude CLI

```python
# 错误做法（hss_kb_client 旧版，GUI 独立运行时报 "Not logged in"）
claude_cmd = ["~/.local/bin/claude", "--dangerously-skip-permissions", "--print", ...]

# 正确做法（使用与普通 AI 回复相同的 mc 命令）
cmd = [ai_command, "--code", "-p", "--tools", "", "--no-session-persistence", full_prompt]
```

**根本原因**：`claude` CLI 通过 `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_CUSTOM_HEADERS` 两个 env 变量认证，这两个变量**仅在 Claude Code 会话内由 harness 动态注入**。GUI 从普通终端或 `.app` 启动时，子进程环境中不存在这两个变量，`claude` 返回 `"Not logged in"`。

`mc --code` 使用公司内部独立认证，与 Claude Code 会话无关，不受影响。

`query_cloud()` 的 `ai_command`/`ai_args` 参数由 `generate_reply()` 传入 `config.command/args`，保证云端 KB 查询与普通 AI 回复使用同一命令入口。

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
- 消息历史 AXTable → **不存在**（AX 读不到，改用 OCR，见第 11.1 条）
- 坐标点击输入框区域 → **可靠**（真机验证通过）

**进程名**：AppleScript `tell process "WeChat"`（不是 "微信"）

**与大象的区别**：大象使用 WebView 渲染（AXWebArea），AX 可穿透，输入框在 depth=23，走 BFS 路径（`allow_with_value=True`），无需坐标点击。

---

### 11.1 微信消息读取走 Vision OCR（真机验证 2026-06-09，macOS 26.5.1）

微信 Qt 不暴露 AX 消息，改用「截图 + macOS Vision OCR」读取（`im_clients/wechat_ocr.py`）。
`can_read_chat=True`。真机踩坑（**全部必做，缺一中文就识别不出**）：

```python
request = Vision.VNRecognizeTextRequest.alloc().init()
request.setRevision_(3)          # ★ revision 1 仅支持 en-US！中文需 ≥2（取最高可用）
request.setRecognitionLevel_(0)  # ★ Fast！macOS 26 上 Accurate(=1) 中文模型损坏，全乱码
request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
```

| 坑 | 现象 | 解法 |
|----|------|------|
| **revision 默认=1** | 中文 0 识别，只认英文 | `setRevision_(最高可用，≥2)` |
| **Accurate 中文损坏** | 中文全乱码，置信度恒为 0.30/0.50 | `setRecognitionLevel_(0)` 用 Fast，置信度回到 1.00 |
| **截图抓错窗口** | 被遮挡时截到遮挡窗口（如系统设置）| 按窗口 ID `kCGWindowListOptionIncludingWindow`，不用 `OptionAll`+矩形 |
| **侧边栏污染** | 左侧会话列表的名字/时间戳混进消息 | `_filter_chat_area` 按 x 过滤（`x_center<0.40`=侧边栏）再归一化 |

**窗口发现用 CGWindowList 不用 AX**：`find_main_window()` 经 `CGWindowListCopyWindowInfo`
（owner∈{微信,WeChat}、layer=0、width>400 取最大）拿窗口 ID + bounds，只需「屏幕录制」
权限。AX 需「辅助功能」权限，GUI 独立运行时常没有（报 `kAXErrorAPIDisabled=-25211`）。

**左右归属**：聊天面板内 `x_center>0.5`（面板归一化后）= 我，否则 = 对方。表情/贴纸
会 OCR 成少量噪声（如 `%~`），可接受。调试用 `tools/debug_ocr.py`。

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

**消息读取（2026-06-08 更新）**：
- depth=22（非 AXList 父节点）= 当前打开聊天的消息，AXList 父节点下的 = 侧边栏会话列表
- BFS 时需携带 `under_axlist` 标志排除侧边栏；`windows >= 2` 判断改为 `>= 1`
- 序列格式：时间戳和发送者名**顺序不固定**（T→S 或 S→T 均有），需用状态机解析（`in_content` 标志区分是否已进入内容区）
- 大象 App 版本更新后 WebView 消息虚拟化：AX 树只暴露可见区域的少数消息文本，历史消息无法全量读取
- `_SENDER_RE` 匹配 2-4 汉字+可选 `(Pinyin)`，不匹配英文开头的名称（如 `Xray平台`）

---

### 13. AX depth 魔法数收敛到 `im_clients/probes.py` + 启动自检

所有「AX 树固定 depth」的魔法数（企业微信输入框≤10/消息 AXTable@6、大象输入框≤26/消息
AXStaticText@22、微信坐标点击偏移 50px）**收敛到 `probes.py` 的 `PROBES` 字典**，作为单一
事实来源。`sender.py`、`daxiang.py`、`wechat.py` 从中读取常量，不再各写各的。客户端版本
更新致 depth 偏移时，**只改 `probes.py` 一处**。

```python
PROBES["wechat_work"].input.max_depth   # 10（sender._WW_INPUT_MAX_DEPTH 从此读）
PROBES["daxiang"].input.max_depth       # 26（DaxiangAdapter._INPUT_MAX_DEPTH 从此读）
```

**自检**（`probes.run_self_check` / `run_probe`）：BFS 验证各客户端的输入框/消息节点是否仍在
预期 depth；找不到 → `STATUS_DEGRADED`（客户端可能已更新，需 `tools/explore_ax.py` 重探）。
状态区分：`ok` / `degraded` / `no_window` / `no_permission`（`kAXErrorAPIDisabled=-25211`）/
`not_running`。`ElementProbe.root` 标记 BFS 起点是 `app` 还是 `window`（大象输入框从 app 根算，
消息从 window 根算，两者不同）。

GUI：顶栏 `⋯` 菜单「AX 结构自检」手动触发全量自检（激活逐个检查，弹窗汇总）；启动后 1.2s
做一次**被动**自检（`activate=False`，不抢焦点），只对「与激活无关的确定问题」告警——权限
缺失，或微信（非 AX）窗口不可达——其余（AX 客户端非前台的 no_window）静默，避免误报。

### 14. UI 反馈体系（2026-06-10 迭代，spec v2 P0/P2 落地）

- **草稿台即主界面**：双模式切换行已删，「话术」入口在顶栏（`view_toggle_btn`）。
- **状态文字降级**：`status_label` 仍存在但**不进布局**（兼容旧引用），统一走
  `_set_status_text()`；瞬时结果用 `_show_toast()`，非破坏性错误用
  `_show_inline_error(message, retry=...)`（草稿框上方红条），破坏性确认仍用弹窗。
- **改写可撤销**：`DraftHistory`（模块级，有单测）+ `_push_draft_history()`；
  发送/清空草稿时清栈。
- **跨分组搜索**：`filter_phrases()`（模块级，有单测）返回 `(分组, 索引, 话术)`；
  卡片携带 `_group/_group_index`，删除/编辑按归属分组操作。
- 纯逻辑单测在 `tests/test_gui_panel_ui.py`（stub customtkinter/sender 导入）。

---

## 项目文件结构

```
gui_panel.py      # CustomTkinter GUI（BlockEditor、PhraseCard、发送逻辑）
window_follow.py  # 拖拽跟随：NSEvent 全局监听 + 鼠标偏移预测，面板丝滑贴合（见第 8 条）
sender.py         # 核心：send_message/send_image/send_blocks/AX API/read_chat（企业微信）
phrases.json      # 话术数据（用户数据）
build.spec        # PyInstaller 打包配置（arm64）
build.sh          # 一键打包脚本（输出 dist/miaohui-sidekick.dmg ~31MB）
im_clients/
  base.py           # IMClientAdapter 基类、TakeoverCapabilities、UnsupportedClientAction
  probes.py         # AX depth 魔法数单一事实来源 + 启动自检（run_self_check/run_probe）
  registry.py       # discover_clients()、choose_default_client()
  ax_helpers.py     # 通用 AX 工具（参数化 app_name）
  wechat_work.py    # 企业微信 adapter（委托 sender.py，verified=True）
  wechat.py         # 微信个人版 adapter（Qt 渲染，坐标点击发送，verified=True）
  wechat_ocr.py     # 微信消息读取（CGWindowList 发现窗口 + Vision OCR，Fast+rev≥2）
  daxiang.py        # 大象 adapter（发送 + 读取 verified=True）
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
| `feature/multi-im-adapters` | **活跃，待合并** | 微信/大象 发送+读取均 verified=True，OCR 读取微信消息实现中 |
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

9. **微信 Qt 渲染 AX 不透过**：微信个人版 macOS 使用 Qt 渲染，AX 树只有 6 个节点，BFS 找不到输入框。发送改用坐标点击（窗口底部中央距底 50px）。**读取改用 Vision OCR**（`can_read_chat=True`，见第 11.1 条）：必须 `setRevision_(≥2)` + `setRecognitionLevel_(0/Fast)`，否则中文 0 识别。窗口发现用 CGWindowList（屏幕录制权限）不用 AX（辅助功能权限）。AppleScript 进程名为 `"WeChat"` 不是 `"微信"`。

10. **新增 IM adapter 流程**：先用 `tools/explore_ax.py <app名> 12` 探测 AX 树（需先激活 app，否则 kAXWindowsAttribute 返回 0）。若 AX 树能暴露 AXTextArea，走 BFS 路径；若树浅（≤10节点），改用坐标点击路径（参考 wechat.py）。

11. **大象 bundle ID**：实际为 `cn.neixin.pc`（非 `com.sankuai.daxiang`）。输入框在 depth=23，有占位符文本，需 `allow_with_value=True`。`kAXWindowsAttribute` 在未激活时返回空，activate 后才有窗口。**AppleScript 进程名 `"大象"` 已真机验证可用**（发送 verified=True）。

12. **大象消息读取**：大象无 AXTable，消息在 AXStaticText depth=22（from window）。前 6 个节点是 UI 过滤器（未读/稍后/@我/单聊/群聊/图标），跳过。之后按序：时间戳 → 发送者名（2-4 汉字）→ 消息正文。depth=23 是侧边栏，不读取。已实现，真机验证通过。

13. **云端知识库查询不能用 claude CLI，用 mc**：`claude CLI` 依赖 `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_CUSTOM_HEADERS`，这两个 env 变量仅在 Claude Code 会话内动态注入，GUI 独立启动时不存在，导致 `"Not logged in"`。`hss_kb_client.query_cloud()` 使用 `ai_command`/`ai_args` 参数（由调用方传入 `mc` 路径），不硬编码 claude。

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
./build.sh   # 输出 dist/miaohui-sidekick.dmg
```
