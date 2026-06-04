from __future__ import annotations

from .base import IMClientAdapter, TakeoverCapabilities
import sender


class WechatWorkAdapter(IMClientAdapter):
    client_id = "wechat_work"
    display_name = "企业微信"
    app_names = ("企业微信", "WeCom", "WeChat Work")
    bundle_ids = ("com.tencent.WeWorkMac", "com.tencent.WeWork")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=True,
    )

    def is_running(self) -> bool:
        return sender.is_wx_running()

    def activate(self) -> bool:
        return sender.activate_wx()

    def window_bounds(self) -> tuple[int, int, int, int] | None:
        return super().window_bounds()

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        return sender.read_chat_messages(max_messages=max_messages)

    def send_blocks(self, blocks: list) -> bool:
        if any(block.get("type") == "image" for block in blocks if isinstance(block, dict)):
            return sender.send_blocks_single(blocks)
        return sender.send_blocks(blocks)
