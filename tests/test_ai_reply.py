import subprocess
import unittest
from unittest.mock import patch

from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
    build_reply_prompt,
    resolve_ai_command,
    generate_reply,
)


class BuildReplyPromptTests(unittest.TestCase):
    def test_includes_recent_messages_and_reply_constraints(self):
        messages = [
            {"time": "10:01", "content": "客户：我这个订单怎么还没发货？"},
            {"time": "10:02", "content": "客服：我帮您查一下。"},
        ]

        prompt = build_reply_prompt(messages)

        self.assertIn("客户：我这个订单怎么还没发货？", prompt)
        self.assertIn("客服：我帮您查一下。", prompt)
        self.assertIn("只输出", prompt)
        self.assertIn("中文回复", prompt)

    def test_limits_messages_to_max_messages(self):
        messages = [{"content": f"消息{i}", "time": None} for i in range(25)]

        prompt = build_reply_prompt(messages, max_messages=3)

        self.assertNotIn("消息21", prompt)
        self.assertIn("消息22", prompt)
        self.assertIn("消息23", prompt)
        self.assertIn("消息24", prompt)


class GenerateReplyTests(unittest.TestCase):
    @patch("ai_reply.os.path.exists")
    @patch("ai_reply.shutil.which", return_value=None)
    def test_resolve_ai_command_falls_back_to_common_paths(self, _which_mock, exists_mock):
        exists_mock.side_effect = lambda path: path == "/usr/local/bin/mc"

        self.assertEqual(resolve_ai_command(), "/usr/local/bin/mc")

    @patch("ai_reply.subprocess.run")
    def test_generate_reply_returns_stdout(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=0, stdout="您好，我来帮您确认。\n", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5)

        result = generate_reply([{"content": "客户：请帮我看一下"}], config)

        self.assertEqual(result, "您好，我来帮您确认。")
        self.assertEqual(run_mock.call_args.args[0][0], config.command)

    @patch("ai_reply.subprocess.run", side_effect=FileNotFoundError)
    def test_command_not_found(self, _run_mock):
        with self.assertRaises(AICommandNotFoundError):
            generate_reply([{"content": "客户：在吗"}])

    @patch("ai_reply.subprocess.run", side_effect=subprocess.TimeoutExpired(["mc"], timeout=1))
    def test_command_timeout(self, _run_mock):
        with self.assertRaises(AICommandTimeoutError):
            generate_reply([{"content": "客户：在吗"}], AIReplyConfig(timeout=1))

    @patch("ai_reply.subprocess.run")
    def test_nonzero_exit(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=2, stdout="", stderr="auth failed"
        )
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "客户：在吗"}])

    @patch("ai_reply.subprocess.run")
    def test_empty_stdout(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["mc"], returncode=0, stdout="\n", stderr=""
        )
        with self.assertRaises(AIEmptyResponseError) as ctx:
            generate_reply([{"content": "客户：在吗"}], AIReplyConfig(command="mc"))
        self.assertIn("AI 命令没有输出", str(ctx.exception))
        self.assertIn("mc --code -p", str(ctx.exception))


class BuildReplyPromptKBTests(unittest.TestCase):
    def test_no_kb_preamble_when_disabled(self):
        prompt = build_reply_prompt([{"content": "你好"}], kb_enabled=False)
        self.assertNotIn("知识库", prompt)

    def test_kb_preamble_present_when_enabled(self):
        prompt = build_reply_prompt([{"content": "你好"}], kb_enabled=True)
        self.assertIn("知识库", prompt)
        self.assertIn("检索相关文档", prompt)


class GenerateReplyKBTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_kb_enabled_uses_add_dir_and_no_tools_flag(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="回复内容", stderr=""
        )
        config = AIReplyConfig(
            command="mc", timeout=5,
            kb_enabled=True, kb_vault_path="/tmp",
        )
        generate_reply([{"content": "问题"}], config)
        cmd = run_mock.call_args.args[0]
        self.assertIn("--add-dir", cmd)
        self.assertIn("/tmp", cmd)
        self.assertNotIn("--tools", cmd)

    @patch("ai_reply.subprocess.run")
    def test_kb_disabled_uses_tools_empty_arg(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="回复内容", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5, kb_enabled=False)
        generate_reply([{"content": "问题"}], config)
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--add-dir", cmd)
        self.assertIn("--tools", cmd)

    def test_kb_enabled_with_empty_path_raises(self):
        config = AIReplyConfig(command="mc", timeout=5, kb_enabled=True, kb_vault_path="")
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "问题"}], config)

    def test_kb_enabled_with_nonexistent_path_raises(self):
        config = AIReplyConfig(
            command="mc", timeout=5,
            kb_enabled=True, kb_vault_path="/nonexistent/vault/xyz",
        )
        with self.assertRaises(AICommandFailedError):
            generate_reply([{"content": "问题"}], config)


# ── extract_kb_entry ─────────────────────────────────────────────────────────

from ai_reply import extract_kb_entry


class ExtractKBEntryTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_returns_parsed_dict_on_success(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"title": "订单查询", "scenario": "用户询问进度", "tags": ["订单", "客服"]}',
            stderr="",
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "订单查询")
        self.assertEqual(result["tags"], ["订单", "客服"])

    @patch("ai_reply.subprocess.run")
    def test_returns_none_on_invalid_json(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="不是 JSON 内容", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run", side_effect=subprocess.TimeoutExpired(["mc"], timeout=10))
    def test_returns_none_on_timeout(self, _run_mock):
        config = AIReplyConfig(command="mc", timeout=10)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_when_command_not_found(self, _run_mock):
        config = AIReplyConfig(command="nonexistent-cmd", timeout=5)
        result = extract_kb_entry([{"content": "test"}], "reply", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run")
    def test_returns_none_on_nonzero_exit(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "询问进度"}], "您好", config)
        self.assertIsNone(result)

    @patch("ai_reply.subprocess.run")
    def test_command_never_uses_add_dir(self, run_mock):
        """提炼任务不需要访问 vault，确保命令中没有 --add-dir。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"title": "t", "scenario": "s", "tags": []}',
            stderr="",
        )
        config = AIReplyConfig(
            command="mc", timeout=5, kb_enabled=True, kb_vault_path="/tmp"
        )
        extract_kb_entry([{"content": "test"}], "reply", config)
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--add-dir", cmd)
        self.assertIn("--tools", cmd)

    @patch("ai_reply.subprocess.run")
    def test_strips_markdown_code_fence(self, run_mock):
        """mc 有时会把 JSON 包在 ```json ... ``` 里，应能正常解析。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='```json\n{"title": "t", "scenario": "s", "tags": []}\n```',
            stderr="",
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = extract_kb_entry([{"content": "test"}], "reply", config)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "t")


if __name__ == "__main__":
    unittest.main()
