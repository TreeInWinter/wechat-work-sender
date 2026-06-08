#!/usr/bin/env python3
"""AI reply generation helpers for the WeCom sidebar."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import shutil
import subprocess
import threading

try:
    from kb_search import search, update_index
except ImportError:
    def search(*args, **kwargs):  # type: ignore[misc]
        return []
    def update_index(*args, **kwargs):  # type: ignore[misc]
        return 0, 0

try:
    from hss_kb_client import (
        query_cloud as _hss_kb_query,
        is_available as _hss_kb_available,
        HssKBUnavailableError,
        HssKBTimeoutError,
        HssKBQueryError,
    )
except ImportError:
    _hss_kb_query = None       # type: ignore[assignment]
    _hss_kb_available = None   # type: ignore[assignment]
    HssKBUnavailableError = Exception   # type: ignore[assignment,misc]
    HssKBTimeoutError = Exception       # type: ignore[assignment,misc]
    HssKBQueryError = Exception         # type: ignore[assignment,misc]


class AIReplyError(Exception):
    """Base class for AI reply generation failures."""


class AICommandNotFoundError(AIReplyError):
    """AI command is not installed or not visible in PATH."""


class AICommandTimeoutError(AIReplyError):
    """AI command exceeded the configured timeout."""


class AICommandFailedError(AIReplyError):
    """AI command exited with a non-zero status, or a pre-flight config check failed."""


class AIEmptyResponseError(AIReplyError):
    """AI command returned no usable reply."""


def resolve_ai_command() -> str:
    found = shutil.which("mc")
    if found:
        return found
    for path in ("/usr/local/bin/mc", "/opt/homebrew/bin/mc"):
        if os.path.exists(path):
            return path
    return "mc"


@dataclass
class AIReplyConfig:
    command: str = field(default_factory=resolve_ai_command)
    args: list[str] = field(
        default_factory=lambda: ["--code", "-p", "--tools", "", "--no-session-persistence"]
    )
    timeout: int = 60
    max_messages: int = 20
    kb_enabled: bool = False    # 保留向后兼容；新代码优先使用 kb_mode
    kb_vault_path: str = ""
    # kb_mode: "none" | "local" | "cloud"
    # "local"  — 本地 Obsidian vault（FTS5 两级检索）
    # "cloud"  — hss-kb-serve-entry 云端知识库（需 hss-kb CLI）
    # "none"   — 不启用知识库
    kb_mode: str = "none"
    kb_scope: str = ""          # 云端模式的查询范围（服务名/模块名），可选


def _extract_query(messages: list[dict], n: int = 3) -> str:
    """取最后 n 条非空消息的内容拼成查询串。"""
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-n:]
    return " ".join(str(m.get("content", "")).strip() for m in selected)


def _format_message(message: dict) -> str:
    """格式化单条消息，包含发送者，便于 AI 区分对话双方。"""
    sender = str(message.get("sender", "")).strip() or "对方"
    content = str(message.get("content", "")).strip()
    time_str = message.get("time")
    if time_str:
        return f"{sender} [{time_str}]: {content}"
    return f"{sender}: {content}"


def build_reply_prompt(
    messages: list[dict],
    max_messages: int = 20,
    kb_enabled: bool = False,
    search_results=None,          # list[SearchResult] | None
    cloud_kb_context: str = "",   # 云端知识库查询结果，由 hss-kb ask sync 返回
) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)

    # 云端知识库参考段落（hss-kb-serve-entry 返回的答案）
    cloud_section = ""
    if cloud_kb_context:
        cloud_section = (
            "以下是从云端知识库查询到的相关参考信息，请在生成回复时优先参考：\n\n"
            "【云端知识库参考】\n"
            f"{cloud_kb_context}\n\n"
        )

    # 候选文档段落（本地两级检索时注入）
    candidate_section = ""
    if search_results:
        lines = [
            "以下是从知识库中预检索到的候选文档（按相关度排序），"
            "请从中选择 3~5 个你认为最相关的文件精读后再生成回复。"
            "如果这些文档都不相关，可以不参考。\n\n【候选文档】"
        ]
        for i, r in enumerate(search_results, 1):
            tags_str = " ".join(r.tags) if r.tags else ""
            lines.append(
                f"{i}. {r.title}\n"
                f"   场景：{r.scenario}\n"
                f"   标签：{tags_str}\n"
                f"   摘要：{r.snippet}"
            )
        candidate_section = "\n".join(lines) + "\n\n"

    kb_preamble = (
        "你可以访问本地知识库目录中的文档。请先根据聊天内容在知识库中检索相关文档，"
        "结合检索结果和聊天上下文，生成一段可以直接发送的中文回复。\n\n"
        if kb_enabled and not search_results
        else ""
    )
    return (
        f"{cloud_section}"
        f"{candidate_section}"
        f"{kb_preamble}"
        "你是 IM 聊天回复助手。请根据下面最近的聊天记录，生成一段可以直接发送的中文回复。\n\n"
        "要求：\n"
        "1. 只输出最终回复正文，不要标题、解释、Markdown 或代码块。\n"
        "2. 语气礼貌、简洁、专业。\n"
        "3. 不要承诺无法从聊天记录确认的事实。\n"
        "4. 如果信息不足，先表达已收到，并说明需要进一步确认。\n\n"
        "最近聊天记录（格式：发送者 [时间]: 内容；发送者=我 表示你自己发的消息）：\n"
        f"{transcript}\n\n"
        "请输出回复："
    )


def _build_extraction_prompt(
    messages: list[dict], reply: str, max_messages: int = 20
) -> str:
    """构造提炼知识库条目的 prompt，要求模型只输出 JSON。"""
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    return (
        "你是知识库整理助手。请根据下面的聊天记录和候选回复，提炼出结构化的知识库条目。\n\n"
        "严格只输出一个 JSON 对象，不输出任何其他文字，格式：\n"
        '{"title": "简短标题（10字以内）", '
        '"scenario": "适用场景描述（20字以内）", '
        '"tags": ["标签1", "标签2"]}\n\n'
        f"聊天记录：\n{transcript}\n\n"
        f"候选回复：\n{reply}\n\n"
        "输出 JSON："
    )


def extract_kb_entry(
    messages: list[dict],
    reply: str,
    config: AIReplyConfig | None = None,
) -> dict | None:
    """
    根据聊天记录和候选回复提炼结构化知识库条目。
    返回 {"title": ..., "scenario": ..., "tags": [...]}。
    任何错误（超时、解析失败、命令不存在）均返回 None，由调用方降级处理。
    注意：此调用始终使用 --tools ""（不读 vault），与 generate_reply 的 KB 模式不同。
    """
    config = config or AIReplyConfig()
    prompt = _build_extraction_prompt(messages, reply, max_messages=config.max_messages)
    cmd = [
        config.command, "--code", "-p",
        "--tools", "",
        "--no-session-persistence",
        prompt,
    ]
    # Note: config.args is intentionally bypassed here — this call must always use
    # --tools "" (no file access). Using config.args risks inheriting --add-dir if
    # the caller's config has KB enabled.
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    text = (result.stdout or "").strip()
    # 去除可能的 Markdown 代码块包装（```json ... ```）
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def generate_reply(messages: list[dict], config: AIReplyConfig | None = None) -> str:
    config = config or AIReplyConfig()
    if not any(str(m.get("content", "")).strip() for m in messages):
        raise AIEmptyResponseError("没有可用于生成回复的聊天内容")

    # 确定实际 kb_mode（向后兼容：kb_enabled=True 且 kb_mode 未设置时视为 local）
    effective_kb_mode = config.kb_mode
    if effective_kb_mode == "none" and config.kb_enabled:
        effective_kb_mode = "local"

    # ── 云端知识库分支（hss-kb contract + mc，本地执行） ──
    if effective_kb_mode == "cloud":
        if _hss_kb_query is None:
            raise AICommandFailedError(
                "hss_kb_client 模块未找到，请确认 hss_kb_client.py 存在"
            )
        if not (_hss_kb_available and _hss_kb_available()):
            raise AICommandFailedError(
                "hss-kb CLI 未安装，请运行: npm install -g @saas/hss-kb-cli"
            )
        query = _extract_query(messages)
        # query_cloud 内部已完成检索 + AI 全流程，直接返回最终回答
        # 传入 ai_command/ai_args 使用与普通回复相同的 mc 命令，
        # 避免依赖 claude CLI 的 ANTHROPIC_AUTH_TOKEN（仅在 Claude Code 会话内有效）
        try:
            result = _hss_kb_query(
                query,
                caller="wechat-work-sender",
                scope=config.kb_scope,
                timeout=config.timeout,
                ai_command=config.command,
                ai_args=config.args,
            )
        except HssKBUnavailableError as exc:
            raise AICommandFailedError(str(exc)) from exc
        except HssKBTimeoutError as exc:
            raise AICommandTimeoutError(str(exc)) from exc
        except HssKBQueryError as exc:
            raise AICommandFailedError(str(exc)) from exc

        reply = result.answer
        if not reply:
            raise AIEmptyResponseError("云端知识库未返回有效回答")
        return reply

    else:
        # ── 本地知识库 / 不使用知识库 ──
        if effective_kb_mode == "local":
            if not config.kb_vault_path:
                raise AICommandFailedError(
                    "知识库已启用但未配置路径，请在设置中选择 Obsidian vault 文件夹"
                )
            if not os.path.isdir(config.kb_vault_path):
                raise AICommandFailedError(
                    f"知识库路径不存在或不是目录：{config.kb_vault_path}"
                )

        # ── 两级检索 ──
        search_results = []
        use_add_dir = False

        if effective_kb_mode == "local":
            # 后台异步增量更新索引（不等结果）
            def _bg_update(path: str) -> None:
                try:
                    update_index(path)
                except Exception:
                    pass  # vault 被删除或 db 锁定时静默忽略，下次调用重试

            threading.Thread(target=_bg_update, args=(config.kb_vault_path,), daemon=True).start()
            # 同步 FTS5 粗筛；任何意外异常均降级为 --add-dir
            query = _extract_query(messages)
            try:
                search_results = search(query, config.kb_vault_path)
            except Exception:
                search_results = []
            if not search_results:
                use_add_dir = True  # 检索为空或出错，降级

        prompt = build_reply_prompt(
            messages,
            max_messages=config.max_messages,
            kb_enabled=(effective_kb_mode == "local"),
            search_results=search_results if search_results else None,
        )

        if effective_kb_mode == "local":
            if use_add_dir:
                cmd = [
                    config.command, "--code", "-p",
                    "--add-dir", config.kb_vault_path,
                    "--no-session-persistence",
                    prompt,
                ]
            else:
                cmd = [
                    config.command, "--code", "-p",
                    "--no-session-persistence",
                ]
                for r in search_results:
                    cmd += ["--add-file", r.path]
                cmd.append(prompt)
        else:
            cmd = [config.command, *config.args, prompt]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AICommandNotFoundError(f"未找到 AI 命令: {config.command}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AICommandTimeoutError("AI 生成超时，请稍后重试") from exc

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise AICommandFailedError(err or f"AI 命令退出码: {result.returncode}")

    reply = (result.stdout or "").strip()
    if not reply:
        # 用实际构建的 cmd 前几段（排除 prompt 内容）给出有意义的调试提示
        visible_cmd = " ".join(cmd[:6])
        raise AIEmptyResponseError(
            f"AI 命令没有输出，请在终端确认可用：{visible_cmd} \"只输出两个字：可以\""
        )
    return reply
