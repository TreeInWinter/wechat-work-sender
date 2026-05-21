# 话术图文混排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 话术支持图文混排（文字块 + 图片块），编辑时用 BlockEditor 对话框，发送时按块顺序依次发出文字和图片。

**Architecture:** 话术值由纯字符串扩展为 Block 列表（`[{"type":"text","content":"..."},{"type":"image","path":"..."}]`），向后兼容旧字符串。`normalize_phrase()` 统一为块列表。新增 `BlockEditor` CTkToplevel，新增 `send_image()` 通过 NSPasteboard 发图。

**Tech Stack:** Python 3.13, CustomTkinter 5.2.x, pyobjc AppKit (NSImage + NSPasteboard)

---

## 文件结构

| 文件 | 变更 |
|------|------|
| `gui_panel.py` | 新增工具函数、BlockEditor 类；更新 PhraseCard、_refresh_cards、_do_send、_add_phrase、_delete_phrase、_edit_phrase |
| `sender.py` | 新增 `send_image(path)` 函数；import 添加 NSImage |

---

## Task 1：创建分支 + 新增 Phrase 工具函数

**Files:**
- Modify: `gui_panel.py`（import 区 + DEFAULT_PHRASES 之后）

- [ ] **Step 1: 从 master 创建新分支**

```bash
git checkout master
git checkout -b feature/rich-text
git push -u origin feature/rich-text
```

- [ ] **Step 2: 在 gui_panel.py 的 `import` 区末尾补充 `import re` 和 `import copy`**

找到 `import threading` 那一行，在其后插入：

```python
import re
import copy
```

- [ ] **Step 3: 在 `save_phrases()` 函数之后插入三个工具函数**

```python
def normalize_phrase(phrase) -> list:
    """将话术值统一转换为 Block 列表（兼容旧纯字符串）。
    str  → [{"type": "text", "content": str}]
    list → list (原样返回)
    """
    if isinstance(phrase, str):
        return [{"type": "text", "content": phrase}]
    return list(phrase)


def phrase_preview_text(phrase) -> str:
    """返回用于卡片展示的纯文本摘要（去换行，图片块替换为 🖼）。"""
    parts = []
    for block in normalize_phrase(phrase):
        if block.get("type") == "text" and block.get("content", "").strip():
            parts.append(block["content"].replace("\n", " ").strip())
        elif block.get("type") == "image":
            parts.append("🖼")
    return "  ".join(p for p in parts if p)


def has_images(phrase) -> bool:
    """话术中是否含有图片块。"""
    if isinstance(phrase, str):
        return False
    return any(b.get("type") == "image" for b in phrase)
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 5: 快速验证逻辑**

```bash
.venv/bin/python -c "
from gui_panel import normalize_phrase, phrase_preview_text, has_images
# str
assert normalize_phrase('hello') == [{'type':'text','content':'hello'}]
# list passthrough
blocks = [{'type':'text','content':'hi'},{'type':'image','path':'/tmp/a.png'}]
assert normalize_phrase(blocks) is not blocks  # copy
# preview
assert phrase_preview_text('hello') == 'hello'
assert '🖼' in phrase_preview_text(blocks)
# has_images
assert has_images(blocks) == True
assert has_images('hello') == False
print('OK')
"
```

Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add gui_panel.py
git commit -m "feat: 新增 normalize_phrase / phrase_preview_text / has_images 工具函数"
```

---

## Task 2：send_image() 函数（sender.py）

**Files:**
- Modify: `sender.py`

- [ ] **Step 1: 在 sender.py 的 AppKit import 行添加 NSImage**

找到：
```python
from AppKit import (
    NSPasteboard, NSStringPboardType, NSPasteboardTypeString,
    NSWorkspace, NSApplicationActivateIgnoringOtherApps,
)
```

替换为：
```python
from AppKit import (
    NSPasteboard, NSStringPboardType, NSPasteboardTypeString,
    NSWorkspace, NSApplicationActivateIgnoringOtherApps,
    NSImage,
)
```

- [ ] **Step 2: 在 `send_message()` 函数之后插入 `send_image()`**

