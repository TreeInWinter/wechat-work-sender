# im_clients/daxiang.py
from __future__ import annotations

import os
import tempfile

import sender  # 复用企业微信已验证的图片合成逻辑（render_blocks_to_image）
from .ax_helpers import (
    activate_app,
    focus_input,
    get_ax_element,
    get_clipboard_text,
    is_app_running,
    paste_and_send,
    set_clipboard_png,
    set_clipboard_text,
)
from .base import IMClientAdapter, TakeoverCapabilities, UnsupportedClientAction


class DaxiangAdapter(IMClientAdapter):
    """
    大象（美团内部 IM）适配器。

    真机探测结论（2026-06-05）：
      - bundle ID: cn.neixin.pc（非 com.sankuai.daxiang）
      - AX 树：WebView 渲染，AXWebArea 在 depth=5，聊天输入框 AXTextArea 在 depth=23
        （从 app root 算为 depth=24），有占位符文本 '说点什么...'
      - 发送：AX 找到输入框（max_depth=26，allow_with_value=True）→ Cmd+V → Enter
      - 读取：消息以 AXStaticText 散布在 depth=22-25，无 AXTable 结构
    """

    client_id = "daxiang"
    display_name = "大象"
    app_names = ("大象", "Daxiang", "DaXiang")
    bundle_ids = ("cn.neixin.pc", "com.sankuai.daxiang", "com.meituan.daxiang")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=True,   # 真机验证：focus_input depth=26 + Cmd+V + AppleScript Enter 可靠
    )

    # AppleScript tell process 用的进程名（真机验证：大象）
    _PROCESS_NAME = "大象"

    # 大象输入框在 AX 树深处（depth=23 from window = depth=24 from app root）
    _INPUT_MAX_DEPTH = 26

    def is_running(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return True
        return False

    def activate(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return activate_app(name)
        return False

    def _get_app_name(self) -> str | None:
        """返回当前正在运行的 app_name（用于 AX 查找）。"""
        for name in self.app_names:
            if is_app_running(name):
                return name
        return None

    def send_blocks(self, blocks: list) -> bool:
        """
        发送 blocks 到当前大象聊天窗口。

        纯文字：set_clipboard_text + paste_and_send
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png + paste_and_send
        图文混排：合成单张图片发送（保证只出现一条消息）

        注意：大象输入框在 AX 树 depth=24（从 app root 算），有占位符文本，
        需要 max_depth=26 且 allow_with_value=True。
        """
        app_name = self._get_app_name()
        if app_name is None:
            return False

        if not activate_app(app_name):
            return False

        ax = get_ax_element(app_name)
        if ax is None:
            return False

        try:
            if not focus_input(ax, max_depth=self._INPUT_MAX_DEPTH, allow_with_value=True):
                raise UnsupportedClientAction("大象未找到聊天输入框，请先选中一个聊天")
        except UnsupportedClientAction:
            raise
        except Exception as e:
            raise UnsupportedClientAction("大象 AX 访问失败，请检查辅助功能权限") from e

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks)
        else:
            return self._send_text_blocks(blocks)

    def _send_text_blocks(self, blocks: list) -> bool:
        """纯文字 blocks：拼接后写剪贴板，paste_and_send。"""
        text = "\n".join(
            b.get("content", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            return False
        original = get_clipboard_text()
        try:
            set_clipboard_text(text)
            paste_and_send(app_name=self._PROCESS_NAME)
        finally:
            set_clipboard_text(original)
        return True

    def _send_as_image(self, blocks: list) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=self._PROCESS_NAME)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"大象图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """
        读取当前大象聊天窗口的消息记录。

        TODO: 大象使用 WebView 渲染，消息以 AXStaticText 散布在 depth=22-25，
              无 AXTable 结构，需专门实现基于 AXStaticText 的解析器。
              当前版本返回空列表，不影响发送功能。
        """
        return []
