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

    im_base = types.ModuleType("im_clients.base")

    class UnsupportedClientAction(Exception):
        pass

    im_base.UnsupportedClientAction = UnsupportedClientAction
    sys.modules.setdefault("im_clients.base", im_base)

    im_registry = types.ModuleType("im_clients.registry")
    im_registry.discover_clients = lambda: []
    im_registry.choose_default_client = lambda clients: clients[0] if clients else None
    sys.modules.setdefault("im_clients.registry", im_registry)


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


class ClientRoutingTests(unittest.TestCase):
    def test_send_blocks_with_client_routes_to_selected_adapter(self):
        calls = []

        class Adapter:
            def send_blocks(self, blocks):
                calls.append(blocks)
                return True

        class Client:
            adapter = Adapter()

        blocks = [{"type": "text", "content": "您好"}]

        result = gui_panel.send_blocks_with_client(Client(), blocks)

        self.assertTrue(result)
        self.assertEqual(calls, [blocks])

    def test_read_chat_with_client_routes_to_selected_adapter(self):
        class Adapter:
            def read_chat_messages(self, max_messages=20):
                return [{"content": f"{max_messages}条", "time": None}]

        class Client:
            adapter = Adapter()

        self.assertEqual(
            gui_panel.read_chat_with_client(Client(), max_messages=8),
            [{"content": "8条", "time": None}],
        )


if __name__ == "__main__":
    unittest.main()
