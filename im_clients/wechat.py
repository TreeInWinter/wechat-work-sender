from __future__ import annotations

from .base import IMClientAdapter, TakeoverCapabilities


class WechatAdapter(IMClientAdapter):
    client_id = "wechat"
    display_name = "微信"
    app_names = ("微信", "WeChat")
    bundle_ids = ("com.tencent.xinWeChat", "com.tencent.xinwechat")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=False,
        can_read_chat=False,
        verified=False,
    )

