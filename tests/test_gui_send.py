import unittest
import sys
import types
from unittest.mock import patch


def _install_gui_panel_import_stubs():
    ctk = types.ModuleType("customtkinter")

    class DummyWidget:
        pass

    ctk.CTkToplevel = DummyWidget
    ctk.CTkFrame = DummyWidget
    ctk.__getattr__ = lambda _name: DummyWidget
    ctk.set_appearance_mode = lambda *_args, **_kwargs: None
    ctk.set_default_color_theme = lambda *_args, **_kwargs: None
    sys.modules.setdefault("customtkinter", ctk)

    appkit = types.ModuleType("AppKit")
    appkit.NSWorkspace = object
    sys.modules.setdefault("AppKit", appkit)

    app_services = types.ModuleType("ApplicationServices")
    for name in (
        "AXUIElementCreateApplication",
        "AXUIElementCopyAttributeValue",
        "AXValueGetValue",
        "AXIsProcessTrusted",
    ):
        setattr(app_services, name, lambda *_args, **_kwargs: None)
    for name in (
        "kAXWindowsAttribute",
        "kAXPositionAttribute",
        "kAXSizeAttribute",
        "kAXValueCGPointType",
        "kAXValueCGSizeType",
    ):
        setattr(app_services, name, name)
    sys.modules.setdefault("ApplicationServices", app_services)

    sender = types.ModuleType("sender")
    sender.send_blocks = lambda *_args, **_kwargs: None
    sender.send_blocks_single = lambda *_args, **_kwargs: None
    sender.is_wx_running = lambda: False
    sender.read_chat_messages = lambda max_messages=30: []

    class NoChatWindowError(Exception):
        pass

    sender.NoChatWindowError = NoChatWindowError
    sys.modules.setdefault("sender", sender)


_install_gui_panel_import_stubs()
import gui_panel


class PrepareDirectSendBlocksTests(unittest.TestCase):
    @patch.dict(
        gui_panel.SYSTEM_VARIABLES,
        {
            "日期": lambda: "2026-06-04",
            "时间": lambda: "10:30",
            "星期": lambda: "四",
        },
    )
    def test_renders_system_variables_without_user_preview(self):
        blocks = [{"type": "text", "content": "今天是{{日期}} {{星期}} {{时间}}"}]

        rendered = gui_panel.prepare_direct_send_blocks(blocks)

        self.assertEqual(
            rendered,
            [{"type": "text", "content": "今天是2026-06-04 四 10:30"}],
        )

    def test_keeps_unfilled_custom_variables(self):
        blocks = [{"type": "text", "content": "您好 {{客户名}}"}]

        rendered = gui_panel.prepare_direct_send_blocks(blocks)

        self.assertEqual(rendered, [{"type": "text", "content": "您好 {{客户名}}"}])


if __name__ == "__main__":
    unittest.main()
