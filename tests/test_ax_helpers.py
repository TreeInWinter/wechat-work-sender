# tests/test_ax_helpers.py
import unittest
from unittest.mock import MagicMock, patch
import subprocess


class GetRunningAppTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.NSWorkspace")
    def test_returns_app_when_found(self, ws_mock):
        app = MagicMock()
        app.localizedName.return_value = "微信"
        ws_mock.sharedWorkspace.return_value.runningApplications.return_value = [app]

        from im_clients.ax_helpers import get_running_app
        result = get_running_app("微信")

        self.assertIs(result, app)

    @patch("im_clients.ax_helpers.NSWorkspace")
    def test_returns_none_when_not_found(self, ws_mock):
        ws_mock.sharedWorkspace.return_value.runningApplications.return_value = []

        from im_clients.ax_helpers import get_running_app
        result = get_running_app("微信")

        self.assertIsNone(result)


class IsAppRunningTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.get_running_app", return_value=MagicMock())
    def test_returns_true_when_app_found(self, _):
        from im_clients.ax_helpers import is_app_running
        self.assertTrue(is_app_running("微信"))

    @patch("im_clients.ax_helpers.get_running_app", return_value=None)
    def test_returns_false_when_app_not_found(self, _):
        from im_clients.ax_helpers import is_app_running
        self.assertFalse(is_app_running("微信"))


class ActivateAppTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.get_running_app")
    def test_activates_app_and_returns_true(self, get_app_mock):
        app = MagicMock()
        get_app_mock.return_value = app

        from im_clients.ax_helpers import activate_app
        result = activate_app("微信")

        self.assertTrue(result)
        app.activateWithOptions_.assert_called_once()

    @patch("im_clients.ax_helpers.get_running_app", return_value=None)
    def test_returns_false_when_not_running(self, _):
        from im_clients.ax_helpers import activate_app
        self.assertFalse(activate_app("微信"))


class SetClipboardTextTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.NSPasteboard")
    def test_writes_string_to_pasteboard(self, pb_mock):
        pb = MagicMock()
        pb_mock.generalPasteboard.return_value = pb

        from im_clients.ax_helpers import set_clipboard_text
        set_clipboard_text("hello")

        pb.clearContents.assert_called_once()
        pb.setString_forType_.assert_called_once()
        args = pb.setString_forType_.call_args.args
        self.assertEqual(args[0], "hello")


class PasteAndSendTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.subprocess.run")
    @patch("im_clients.ax_helpers.CGEventPost")
    @patch("im_clients.ax_helpers.CGEventCreateKeyboardEvent")
    @patch("im_clients.ax_helpers.CGEventSetFlags")
    def test_paste_triggers_cmd_v_and_applescript_enter(
        self, _flags, _create, post_mock, run_mock
    ):
        run_mock.return_value = subprocess.CompletedProcess([], 0)

        from im_clients.ax_helpers import paste_and_send
        paste_and_send(app_name="微信", delay=0)

        # Cmd+V 触发了 CGEventPost（至少 2 次：key down + key up）
        self.assertGreaterEqual(post_mock.call_count, 2)
        # AppleScript Enter 被调用
        run_mock.assert_called_once()
        script_arg = run_mock.call_args.args[0]
        self.assertIn("osascript", script_arg)


class DedupAxValueTests(unittest.TestCase):
    def test_deduplicates_repeated_string(self):
        from im_clients.ax_helpers import _dedup_ax_value
        self.assertEqual(_dedup_ax_value("你好你好"), "你好")

    def test_leaves_non_duplicated_string_unchanged(self):
        from im_clients.ax_helpers import _dedup_ax_value
        self.assertEqual(_dedup_ax_value("你好"), "你好")

    def test_empty_string_unchanged(self):
        from im_clients.ax_helpers import _dedup_ax_value
        self.assertEqual(_dedup_ax_value(""), "")


