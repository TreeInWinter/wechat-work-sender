# UI 观感与交互迭代 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 v2 交互稿的 P0 结构收尾 + P2 视觉规范化，并增补调研验证的 3 项体验改进（改写撤销、AI 来源标识、跨分组搜索）。

**Architecture:** 全部改动集中在 `gui_panel.py`（CustomTkinter 单文件 GUI）。可测逻辑抽成模块级纯函数/类（`DraftHistory`、`filter_phrases`、`make_source_caption`），GUI 装配改动用 `py_compile` + 启动冒烟验证。新增测试文件复用 `tests/test_gui_send.py` 的 import-stub 模式。

**Tech Stack:** Python 3.10+ / CustomTkinter 5.2.x / unittest。运行 `.venv/bin/python`。

**Spec:** `docs/superpowers/specs/2026-06-10-ui-visual-feedback-iteration-design.md`

**注意：** 主窗 420×600 固定、`resizable(False, False)` 不变。每个 Task 结束跑
`.venv/bin/python -m py_compile gui_panel.py` 并提交。行号会随任务推进漂移，
定位一律用本文给出的**锚点字符串** grep。

---

### Task 1: B1 色彩 Token 迁移

**Files:**
- Modify: `gui_panel.py`（`# ── 配色令牌` 块，约 141-170 行；`_update_kb_row`）

- [ ] **Step 1: 替换 Token 值**

锚点 `PRIMARY    = "#4F46E5"`，整块改为：

```python
# 强调色（收敛蓝，对齐交互稿 v2 视觉 token）
PRIMARY    = "#2B5CE6"   # 主按钮 / 选中态 / 链接
PRIMARY_H  = "#1E47C0"   # hover / 按下
ACCENT_SOFT = "#EAF0FD"  # 极浅蓝底（选中卡片 / 浅强调 hover）
```

状态色块（锚点 `DOT_OK`）改为：

```python
DOT_OK    = "#34C759"
DOT_ERR   = "#FF3B30"
DOT_WAIT  = "#8F959E"   # 检测中=中性灰（spec：检测中不是警告）
```

`PhraseCard.SELECTED_BORDER = "#D9DCF7"` 改为 `"#C7D7F8"`；
`PhraseCard` 内两处 hover_color `"#D9DCF7"` 同步改 `"#C7D7F8"`。

- [ ] **Step 2: KB 状态行去彩色底**

`_update_kb_row` 中三个分支的 `kb_row.configure(...)` 统一为
`fg_color=SURFACE, border_color=BORDER`（删除 `#f6ffed/#b7eb8f/#91d5ff/ACCENT_SOFT` 底色），
仅 label 文字着色：cloud → `text_color=PRIMARY`；local → `text_color="#389e0d"`；
未启用 → `text_color=TEXT_WEAK`。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
grep -n "4F46E5\|4338CA\|EEF0FF\|22C55E\|F59E0B\|EF4444" gui_panel.py   # 应无输出
git add gui_panel.py && git commit -m "style: 色彩 Token 迁移至 v2 收敛蓝，KB 行去彩色底"
```

---

### Task 2: B2 emoji → 线性符号 + 弹窗标题栏统一

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: 枚举所有 emoji 站点**

```bash
grep -n "➕\|🗑\|💾\|📂\|📗\|☁\|🩺\|✅\|❌\|🖼\|⚙\|✦\|📋" gui_panel.py
```

- [ ] **Step 2: 按替换表逐一修改**

| 现文案 | 改为 |
|---|---|
| `➕ 添加话术` | `⊕ 添加话术` |
| `🗑️ 删除选中` | `删除选中` |
| `💾 存入知识库`（含 overflow 菜单项） | `存入知识库` |
| `📂 知识库未启用 — 点击设置` | `知识库未启用 · 点击设置` |
| `📗 知识库已启用 · {name}` | `✓ 知识库已启用 · {name}` |
| `☁️ 云端知识库已启用{scope}` | `✓ 云端知识库已启用{scope}` |
| `🖼 `（PhraseCard 图片前缀） | `[图] ` |
| `✅ 发送成功` / `❌ …`（status_label 反馈） | 本任务保持文字、去 emoji（`发送成功`/`发送失败`），Task 4 再迁 toast |
| 其余 `⚙️ 🩺 📋` 等菜单/按钮 emoji | 去掉 emoji 留纯文字 |

- [ ] **Step 3: Toplevel 弹窗标题栏统一近白**

```bash
grep -n 'corner_radius=0, fg_color=PRIMARY' gui_panel.py
```
4 处（BlockEditor、AI 设置、KB 提炼、自检汇总等）`height=44` header：
`fg_color=PRIMARY` → `fg_color=HEADER_BG`；header 内标题 label `text_color="white"`
→ `text_color=TEXT_MAIN`；关闭/次按钮 `text_color="white", hover_color=PRIMARY_H`
→ `text_color=TEXT_SUB, hover_color=PILL_HOVER`；白底反色按钮（`fg_color="white",
text_color=PRIMARY`）→ 主色实心（`fg_color=PRIMARY, text_color="white",
hover_color=PRIMARY_H`）。每个 header 之后紧跟
`ctk.CTkFrame(<win>, height=1, corner_radius=0, fg_color=BORDER).pack(fill="x")`。

- [ ] **Step 4: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python gui_panel.py &  # 冒烟：主窗 + 打开 AI 设置弹窗看标题栏，然后关闭
git add gui_panel.py && git commit -m "style: emoji 全替换为线性符号/纯文字，弹窗标题栏统一近白"
```

