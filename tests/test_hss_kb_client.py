"""Unit tests for hss_kb_client — cloud KB Q&A wrapper."""
import subprocess
import unittest
from unittest.mock import patch

from hss_kb_client import (
    HssKBQueryError,
    HssKBResult,
    HssKBTimeoutError,
    HssKBUnavailableError,
    is_available,
    query_cloud,
)


class IsAvailableTests(unittest.TestCase):
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_returns_true_when_binary_found(self, _which):
        self.assertTrue(is_available())

    @patch("hss_kb_client.shutil.which", return_value=None)
    def test_returns_false_when_binary_missing(self, _which):
        self.assertFalse(is_available())


class QueryCloudTests(unittest.TestCase):
    @patch("hss_kb_client.shutil.which", return_value=None)
    def test_raises_unavailable_when_cli_missing(self, _which):
        with self.assertRaises(HssKBUnavailableError):
            query_cloud("什么是充电宝借还流程？")

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_returns_result_on_success(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0,
            stdout="充电宝借出流程：扫码→弹宝→计费。\n", stderr=""
        )
        result = query_cloud("充电宝借还流程")
        self.assertIsInstance(result, HssKBResult)
        self.assertEqual(result.answer, "充电宝借出流程：扫码→弹宝→计费。")
        self.assertEqual(result.error, "")

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_raises_query_error_on_nonzero_exit(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=1, stdout="", stderr="connection refused"
        )
        with self.assertRaises(HssKBQueryError) as ctx:
            query_cloud("test")
        self.assertIn("exitcode=1", str(ctx.exception))

    @patch("hss_kb_client.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hss-kb", timeout=5))
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_raises_timeout_error(self, _which, _run):
        with self.assertRaises(HssKBTimeoutError):
            query_cloud("test", timeout=5)

    @patch("hss_kb_client.subprocess.run", side_effect=FileNotFoundError)
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_raises_unavailable_on_file_not_found(self, _which, _run):
        with self.assertRaises(HssKBUnavailableError):
            query_cloud("test")

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_scope_included_in_command(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0, stdout="answer", stderr=""
        )
        query_cloud("test", scope="用户端")
        cmd = run_mock.call_args[0][0]
        self.assertIn("--scope", cmd)
        self.assertIn("用户端", cmd)

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_caller_included_in_command(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0, stdout="answer", stderr=""
        )
        query_cloud("test", caller="wechat-work-sender")
        cmd = run_mock.call_args[0][0]
        self.assertIn("--caller", cmd)
        self.assertIn("wechat-work-sender", cmd)

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_quiet_flag_included_by_default(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0, stdout="answer", stderr=""
        )
        query_cloud("test")
        cmd = run_mock.call_args[0][0]
        self.assertIn("-q", cmd)

    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_quiet_flag_omitted_when_false(self, _which, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0, stdout="answer", stderr=""
        )
        query_cloud("test", quiet=False)
        cmd = run_mock.call_args[0][0]
        self.assertNotIn("-q", cmd)
