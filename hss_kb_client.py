# hss_kb_client.py
"""Cloud KB Q&A client — wraps hss-kb CLI (hss-kb-serve-entry integration).

公开接口：
  is_available()              -> bool
  query_cloud(prompt, **opts) -> HssKBResult
  INSTALL_HINT                -> str   （未安装时的提示语）
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

INSTALL_HINT = "npm install -g @saas/hss-kb-cli"


@dataclass
class HssKBResult:
    answer: str       # 最终回答正文
    raw_output: str   # hss-kb 命令的完整 stdout
    error: str = ""   # 错误描述（成功时为空字符串）


class HssKBUnavailableError(Exception):
    """hss-kb CLI 未安装或不在 PATH 中。"""


class HssKBTimeoutError(Exception):
    """hss-kb ask sync 超时。"""


class HssKBQueryError(Exception):
    """hss-kb 返回非零退出码。"""


def _bin() -> str:
    found = shutil.which("hss-kb")
    return found if found else "hss-kb"


def is_available() -> bool:
    """Return True if the hss-kb CLI is installed and reachable."""
    return shutil.which("hss-kb") is not None


def query_cloud(
    prompt: str,
    *,
    caller: str = "wechat-work-sender",
    scope: str = "",
    output_format: str = "纯文本",
    timeout: int = 120,
    quiet: bool = True,
) -> HssKBResult:
    """调用 `hss-kb ask sync <prompt>` 并返回结果。

    Args:
        prompt:        问题内容。
        caller:        传给 --caller 的标识符（默认 wechat-work-sender）。
        scope:         可选的查询范围（服务名/模块名），传给 --scope。
        output_format: 期望输出格式，传给 --output（默认"纯文本"）。
        timeout:       最长等待秒数，同时传给 --timeout（默认 120）。
        quiet:         静默模式，传 -q 屏蔽轮询进度输出（默认 True）。

    Returns:
        HssKBResult(answer, raw_output)；成功时 error 为空字符串。

    Raises:
        HssKBUnavailableError: hss-kb 未安装。
        HssKBTimeoutError:     命令超时。
        HssKBQueryError:       hss-kb 返回非零退出码。
    """
    if not is_available():
        raise HssKBUnavailableError(
            f"hss-kb CLI 未安装，请运行: {INSTALL_HINT}"
        )

    cmd = [
        _bin(), "ask", "sync", prompt,
        "--caller", caller,
        "--output", output_format,
        "--timeout", str(timeout),
    ]
    if scope:
        cmd += ["--scope", scope]
    if quiet:
        cmd.append("-q")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 15,   # 留 buffer；--timeout 内部已处理，外层兜底
            check=False,
        )
    except FileNotFoundError as exc:
        raise HssKBUnavailableError("hss-kb CLI 未找到，请确认已安装") from exc
    except subprocess.TimeoutExpired as exc:
        raise HssKBTimeoutError(f"云端知识库查询超时（{timeout}s）") from exc

    raw = (result.stdout or "").strip()
    if result.returncode != 0:
        err = (result.stderr or raw or "").strip()
        raise HssKBQueryError(
            f"hss-kb 返回错误（exitcode={result.returncode}）: {err[:200]}"
        )

    return HssKBResult(answer=raw, raw_output=raw)
