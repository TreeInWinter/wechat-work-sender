"""gui_panel 纯逻辑单元测试：DraftHistory / make_source_caption / filter_phrases。

GUI 装配（CustomTkinter 布局）不在此测试，走启动冒烟验证。
"""
import unittest
import sys
import types
from datetime import date, datetime, timezone
from unittest.mock import patch


def _install_gui_panel_import_stubs():
    # customtkinter: stub only if not already installed (e.g. headless CI without display).
    ctk = types.ModuleType("customtkinter")

    class DummyWidget:
        pass

    ctk.CTkToplevel = DummyWidget
    ctk.CTkFrame = DummyWidget
    ctk.__getattr__ = lambda _name: DummyWidget
    ctk.set_appearance_mode = lambda *_args, **_kwargs: None
    ctk.set_default_color_theme = lambda *_args, **_kwargs: None
    sys.modules.setdefault("customtkinter", ctk)

    sender = types.ModuleType("sender")
    sender.send_blocks = lambda *_args, **_kwargs: None
    sender.send_blocks_single = lambda *_args, **_kwargs: None
    sender.is_wx_running = lambda: False
    sender.read_chat_messages = lambda max_messages=30: []
    sender.activate_wx = lambda: True
    sender.render_blocks_to_image = lambda *_args, **_kwargs: None

    class NoChatWindowError(Exception):
        pass

    sender.NoChatWindowError = NoChatWindowError
    sys.modules.setdefault("sender", sender)


_install_gui_panel_import_stubs()
import gui_panel


class SnapFilterTests(unittest.TestCase):
    """目标读数可信性：拒单 tick 毛刺 / 消失重现立即可信 / 大位移两 tick 收敛。"""

    A = (230, 185, 960, 640)
    FAR = (800, 600, 960, 640)      # 与 A 差 >300 的真实新位置
    GLITCH = (-5000, 0, 100, 50)    # 单 tick AX 毛刺

    def _filter(self):
        f = gui_panel.SnapFilter()
        self.assertEqual(f.validate(self.A), self.A)  # 首个读数直接可信
        return f

    def test_small_moves_always_trusted(self):
        # 微抖动也返回可信读数——动不动面板由调用方对比实际位置决定
        f = self._filter()
        jitter = (232, 186, 960, 640)
        self.assertEqual(f.validate(jitter), jitter)
        self.assertEqual(f.validate((280, 185, 960, 640)), (280, 185, 960, 640))

    def test_minimize_then_restore_trusted_immediately(self):
        f = self._filter()
        self.assertIsNone(f.validate(None))        # 最小化：窗口消失
        self.assertIsNone(f.validate(None))
        self.assertEqual(f.validate(self.A), self.A)   # 恢复原位：立即可信
        # 消失后恢复到远处也立即可信（不走大跳变确认）
        self.assertIsNone(f.validate(None))
        self.assertEqual(f.validate(self.FAR), self.FAR)

    def test_big_jump_trusted_after_two_consistent_ticks(self):
        # 旧实现的永久丢弃 bug：>300px 跳变每 tick 都被拒，面板从此不跟随
        f = self._filter()
        self.assertIsNone(f.validate(self.FAR))        # 第 1 次：候选，暂不可信
        self.assertEqual(f.validate(self.FAR), self.FAR)  # 第 2 次一致：可信
        self.assertEqual(f.last, self.FAR)

    def test_single_tick_glitch_rejected(self):
        f = self._filter()
        self.assertIsNone(f.validate(self.GLITCH))     # 毛刺：候选
        self.assertEqual(f.validate(self.A), self.A)   # 回到真值：可信
        self.assertIsNone(f.validate(self.GLITCH))     # 不同毛刺不累计
        self.assertEqual(f.validate((280, 185, 960, 640)), (280, 185, 960, 640))

    def test_reset_forces_next_trusted(self):
        f = self._filter()
        f.reset()
        self.assertEqual(f.validate(self.FAR), self.FAR)  # 重新吸附/切目标