---

### Task 3: B3 字号 / 圆角收敛

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: 圆角收敛**

```bash
grep -n "corner_radius=4\|corner_radius=6" gui_panel.py
```
按钮类 `corner_radius=4/6` → `8`（PhraseCard 编辑/插入/发送按钮等）；输入框/文本框保持 10；
卡片容器保持 10；`kb_row corner_radius=6` → `8`。

- [ ] **Step 2: 字号收敛**

```bash
grep -n "size=10\b" gui_panel.py
```
`size=10` → `size=11`（辅助级下限 11）。13/12/11 之外的正文字号归并到最近一级
（标题 13、正文 12、辅助 11；`⋯` 等图标按钮的 16/20 保留）。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
git add gui_panel.py && git commit -m "style: 字号三级与圆角规范收敛（13/12/11，按钮 8 输入框 10）"
```

---

### Task 4: C1 轻 toast 组件

**Files:**
- Modify: `gui_panel.py`（`WXSenderApp` 新增方法；替换 status_label 的瞬时反馈调用）

- [ ] **Step 1: 实现 `_show_toast`**

加在 `_show_warning` 方法之前：

```python
def _show_toast(self, message: str, duration_ms: int = 1800):
    """轻量浮层提示：主窗底部居中，自动消失，不抢焦点（替代弹窗/状态栏瞬时反馈）。"""
    old = getattr(self, "_toast_label", None)
    if old is not None:
        try:
            old.destroy()
        except Exception:
            pass
    if getattr(self, "_toast_after_id", None):
        try:
            self.root.after_cancel(self._toast_after_id)
        except Exception:
            pass
    toast = ctk.CTkLabel(
        self.root, text=f"  {message}  ",
        fg_color="#323232", text_color="#FFFFFF",
        corner_radius=13, height=26,
        font=ctk.CTkFont(family="PingFang SC", size=11),
    )
    toast.place(relx=0.5, rely=1.0, y=-52, anchor="s")
    self._toast_label = toast

    def _dismiss():
        try:
            toast.destroy()
        except Exception:
            pass
        self._toast_label = None
        self._toast_after_id = None

    self._toast_after_id = self.root.after(duration_ms, _dismiss)
