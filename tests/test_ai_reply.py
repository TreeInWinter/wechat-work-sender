import os
import subprocess
import unittest
from unittest.mock import patch
import pytest

from ai_reply import (
    AICommandFailedError,
    AICommandNotFoundError,
    AICommandTimeoutError,
    AIEmptyResponseError,
    AIReplyConfig,
    REFINE_PRESETS,
    build_reply_prompt,
    build_refine_prompt,
    resolve_ai_command,
    generate_reply,
    refine_reply,
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
    @patch("ai_reply.update_index")
    @patch("ai_reply.search", return_value=[])   # 空结果 → 降级 --add-dir
    @patch("ai_reply.subprocess.run")
    def test_kb_enabled_uses_add_dir_and_no_tools_flag(self, run_mock, _mock_search, _mock_update):
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


class BuildRefinePromptTests(unittest.TestCase):
    def test_includes_draft_instruction_and_context(self):
        messages = [{"time": "10:01", "content": "客户：发票什么时候开？"}]
        prompt = build_refine_prompt(messages, "稍后给您开具。", "更正式", max_messages=20)
        self.assertIn("稍后给您开具。", prompt)        # 当前草稿
        self.assertIn("更正式", prompt)                # 修改要求
        self.assertIn("客户：发票什么时候开？", prompt)  # 聊天上下文
        self.assertIn("只输出", prompt)                # 约束

    def test_works_without_context(self):
        prompt = build_refine_prompt([], "你好", "更简短")
        self.assertIn("你好", prompt)
        self.assertIn("更简短", prompt)
        # 无聊天记录时不应包含上下文标题
        self.assertNotIn("最近聊天记录", prompt)


class RefineReplyTests(unittest.TestCase):
    @patch("ai_reply.subprocess.run")
    def test_returns_refined_stdout(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="您好，稍后将为您开具发票。", stderr=""
        )
        config = AIReplyConfig(command="mc", timeout=5)
        result = refine_reply([{"content": "发票"}], "稍后开", "更正式", config)
        self.assertEqual(result, "您好，稍后将为您开具发票。")

    def test_empty_draft_raises(self):
        config = AIReplyConfig(command="mc", timeout=5)
        with pytest.raises(AIEmptyResponseError):
            refine_reply([{"content": "x"}], "   ", "更正式", config)

    def test_empty_instruction_raises(self):
        config = AIReplyConfig(command="mc", timeout=5)
        with pytest.raises(AICommandFailedError):
            refine_reply([{"content": "x"}], "草稿", "  ", config)

    @patch("ai_reply.subprocess.run", side_effect=subprocess.TimeoutExpired(["mc"], timeout=1))
    def test_timeout_raises(self, _run_mock):
        config = AIReplyConfig(command="mc", timeout=1)
        with pytest.raises(AICommandTimeoutError):
            refine_reply([{"content": "x"}], "草稿", "更简短", config)

    @patch("ai_reply.subprocess.run", side_effect=FileNotFoundError)
    def test_command_not_found_raises(self, _run_mock):
        config = AIReplyConfig(command="nope", timeout=5)
        with pytest.raises(AICommandNotFoundError):
            refine_reply([{"content": "x"}], "草稿", "更简短", config)

    @patch("ai_reply.subprocess.run")
    def test_refine_never_reads_kb(self, run_mock):
        """改写应走纯文本模式（config.args），不注入 --add-dir/--add-file。"""
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="改写结果", stderr=""
        )
        config = AIReplyConfig(
            command="mc", timeout=5, kb_mode="local", kb_vault_path="/tmp"
        )
        refine_reply([{"content": "x"}], "草稿", "更正式", config)
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--add-dir", cmd)
        self.assertNotIn("--add-file", cmd)
        self.assertIn("--tools", cmd)  # 来自默认 config.args

    def test_presets_are_nonempty_strings(self):
        for key in ("formal", "shorter", "rephrase"):
            self.assertIn(key, REFINE_PRESETS)
            self.assertTrue(REFINE_PRESETS[key].strip())


if __name__ == "__main__":
    unittest.main()


from unittest.mock import MagicMock
from pathlib import Path
from kb_search import SearchResult


def test_build_reply_prompt_includes_candidate_docs_when_search_results_provided():
    msgs = [{"sender": "对方", "content": "我的订单到哪了", "time": "10:00"}]
    results = [
        SearchResult(
            path="/vault/订单查询.md",
            title="订单查询",
            scenario="用户询问订单进度",
            tags=["订单", "客服"],
            snippet="您好我帮您查...",
            score=1.5,
        )
    ]
    prompt = build_reply_prompt(msgs, search_results=results)
    assert "候选文档" in prompt
    assert "订单查询" in prompt
    assert "用户询问订单进度" in prompt


def test_build_reply_prompt_no_candidate_section_when_no_results():
    msgs = [{"sender": "对方", "content": "你好", "time": "10:00"}]
    prompt = build_reply_prompt(msgs, search_results=[])
    assert "候选文档" not in prompt


def test_build_reply_prompt_no_candidate_section_when_results_is_none():
    msgs = [{"sender": "对方", "content": "你好", "time": "10:00"}]
    prompt = build_reply_prompt(msgs, search_results=None)
    assert "候选文档" not in prompt


