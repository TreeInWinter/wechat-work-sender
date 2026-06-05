# tests/test_wechat_ocr.py
import unittest


def _obs(text, x_center, y_top, width=0.3, height=0.03):
    """构造 _parse_observations 所需的 obs dict（等价于 _obs_to_dict 的输出）。"""
    return {
        "text": text,
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
        obs.topCandidates_.return_value = [candidate]

        box = MagicMock()
        box.origin.x = 0.1
        box.origin.y = 0.3   # Vision 左下原点
        box.size.width = 0.2
        box.size.height = 0.05
        obs.boundingBox.return_value = box

        result = _obs_to_dict(obs)

        self.assertEqual(result["text"], "你好")
        self.assertAlmostEqual(result["x_center"], 0.2)         # 0.1 + 0.2/2
        self.assertAlmostEqual(result["y_top"], 0.65)           # 1 - (0.3 + 0.05)
        self.assertAlmostEqual(result["width"], 0.2)
        self.assertAlmostEqual(result["height"], 0.05)


if __name__ == "__main__":
    unittest.main()