```python
def send_image(path: str) -> bool:
    """向企业微信当前聊天窗口发送一张图片。

    参数：
        path: 图片文件路径（支持 ~ 展开）

    返回：
        是否发送成功
    """
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise FileNotFoundError(f"图片不存在: {expanded}")

    if not is_daxiang_running():
        print("[错误] 企业微信未运行")
        return False

    if not activate_daxiang():
        return False

    if not focus_chat_input():
        raise NoChatWindowError("请先在企业微信中选中聊天窗口")

    image = NSImage.alloc().initWithContentsOfFile_(expanded)
    if image is None:
        raise ValueError(f"无法加载图片: {expanded}")

    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.writeObjects_([image])

    time.sleep(0.1)
    paste()
    time.sleep(0.5)   # 图片较大，等待渲染
    press_enter()
    time.sleep(0.2)

    print(f"[成功] 图片已发送: {os.path.basename(expanded)}")
    return True
```

- [ ] **Step 3: 验证语法**

```bash
.venv/bin/python -m py_compile sender.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: 验证 NSImage 可用**

```bash
.venv/bin/python -c "from sender import send_image; print('send_image imported OK')"
```

Expected: `send_image imported OK`

- [ ] **Step 5: 提交**

```bash
git add sender.py
git commit -m "feat: 新增 send_image()，通过 NSPasteboard 发送图片到企业微信"
```

---

## Task 3：BlockEditor 类

**Files:**
- Modify: `gui_panel.py`（在 `PhraseCard` 类之前插入）

- [ ] **Step 1: 在 gui_panel.py 中 `class PhraseCard` 之前插入 BlockEditor**

```python
class BlockEditor(ctk.CTkToplevel):
    """话术块编辑器：支持文字块和图片块的混排编辑。"""

    def __init__(self, parent, initial_phrase=None):
        super().__init__(parent)
        self.title("编辑话术")
        self.geometry("480x420")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._result = None
        self._text_widgets: dict = {}

        if initial_phrase is None:
            self.blocks = [{"type": "text", "content": ""}]
        elif isinstance(initial_phrase, str):
            self.blocks = [{"type": "text", "content": initial_phrase}]
        else:
            self.blocks = copy.deepcopy(initial_phrase)

        self._build()
        self.grab_set()

    def _build(self):
        self.blocks_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0
        )
        self.blocks_frame.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        toolbar = ctk.CTkFrame(self, fg_color="transparent", height=48)
        toolbar.pack(fill="x", padx=10, pady=8)
        toolbar.pack_propagate(False)

        ctk.CTkButton(
            toolbar, text="＋文字", width=80, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=PRIMARY,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12),
            command=self._add_text_block,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            toolbar, text="＋图片", width=80, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color=PRIMARY,
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12),
            command=self._add_image_block,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="取消", width=64, height=32, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#d9d9d9",
            text_color="#666",
            command=self.destroy,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            toolbar, text="确认", width=64, height=32, corner_radius=8,
            fg_color=PRIMARY, hover_color=PRIMARY_H, text_color="white",
            command=self._confirm,
        ).pack(side="right")

        self._refresh_blocks()

    def _refresh_blocks(self):
        self._sync_text_widgets()
        for w in self.blocks_frame.winfo_children():
            w.destroy()
        self._text_widgets = {}
        for i, block in enumerate(self.blocks):
            self._render_block(i, block)

    def _render_block(self, i: int, block: dict):
        row = ctk.CTkFrame(self.blocks_frame, fg_color="#f8f8f8", corner_radius=8)
        row.pack(fill="x", pady=(0, 6))

        # Controls (right side)
        ctrl = ctk.CTkFrame(row, fg_color="transparent", width=76)
        ctrl.pack(side="right", padx=4, pady=4)
        ctrl.pack_propagate(False)

        ctk.CTkButton(
            ctrl, text="🗑", width=28, height=26, corner_radius=6,
            fg_color="transparent", text_color="#ff4d4f",
            command=lambda idx=i: self._delete_block(idx),
        ).pack(pady=(0, 2))
        if i > 0:
            ctk.CTkButton(
                ctrl, text="↑", width=28, height=26, corner_radius=6,
                fg_color="transparent", text_color="#666",
                command=lambda idx=i: self._move_block(idx, -1),
            ).pack(pady=1)
        if i < len(self.blocks) - 1:
            ctk.CTkButton(
                ctrl, text="↓", width=28, height=26, corner_radius=6,
                fg_color="transparent", text_color="#666",
                command=lambda idx=i: self._move_block(idx, 1),
            ).pack(pady=1)

        # Content
        if block["type"] == "text":
            tb = ctk.CTkTextbox(
                row, height=80, corner_radius=6,
                font=ctk.CTkFont(family="PingFang SC", size=12),
                border_width=1, border_color="#e0e0e0",
            )
            tb.pack(fill="x", padx=(8, 4), pady=8)
            tb.insert("end", block.get("content", ""))
            self._text_widgets[i] = tb
        elif block["type"] == "image":
            name = os.path.basename(block.get("path", "")) or "（未选择）"
            ctk.CTkLabel(
                row, text=f"🖼  {name}", anchor="w",
                font=ctk.CTkFont(family="PingFang SC", size=12),
                text_color="#555",
            ).pack(fill="x", padx=(10, 4), pady=12)

    def _sync_text_widgets(self):
        for i, tb in self._text_widgets.items():
            if i < len(self.blocks) and self.blocks[i]["type"] == "text":
                try:
                    self.blocks[i]["content"] = tb.get("1.0", "end").strip()
                except Exception:
                    pass

    def _add_text_block(self):
        self._sync_text_widgets()
        self.blocks.append({"type": "text", "content": ""})
        self._refresh_blocks()

    def _add_image_block(self):
        from tkinter import filedialog
        self._sync_text_widgets()
        path = filedialog.askopenfilename(
            parent=self,
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks.append({"type": "image", "path": path})
            self._refresh_blocks()

    def _delete_block(self, i: int):
        self._sync_text_widgets()
        self.blocks.pop(i)
        self._refresh_blocks()

    def _move_block(self, i: int, direction: int):
        self._sync_text_widgets()
        j = i + direction
        if 0 <= j < len(self.blocks):
            self.blocks[i], self.blocks[j] = self.blocks[j], self.blocks[i]
        self._refresh_blocks()

    def _confirm(self):
        self._sync_text_widgets()
        result = [
            b for b in self.blocks
            if (b["type"] == "text" and b.get("content", "").strip())
            or b["type"] == "image"
        ]
        if not result:
            return
        self._result = result
        self.destroy()

    def get_result(self):
        """等待对话框关闭，返回 blocks 列表或 None（取消时）。"""
        self.wait_window()
        return self._result
```

- [ ] **Step 2: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add gui_panel.py
git commit -m "feat: 新增 BlockEditor 图文混排编辑对话框"
```

---

## Task 4：更新 PhraseCard 支持混排预览 + 编辑按钮

**Files:**
- Modify: `gui_panel.py`（`PhraseCard` 类，约第 150 行）

- [ ] **Step 1: 更新 PhraseCard.__init__ 签名和属性**

将 `PhraseCard.__init__` 方法完整替换为：

```python
def __init__(self, parent, phrase, on_send, on_select, on_edit=None, **kwargs):
    super().__init__(parent, corner_radius=10, fg_color=self.NORMAL_BG,
                     border_width=1, border_color="#e8e8e8", **kwargs)
    self._phrase = phrase       # str 或 list of blocks
    self._on_send = on_send
    self._on_select = on_select
    self._on_edit = on_edit
    self._selected = False
    self._build()
```

- [ ] **Step 2: 更新 PhraseCard._build 方法**

将 `_build` 方法完整替换为：

```python
def _build(self):
    self.grid_columnconfigure(0, weight=1)

    preview = phrase_preview_text(self._phrase)
    has_img = has_images(self._phrase)

    self._label = ctk.CTkLabel(
        self,
        text=("🖼 " if has_img else "") + preview,
        wraplength=200,
        justify="left", anchor="w",
        text_color="#333",
        font=ctk.CTkFont(family="PingFang SC", size=12),
    )
    self._label.grid(row=0, column=0, padx=(10, 4), pady=8, sticky="ew")

    btn_frame = ctk.CTkFrame(self, fg_color="transparent")
    btn_frame.grid(row=0, column=1, padx=(0, 6), pady=8)

    if self._on_edit:
        ctk.CTkButton(
            btn_frame, text="编辑", width=36, height=22,
            corner_radius=4, fg_color="transparent",
            border_width=1, border_color="#d9d9d9",
            text_color="#888", hover_color="#f0f0f0",
            font=ctk.CTkFont(size=10),
            command=self._on_edit,
        ).pack(side="top", pady=(0, 3))

    self._send_btn = ctk.CTkButton(
        btn_frame, text="发送", width=44, height=26,
        corner_radius=6, fg_color=CARD_BG,
        text_color=PRIMARY, hover_color="#bbd6ff",
        font=ctk.CTkFont(size=11, weight="bold"),
        command=self._on_send,
    )
    self._send_btn.pack(side="top")

    self._label.bind("<Button-1>", lambda e: self._on_select(self))
    self.bind("<Button-1>", lambda e: self._on_select(self))
```

- [ ] **Step 3: 替换 `text` property，新增 `phrase` property**

找到 `@property` / `def text` 块，替换为：

```python
@property
def text(self) -> str:
    """纯文本摘要（向后兼容，用于日志等场景）。"""
    return phrase_preview_text(self._phrase)

@property
def phrase(self):
    """原始话术值（str 或 list of blocks）。"""
    return self._phrase
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "feat: PhraseCard 支持图文混排预览和编辑按钮"
```

---

## Task 5：更新 _refresh_cards、_do_send、_edit_phrase

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: 更新 `_refresh_cards`**

将 `_refresh_cards` 方法完整替换为：

```python
def _refresh_cards(self):
    for widget in self.cards_frame.winfo_children():
        widget.destroy()
    self._selected_card = None
    group = self.group_var.get()
    for i, phrase in enumerate(self.phrases.get(group, [])):
        card = PhraseCard(
            self.cards_frame,
            phrase=phrase,
            on_send=lambda p=phrase: self._do_send(p),
            on_select=self._select_card,
            on_edit=lambda idx=i: self._edit_phrase(idx),
        )
        card.pack(fill="x", pady=(0, 5))
```

- [ ] **Step 2: 更新 `_do_send` 支持 Block 列表**

将 `_do_send` 方法完整替换为：

```python
def _do_send(self, phrase):
    """发送话术（str 或 list of blocks），按块顺序依次发出文字和图片。"""
    blocks = normalize_phrase(phrase)

    def send_task():
        try:
            for block in blocks:
                if block.get("type") == "text" and block.get("content", "").strip():
                    send_message(block["content"])
                    time.sleep(0.3)
                elif block.get("type") == "image":
                    send_image(block["path"])
                    time.sleep(0.5)
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_OK))
            self.root.after(0, lambda: self.status_label.configure(text="✅ 发送成功"))
        except NoChatWindowError as e:
            msg = str(e)
            self.root.after(0, lambda: self._show_warning(msg))
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_WAIT))
            self.root.after(0, lambda: self.status_label.configure(text="未选中聊天窗口"))
        except FileNotFoundError as e:
            msg = str(e)
            self.root.after(0, lambda: self._show_warning(msg))
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
            self.root.after(0, lambda: self.status_label.configure(text="❌ 图片文件不存在"))
        except Exception:
            self.root.after(0, lambda: self.status_dot.configure(text_color=DOT_ERR))
            self.root.after(0, lambda: self.status_label.configure(text="❌ 发送失败"))
        self.root.after(3000, self._check_status)

    threading.Thread(target=send_task, daemon=True).start()
```

- [ ] **Step 3: 新增 `_edit_phrase` 方法**

在 `_delete_phrase` 方法之后插入：

```python
def _edit_phrase(self, idx: int):
    """打开 BlockEditor 编辑第 idx 条话术并保存。"""
    group = self.group_var.get()
    phrases_list = self.phrases.get(group, [])
    if idx >= len(phrases_list):
        return

    self.root.attributes("-topmost", False)
    editor = BlockEditor(self.root, initial_phrase=phrases_list[idx])
    result = editor.get_result()
    self.root.attributes("-topmost", True)

    if result is None:
        return
    # 单文字块存为纯字符串（向后兼容）
    if len(result) == 1 and result[0]["type"] == "text":
        phrases_list[idx] = result[0]["content"]
    else:
        phrases_list[idx] = result
    save_phrases(self.phrases)
    self._refresh_cards()
```

- [ ] **Step 4: 在 gui_panel.py 的 sender import 行添加 send_image**

找到：
```python
from sender import send_message, is_daxiang_running, NoChatWindowError, read_chat_messages
```

替换为：
```python
from sender import send_message, send_image, is_daxiang_running, NoChatWindowError, read_chat_messages
```

- [ ] **Step 5: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add gui_panel.py
git commit -m "feat: _refresh_cards/_do_send 支持 Block，新增 _edit_phrase"
```

---

## Task 6：更新 _add_phrase 和 _delete_phrase

**Files:**
- Modify: `gui_panel.py`

- [ ] **Step 1: 替换 `_add_phrase`**

将 `_add_phrase` 方法完整替换为：

```python
def _add_phrase(self):
    self.root.attributes("-topmost", False)
    editor = BlockEditor(self.root)
    result = editor.get_result()
    self.root.attributes("-topmost", True)

    if not result:
        return
    group = self.group_var.get()
    # 单文字块存为纯字符串（向后兼容）
    phrase = result[0]["content"] if len(result) == 1 and result[0]["type"] == "text" else result
    self.phrases.setdefault(group, []).append(phrase)
    save_phrases(self.phrases)
    self._refresh_cards()
```

- [ ] **Step 2: 更新 `_delete_phrase`，改用 `.phrase` 属性**

将 `_delete_phrase` 方法完整替换为：

```python
def _delete_phrase(self):
    if not self._selected_card:
        self._show_warning("请先选中要删除的话术")
        return
    if self._ask_yesno("确认", "确定要删除这条话术吗？"):
        group = self.group_var.get()
        target = self._selected_card.phrase
        phrases_list = self.phrases.get(group, [])
        for i, p in enumerate(phrases_list):
            if p == target:
                phrases_list.pop(i)
                break
        save_phrases(self.phrases)
        self._refresh_cards()
```

- [ ] **Step 3: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py sender.py && echo "ALL OK"
```

Expected: `ALL OK`

- [ ] **Step 4: 提交**

```bash
git add gui_panel.py
git commit -m "feat: _add_phrase 改用 BlockEditor，_delete_phrase 用 .phrase 属性"
```

---

## Task 7：冒烟测试 + 推送

**Files:**
- 无代码变更，手动验证

- [ ] **Step 1: 启动应用**

```bash
.venv/bin/python gui_panel.py
```

逐项验证：

| 测试项 | 预期结果 |
|--------|---------|
| 旧纯文本话术正常显示 | 卡片正常显示文字，无 🖼 图标 |
| 点击「➕ 添加话术」| 弹出 BlockEditor（非旧单行输入框）|
| BlockEditor 添加文字块 | CTkTextbox 可输入多行文字 |
| BlockEditor 添加图片块 | 文件选择对话框，选后显示文件名 |
| BlockEditor 上移/下移块 | 块顺序变化 |
| BlockEditor 删除块 | 块消失 |
| BlockEditor 点「确认」| 卡片显示，图文话术卡片有 🖼 图标 |
| 点击图文话术「发送」| 企业微信依次收到文字→图片→文字 |
| 点击图文话术「编辑」| BlockEditor 预填已有内容，修改后保存 |
| 纯文本话术「发送」| 企业微信收到文字（行为不变）|
| 图片路径不存在时发送 | 状态栏显示「❌ 图片文件不存在」，弹窗提示 |

- [ ] **Step 2: 推送**

```bash
git push
```
