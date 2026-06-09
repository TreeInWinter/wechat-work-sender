# tests/test_wechat_ocr.py
import unittest
from unittest.mock import patch


def _obs(text, x_center, y_top, width=0.3, height=0.03, confidence=1.0):
    """构造 _parse_observations 所需的 obs dict（等价于 _obs_to_dict 的输出）。"""
    return {
        "text": text,
        "confidence": confidence,
        "x": x_center - width / 2,
        "y_top": y_top,
        "width": width,
        "height": height,
        "x_center": x_center,
    }


class ParseObservationsTests(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        from im_clients.wechat_ocr import _parse_observations
        self.assertEqual(_parse_observations([]), [])

    def test_single_chat_left_right(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("你好", 0.25, 0.1),    # 左侧 → 对方
            _obs("你好呀", 0.75, 0.2),  # 右侧 → 我
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "你好")
        self.assertEqual(result[1]["sender"], "我")
        self.assertEqual(result[1]["content"], "你好呀")

    def test_time_separator_becomes_time_field_not_message(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("上午 10:30", 0.5, 0.05),  # 居中时间戳
            _obs("你好", 0.25, 0.15),
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["time"], "上午 10:30")
        self.assertNotIn("10:30", result[0]["content"])
        self.assertEqual(result[0]["sender"], "对方")

    def test_group_chat_sender_name_linked_to_next_message(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("张三", 0.2, 0.10),    # 昵称（短文本，靠左）
            _obs("明天几点", 0.3, 0.13),  # 消息，左侧，y 接近
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sender"], "张三")
        self.assertEqual(result[0]["content"], "明天几点")

    def test_short_left_text_is_message_when_next_is_right_side(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("好的", 0.25, 0.10),   # 短左侧文本，但下一条是右侧 → 应作为消息
            _obs("收到", 0.75, 0.20),
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "好的")

    def test_multiline_same_side_merged(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("第一行", 0.25, 0.10),
            _obs("第二行", 0.25, 0.12),  # y 差 0.02 < 0.04，同侧 → 合并
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "第一行\n第二行")

    def test_multiline_different_side_not_merged(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("对方消息", 0.25, 0.10),
            _obs("我的回复", 0.75, 0.12),  # 虽然 y 很近但侧不同 → 不合并
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)

    def test_time_field_carried_to_subsequent_messages(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("下午 3:00", 0.5, 0.05),
            _obs("消息A", 0.25, 0.10),
            _obs("消息B", 0.75, 0.20),
        ]
        result = _parse_observations(obs)
        self.assertEqual(result[0]["time"], "下午 3:00")
        self.assertEqual(result[1]["time"], "下午 3:00")


class ObsToDictTests(unittest.TestCase):

    def test_converts_vision_observation_to_dict(self):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import _obs_to_dict

        obs = MagicMock()
        candidate = MagicMock()
        candidate.string.return_value = "你好"
        candidate.confidence.return_value = 0.9
        obs.topCandidates_.return_value = [candidate]

        box = MagicMock()
        box.origin.x = 0.1
        box.origin.y = 0.3   # Vision 左下原点
        box.size.width = 0.2
        box.size.height = 0.05
        obs.boundingBox.return_value = box

        result = _obs_to_dict(obs)

        self.assertEqual(result["text"], "你好")
        self.assertAlmostEqual(result["confidence"], 0.9)
        self.assertAlmostEqual(result["x_center"], 0.2)         # 0.1 + 0.2/2
        self.assertAlmostEqual(result["y_top"], 0.65)           # 1 - (0.3 + 0.05)
        self.assertAlmostEqual(result["width"], 0.2)
        self.assertAlmostEqual(result["height"], 0.05)


class FilterChatAreaTests(unittest.TestCase):
    """验证侧边栏过滤 + 面板内 x 归一化。"""

    def test_drops_left_sidebar(self):
        from im_clients.wechat_ocr import _filter_chat_area
        obs = [_obs("会话名", 0.2, 0.3), _obs("聊天消息", 0.7, 0.3)]
        result = _filter_chat_area(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "聊天消息")

    def test_normalizes_x_into_panel(self):
        from im_clients.wechat_ocr import _filter_chat_area
        # sidebar_max_x=0.40，面板跨度 0.60；x_center=0.70 → (0.70-0.40)/0.60=0.5
        obs = [_obs("居中", 0.70, 0.3)]
        result = _filter_chat_area(obs)
        self.assertAlmostEqual(result[0]["x_center"], 0.5)

    def test_drops_low_confidence(self):
        from im_clients.wechat_ocr import _filter_chat_area
        obs = [_obs("噪声", 0.7, 0.3, confidence=0.1)]
        self.assertEqual(_filter_chat_area(obs), [])

    def test_drops_title_and_input_bars(self):
        from im_clients.wechat_ocr import _filter_chat_area
        obs = [
            _obs("标题栏", 0.7, 0.02),   # y_top < _TOP_Y
            _obs("输入框", 0.7, 0.98),   # y_top > _BOTTOM_Y
            _obs("正常消息", 0.7, 0.4),
        ]
        result = _filter_chat_area(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "正常消息")


class CaptureAndOcrIntegrationTests(unittest.TestCase):
    """验证 read_chat_messages 的整体流程（mock 窗口发现、截图和 OCR）。"""

    @patch("im_clients.wechat_ocr.find_main_window", return_value=(None, None))
    def test_returns_empty_when_no_window(self, _find):
        from im_clients.wechat_ocr import read_chat_messages
        self.assertEqual(read_chat_messages(), [])

    @patch("im_clients.wechat_ocr.find_main_window", return_value=(1, (0, 0, 800, 600)))
    @patch("im_clients.wechat_ocr._capture_window", return_value=None)
    def test_returns_empty_when_capture_fails(self, _capture, _find):
        from im_clients.wechat_ocr import read_chat_messages
        self.assertEqual(read_chat_messages(), [])

    @patch("im_clients.wechat_ocr.find_main_window", return_value=(1, (0, 0, 800, 600)))
    @patch("im_clients.wechat_ocr._capture_window")
    @patch("im_clients.wechat_ocr._run_vision_ocr")
    @patch("im_clients.wechat_ocr._obs_to_dict")
    def test_returns_parsed_messages_from_ocr(self, mock_to_dict, mock_ocr, mock_capture, _find):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import read_chat_messages

        mock_capture.return_value = MagicMock()  # 假装截图成功

        # mock OCR 返回 1 个 observation（MagicMock 的 topCandidates_ 是 truthy）
        fake_obs = MagicMock()
        mock_ocr.return_value = [fake_obs]

        # mock _obs_to_dict 返回一个聊天面板内的左侧消息（x_center > 侧边栏阈值 0.40）
        mock_to_dict.return_value = _obs("你好世界", 0.46, 0.2)

        result = read_chat_messages()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "你好世界")

    @patch("im_clients.wechat_ocr.find_main_window", return_value=(1, (0, 0, 800, 600)))
    @patch("im_clients.wechat_ocr._capture_window")
    @patch("im_clients.wechat_ocr._run_vision_ocr")
    @patch("im_clients.wechat_ocr._obs_to_dict")
    def test_respects_max_messages_limit(self, mock_to_dict, mock_ocr, mock_capture, _find):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import read_chat_messages

        mock_capture.return_value = MagicMock()

        # 构造 5 条聊天面板内的消息（x_center > 0.40，y 在标题/输入框之间且不相邻合并）
        fake_obs_list = [MagicMock() for _ in range(5)]
        mock_ocr.return_value = fake_obs_list
        mock_to_dict.side_effect = [
            _obs(f"消息{i}", 0.46, (i + 1) * 0.1) for i in range(5)
        ]

        result = read_chat_messages(max_messages=3)

        self.assertEqual(len(result), 3)  # 只返回最后 3 条


if __name__ == "__main__":
    unittest.main()
