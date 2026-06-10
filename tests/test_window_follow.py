"""window_follow 纯逻辑单元测试：拖拽带判定 / 会话偏移推算。

AppKit/Quartz 集成（NSEvent 监听、CGWindowList）不在此测试，走真机验证。
"""
import unittest

from window_follow import DragSession, in_drag_band


class InDragBandTests(unittest.TestCase):
    BOUNDS = (100, 200, 800, 600)  # x, y, w, h

    def test_inside_band(self):
        self.assertTrue(in_drag_band((500, 230), self.BOUNDS, band=80))

    def test_top_edge_and_band_bottom_inclusive(self):
        self.assertTrue(in_drag_band((100, 200), self.BOUNDS, band=80))
        self.assertTrue(in_drag_band((900, 280), self.BOUNDS, band=80))

    def test_below_band(self):
        self.assertFalse(in_drag_band((500, 281), self.BOUNDS, band=80))

    def test_outside_horizontally(self):
        self.assertFalse(in_drag_band((99, 230), self.BOUNDS, band=80))
        self.assertFalse(in_drag_band((901, 230), self.BOUNDS, band=80))

    def test_band_clamped_to_window_height(self):
        short = (0, 0, 400, 50)  # 窗口比拖拽带还矮
        self.assertTrue(in_drag_band((10, 50), short, band=80))
        self.assertFalse(in_drag_band((10, 51), short, band=80))


class DragSessionTests(unittest.TestCase):
    def test_offset_preserved_during_drag(self):
        # 鼠标按在窗口 (100, 200) 内的 (130, 220)，偏移 = (-30, -20)
        s = DragSession(mouse=(130, 220), bounds=(100, 200, 800, 600))
        self.assertEqual(s.target_bounds_for((130, 220)), (100, 200, 800, 600))
        # 鼠标移动 (+50, +10) → 窗口同步移动，宽高不变
        self.assertEqual(s.target_bounds_for((180, 230)), (150, 210, 800, 600))

    def test_negative_coords_second_screen(self):
        # 第二屏在主屏左侧时 x 为负，推算不应受影响
        s = DragSession(mouse=(-500, 100), bounds=(-600, 80, 400, 300))
        self.assertEqual(s.target_bounds_for((-450, 150)), (-550, 130, 400, 300))


if __name__ == "__main__":
    unittest.main()
