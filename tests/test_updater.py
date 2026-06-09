import json
import unittest
from unittest.mock import patch

import updater
from updater import (
    Appcast,
    UpdaterError,
    UpdateCheckResult,
    check_for_update,
    is_newer,
    parse_appcast,
    parse_version,
)


class ParseVersionTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_version("1.3.0.0"), (1, 3, 0, 0))

    def test_strips_v_prefix(self):
        self.assertEqual(parse_version("v1.4.2"), (1, 4, 2))
        self.assertEqual(parse_version("V2.0"), (2, 0))

    def test_non_numeric_segment(self):
        # "1rc2" → 取前缀数字 1；纯非数字段 → 0
        self.assertEqual(parse_version("1.4.1rc2"), (1, 4, 1))
        self.assertEqual(parse_version("1.x.3"), (1, 0, 3))

    def test_empty(self):
        self.assertEqual(parse_version(""), (0,))
        self.assertEqual(parse_version(None), (0,))


class IsNewerTests(unittest.TestCase):
    def test_strictly_newer(self):
        self.assertTrue(is_newer("1.4.0.0", "1.3.0.0"))
        self.assertTrue(is_newer("1.3.0.1", "1.3.0.0"))
        self.assertTrue(is_newer("2.0", "1.9.9.9"))

    def test_equal_not_newer(self):
        self.assertFalse(is_newer("1.3.0.0", "1.3.0.0"))

    def test_older_not_newer(self):
        self.assertFalse(is_newer("1.2.9.9", "1.3.0.0"))

    def test_different_segment_widths(self):
        # 补零对齐：1.3 == 1.3.0.0
        self.assertFalse(is_newer("1.3", "1.3.0.0"))
        self.assertTrue(is_newer("1.3.0.1", "1.3"))


class ParseAppcastTests(unittest.TestCase):
    def test_full(self):
        ac = parse_appcast({
            "version": "1.4.0.0",
            "download_url": "https://x/app.dmg",
            "notes": "更新说明",
            "page_url": "https://x/releases/v1.4.0.0",
            "min_os": "10.15",
            "pub_date": "2026-06-10",
        })
        self.assertEqual(ac.version, "1.4.0.0")
        self.assertEqual(ac.download_url, "https://x/app.dmg")
        self.assertEqual(ac.notes, "更新说明")
        # open_url 优先 page_url
        self.assertEqual(ac.open_url, "https://x/releases/v1.4.0.0")

    def test_open_url_falls_back_to_download(self):
        ac = parse_appcast({"version": "1.4", "download_url": "https://x/app.dmg"})
        self.assertEqual(ac.open_url, "https://x/app.dmg")

    def test_missing_version_raises(self):
        with self.assertRaises(UpdaterError):
            parse_appcast({"download_url": "https://x/app.dmg"})

    def test_missing_download_url_raises(self):
        with self.assertRaises(UpdaterError):
            parse_appcast({"version": "1.4"})

    def test_non_dict_raises(self):
        with self.assertRaises(UpdaterError):
            parse_appcast(["not", "a", "dict"])


class CheckForUpdateTests(unittest.TestCase):
    """check_for_update 绝不抛异常，错误收敛进 result.error。"""

    def _fake_appcast(self, version="1.4.0.0"):
        return Appcast(version=version, download_url="https://x/app.dmg", notes="n")

    def test_update_available(self):
        with patch.object(updater, "fetch_appcast", return_value=self._fake_appcast("1.4.0.0")):
            res = check_for_update(current_version="1.3.0.0")
        self.assertIsInstance(res, UpdateCheckResult)
        self.assertTrue(res.has_update)
        self.assertIsNone(res.error)
        self.assertEqual(res.appcast.version, "1.4.0.0")

    def test_no_update_when_equal(self):
        with patch.object(updater, "fetch_appcast", return_value=self._fake_appcast("1.3.0.0")):
            res = check_for_update(current_version="1.3.0.0")
        self.assertFalse(res.has_update)
        self.assertIsNone(res.error)

    def test_no_update_when_remote_older(self):
        with patch.object(updater, "fetch_appcast", return_value=self._fake_appcast("1.2.0.0")):
            res = check_for_update(current_version="1.3.0.0")
        self.assertFalse(res.has_update)

    def test_network_error_captured(self):
        with patch.object(updater, "fetch_appcast", side_effect=UpdaterError("网络请求失败")):
            res = check_for_update(current_version="1.3.0.0")
        self.assertFalse(res.has_update)
        self.assertIsNotNone(res.error)
        self.assertIn("网络", res.error)

    def test_unexpected_exception_captured(self):
        with patch.object(updater, "fetch_appcast", side_effect=RuntimeError("boom")):
            res = check_for_update(current_version="1.3.0.0")
        self.assertFalse(res.has_update)
        self.assertIsNotNone(res.error)


class FetchAppcastTests(unittest.TestCase):
    def test_parses_json_response(self):
        payload = json.dumps({
            "version": "1.5.0.0",
            "download_url": "https://x/app.dmg",
        }).encode("utf-8")

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return payload

        with patch.object(updater.urllib.request, "urlopen", return_value=FakeResp()):
            ac = updater.fetch_appcast("https://x/appcast.json")
        self.assertEqual(ac.version, "1.5.0.0")

    def test_network_failure_raises_updater_error(self):
        with patch.object(updater.urllib.request, "urlopen",
                          side_effect=updater.urllib.error.URLError("down")):
            with self.assertRaises(UpdaterError):
                updater.fetch_appcast("https://x/appcast.json")

    def test_bad_json_raises_updater_error(self):
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"not json{"

        with patch.object(updater.urllib.request, "urlopen", return_value=FakeResp()):
            with self.assertRaises(UpdaterError):
                updater.fetch_appcast("https://x/appcast.json")


class GetCurrentVersionTests(unittest.TestCase):
    def test_env_override(self):
        with patch.dict("os.environ", {"WWS_VERSION": "9.9.9.9"}):
            self.assertEqual(updater.get_current_version(), "9.9.9.9")

    def test_reads_version_file(self):
        # 仓库根有 VERSION 文件，去掉 env 覆盖后应读到真实版本
        import os
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("WWS_VERSION", None)
            ver = updater.get_current_version()
        self.assertRegex(ver, r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
