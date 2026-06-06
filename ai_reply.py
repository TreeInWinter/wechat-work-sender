#!/usr/bin/env python3
"""AI reply generation helpers for the WeCom sidebar."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import shutil
import subprocess


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
    kb_enabled: bool = False
    kb_vault_path: str = ""


def _format_message(message: dict) -> str:
    """格式化单条消息，包含发送者，便于 AI 区分对话双方。"""
    sender = str(message.get("sender", "")).strip() or "对方"
    content = str(message.get("content", "")).strip()
    time_str = message.get("time")
    if time_str:
        return f"{sender} [{time_str}]: {content}"
    return f"{sender}: {content}"


def build_reply_prompt(
    messages: list[dict], max_messages: int = 20, kb_enabled: bool = False
) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)
    kb_preamble = (
        "你可以访问本地知识库目录中的文档。请先根据聊天内容在知识库中检索相关文档，"
        "结合检索结果和聊天上下文，生成一段可以直接发送的中文回复。\n\n"
        if kb_enabled
        else ""
    )
    return (
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


def generate_reply(messages: list[dict], config: AIReplyConfig | None = None) -> str:
    config = config or AIReplyConfig()
    if not any(str(m.get("content", "")).strip() for m in messages):
        raise AIEmptyResponseError("没有可用于生成回复的聊天内容")

    if config.kb_enabled:
        if not config.kb_vault_path:
            raise AICommandFailedError(
                "知识库已启用但未配置路径，请在设置中选择 Obsidian vault 文件夹"
            )
        if not os.path.isdir(config.kb_vault_path):
            raise AICommandFailedError(
                f"知识库路径不存在或不是目录：{config.kb_vault_path}"
            )

    prompt = build_reply_prompt(
        messages, max_messages=config.max_messages, kb_enabled=config.kb_enabled
    )
    if config.kb_enabled:
        # KB mode: build command from scratch; config.args is intentionally bypassed
        # because --tools "" would prevent file reading from the vault.
        cmd = [
            config.command, "--code", "-p",
            "--add-dir", config.kb_vault_path,
            "--no-session-persistence",
            prompt,
        ]
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
        visible_cmd = " ".join([config.command, *config.args])
        raise AIEmptyResponseError(
            f"AI 命令没有输出，请在终端确认可用：{visible_cmd} \"只输出两个字：可以\""
        )
    return reply