```

`__init__` 中初始化 `self._toast_label = None`、`self._toast_after_id = None`。

- [ ] **Step 2: 瞬时反馈迁移到 toast**

grep `status_label.configure(text=` 与 `_ai_set_status(`，把**瞬时结果类**改为 toast：
`发送成功` → `self._show_toast("已发送")`；复制成功 → `已复制`；存入知识库成功 →
`已存入知识库`；发送失败/图片不存在 → `self._show_toast("发送失败：…")`。
**持续状态类**（已连接/检测中/正在生成）保持原通道，Task 6 处理。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
git add gui_panel.py && git commit -m "feat: 轻 toast 反馈组件，瞬时结果不再占用状态栏/弹窗"
```

---

### Task 5: A1 移除双模式切换行，「话术」入口上移顶栏

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 的 `mode_frame` 块、`_switch_mode`）

- [ ] **Step 1: 删除 mode_frame 行**

删除 `_build_ui` 中 `# ── 模式切换 ──` 至 `self.ai_mode_btn.grid(...)` 整块
（`self.phrase_mode_btn`/`self.ai_mode_btn` 不再创建）。

- [ ] **Step 2: 顶栏新增「话术」切换按钮**

在 `self.menu_btn.pack(...)` 之后（即視覺上 ⋯ 左侧）插入：

```python
self.view_toggle_btn = ctk.CTkButton(
    status_frame, text="话术", width=48, height=30,
    corner_radius=8, fg_color="transparent",
    hover_color=PILL_HOVER, text_color=TEXT_SUB,
    font=ctk.CTkFont(family="PingFang SC", size=11),
    command=self._toggle_view,
)
self.view_toggle_btn.pack(side="right", padx=(0, 2))
```

- [ ] **Step 3: 重写切换逻辑**

`_switch_mode` 简化为视图 pack/pack_forget（删除对 phrase_mode_btn/ai_mode_btn 的
configure），并新增：

```python
def _toggle_view(self):
    target = "phrases" if self._current_mode == "ai" else "ai"
    self._switch_mode(target)

def _switch_mode(self, mode: str):
    self._current_mode = mode
    if mode == "ai":
        self.phrase_view.pack_forget()
        self.ai_view.pack(fill="both", expand=True)
        self.view_toggle_btn.configure(text="话术")
    else:
        self.ai_view.pack_forget()
        self.phrase_view.pack(fill="both", expand=True)
        self.view_toggle_btn.configure(text="草稿台")
```

`__init__`/`_build_ui` 确认存在 `self._current_mode = "ai"` 初始值（沿用现有变量名，
若现名为别名则统一）。`phrase_view` 初始 `pack` 调用删去（由 `_switch_mode("ai")` 决定）。

- [ ] **Step 4: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python gui_panel.py &  # 冒烟：默认草稿台；点「话术」切换；再切回
git add gui_panel.py && git commit -m "feat: 移除双模式切换行，话术入口上移顶栏（草稿台即主界面）"
```

---

### Task 6: A2 状态点并入对象选择器

**Files:**
- Modify: `gui_panel.py`（`_build_ui` 状态栏块、`_check_status` 一族）

- [ ] **Step 1: 重排状态栏**

左侧 `left` 容器：保留 `status_dot`，删除 `status_label` 的 pack（对象**仍创建**但不进
布局，兼容旧引用），把 `target_menu` 从右侧移到 `left` 内（dot 右侧，`padx=(6,0)`）。
右侧剩：⋯ 菜单、话术切换、脱离/吸附。

- [ ] **Step 2: 状态文字降级**

`_check_status` 系列对 `status_label.configure(text=…)` 的调用保留（对象存在，仅不可见），
同时把状态文本写入 `self._status_text = text`。异常态（需要权限 / 未运行 / 未安装）追加：
dot 置红 + 若当前在 AI 视图则调用 Task 8 的 `_show_inline_error(text, retry=self._refresh_targets_and_status)`
（Task 8 完成前先留 `# TODO(Task8)` 注释行，不调用）。
`status_dot` 绑定点击显示当前状态：`self.status_dot.bind("<Button-1>", lambda e: self._show_toast(self._status_text))`。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python gui_panel.py &  # 冒烟：顶栏 = ● + 选择器；点状态点出 toast
git add gui_panel.py && git commit -m "feat: 状态点并入对象选择器，删除常驻状态文字行"
```

---

### Task 7: A3 上下文区折叠

**Files:**
- Modify: `gui_panel.py`（`_build_ai_view` 上下文块；填充 `ai_context_box` 的方法）

- [ ] **Step 1: 摘要行替代常驻标题+文本框**

`_build_ai_view` 中删除 `聊天上下文` 标题 label 的 pack；在原位置插入摘要行：

```python
self.ctx_summary_btn = ctk.CTkButton(
    self.ai_view, text="▸ 尚未读取会话", height=26, corner_radius=8,
    fg_color="transparent", hover_color=PILL_HOVER,
    text_color=TEXT_SUB, anchor="w",
    font=ctk.CTkFont(family="PingFang SC", size=11),
    command=self._toggle_context,
)
self.ctx_summary_btn.pack(fill="x", padx=12, pady=(0, 2))
self._ctx_expanded = False
```

`ai_context_box` 创建保留（height 改 120），但**不立即 pack**。

- [ ] **Step 2: 展开/收起**

```python
def _toggle_context(self):
    self._ctx_expanded = not self._ctx_expanded
    summary = self.ctx_summary_btn.cget("text").lstrip("▸▾ ")
    if self._ctx_expanded:
        self.ai_context_box.pack(fill="x", padx=12, pady=(0, 6),
                                 after=self.ctx_summary_btn)
        self.ctx_summary_btn.configure(text=f"▾ {summary}")
    else:
        self.ai_context_box.pack_forget()
        self.ctx_summary_btn.configure(text=f"▸ {summary}")
```

- [ ] **Step 3: 读取完成时更新摘要**

grep `ai_context_box.configure(state="normal")` 定位填充处（读取完成回调），在填充后追加：

```python
arrow = "▾" if self._ctx_expanded else "▸"
self.ctx_summary_btn.configure(
    text=f"{arrow} 已读取 {len(self._ai_messages)} 条 · {datetime.now().strftime('%H:%M')}"
)
```

- [ ] **Step 4: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python gui_panel.py &  # 冒烟：默认收起；读取后摘要更新；点击展开/收起
git add gui_panel.py && git commit -m "feat: 聊天上下文折叠为单行摘要，高度让给草稿框"
```

---

### Task 8: C2 内联错误条

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: 实现错误条**

```python
def _show_inline_error(self, message: str, retry=None):
    """草稿框上方内联错误条（替代打断式弹窗）。retry 为可选重试回调。"""
    self._hide_inline_error()
    bar = ctk.CTkFrame(self.ai_view, corner_radius=8, fg_color="#FDECEC",
                       border_width=1, border_color="#F5C2C0")
    ctk.CTkLabel(
        bar, text=f"✕ {message}", text_color="#C0392B", anchor="w",
        font=ctk.CTkFont(family="PingFang SC", size=11),
    ).pack(side="left", fill="x", expand=True, padx=(8, 4), pady=3)
    if retry is not None:
        ctk.CTkButton(
            bar, text="重试", width=44, height=20, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#F5C2C0",
            text_color="#C0392B", hover_color="#FAD9D7",
            font=ctk.CTkFont(family="PingFang SC", size=11),
            command=lambda: (self._hide_inline_error(), retry()),
        ).pack(side="right", padx=(0, 6), pady=3)
    ctk.CTkButton(
        bar, text="✕", width=24, height=20, corner_radius=8,
        fg_color="transparent", text_color="#C0392B", hover_color="#FAD9D7",
        font=ctk.CTkFont(size=11),
        command=self._hide_inline_error,
    ).pack(side="right", padx=(0, 4), pady=3)
    bar.pack(fill="x", padx=12, pady=(0, 4), before=self.ai_reply_box)
    self._inline_error_bar = bar

def _hide_inline_error(self):
    bar = getattr(self, "_inline_error_bar", None)
    if bar is not None:
        try:
            bar.destroy()
        except Exception:
            pass
    self._inline_error_bar = None
```

- [ ] **Step 2: 迁移非破坏性错误**

- `_ai_generate_failed` / `_ai_refine_failed` / 读取失败：`_ai_set_status(message)` 改为
  `self._show_inline_error(message, retry=<对应重试：self._ai_regenerate 或 lambda: self._ai_refine(instruction)>)`。
- AI 视图内 `_show_warning("暂无可复制的回复")`、`("请先生成或输入回复内容")` → `_show_toast`。
- Task 6 留下的 `# TODO(Task8)`：异常态接入 `_show_inline_error(self._status_text, retry=self._refresh_targets_and_status)`。
- 删除分组/话术等破坏性确认与 Toplevel 表单内校验弹窗**保留** `_show_warning`/`_ask_yesno`。
- 成功路径开始时（生成/改写启动）调用 `self._hide_inline_error()`。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
git add gui_panel.py && git commit -m "feat: 内联错误条替代打断式弹窗（AI 读取/生成/改写失败）"
```

---

### Task 9: D1 改写可撤销（DraftHistory）

**Files:**
- Modify: `gui_panel.py`（模块级新增 `DraftHistory`；refine/regenerate 接线）
- Test: `tests/test_gui_panel_ui.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_gui_panel_ui.py`（复制 `tests/test_gui_send.py` 顶部的
`_install_gui_panel_import_stubs()` 函数与调用，再 `import gui_panel`）：

```python
class DraftHistoryTests(unittest.TestCase):
    def test_push_and_undo(self):
        h = gui_panel.DraftHistory()
        h.push("v1"); h.push("v2")
        self.assertEqual(h.undo(), "v2")
        self.assertEqual(h.undo(), "v1")
        self.assertIsNone(h.undo())

    def test_push_ignores_empty_and_duplicate(self):
        h = gui_panel.DraftHistory()
        h.push(""); h.push("a"); h.push("a")
        self.assertEqual(len(h), 1)

    def test_capped_depth(self):
        h = gui_panel.DraftHistory()
        for i in range(30):
            h.push(f"d{i}")
        self.assertEqual(len(h), gui_panel.DraftHistory.MAX_DEPTH)
        self.assertEqual(h.undo(), "d29")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/python -m unittest tests.test_gui_panel_ui -v
# 期望: AttributeError: module 'gui_panel' has no attribute 'DraftHistory'
```

- [ ] **Step 3: 实现 DraftHistory（加在 PhraseCard 类之前）**

```python
class DraftHistory:
    """草稿改写历史栈：refine/重新生成前压栈，支持逐级撤销（Grammarly/Notion 范式）。"""

    MAX_DEPTH = 20

    def __init__(self):
        self._stack: list[str] = []

    def push(self, draft: str):
        if not draft:
            return
        if self._stack and self._stack[-1] == draft:
            return
        self._stack.append(draft)
        if len(self._stack) > self.MAX_DEPTH:
            self._stack.pop(0)

    def undo(self) -> str | None:
        return self._stack.pop() if self._stack else None

    def clear(self):
        self._stack.clear()

    def __len__(self):
        return len(self._stack)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python -m unittest tests.test_gui_panel_ui -v   # 期望: OK
```

- [ ] **Step 5: GUI 接线**

- `__init__`：`self._draft_history = DraftHistory()`。
- `_ai_refine_done(reply)`：`_ai_set_reply(reply)` 前 `self._draft_history.push(draft_before)`
  （`draft_before` 为发起改写时捕获的 `draft`，经 lambda 传入回调：
  `self.root.after(0, lambda: self._ai_refine_done(reply, draft))`，方法签名加参数）。
- `_ai_regenerate` 同理：发起时捕获当前 `self._ai_get_reply()`，成功回调里 push。
- 撤销按钮：`refine_frame.grid_columnconfigure((0, 1, 2), weight=1)` 保持，加 column 3：

```python
self.ai_undo_btn = ctk.CTkButton(
    refine_frame, text="撤销", width=44, height=28, corner_radius=8,
    fg_color="transparent", border_width=1, border_color=BORDER,
    text_color=TEXT_SUB, hover_color=PILL_HOVER,
    font=ctk.CTkFont(family="PingFang SC", size=11),
    command=self._ai_undo_draft,
)
self.ai_undo_btn.grid(row=0, column=3, padx=(3, 0))
self.ai_undo_btn.grid_remove()   # 默认隐藏
```

```python
def _ai_undo_draft(self, *_):
    prev = self._draft_history.undo()
    if prev is None:
        return "break"
    self._ai_set_reply(prev)
    self._show_toast("已撤销改写")
    if len(self._draft_history) == 0:
        self.ai_undo_btn.grid_remove()
    return "break"
```

push 成功后 `self.ai_undo_btn.grid()` 显示；发送成功 / 清空草稿时
`self._draft_history.clear()` + `grid_remove()`。
`_bind_shortcuts` 加 `self.root.bind("<Command-z>", self._ai_undo_draft)`。

- [ ] **Step 6: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python -m unittest tests.test_gui_panel_ui -v
git add gui_panel.py tests/test_gui_panel_ui.py
git commit -m "feat: 改写/重新生成可撤销（DraftHistory 栈 + ⌘Z）"
```

---

### Task 10: D2 AI 来源 caption

**Files:**
- Modify: `gui_panel.py`
- Test: `tests/test_gui_panel_ui.py`

- [ ] **Step 1: 写失败测试**

```python
class SourceCaptionTests(unittest.TestCase):
    def test_with_kb(self):
        self.assertEqual(
            gui_panel.make_source_caption(8, True),
            "ⓘ 据 8 条会话 + 知识库生成 · 发送前请确认",
        )

    def test_without_kb(self):
        self.assertEqual(
            gui_panel.make_source_caption(3, False),
            "ⓘ 据 3 条会话生成 · 发送前请确认",
        )

    def test_zero_messages(self):
        self.assertEqual(
            gui_panel.make_source_caption(0, False),
            "ⓘ AI 生成 · 发送前请确认",
        )
```

运行确认失败后实现（模块级函数，加在 `DraftHistory` 后）：

```python
def make_source_caption(n_messages: int, kb_used: bool) -> str:
    """AI 草稿来源标注（业内 copilot 实践：来源可追溯 + 人审提示）。"""
    if n_messages <= 0:
        return "ⓘ AI 生成 · 发送前请确认"
    kb_part = " + 知识库" if kb_used else ""
    return f"ⓘ 据 {n_messages} 条会话{kb_part}生成 · 发送前请确认"
```

```bash
.venv/bin/python -m unittest tests.test_gui_panel_ui -v   # 期望: OK
```

- [ ] **Step 2: GUI 接线**

`_build_ai_view` 中新增 caption（pack 顺序：在 `refine_frame.pack(side="bottom", ...)`
之后、`ai_reply_box.pack(...)` 之前）：

```python
self.ai_source_caption = ctk.CTkLabel(
    self.ai_view, text="", anchor="w", text_color=TEXT_WEAK,
    font=ctk.CTkFont(family="PingFang SC", size=11),
)
self.ai_source_caption.pack(side="bottom", fill="x", padx=14, pady=(0, 2))
```

- 生成成功回调（grep `_ai_set_reply(` 的生成完成处）：
  `kb_used = self._app_config.get("kb_mode", "none") != "none"`，
  `self.ai_source_caption.configure(text=make_source_caption(len(self._ai_messages), kb_used))`。
- 改写成功（`_ai_refine_done`）保持 caption 不变；发送成功 / 清空草稿 →
  `self.ai_source_caption.configure(text="")`。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
git add gui_panel.py tests/test_gui_panel_ui.py
git commit -m "feat: AI 草稿来源 caption（据 N 条会话/知识库生成 · 发送前请确认）"
```

---

### Task 11: D3 跨分组搜索

**Files:**
- Modify: `gui_panel.py`（模块级 `filter_phrases`；`_refresh_cards`、`PhraseCard`、编辑/删除路径）
- Test: `tests/test_gui_panel_ui.py`

- [ ] **Step 1: 写失败测试**

```python
class FilterPhrasesTests(unittest.TestCase):
    PHRASES = {
        "问候语": ["您好，我是客服", "早上好"],
        "常用回复": ["好的，请稍等", "您好，已收到"],
    }

    def test_empty_query_returns_current_group(self):
        out = gui_panel.filter_phrases(self.PHRASES, "问候语", "")
        self.assertEqual(out, [("问候语", 0, "您好，我是客服"), ("问候语", 1, "早上好")])

    def test_query_searches_all_groups(self):
        out = gui_panel.filter_phrases(self.PHRASES, "问候语", "您好")
        self.assertEqual(
            out,
            [("问候语", 0, "您好，我是客服"), ("常用回复", 1, "您好，已收到")],
        )

    def test_query_case_insensitive_and_stripped(self):
        phrases = {"A": ["Hello World"]}
        out = gui_panel.filter_phrases(phrases, "A", "  hello ")
        self.assertEqual(out, [("A", 0, "Hello World")])
```

运行确认失败后实现：

```python
def filter_phrases(phrases: dict, current_group: str, query: str) -> list[tuple]:
    """话术过滤：空查询 → 当前分组全部；非空 → 跨全部分组匹配（Raycast 搜索优先范式）。

    返回 [(分组名, 组内索引, 话术), ...]，顺序按分组定义序。
    """
    query = (query or "").strip().lower()
    if not query:
        return [(current_group, i, p) for i, p in enumerate(phrases.get(current_group, []))]
    out = []
    for group, items in phrases.items():
        for i, p in enumerate(items):
            if query in phrase_preview_text(p).lower():
                out.append((group, i, p))
    return out
```

```bash
.venv/bin/python -m unittest tests.test_gui_panel_ui -v   # 期望: OK
```

- [ ] **Step 2: `_refresh_cards` 改用 filter_phrases**

替换现有 group/query 过滤逻辑：

```python
query = self.search_var.get() if hasattr(self, "search_var") else ""
results = filter_phrases(self.phrases, self.group_var.get(), query)
self._visible_phrases = [p for _, _, p in results]
cross_group = bool(query.strip())
```

卡片循环改为 `for visible_i, (group, i, phrase) in enumerate(results, 1):`，
PhraseCard 传 `group_label=group if cross_group and group != self.group_var.get() else None`，
且 `on_edit=lambda idx=i, g=group: self._edit_phrase(idx, g)`、
`on_send`/`on_insert` lambda 不变（话术值已捕获）。卡片记录归属：构造后
`card._group, card._group_index = group, i`。

- [ ] **Step 3: PhraseCard 支持分组标签**

`__init__` 加参数 `group_label: str | None = None`；`_build` 中 label 文案前缀：

```python
prefix = f"{self._index}. " if self._index is not None else ""
suffix = f"  〔{self._group_label}〕" if self._group_label else ""
```

`suffix` 拼在 preview 之后（弱化显示可接受，单 label 实现即可）。

- [ ] **Step 4: 编辑/删除路径带分组**

- `_edit_phrase(self, idx)` → `_edit_phrase(self, idx, group=None)`，内部
  `group = group or self.group_var.get()`，读写 `self.phrases[group][idx]`。
- `_delete_phrase`：从 `self._selected_card` 取 `card._group, card._group_index`
  定位删除（原先假定当前分组）。
- ⌘1-9 `_send_visible_phrase` 基于 `_visible_phrases`，行为天然兼容，不改。

- [ ] **Step 5: 验证 + 提交**

```bash
.venv/bin/python -m py_compile gui_panel.py
.venv/bin/python -m unittest tests.test_gui_panel_ui tests.test_gui_send -v
.venv/bin/python gui_panel.py &  # 冒烟：搜索词命中他组话术并显示分组标签；编辑/删除跨组卡片
git add gui_panel.py tests/test_gui_panel_ui.py
git commit -m "feat: 话术搜索跨全部分组，结果卡片标注来源分组"
```

---

### Task 12: 全量回归 + 文档收尾

**Files:**
- Modify: `CHANGELOG.md`、`CLAUDE.md`（界面结构相关描述）、`docs/ui-interaction-spec-v2.md`（勾选已完成项）

- [ ] **Step 1: 全量测试**

```bash
.venv/bin/python -m unittest discover tests -v   # 期望: 全部 OK（OCR/AX 相关跳过项正常）
.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py
```

- [ ] **Step 2: 完整冒烟清单（手动）**

启动 `.venv/bin/python gui_panel.py`，核对：
1. 顶栏 = `●` + IM 选择器（左）｜话术 · 脱离 · ⋯（右），无双模式行
2. 默认草稿台；上下文为折叠摘要行；草稿框明显变高
3. 全界面无 emoji；主色为 `#2B5CE6` 蓝
4. 生成 → caption 出现；改写 → 撤销按钮出现，⌘Z 可回退
5. 拔掉 AI 命令配置触发失败 → 内联错误条 + 重试，无弹窗
6. 发送成功 → 底部 toast「已发送」
7. 话术页搜索跨分组并显示分组标签

- [ ] **Step 3: 更新文档**

- `CHANGELOG.md` 新条目（版本号按现有惯例）。
- `docs/ui-interaction-spec-v2.md` 第 7 节勾选本轮完成的 P0/P2 项。
- `CLAUDE.md`「项目文件结构 / 已知坑」如有受影响描述则同步（如 status_label 已隐藏、
  反馈走 toast）。

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md CLAUDE.md docs/ui-interaction-spec-v2.md
git commit -m "docs: UI 迭代收尾 — CHANGELOG/spec 勾选/CLAUDE.md 同步"
```
