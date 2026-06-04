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


if __name__ == "__main__":
    unittest.main()