class ParseGeometryPosTests(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(gui_panel.parse_geometry_pos("420x600+650+185"), (650, 185))

    def test_negative_coords_second_screen(self):
        self.assertEqual(gui_panel.parse_geometry_pos("420x600+-550+185"), (-550, 185))
        self.assertEqual(gui_panel.parse_geometry_pos("420x600+650+-30"), (650, -30))

    def test_malformed_returns_none(self):
        self.assertIsNone(gui_panel.parse_geometry_pos("garbage"))


class DragFollowCallbackTests(unittest.TestCase):
    """拖拽跟随回调必须是 handler-safe 的：只做纯 Python 赋值。

    在 NSEvent 全局监听 handler 上下文里调 Tk 或动 NSWindow 会触发
    PyEval_RestoreThread fatal（GIL 状态冲突，已踩坑）。这里用裸 stub
    调用未绑定方法，若回调引入任何 Tk/AppKit 依赖会直接 AttributeError。
    """

    def test_on_target_dragged_only_stores_pending_pos(self):
        stub = types.SimpleNamespace(_pending_drag_pos=None)
        gui_panel.WXSenderApp._on_target_dragged(stub, (100, 200, 800, 600))
        self.assertEqual(stub._pending_drag_pos, (900, 200))  # 面板贴右缘

    def test_on_target_drag_end_only_sets_flag(self):
        stub = types.SimpleNamespace(_drag_end_pending=False)
        gui_panel.WXSenderApp._on_target_drag_end(stub)
        self.assertTrue(stub._drag_end_pending)


class DragFollowSafetyTests(unittest.TestCase):
    def test_event_driven_drag_follow_disabled_by_default(self):
        with patch.dict(gui_panel.os.environ, {}, clear=True):
            self.assertFalse(gui_panel.drag_follow_enabled())

    def test_event_driven_drag_follow_can_be_enabled_for_experiments(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(
                    gui_panel.os.environ,
                    {"SIDEKICK_ENABLE_DRAG_FOLLOW": value},
                    clear=True,
                ):
                    self.assertTrue(gui_panel.drag_follow_enabled())


class DraftHistoryTests(unittest.TestCase):
    def test_push_and_undo(self):
        h = gui_panel.DraftHistory()
        h.push("v1")
        h.push("v2")
        self.assertEqual(h.undo(), "v2")
        self.assertEqual(h.undo(), "v1")
        self.assertIsNone(h.undo())

    def test_push_ignores_empty_and_duplicate(self):
        h = gui_panel.DraftHistory()
        h.push("")
        h.push("a")
        h.push("a")
        self.assertEqual(len(h), 1)

    def test_clear(self):
        h = gui_panel.DraftHistory()
        h.push("a")
        h.clear()
        self.assertEqual(len(h), 0)
        self.assertIsNone(h.undo())

    def test_capped_depth(self):
        h = gui_panel.DraftHistory()
        for i in range(30):
            h.push(f"d{i}")
        self.assertEqual(len(h), gui_panel.DraftHistory.MAX_DEPTH)
        self.assertEqual(h.undo(), "d29")


class SourceCaptionTests(unittest.TestCase):
    def test_with_kb(self):
        self.assertEqual(
            gui_panel.make_source_caption(8, True),
            "ⓘ 据 8 条会话 + 知识库生成 · 发送前请确认",
        )

    def test_without_kb(self):
        self.assertEqual(
            gui_panel.make_source_caption(3, False),
            "ⓘ 据 3 条会话生成 · 发送前请确认",
        )

    def test_zero_messages(self):
        self.assertEqual(
            gui_panel.make_source_caption(0, False),
            "ⓘ AI 生成 · 发送前请确认",
        )


class ResourcePathTests(unittest.TestCase):
    def test_app_resource_path_resolves_project_files(self):
        path = gui_panel.app_resource_path("phrases.json")
        self.assertTrue(path.endswith("phrases.json"))
        self.assertTrue(path.startswith(gui_panel.SCRIPT_DIR))

    def test_donation_qr_asset_is_bundled_resource(self):
        path = gui_panel.app_resource_path(gui_panel.DONATION_QR_RELATIVE_PATH)
        self.assertTrue(path.endswith("assets/donation-wechat.jpg"))
        self.assertTrue(gui_panel.os.path.exists(path))


class DonationPromptTests(unittest.TestCase):
    def test_prompts_every_tenth_successful_send(self):
        cases = [
            (0, 1, False),
            (8, 9, False),
            (9, 10, True),
            (10, 11, False),
            (19, 20, True),
        ]
        for current, expected_next, expected_prompt in cases:
            with self.subTest(current=current):
                next_count, should_prompt = gui_panel.next_donation_send_count(current)
                self.assertEqual(next_count, expected_next)
                self.assertEqual(should_prompt, expected_prompt)

    def test_invalid_saved_count_starts_from_zero(self):
        self.assertEqual(gui_panel.next_donation_send_count("bad"), (1, False))
        self.assertEqual(gui_panel.next_donation_send_count(None), (1, False))

    def test_free_supporter_uses_every_tenth_send_prompt_policy(self):
        updates, should_prompt = gui_panel.next_donation_prompt_state(
            {gui_panel.DONATION_SEND_COUNT_KEY: 9},
            now=date(2026, 6, 12),
        )

        self.assertEqual(updates[gui_panel.DONATION_SEND_COUNT_KEY], 10)
        self.assertTrue(should_prompt)

    def test_unexpired_payment_entitlement_suppresses_prompt(self):
        updates, should_prompt = gui_panel.next_donation_prompt_state(
            {
                gui_panel.DONATION_SEND_COUNT_KEY: 9,
                gui_panel.PAYMENT_ENTITLEMENT_CACHE_KEY: {
                    "tier": "supporter",
                    "support_until": "2026-07-13T00:00:00+08:00",
                },
            },
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )

        self.assertEqual(updates[gui_panel.DONATION_SEND_COUNT_KEY], 10)
        self.assertFalse(should_prompt)

    def test_expired_payment_entitlement_uses_free_prompt_policy(self):
        updates, should_prompt = gui_panel.next_donation_prompt_state(
            {
                gui_panel.DONATION_SEND_COUNT_KEY: 9,
                gui_panel.PAYMENT_ENTITLEMENT_CACHE_KEY: {
                    "tier": "supporter",
                    "support_until": "2026-06-01T00:00:00+08:00",
                },
            },
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )

        self.assertEqual(updates[gui_panel.DONATION_SEND_COUNT_KEY], 10)
        self.assertTrue(should_prompt)

    def test_legacy_donation_profile_no_longer_suppresses_prompt(self):
        updates, should_prompt = gui_panel.next_donation_prompt_state(
            {
                gui_panel.DONATION_SEND_COUNT_KEY: 9,
                gui_panel.DONATION_PROFILE_KEY: {
                    "tier": "at_least_10",
                    "channel": "wechat",
                    "registered_at": "2026-06-12",
                    "last_donation_at": "2026-06-12",
                    "last_prompted_at": "2026-06-12",
                    "prompt_interval_months": 1,
                },
            },
            now=date(2026, 6, 13),
        )

        self.assertEqual(updates[gui_panel.DONATION_SEND_COUNT_KEY], 10)
        self.assertTrue(should_prompt)
        self.assertNotIn(gui_panel.DONATION_PROFILE_KEY, updates)

    def test_local_support_registration_helper_is_removed(self):
        self.assertFalse(hasattr(gui_panel, "donation_support_registration_update"))
        self.assertFalse(hasattr(gui_panel.WXSenderApp, "_save_donation_support"))


class PaymentProviderReadinessTests(unittest.TestCase):
    def test_formats_configured_and_missing_provider_env(self):
        text, color = gui_panel.format_payment_provider_readiness({
            "providers": [
                {"provider": "mock", "configured": True, "missing": []},
                {
                    "provider": "wechat",
                    "configured": False,
                    "missing": ["WECHAT_PAY_MCHID", "WECHAT_PAY_APPID"],
                },
                {
                    "provider": "alipay",
                    "configured": False,
                    "missing": ["ALIPAY_APP_ID"],
                },
            ]
        })

        self.assertEqual(
            text,
            "支付服务连接正常 · Mock 可用；微信支付缺 WECHAT_PAY_MCHID、WECHAT_PAY_APPID；支付宝缺 ALIPAY_APP_ID",
        )
        self.assertEqual(color, gui_panel.DOT_ERR)


class FilterPhrasesTests(unittest.TestCase):
    PHRASES = {
        "问候语": ["您好，我是客服", "早上好"],
        "常用回复": ["好的，请稍等", "您好，已收到"],
    }

    def test_empty_query_returns_current_group(self):
        out = gui_panel.filter_phrases(self.PHRASES, "问候语", "")
        self.assertEqual(out, [("问候语", 0, "您好，我是客服"), ("问候语", 1, "早上好")])

    def test_query_searches_all_groups(self):
        out = gui_panel.filter_phrases(self.PHRASES, "问候语", "您好")
        self.assertEqual(
            out,
            [("问候语", 0, "您好，我是客服"), ("常用回复", 1, "您好，已收到")],
        )

    def test_query_case_insensitive_and_stripped(self):
        phrases = {"A": ["Hello World"]}
        out = gui_panel.filter_phrases(phrases, "A", "  hello ")
        self.assertEqual(out, [("A", 0, "Hello World")])


if __name__ == "__main__":
    unittest.main()