def _make_msgs():
    return [{"sender": "对方", "content": "订单到了吗", "time": "10:00"}]


def test_generate_reply_uses_add_file_when_search_results_found(tmp_path):
    """当 FTS5 检索到结果时，命令应包含 --add-file 而非 --add-dir。"""
    vault = str(tmp_path / "vault")
    os.makedirs(vault)
    md_file = os.path.join(vault, "订单.md")
    Path(md_file).write_text("---\ntitle: 订单\n---\n内容", encoding="utf-8")

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "好的，帮您查一下"

    with patch("ai_reply.search") as mock_search, \
         patch("ai_reply.update_index"), \
         patch("ai_reply.subprocess.run", return_value=fake_result) as mock_run:

        mock_search.return_value = [
            SearchResult(path=md_file, title="订单查询", scenario="测试", tags=[], snippet="", score=1.0)
        ]
        config = AIReplyConfig(kb_enabled=True, kb_vault_path=vault)
        reply = generate_reply(_make_msgs(), config)

    cmd = mock_run.call_args[0][0]
    assert "--add-file" in cmd
    assert "--add-dir" not in cmd
    assert reply == "好的，帮您查一下"


def test_generate_reply_fallback_to_add_dir_when_search_empty(tmp_path):
    """FTS5 返回空时，命令应降级为 --add-dir。"""
    vault = str(tmp_path / "vault")
    os.makedirs(vault)

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "收到，稍后处理"

    with patch("ai_reply.search", return_value=[]), \
         patch("ai_reply.update_index"), \
         patch("ai_reply.subprocess.run", return_value=fake_result) as mock_run:

        config = AIReplyConfig(kb_enabled=True, kb_vault_path=vault)
        generate_reply(_make_msgs(), config)

    cmd = mock_run.call_args[0][0]
    assert "--add-dir" in cmd
    assert "--add-file" not in cmd


# ── Cloud KB 模式测试 ────────────────────────────────────────────────────────

def test_build_reply_prompt_includes_cloud_kb_context():
    """cloud_kb_context 非空时，prompt 中应包含云端知识库参考段落。"""
    msgs = [{"sender": "对方", "content": "什么是借还流程", "time": "10:00"}]
    prompt = build_reply_prompt(msgs, cloud_kb_context="借出流程：扫码→弹宝→计费。")
    assert "云端知识库参考" in prompt
    assert "借出流程：扫码→弹宝→计费。" in prompt


def test_build_reply_prompt_no_cloud_section_when_empty():
    """cloud_kb_context 为空时，prompt 中不应出现云端知识库段落。"""
    msgs = [{"sender": "对方", "content": "你好", "time": "10:00"}]
    prompt = build_reply_prompt(msgs, cloud_kb_context="")
    assert "云端知识库参考" not in prompt


def test_generate_reply_cloud_mode_returns_kb_answer():
    """kb_mode='cloud' 时，generate_reply 应直接返回 query_cloud 的答案。

    新实现：query_cloud 内部已完成 contract + claude 全流程，
    ai_reply.generate_reply 在 cloud 模式下直接 return result.answer，
    不再二次调用 mc。
    """
    from unittest.mock import MagicMock
    fake_hss_result = MagicMock()
    fake_hss_result.answer = "借出流程：扫码→弹宝→计费。"

    with patch("ai_reply._hss_kb_available", return_value=True), \
         patch("ai_reply._hss_kb_query", return_value=fake_hss_result) as mock_query:

        config = AIReplyConfig(kb_mode="cloud", kb_scope="用户端", timeout=30)
        reply = generate_reply([{"content": "借还流程是什么"}], config)

    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args[1]
    assert call_kwargs.get("scope") == "用户端"
    # generate_reply 直接返回 query_cloud 的答案
    assert reply == "借出流程：扫码→弹宝→计费。"


def test_generate_reply_cloud_mode_raises_when_cli_missing():
    """hss-kb CLI 不可用时，cloud 模式应抛出 AICommandFailedError。"""
    with patch("ai_reply._hss_kb_available", return_value=False):
        config = AIReplyConfig(kb_mode="cloud", timeout=30)
        with pytest.raises(AICommandFailedError):
            generate_reply([{"content": "你好"}], config)


def test_generate_reply_backward_compat_kb_enabled_uses_local_path(tmp_path):
    """旧配置 kb_enabled=True 且 kb_mode='none' 时应走本地知识库分支。"""
    from unittest.mock import MagicMock
    vault = str(tmp_path / "vault")
    os.makedirs(vault)

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "本地知识库回复"

    with patch("ai_reply.search", return_value=[]), \
         patch("ai_reply.update_index"), \
         patch("ai_reply.subprocess.run", return_value=fake_result) as mock_run:

        config = AIReplyConfig(kb_enabled=True, kb_vault_path=vault, kb_mode="none")
        generate_reply([{"content": "你好"}], config)

    cmd = mock_run.call_args[0][0]
    # 向后兼容路径：kb_enabled=True + kb_mode=none → 走 local 路径，应有 --add-dir
    assert "--add-dir" in cmd
