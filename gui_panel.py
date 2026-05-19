#!/usr/bin/env python3
"""
企业微信话术快捷发送面板 (macOS GUI Demo)

功能：
- 话术列表面板，点击即发送到企业微信
- 支持自定义话术、分组管理
- 支持自定义输入发送
- 窗口置顶，方便随时使用

依赖：
- tkinter (Python 内置)
- sender.py (同目录)
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import threading

# 导入发送模块
from sender import send_message, is_daxiang_running

# ============================================================
# 话术数据管理
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")

# 默认话术库
DEFAULT_PHRASES = {
    "问候语": [
        "您好，我是您的专属客服，请问有什么可以帮您？",
        "您好，感谢您的耐心等待，现在为您处理。",
        "早上好！有什么需要帮助的吗？",
    ],
    "常用回复": [
        "好的，我这边帮您查一下，请稍等。",
        "已收到您的反馈，我们会尽快处理。",
        "非常抱歉给您带来不便，我们马上为您解决。",
        "感谢您的理解与支持！",
    ],
    "结束语": [
        "还有其他问题吗？如果没有的话，祝您生活愉快！",
        "问题已解决，如有其他需要随时联系我们。",
        "感谢咨询，再见！",
    ],
}


def load_phrases() -> dict:
    """加载话术库"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_PHRASES.copy()


