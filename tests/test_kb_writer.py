# tests/test_kb_writer.py
import os
import tempfile
import unittest

from kb_writer import KBEntry, save_to_vault


class SaveToVaultTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        self.entry = KBEntry(
            title="订单查询",
            scenario="用户询问订单处理进度",
            tags=["订单", "客服", "SOP"],
            reply="您好，我帮您查一下。",
            source="企业微信",
            date="2026-06-06",
        )

    def test_creates_im_records_directory(self):
        save_to_vault(self.entry, self.vault)
        self.assertTrue(os.path.isdir(os.path.join(self.vault, "IM回复记录")))

    def test_filename_starts_with_date_and_title(self):
        path = save_to_vault(self.entry, self.vault)
        filename = os.path.basename(path)
        self.assertTrue(filename.startswith("2026-06-06-订单查询"))
        self.assertTrue(filename.endswith(".md"))

    def test_file_contains_yaml_frontmatter(self):
        path = save_to_vault(self.entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn('title: "订单查询"', content)
        self.assertIn("date: 2026-06-06", content)
        self.assertIn('tags: ["订单", "客服", "SOP"]', content)
        self.assertIn('source: "企业微信"', content)

    def test_file_contains_body_sections(self):
        path = save_to_vault(self.entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn("## 适用场景", content)
        self.assertIn("用户询问订单处理进度", content)
        self.assertIn("## 标准回复", content)
        self.assertIn("您好，我帮您查一下。", content)

    def test_collision_creates_unique_filename(self):
        path1 = save_to_vault(self.entry, self.vault)
        path2 = save_to_vault(self.entry, self.vault)
        self.assertNotEqual(path1, path2)
        self.assertTrue(os.path.exists(path2))

    def test_returns_absolute_path(self):
        path = save_to_vault(self.entry, self.vault)
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(os.path.exists(path))

    def test_empty_tags_writes_empty_list(self):
        entry = KBEntry(
            title="测试", scenario="测试场景", tags=[],
            reply="回复", source="微信", date="2026-06-06",
        )
        path = save_to_vault(entry, self.vault)
        content = open(path, encoding="utf-8").read()
        self.assertIn("tags: []", content)

    def test_unsafe_filename_chars_stripped(self):
        entry = KBEntry(
            title="订单/查询:测试",
            scenario="s", tags=[], reply="r", source="微信", date="2026-06-06",
        )
        path = save_to_vault(entry, self.vault)
        filename = os.path.basename(path)
        self.assertNotIn("/", filename)
        self.assertNotIn(":", filename)


from unittest.mock import patch


def test_save_to_vault_triggers_update_index_in_background(tmp_path):
    """存入后应异步触发 update_index，不阻塞主线程。"""
    entry = KBEntry(
        title="测试",
        scenario="测试场景",
        tags=["测试"],
        reply="好的",
        source="企业微信",
        date="2026-06-07",
    )
    with patch("kb_writer.update_index") as mock_update:
        save_to_vault(entry, str(tmp_path))
        # 给后台线程一点时间运行
        import time; time.sleep(0.15)
        mock_update.assert_called_once_with(str(tmp_path))
