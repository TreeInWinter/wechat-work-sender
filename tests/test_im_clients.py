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
        self.assertFalse(by_id["wechat"].capabilities.can_send)
        self.assertFalse(by_id["daxiang"].capabilities.can_read_chat)

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
    def test_unverified_adapter_blocks_send(self):
        clients = discover_clients(
            [
                ApplicationInfo(name="微信", bundle_id="com.tencent.xinWeChat", running=True, pid=1234),
            ]
        )
        wechat = next(client for client in clients if client.client_id == "wechat")

        with self.assertRaises(UnsupportedClientAction):
            wechat.adapter.send_blocks([{"type": "text", "content": "hello"}])

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
        running_app = Mock()
        running_app.activateWithOptions_.return_value = None
        adapter = next(
            client.adapter
            for client in discover_clients(
                [ApplicationInfo(name="微信", bundle_id="com.tencent.xinWeChat", running=True, pid=1234)]
            )
            if client.client_id == "wechat"
        )
        adapter.set_runtime_app_provider(lambda: running_app)
        adapter.set_window_bounds_provider(lambda: (1, 2, 3, 4))

        self.assertTrue(adapter.activate())
        self.assertEqual(adapter.window_bounds(), (1, 2, 3, 4))
        running_app.activateWithOptions_.assert_called_once()


if __name__ == "__main__":
    unittest.main()