def save_phrases(phrases: dict):
    """保存话术库"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(phrases, f, ensure_ascii=False, indent=2)


# ============================================================
# GUI 应用
# ============================================================

class DaxiangSenderApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("企业微信快捷发送 - Demo")
        self.root.geometry("420x600")
        self.root.attributes("-topmost", True)  # 窗口置顶
        self.root.configure(bg="#f5f5f5")

        self.phrases = load_phrases()
        self.current_group = list(self.phrases.keys())[0] if self.phrases else ""

        self._build_ui()

    def _build_ui(self):
        """构建界面"""
        # 顶部状态栏
        status_frame = tk.Frame(self.root, bg="#2c3e50", height=40)
        status_frame.pack(fill=tk.X)
        status_frame.pack_propagate(False)

        self.status_label = tk.Label(
            status_frame,
            text="⏳ 检测中...",
            fg="white",
            bg="#2c3e50",
            font=("PingFang SC", 12),
        )
        self.status_label.pack(side=tk.LEFT, padx=10, pady=8)

        refresh_btn = tk.Button(
            status_frame,
            text="🔄",
            command=self._check_status,
            bg="#2c3e50",
            fg="white",
            borderwidth=0,
            font=("", 14),
        )
        refresh_btn.pack(side=tk.RIGHT, padx=10)

        # 分组选择
        group_frame = tk.Frame(self.root, bg="#f5f5f5")
        group_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        tk.Label(
            group_frame, text="话术分组:", bg="#f5f5f5", font=("PingFang SC", 11)
        ).pack(side=tk.LEFT)

        self.group_var = tk.StringVar(value=self.current_group)
        self.group_combo = ttk.Combobox(
            group_frame,
            textvariable=self.group_var,
            values=list(self.phrases.keys()),
            state="readonly",
            width=15,
        )
        self.group_combo.pack(side=tk.LEFT, padx=5)
        self.group_combo.bind("<<ComboboxSelected>>", self._on_group_change)

        add_group_btn = tk.Button(
            group_frame,
            text="+ 新分组",
            command=self._add_group,
            font=("PingFang SC", 10),
        )
        add_group_btn.pack(side=tk.RIGHT)

        # 话术列表（可点击发送）
        list_frame = tk.Frame(self.root, bg="#f5f5f5")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.phrase_listbox = tk.Listbox(
            list_frame,
            font=("PingFang SC", 11),
            selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
            bg="white",
            selectbackground="#3498db",
            selectforeground="white",
            activestyle="none",
            borderwidth=1,
            relief=tk.SOLID,
        )
        self.phrase_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.phrase_listbox.yview)

        # 双击发送
        self.phrase_listbox.bind("<Double-Button-1>", self._on_double_click_send)

        # 操作按钮区
        btn_frame = tk.Frame(self.root, bg="#f5f5f5")
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        send_btn = tk.Button(
            btn_frame,
            text="📤 发送选中",
            command=self._send_selected,
            bg="#27ae60",
            fg="white",
            font=("PingFang SC", 11, "bold"),
            width=12,
        )
        send_btn.pack(side=tk.LEFT, padx=(0, 5))

        add_btn = tk.Button(
            btn_frame,
            text="➕ 添加话术",
            command=self._add_phrase,
            font=("PingFang SC", 10),
            width=10,
        )
        add_btn.pack(side=tk.LEFT, padx=5)

        del_btn = tk.Button(
            btn_frame,
            text="🗑️ 删除",
            command=self._delete_phrase,
            font=("PingFang SC", 10),
            width=8,
        )
        del_btn.pack(side=tk.RIGHT)

        # 自定义输入区
        input_frame = tk.Frame(self.root, bg="#f5f5f5")
        input_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

        tk.Label(
            input_frame, text="自定义消息:", bg="#f5f5f5", font=("PingFang SC", 11)
        ).pack(anchor=tk.W)

        self.custom_input = tk.Text(
            input_frame,
            height=3,
            font=("PingFang SC", 11),
            borderwidth=1,
            relief=tk.SOLID,
        )
        self.custom_input.pack(fill=tk.X, pady=(3, 5))

        custom_send_btn = tk.Button(
            input_frame,
            text="发送自定义消息",
            command=self._send_custom,
            bg="#3498db",
            fg="white",
            font=("PingFang SC", 11),
        )
        custom_send_btn.pack(fill=tk.X)

        # 底部提示
        tip_label = tk.Label(
            self.root,
            text="💡 双击话术即可发送 | 请确保企业微信聊天窗口已打开",
            bg="#f5f5f5",
            fg="#7f8c8d",
            font=("PingFang SC", 9),
        )
        tip_label.pack(side=tk.BOTTOM, pady=5)

        # 初始化
        self._refresh_list()
        self._check_status()

    def _refresh_list(self):
        """刷新话术列表"""
        self.phrase_listbox.delete(0, tk.END)
        group = self.group_var.get()
        if group in self.phrases:
            for phrase in self.phrases[group]:
                # 截断显示，避免单行太长
                display = phrase if len(phrase) <= 50 else phrase[:47] + "..."
                self.phrase_listbox.insert(tk.END, display)

    def _on_group_change(self, event=None):
        """切换分组"""
        self._refresh_list()

    def _check_status(self):
        """检查企业微信状态"""
        def check():
            running = is_daxiang_running()
            self.root.after(0, lambda: self._update_status(running))

        threading.Thread(target=check, daemon=True).start()

    def _update_status(self, running: bool):
        """更新状态显示"""
        if running:
            self.status_label.config(text="✅ 企业微信已运行", fg="#2ecc71")
        else:
            self.status_label.config(text="❌ 企业微信未运行", fg="#e74c3c")

    def _send_selected(self):
        """发送选中的话术"""
        selection = self.phrase_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择一条话术")
            return

        group = self.group_var.get()
        idx = selection[0]
        text = self.phrases[group][idx]
        self._do_send(text)

    def _on_double_click_send(self, event):
        """双击直接发送"""
        selection = self.phrase_listbox.curselection()
        if selection:
            group = self.group_var.get()
            idx = selection[0]
            text = self.phrases[group][idx]
            self._do_send(text)

    def _send_custom(self):
        """发送自定义消息"""
        text = self.custom_input.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("提示", "请输入消息内容")
            return
        self._do_send(text)
        self.custom_input.delete("1.0", tk.END)

    def _do_send(self, text: str):
        """执行发送（在后台线程中）"""
        def send_task():
            success = send_message(text)
            if success:
                self.root.after(0, lambda: self.status_label.config(
                    text="✅ 发送成功", fg="#2ecc71"
                ))
            else:
                self.root.after(0, lambda: self.status_label.config(
                    text="❌ 发送失败", fg="#e74c3c"
                ))
            # 3秒后恢复状态
            self.root.after(3000, self._check_status)

        # 直接在后台线程执行发送，窗口保持不动
        threading.Thread(target=send_task, daemon=True).start()

    def _add_phrase(self):
        """添加新话术"""
        text = simpledialog.askstring("添加话术", "请输入话术内容：", parent=self.root)
        if text and text.strip():
            group = self.group_var.get()
            if group not in self.phrases:
                self.phrases[group] = []
            self.phrases[group].append(text.strip())
            save_phrases(self.phrases)
            self._refresh_list()

    def _delete_phrase(self):
        """删除选中话术"""
        selection = self.phrase_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的话术")
            return

        if messagebox.askyesno("确认", "确定要删除这条话术吗？"):
            group = self.group_var.get()
            idx = selection[0]
            self.phrases[group].pop(idx)
            save_phrases(self.phrases)
            self._refresh_list()

    def _add_group(self):
        """添加新分组"""
        name = simpledialog.askstring("新分组", "请输入分组名称：", parent=self.root)
        if name and name.strip():
            name = name.strip()
            if name not in self.phrases:
                self.phrases[name] = []
                save_phrases(self.phrases)
                self.group_combo["values"] = list(self.phrases.keys())
                self.group_var.set(name)
                self._refresh_list()

    def run(self):
        """启动应用"""
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  企业微信快捷发送面板 (macOS Demo)")
    print("  请确保已授予辅助功能权限")
    print("=" * 50)
    app = DaxiangSenderApp()
    app.run()
