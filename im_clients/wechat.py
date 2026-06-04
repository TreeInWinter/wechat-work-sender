# im_clients/wechat.py
from __future__ import annotations

import os
import tempfile

from .ax_helpers import (
    activate_app,
    bfs_find_msg_table,
    focus_input,
    get_ax_element,
    get_clipboard_text,
    is_app_running,
    paste_and_send,
    read_messages_from_table,
    set_clipboard_png,
    set_clipboard_text,
)
from .base import IMClientAdapter, TakeoverCapabilities, UnsupportedClientAction


class WechatAdapter(IMClientAdapter):
    """
    微信（个人版）IM 适配器。

    AX 树结构待真机探测（运行 tools/explore_ax.py 微信）后确认。
    发送流程与企业微信一致：剪贴板 Cmd+V + AppleScript Enter。
    verified=False：真机测试通过后改为 True。
    """

    client_id = "wechat"
    display_name = "微信"
    app_names = ("微信", "WeChat")
    bundle_ids = ("com.tencent.xinWeChat", "com.tencent.xinwechat")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=False,  # 真机测试通过后改为 True
    )

    # 进程名（AppleScript tell process 用）
    # 微信实际进程名可能为 "微信" 或 "WeChat"，真机探测后确认
    _PROCESS_NAME = "微信"

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
        发送 blocks 到当前微信聊天窗口。

        纯文字：set_clipboard_text + paste_and_send
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png + paste_and_send
        图文混排：合成单张图片发送（保证只出现一条消息）
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
            if not focus_input(ax):
                raise UnsupportedClientAction("微信未找到聊天输入框，请先选中一个聊天")
        except UnsupportedClientAction:
            raise
        except Exception:
            raise UnsupportedClientAction("微信 AX 访问失败，请检查辅助功能权限")

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks, app_name)
        else:
            return self._send_text_blocks(blocks, app_name)

    def _send_text_blocks(self, blocks: list, app_name: str) -> bool:
        """纯文字 blocks：拼接后写剪贴板，paste_and_send。"""
        text = "\n".join(
            b.get("content", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            return False
        original = get_clipboard_text()
        set_clipboard_text(text)
        paste_and_send(app_name=app_name)
        set_clipboard_text(original)
        return True

    def _send_as_image(self, blocks: list, app_name: str) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        import sender  # 复用企业微信已验证的图片合成逻辑

        tmp = tempfile.mktemp(suffix=".png")
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=app_name)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"微信图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """读取当前微信聊天窗口的消息记录。"""
        app_name = self._get_app_name()
        if app_name is None:
            return []

        ax = get_ax_element(app_name)
        if ax is None:
            return []

        try:
            table = bfs_find_msg_table(ax)
            if table is None:
                return []
            return read_messages_from_table(table, max_messages)
        except Exception:
            return []
