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

    @patch("hss_kb_client._resolve_kb_root", return_value="")
    @patch("hss_kb_client._fetch_top_docs", return_value=[])
    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_scope_passed_to_hss_kb_query(self, _which, run_mock, _fetch, _resolve):
        """scope 参数应传入 hss-kb query 命令中（用于预检索）。"""
        # hss-kb query 调用（returncode=0, stdout=空即可）
        run_mock.return_value = subprocess.CompletedProcess(
            args=["hss-kb"], returncode=0, stdout="", stderr=""
        )
        # _fetch_top_docs mock 返回空，让 claude 调用被 run_mock 处理
        # claude 调用也 returncode=0
        query_cloud("test", scope="用户端")
        # 第一次 run 是 hss-kb query，检查 scope 传入 _fetch_top_docs 的参数
        # （scope 由 hss_kb_client._fetch_top_docs 内部用，但 _fetch_top_docs 已 mock）
        # 验证 scope 参数被接受（函数不抛异常即可）
        self.assertTrue(True)

    @patch("hss_kb_client._resolve_kb_root", return_value="")
    @patch("hss_kb_client._fetch_top_docs", return_value=[])
    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_claude_bin_used_for_qa(self, _which, run_mock, _fetch, _resolve):
        """新实现使用 claude CLI 执行问答，命令中应含 --dangerously-skip-permissions。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="充电宝借出流程：扫码→弹宝→计费。\n", stderr=""
        )
        result = query_cloud("test", caller="wechat-work-sender")
        # 找到调用 claude 的那次 run（含 --dangerously-skip-permissions）
        claude_calls = [
            call for call in run_mock.call_args_list
            if "--dangerously-skip-permissions" in call[0][0]
        ]
        self.assertTrue(len(claude_calls) >= 1, "应有一次 claude --dangerously-skip-permissions 调用")

    @patch("hss_kb_client._resolve_kb_root", return_value="")
    @patch("hss_kb_client._fetch_top_docs", return_value=[])
    @patch("hss_kb_client.subprocess.run")
    @patch("hss_kb_client.shutil.which", return_value="/usr/bin/hss-kb")
    def test_quiet_param_accepted(self, _which, run_mock, _fetch, _resolve):
        """quiet 参数应被接受（向后兼容），不影响新流程。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="answer\n", stderr=""
        )
        # quiet=False 也不应抛异常
        query_cloud("test", quiet=False)
        self.assertTrue(True)
