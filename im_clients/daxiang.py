from __future__ import annotations

from .base import IMClientAdapter, TakeoverCapabilities


class DaxiangAdapter(IMClientAdapter):
    client_id = "daxiang"
    display_name = "大象"
    app_names = ("大象", "Daxiang", "DaXiang")
    bundle_ids = ("com.sankuai.daxiang", "com.meituan.daxiang")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=False,
        can_read_chat=False,
        verified=False,
    )

