# BlockEditor WYSIWYG 重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `BlockEditor` 从简陋块列表改造为内联画布风格——文字块内嵌 CTkTextbox 直接编辑，图片块显示 Pillow 缩略图，活跃块蓝框高亮，整体像消息草稿编辑器。

**Architecture:** 完整替换 `BlockEditor` 类（gui_panel.py），新增模块级 `make_thumbnail()` 工具函数（Pillow）。用 `_text_widgets` dict 跟踪 CTkTextbox 引用，`_render_all()` 先 sync 所有文字内容再重绘。

**Tech Stack:** Python 3.13, CustomTkinter 5.2.x, Pillow (新增)

---

## 文件结构

| 文件 | 变更 |
|------|------|
| `gui_panel.py` | 新增 `make_thumbnail()`；完整替换 `BlockEditor` 类 |

---

## Task 1：安装 Pillow + make_thumbnail()

**Files:**
- Modify: `gui_panel.py`（`save_phrases()` 之后）

- [ ] **Step 1: 安装 Pillow**

```bash
cd /Users/baijinshan/Desktop/coffe_hours/wechat_work_sender
uv pip install Pillow --python .venv/bin/python
```

Expected: 安装成功，无报错

- [ ] **Step 2: 验证 Pillow 可用**

```bash
.venv/bin/python -c "from PIL import Image; print('Pillow OK')"
```

Expected: `Pillow OK`

- [ ] **Step 3: 在 `has_images()` 之后插入 `make_thumbnail()` 函数**

```python
def make_thumbnail(path: str, size: tuple = (72, 54)):
    """用 Pillow 生成 CTkImage 缩略图。加载失败返回 None。"""
    try:
        from PIL import Image as PILImage
        expanded = os.path.expanduser(path)
        img = PILImage.open(expanded).convert("RGBA")
        img.thumbnail((size[0] * 3, size[1] * 3), PILImage.LANCZOS)
        # 居中裁剪到目标尺寸
        w, h = img.size
        tw, th = size
        left = (w - tw) // 2 if w > tw else 0
        top  = (h - th) // 2 if h > th else 0
        img = img.crop((left, top, left + min(w, tw), top + min(h, th)))
        new = PILImage.new("RGBA", size, (240, 244, 255, 255))
        new.paste(img, ((tw - min(w, tw)) // 2, (th - min(h, th)) // 2))
        return ctk.CTkImage(light_image=new, dark_image=new, size=size)
    except Exception:
        return None
```

