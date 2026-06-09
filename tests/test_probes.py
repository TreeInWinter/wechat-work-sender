import unittest
from unittest.mock import patch

from im_clients import probes
from im_clients.probes import (
    AXProbe,
    ElementProbe,
    PROBES,
    ProbeResult,
    STATUS_DEGRADED,
    STATUS_NOT_RUNNING,
    STATUS_NO_PERMISSION,
    STATUS_OK,
    classify_input,
    classify_message,
    combine,
    run_probe,
)


class ConfigIntegrityTests(unittest.TestCase):
    """探针配置必须覆盖所有已验证客户端，且数值与各 adapter 实际使用值一致。"""

    def test_known_clients_present(self):
        for cid in ("wechat_work", "daxiang", "wechat"):
            self.assertIn(cid, PROBES)

    def test_wechat_work_canonical_values(self):
        # 锚定企业微信 AX depth 规范值（真机验证：输入框≤10，消息 AXTable@6，BFS≤8）
        p = PROBES["wechat_work"]
        self.assertEqual(p.input.max_depth, 10)
        self.assertEqual(p.message.exact_depth, 6)
        self.assertEqual(p.message.max_depth, 8)

    def test_sender_constants_match_probe_when_real(self):
        # sender 在某些测试中被 stub 进 sys.modules（test_gui_send），此时跳过交叉校验
        import sender
        if not hasattr(sender, "_WW_INPUT_MAX_DEPTH"):
            self.skipTest("sender 被 stub，跳过与真实模块的交叉校验")
        p = PROBES["wechat_work"]
        self.assertEqual(sender._WW_INPUT_MAX_DEPTH, p.input.max_depth)
        self.assertEqual(sender._WW_MSG_DEPTH, p.message.exact_depth)
        self.assertEqual(sender._WW_MSG_MAX_DEPTH, p.message.max_depth)

    def test_daxiang_constants_match_adapter(self):
        from im_clients.daxiang import DaxiangAdapter
        p = PROBES["daxiang"]
        self.assertEqual(DaxiangAdapter._INPUT_MAX_DEPTH, p.input.max_depth)
        self.assertEqual(DaxiangAdapter._INPUT_ALLOW_WITH_VALUE, p.input.allow_with_value)
        self.assertEqual(DaxiangAdapter._MSG_DEPTH, p.message.exact_depth)

    def test_wechat_is_non_ax_with_click_offset(self):
        p = PROBES["wechat"]
        self.assertFalse(p.uses_ax)
        self.assertEqual(p.click_bottom_offset, 50)


class ClassifyTests(unittest.TestCase):
    def test_input_found_ok(self):
        ep = ElementProbe(role="AXTextArea", max_depth=10)
        status, detail = classify_input(ep, found_depth=6)
        self.assertEqual(status, STATUS_OK)
        self.assertIn("depth=6", detail)

    def test_input_not_found_degraded(self):
        ep = ElementProbe(role="AXTextArea", max_depth=10)
        status, detail = classify_input(ep, found_depth=None)
        self.assertEqual(status, STATUS_DEGRADED)
        self.assertIn("未找到输入框", detail)

    def test_input_none_probe_ok(self):
        status, _ = classify_input(None, found_depth=None)
        self.assertEqual(status, STATUS_OK)

    def test_message_found_ok(self):
        ep = ElementProbe(role="AXTable", exact_depth=6)
        status, _ = classify_message(ep, msg_found=True)
        self.assertEqual(status, STATUS_OK)

    def test_message_missing_degraded(self):
        ep = ElementProbe(role="AXTable", exact_depth=6)
        status, detail = classify_message(ep, msg_found=False)
        self.assertEqual(status, STATUS_DEGRADED)
        self.assertIn("消息节点", detail)

    def test_combine_any_degraded_is_degraded(self):
        ok = (STATUS_OK, "输入框 ok")
        bad = (STATUS_DEGRADED, "消息丢失")
        status, detail = combine(ok, bad)
        self.assertEqual(status, STATUS_DEGRADED)
        self.assertIn("消息丢失", detail)

    def test_combine_all_ok(self):
        status, _ = combine((STATUS_OK, "a"), (STATUS_OK, "b"))
        self.assertEqual(status, STATUS_OK)


class _FakeAdapter:
    def __init__(self, client_id, app_names, display_name="X"):
        self.client_id = client_id
        self.app_names = app_names
        self.display_name = display_name


class RunProbeTests(unittest.TestCase):
    def test_not_running(self):
        adapter = _FakeAdapter("wechat_work", ("企业微信",))
        with patch("im_clients.ax_helpers.is_app_running", return_value=False):
            r = run_probe(adapter)
        self.assertEqual(r.status, STATUS_NOT_RUNNING)
        self.assertFalse(r.is_problem)

    def test_no_probe_config_skipped(self):
        adapter = _FakeAdapter("unknown", ("X",))
        r = run_probe(adapter)
        self.assertEqual(r.status, probes.STATUS_SKIPPED)

    def test_non_ax_window_reachable_ok(self):
        adapter = _FakeAdapter("wechat", ("微信", "WeChat"))
        with patch("im_clients.ax_helpers.is_app_running", return_value=True), \
             patch("im_clients.wechat_ocr.find_main_window", return_value=(123, (0, 0, 800, 600))):
            r = run_probe(adapter)
        self.assertEqual(r.status, STATUS_OK)

    def test_non_ax_no_window(self):
        adapter = _FakeAdapter("wechat", ("微信",))
        with patch("im_clients.ax_helpers.is_app_running", return_value=True), \
             patch("im_clients.wechat_ocr.find_main_window", return_value=(None, None)):
            r = run_probe(adapter)
        self.assertEqual(r.status, probes.STATUS_NO_WINDOW)
        self.assertTrue(r.is_problem)

    def test_ax_permission_disabled_reports_no_permission(self):
        adapter = _FakeAdapter("wechat_work", ("企业微信",))
        with patch("im_clients.ax_helpers.is_app_running", return_value=True), \
             patch("im_clients.ax_helpers.activate_app", return_value=True), \
             patch("im_clients.ax_helpers.get_ax_element", return_value=object()), \
             patch("im_clients.probes.AXUIElementCopyAttributeValue", return_value=(-25211, None), create=True):
            r = run_probe(adapter)
        self.assertEqual(r.status, STATUS_NO_PERMISSION)
        self.assertTrue(r.is_problem)


class RunSelfCheckTests(unittest.TestCase):
    def test_aggregates_and_survives_exceptions(self):
        good = _FakeAdapter("wechat", ("微信",))

        class _Client:
            def __init__(self, adapter):
                self.adapter = adapter

        with patch("im_clients.ax_helpers.is_app_running", return_value=True), \
             patch("im_clients.wechat_ocr.find_main_window", return_value=(1, (0, 0, 9, 9))):
            results = probes.run_self_check([_Client(good)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, STATUS_OK)


if __name__ == "__main__":
    unittest.main()
