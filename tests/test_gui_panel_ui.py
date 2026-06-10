"""gui_panel 纯逻辑单元测试：DraftHistory / make_source_caption / filter_phrases。

GUI 装配（CustomTkinter 布局）不在此测试，走启动冒烟验证。
"""
import unittest
import sys
import types


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
