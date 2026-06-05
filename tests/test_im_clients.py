import unittest
from unittest.mock import Mock, patch

from im_clients.base import ApplicationInfo, UnsupportedClientAction
from im_clients.registry import choose_default_client, discover_clients


class IMClientDiscoveryTests(unittest.TestCase):
    def test_discovers_supported_clients_from_installed_apps(self):
        apps = [
            ApplicationInfo(name="企业微信", bundle_id="com.tencent.WeWorkMac", path="/Applications/企业微信.app"),
            ApplicationInfo(name="微信", bundle_id="com.tencent.xinWeChat", path="/Applications/微信.app"),
            ApplicationInfo(name="大象", bundle_id="com.sankuai.daxiang", path="/Applications/大象.app"),
        ]

        clients = discover_clients(apps)

        by_id = {client.client_id: client for client in clients}
        self.assertTrue(by_id["wechat_work"].installed)
        self.assertTrue(by_id["wechat"].installed)
        self.assertTrue(by_id["daxiang"].installed)
        self.assertTrue(by_id["wechat_work"].capabilities.can_send)
        self.assertTrue(by_id["wechat"].capabilities.can_send)
        self.assertTrue(by_id["daxiang"].capabilities.can_send)
        # 微信 OCR 实现后 can_read_chat=True
        self.assertTrue(by_id["wechat"].capabilities.can_read_chat)
        self.assertTrue(by_id["daxiang"].capabilities.can_read_chat)

    def test_marks_running_state_independently_from_installed_state(self):
        apps = [
            ApplicationInfo(name="微信", bundle_id="com.tencent.xinWeChat", running=True, pid=1234),
        ]

        clients = discover_clients(apps)

        by_id = {client.client_id: client for client in clients}
        self.assertFalse(by_id["wechat_work"].installed)
        self.assertFalse(by_id["wechat_work"].running)
        self.assertTrue(by_id["wechat"].installed)
        self.assertTrue(by_id["wechat"].running)

    def test_default_selection_prefers_enterprise_wechat_when_installed(self):
        clients = discover_clients(
            [
                ApplicationInfo(name="微信", bundle_id="com.tencent.xinWeChat", path="/Applications/微信.app"),
                ApplicationInfo(name="企业微信", bundle_id="com.tencent.WeWorkMac", path="/Applications/企业微信.app"),
            ]
        )

        selected = choose_default_client(clients)

        self.assertEqual(selected.client_id, "wechat_work")

    def test_default_selection_uses_first_installed_client_when_enterprise_wechat_missing(self):
        clients = discover_clients(
            [
                ApplicationInfo(name="大象", bundle_id="com.sankuai.daxiang", path="/Applications/大象.app"),
            ]
        )

        selected = choose_default_client(clients)

        self.assertEqual(selected.client_id, "daxiang")


class IMClientAdapterTests(unittest.TestCase):
    def test_daxiang_discovered_by_real_bundle_id(self):
        """大象真实 bundle ID cn.neixin.pc 能被正确识别（真机探测 2026-06-05）。"""
        clients = discover_clients(
            [
                ApplicationInfo(name="大象", bundle_id="cn.neixin.pc", running=True, pid=797),
            ]
        )
        daxiang = next(client for client in clients if client.client_id == "daxiang")
        self.assertTrue(daxiang.installed)
        self.assertTrue(daxiang.running)

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.focus_input", return_value=True)
    @patch("im_clients.daxiang.get_clipboard_text", return_value="")
    @patch("im_clients.daxiang.paste_and_send")
    @patch("im_clients.daxiang.set_clipboard_text")
    def test_daxiang_focus_input_called_with_deep_max_depth(
        self, set_clip, paste_mock, get_clip, focus_mock, ax_el, running, activate
    ):
        """大象输入框在 depth=24，focus_input 必须用 max_depth=26, allow_with_value=True。"""
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        adapter.send_blocks([{"type": "text", "content": "hello"}])
        focus_mock.assert_called_once_with(
            ax_el.return_value, max_depth=26, allow_with_value=True
        )

    @patch("im_clients.wechat_work.sender")
    def test_enterprise_wechat_adapter_delegates_to_existing_sender(self, sender_mock):
        sender_mock.is_wx_running.return_value = True
        sender_mock.read_chat_messages.return_value = [{"content": "hi", "time": None}]
        sender_mock.send_blocks.return_value = True
        sender_mock.send_blocks_single.return_value = True
        clients = discover_clients(
            [
                ApplicationInfo(name="企业微信", bundle_id="com.tencent.WeWorkMac", running=True, pid=5678),
            ]
        )
        adapter = next(client.adapter for client in clients if client.client_id == "wechat_work")

        self.assertTrue(adapter.is_running())
        self.assertEqual(adapter.read_chat_messages(max_messages=5), [{"content": "hi", "time": None}])
        self.assertTrue(adapter.send_blocks([{"type": "text", "content": "hello"}]))
        self.assertTrue(adapter.send_blocks([{"type": "image", "path": "/tmp/a.png"}]))

        sender_mock.read_chat_messages.assert_called_once_with(max_messages=5)
        sender_mock.send_blocks.assert_called_once_with([{"type": "text", "content": "hello"}])
        sender_mock.send_blocks_single.assert_called_once_with([{"type": "image", "path": "/tmp/a.png"}])

    def test_generic_adapter_uses_running_app_for_activation_and_bounds(self):
        from im_clients.base import IMClientAdapter
        adapter = IMClientAdapter()
        adapter.app_names = ("TestApp",)

        running_app = Mock()
        running_app.activateWithOptions_.return_value = None
        adapter.set_runtime_app_provider(lambda: running_app)
        adapter.set_window_bounds_provider(lambda: (1, 2, 3, 4))

        self.assertTrue(adapter.activate())
        self.assertEqual(adapter.window_bounds(), (1, 2, 3, 4))
        running_app.activateWithOptions_.assert_called_once()