- [ ] **Step 4: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add gui_panel.py
git commit -m "feat: 安装 Pillow，新增 make_thumbnail() 缩略图工具函数"
```

---

## Task 2：完整替换 BlockEditor 类

**Files:**
- Modify: `gui_panel.py`（替换第 150 行附近的 `class BlockEditor`，约 165 行 → 约 280 行）

- [ ] **Step 1: 找到 BlockEditor 类的起止行**

```bash
grep -n "^class BlockEditor\|^class PhraseCard" gui_panel.py
```

Expected: 类似 `150:class BlockEditor` 和 `320:class PhraseCard`（行号以实际为准）

- [ ] **Step 2: 将 BlockEditor 类完整替换为以下实现**

删除旧 `class BlockEditor`（从 `class BlockEditor` 到 `class PhraseCard` 之前），插入：

```python
class BlockEditor(ctk.CTkToplevel):
    """WYSIWYG 内联画布话术编辑器：文字块直接编辑，图片块显示缩略图。"""

    TEXT_LABEL_BG     = "#e6f0ff"
    IMAGE_LABEL_BG    = "#fff8f0"
    INACTIVE_LABEL_BG = "#f8f8f8"

    def __init__(self, parent, initial_phrase=None):
        super().__init__(parent)
        self.title("编辑话术")
        self.geometry("520x500")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._result      = None
        self._active_idx  = 0
        self._text_widgets: dict = {}   # {block_index: CTkTextbox}

        if initial_phrase is None:
            self.blocks = [{"type": "text", "content": ""}]
        elif isinstance(initial_phrase, str):
            self.blocks = [{"type": "text", "content": initial_phrase}]
        else:
            self.blocks = copy.deepcopy(initial_phrase)

        self._build()
        self.grab_set()
        self.after(120, lambda: self._focus_active_textbox())

    # ── 构建固定框架 ─────────────────────────────────────────

    def _build(self):
        # 标题栏
        header = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color=PRIMARY)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="编辑话术", text_color="white",
            font=ctk.CTkFont(family="PingFang SC", size=13, weight="bold"),
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            header, text="确认", width=60, height=28, corner_radius=6,
            fg_color="white", text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._confirm,
        ).pack(side="right", padx=(4, 10))

        ctk.CTkButton(
            header, text="取消", width=60, height=28, corner_radius=6,
            fg_color="transparent", text_color="white", hover_color=PRIMARY_H,
            border_width=1, border_color="rgba(255,255,255,0.5)",
            font=ctk.CTkFont(size=12),
            command=self.destroy,
        ).pack(side="right")

        # 可滚动画布
        self._canvas = ctk.CTkScrollableFrame(
            self, fg_color="#f5f7ff", corner_radius=0
        )
        self._canvas.pack(fill="both", expand=True)

        # 底部添加按钮栏
        add_bar = ctk.CTkFrame(self, fg_color="white", height=52, corner_radius=0)
        add_bar.pack(fill="x")
        add_bar.pack_propagate(False)

        inner = ctk.CTkFrame(add_bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=8)
        inner.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            inner, text="＋ 添加文字", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#bbd6ff",
            text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=11),
            command=self._add_text,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")

        ctk.CTkButton(
            inner, text="＋ 添加图片", height=34, corner_radius=8,
            fg_color="transparent", border_width=1, border_color="#ffd591",
            text_color="#fa8c16", hover_color="#fff8f0",
            font=ctk.CTkFont(size=11),
            command=self._add_image,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self._render_all()

    # ── 渲染 ─────────────────────────────────────────────────

    def _render_all(self):
        self._sync_all_texts()
        for w in self._canvas.winfo_children():
            w.destroy()
        self._text_widgets = {}
        for i, block in enumerate(self.blocks):
            self._render_block(i, block)

    def _render_block(self, i: int, block: dict):
        active   = (i == self._active_idx)
        b_color  = PRIMARY if active else "#e8e8e8"
        b_width  = 2 if active else 1

        outer = ctk.CTkFrame(
            self._canvas, corner_radius=10, fg_color="white",
            border_color=b_color, border_width=b_width,
        )
        outer.pack(fill="x", padx=12, pady=(0, 7))

        # 标签条
        if block["type"] == "text":
            lbg   = self.TEXT_LABEL_BG if active else self.INACTIVE_LABEL_BG
            lcolor = PRIMARY if active else "#999"
            ltxt  = "文字"
        else:
            lbg   = self.IMAGE_LABEL_BG
            lcolor = "#fa8c16"
            ltxt  = "图片"

        label_bar = ctk.CTkFrame(outer, fg_color=lbg, corner_radius=0, height=24)
        label_bar.pack(fill="x")
        label_bar.pack_propagate(False)

        ctk.CTkLabel(
            label_bar, text=ltxt, text_color=lcolor,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=8)

        # 控制按钮
        btn_area = ctk.CTkFrame(label_bar, fg_color="transparent")
        btn_area.pack(side="right", padx=4)

        if i > 0:
            ctk.CTkButton(
                btn_area, text="↑", width=20, height=18, corner_radius=4,
                fg_color="transparent", text_color="#aaa", hover_color="#f0f0f0",
                font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._move(idx, -1),
            ).pack(side="left", padx=1)

        if i < len(self.blocks) - 1:
            ctk.CTkButton(
                btn_area, text="↓", width=20, height=18, corner_radius=4,
                fg_color="transparent", text_color="#aaa", hover_color="#f0f0f0",
                font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._move(idx, 1),
            ).pack(side="left", padx=1)

        ctk.CTkButton(
            btn_area, text="🗑", width=20, height=18, corner_radius=4,
            fg_color="transparent", text_color="#ff4d4f", hover_color="#fff0f0",
            font=ctk.CTkFont(size=11),
            command=lambda idx=i: self._delete(idx),
        ).pack(side="left", padx=(1, 4))

        # 内容区
        if block["type"] == "text":
            tb = ctk.CTkTextbox(
                outer, height=72, corner_radius=0, border_width=0,
                font=ctk.CTkFont(family="PingFang SC", size=12),
            )
            tb.pack(fill="x", padx=10, pady=(6, 10))
            tb.insert("end", block.get("content", ""))
            tb.bind("<FocusIn>",  lambda e, idx=i: self._on_focus_in(idx))
            tb.bind("<FocusOut>", lambda e, idx=i, w=tb: self._on_focus_out(idx, w))
            self._text_widgets[i] = tb
        else:
            self._render_image_content(outer, i, block)

    def _render_image_content(self, parent, i: int, block: dict):
        path = block.get("path", "")
        row  = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)

        # 缩略图
        thumb = make_thumbnail(path) if path else None
        if thumb:
            ctk.CTkLabel(row, image=thumb, text="", width=72, height=54).pack(
                side="left", padx=(0, 10)
            )
        else:
            ctk.CTkLabel(
                row, text="🖼", font=ctk.CTkFont(size=24),
                width=72, height=54, fg_color="#e0eeff", corner_radius=6,
                text_color="#7ba8e0",
            ).pack(side="left", padx=(0, 10))

        # 信息列
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        name = os.path.basename(path) if path else "（未选择）"
        ctk.CTkLabel(
            info, text=name, anchor="w",
            font=ctk.CTkFont(family="PingFang SC", size=11, weight="bold"),
            text_color="#333",
        ).pack(anchor="w")

        expanded = os.path.expanduser(path) if path else ""
        if expanded and os.path.exists(expanded):
            try:
                sz = os.path.getsize(expanded)
                size_str = f"{sz // 1024} KB" if sz >= 1024 else f"{sz} B"
                ctk.CTkLabel(
                    info, text=size_str, anchor="w",
                    font=ctk.CTkFont(size=10), text_color="#999",
                ).pack(anchor="w")
            except Exception:
                pass

        ctk.CTkButton(
            info, text="替换图片", width=60, height=20, corner_radius=4,
            fg_color="transparent", text_color=PRIMARY, hover_color=CARD_BG,
            font=ctk.CTkFont(size=10),
            command=lambda idx=i: self._replace_image(idx),
        ).pack(anchor="w", pady=(4, 0))

    # ── 事件处理 ─────────────────────────────────────────────

    def _focus_active_textbox(self):
        tb = self._text_widgets.get(self._active_idx)
        if tb:
            tb.focus_set()

    def _sync_all_texts(self):
        """将所有 CTkTextbox 内容同步回 self.blocks。"""
        for i, tb in self._text_widgets.items():
            if i < len(self.blocks) and self.blocks[i]["type"] == "text":
                try:
                    self.blocks[i]["content"] = tb.get("1.0", "end").strip()
                except Exception:
                    pass

    def _on_focus_in(self, idx: int):
        if self._active_idx != idx:
            self._active_idx = idx
            self._render_all()

    def _on_focus_out(self, idx: int, tb: ctk.CTkTextbox):
        if idx < len(self.blocks) and self.blocks[idx]["type"] == "text":
            try:
                self.blocks[idx]["content"] = tb.get("1.0", "end").strip()
            except Exception:
                pass

    def _move(self, i: int, direction: int):
        self._sync_all_texts()
        j = i + direction
        if 0 <= j < len(self.blocks):
            self.blocks[i], self.blocks[j] = self.blocks[j], self.blocks[i]
            self._active_idx = j
        self._render_all()

    def _delete(self, i: int):
        self._sync_all_texts()
        self.blocks.pop(i)
        self._active_idx = min(self._active_idx, max(0, len(self.blocks) - 1))
        self._render_all()

    def _add_text(self):
        self._sync_all_texts()
        self.blocks.append({"type": "text", "content": ""})
        self._active_idx = len(self.blocks) - 1
        self._render_all()
        self.after(80, self._focus_active_textbox)

    def _add_image(self):
        from tkinter import filedialog
        self._sync_all_texts()
        path = filedialog.askopenfilename(
            parent=self,
            title="选择图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks.append({"type": "image", "path": path})
            self._active_idx = len(self.blocks) - 1
            self._render_all()

    def _replace_image(self, i: int):
        from tkinter import filedialog
        self._sync_all_texts()
        path = filedialog.askopenfilename(
            parent=self,
            title="替换图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.blocks[i]["path"] = path
            self._active_idx = i
            self._render_all()

    def _confirm(self):
        self._sync_all_texts()
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

- [ ] **Step 3: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: 验证 BlockEditor 可导入**

```bash
.venv/bin/python -c "
from gui_panel import BlockEditor, make_thumbnail
print('BlockEditor OK')
print('make_thumbnail OK')
"
```

Expected:
```
BlockEditor OK
make_thumbnail OK
```

- [ ] **Step 5: 提交并推送**

```bash
git add gui_panel.py
git commit -m "feat: BlockEditor WYSIWYG 重设计——内联画布，图片缩略图，活跃块高亮"
git push
```

---

## Task 3：手动冒烟测试

**Files:** 无代码变更，手动验证

- [ ] **Step 1: 启动应用**

```bash
.venv/bin/python gui_panel.py
```

| 测试项 | 预期结果 |
|--------|---------|
| 点击「➕ 添加话术」| 打开新 BlockEditor，默认一个空文字块，蓝框高亮 |
| 在文字块输入内容 | 直接输入，无需额外点击 |
| 点「＋ 添加文字」| 新文字块出现在底部，自动获得焦点 |
| 点「＋ 添加图片」| 文件选择对话框，选 PNG/JPG 后图片块显示缩略图 |
| 缩略图显示 | 72×54 居中裁剪，图片名称和文件大小正确 |
| 点「替换图片」| 重新选择文件，缩略图更新 |
| 点 ↑ / ↓ | 块顺序正确交换，焦点跟随移动块 |
| 点 🗑 | 块删除，剩余块正常显示 |
| 点「确认」| 对话框关闭，话术卡片更新（图文块显示 🖼 前缀）|
| 编辑旧纯文本话术 | BlockEditor 打开，内容预填在第一个文字块 |
| 图片路径不存在时 | 显示蓝色占位框 + 🖼，不崩溃 |
| PIL 加载失败时 | 同上，占位框而非报错 |