class BfsFindInputTests(unittest.TestCase):
    def _make_ax_tree(self, roles_and_values):
        """
        构造简单 AX 树：roles_and_values 是 [(role, value), ...] 列表，
        按顺序构造父子链：root -> child[0] -> child[1] -> ...
        返回根节点 mock。
        """
        nodes = []
        for role, val in roles_and_values:
            node = MagicMock()
            node._role = role
            node._val = val
            nodes.append(node)

        def ax_attr(el, attr, _):
            from ApplicationServices import kAXRoleAttribute, kAXValueAttribute, kAXChildrenAttribute
            if attr == kAXRoleAttribute:
                return (None, el._role)
            if attr == kAXValueAttribute:
                return (None, el._val)
            if attr == kAXChildrenAttribute:
                idx = nodes.index(el)
                if idx + 1 < len(nodes):
                    return (None, [nodes[idx + 1]])
                return (None, None)
            return (None, None)

        return nodes[0], ax_attr

    @patch("im_clients.ax_helpers.AXUIElementCopyAttributeValue")
    def test_finds_empty_textarea_as_input(self, ax_mock):
        root, ax_attr = self._make_ax_tree([
            ("AXWindow", None),
            ("AXGroup", None),
            ("AXTextArea", None),  # 候选输入框：value=None
        ])
        ax_mock.side_effect = ax_attr

        from im_clients.ax_helpers import bfs_find_input
        result = bfs_find_input(root)

        self.assertIsNotNone(result)

    @patch("im_clients.ax_helpers.AXUIElementCopyAttributeValue")
    def test_skips_textarea_with_content(self, ax_mock):
        root, ax_attr = self._make_ax_tree([
            ("AXWindow", None),
            ("AXTextArea", "有内容的只读消息"),  # 消息历史，应跳过
        ])
        ax_mock.side_effect = ax_attr

        from im_clients.ax_helpers import bfs_find_input
        result = bfs_find_input(root)

        self.assertIsNone(result)

    @patch("im_clients.ax_helpers.AXUIElementCopyAttributeValue")
    def test_returns_none_when_no_textarea(self, ax_mock):
        root, ax_attr = self._make_ax_tree([
            ("AXWindow", None),
            ("AXGroup", None),
        ])
        ax_mock.side_effect = ax_attr

        from im_clients.ax_helpers import bfs_find_input
        result = bfs_find_input(root)

        self.assertIsNone(result)


class GetAxElementTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.AXUIElementCreateApplication")
    @patch("im_clients.ax_helpers.get_running_app")
    def test_returns_ax_element_when_app_running(self, get_app_mock, ax_create_mock):
        app = MagicMock()
        app.processIdentifier.return_value = 1234
        get_app_mock.return_value = app
        ax_elem = MagicMock()
        ax_create_mock.return_value = ax_elem

        from im_clients.ax_helpers import get_ax_element
        result = get_ax_element("微信")

        self.assertIs(result, ax_elem)
        ax_create_mock.assert_called_once_with(1234)

    @patch("im_clients.ax_helpers.get_running_app", return_value=None)
    def test_returns_none_when_app_not_running(self, _):
        from im_clients.ax_helpers import get_ax_element
        self.assertIsNone(get_ax_element("微信"))


class GetClipboardTextTests(unittest.TestCase):
    @patch("im_clients.ax_helpers.NSPasteboard")
    def test_returns_clipboard_string(self, pb_mock):
        pb = MagicMock()
        pb.stringForType_.return_value = "hello"
        pb_mock.generalPasteboard.return_value = pb

        from im_clients.ax_helpers import get_clipboard_text
        result = get_clipboard_text()

        self.assertEqual(result, "hello")

    @patch("im_clients.ax_helpers.NSPasteboard")
    def test_returns_empty_string_when_no_content(self, pb_mock):
        pb = MagicMock()
        pb.stringForType_.return_value = None
        pb_mock.generalPasteboard.return_value = pb

        from im_clients.ax_helpers import get_clipboard_text
        result = get_clipboard_text()

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