class WechatAdapterSendTests(unittest.TestCase):
    """
    微信 adapter 测试。

    微信 macOS 用 Qt 渲染，AX 树只有 6 个节点，无法用 AX API 找到输入框。
    send_blocks 改用坐标点击（_click_input_area）定位输入框。
    read_chat_messages 通过 Vision OCR 截图识别，委托 wechat_ocr.read_chat_messages()。
    """

    @patch("im_clients.wechat.is_app_running", return_value=False)
    def test_send_blocks_returns_false_when_not_running(self, _):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "hello"}])
        self.assertFalse(result)

    @patch("im_clients.wechat.activate_app", return_value=True)
    @patch("im_clients.wechat.is_app_running", return_value=True)
    @patch("im_clients.wechat.get_clipboard_text", return_value="")
    @patch("im_clients.wechat.paste_and_send")
    @patch("im_clients.wechat.set_clipboard_text")
    def test_send_text_calls_clipboard_and_paste(
        self, set_clip, paste_mock, get_clip, running, activate
    ):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        # mock _click_input_area 返回 True（绕过真实 AX/鼠标调用）
        adapter._click_input_area = lambda: True
        result = adapter.send_blocks([{"type": "text", "content": "你好"}])
        self.assertTrue(result)
        set_clip.assert_any_call("你好")
        paste_mock.assert_called_once()

    @patch("im_clients.wechat.activate_app", return_value=True)
    @patch("im_clients.wechat.is_app_running", return_value=True)
    def test_send_raises_when_no_chat_window(self, running, activate):
        from im_clients.base import UnsupportedClientAction
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        # _click_input_area 返回 False 模拟没有聊天窗口
        adapter._click_input_area = lambda: False
        with self.assertRaises(UnsupportedClientAction):
            adapter.send_blocks([{"type": "text", "content": "你好"}])

    @patch("im_clients.wechat_ocr.read_chat_messages", return_value=[])
    def test_read_chat_returns_empty_when_no_window(self, mock_ocr):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        adapter._get_window_bounds = lambda: None  # 无窗口
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])

    @patch("im_clients.wechat_ocr.read_chat_messages")
    def test_read_chat_delegates_to_ocr_with_window_bounds(self, mock_ocr):
        from im_clients.wechat import WechatAdapter
        mock_ocr.return_value = [{"sender": "对方", "content": "你好", "time": None}]
        adapter = WechatAdapter()
        adapter._get_window_bounds = lambda: (100, 200, 800, 600)
        result = adapter.read_chat_messages(max_messages=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "你好")
        mock_ocr.assert_called_once_with((100, 200, 800, 600), max_messages=5)


class DaxiangAdapterSendTests(unittest.TestCase):
    @patch("im_clients.daxiang.is_app_running", return_value=False)
    def test_send_blocks_returns_false_when_not_running(self, _):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "hello"}])
        self.assertFalse(result)

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.focus_input", return_value=True)
    @patch("im_clients.daxiang.get_clipboard_text", return_value="")
    @patch("im_clients.daxiang.paste_and_send")
    @patch("im_clients.daxiang.set_clipboard_text")
    def test_send_text_calls_clipboard_and_paste(
        self, set_clip, paste_mock, get_clip, focus, ax_el, running, activate
    ):
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        result = adapter.send_blocks([{"type": "text", "content": "你好"}])
        self.assertTrue(result)
        set_clip.assert_any_call("你好")
        paste_mock.assert_called_once()

    @patch("im_clients.daxiang.activate_app", return_value=True)
    @patch("im_clients.daxiang.is_app_running", return_value=True)
    @patch("im_clients.daxiang.get_ax_element")
    @patch("im_clients.daxiang.focus_input", return_value=False)
    def test_send_raises_when_no_chat_window(self, focus, ax_el, running, activate):
        from im_clients.base import UnsupportedClientAction
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        with self.assertRaises(UnsupportedClientAction):
            adapter.send_blocks([{"type": "text", "content": "你好"}])

    def test_read_chat_returns_empty(self):
        """大象消息读取尚未实现（WebView 无 AXTable），始终返回 []。"""
        from im_clients.daxiang import DaxiangAdapter
        adapter = DaxiangAdapter()
        self.assertEqual(adapter.read_chat_messages(), [])
        self.assertEqual(adapter.read_chat_messages(max_messages=100), [])


if __name__ == "__main__":
    unittest.main()
