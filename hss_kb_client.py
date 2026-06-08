# hss_kb_client.py
"""Cloud KB Q&A client — wraps hss-kb contract + local mc (hss-kb-serve-entry integration).

方案：hss-kb contract 生成 AI 指令上下文 → mc 本地执行，无需远程服务器权限。

公开接口：
  is_available()              -> bool
  query_cloud(prompt, **opts) -> HssKBResult
  INSTALL_HINT                -> str   （未安装时的提示语）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

INSTALL_HINT = "npm install -g @saas/hss-kb-cli"

# claude CLI 候选路径（用于云端 KB 问答，支持 --dangerously-skip-permissions）
_CLAUDE_CANDIDATES = [
    "~/.local/bin/claude",   # expanduser 在 _claude_bin() 里执行
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
]
# mc 命令的候选路径（与 ai_reply.py 保持一致，用于其他 AI 调用）
_MC_CANDIDATES = ["/usr/local/bin/mc", "/opt/homebrew/bin/mc"]


@dataclass
class HssKBResult:
    answer: str       # 最终回答正文
    raw_output: str   # mc 命令的完整 stdout
    error: str = ""   # 错误描述（成功时为空字符串）


class HssKBUnavailableError(Exception):
    """hss-kb CLI 未安装或不在 PATH 中。"""


class HssKBTimeoutError(Exception):
    """查询超时。"""


class HssKBQueryError(Exception):
    """hss-kb contract 或 mc 返回非零退出码。"""


def _hss_kb_bin() -> str:
    found = shutil.which("hss-kb")
    return found if found else "hss-kb"


def _mc_bin() -> str:
    found = shutil.which("mc")
    if found:
        return found
    for path in _MC_CANDIDATES:
        if os.path.exists(path):
            return path
    return "mc"


def _claude_bin() -> str:
    """返回 claude CLI 路径（优先 PATH，再按候选列表查找）。"""
    found = shutil.which("claude")
    if found:
        return found
    for path in _CLAUDE_CANDIDATES:
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            return expanded
    return "claude"


def _resolve_kb_root(kb_id: str = "") -> str:
    """从 kb-router.json 或 kb-registry.json 解析知识库根目录。

    优先读 hss-kb-serve-entry skill 目录下的 kb-router.json（支持多库）；
    回退到 hss-kb list 命令输出中找匹配的路径。
    返回空字符串表示未找到。
    """
    # 1. 尝试读 skill config/kb-router.json
    skill_dir = os.path.expanduser("~/.claude/skills/hss-kb-serve-entry")
    router_path = os.path.join(skill_dir, "config", "kb-router.json")
    if os.path.exists(router_path):
        try:
            with open(router_path, encoding="utf-8") as f:
                router = json.load(f)
            target_id = kb_id or router.get("default_active", "")
            for lib in router.get("libraries", []):
                if lib.get("id") == target_id or not target_id:
                    root = lib.get("root", "")
                    if root:
                        return os.path.expanduser(root)
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    # 2. 回退：调用 hss-kb list 解析路径（格式：📁 /path/to/kb）
    try:
        result = subprocess.run(
            [_hss_kb_bin(), "list"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        for line in (result.stdout or "").splitlines():
            if "📁" in line:
                path = line.split("📁")[-1].strip()
                if path and os.path.isdir(path):
                    return path
    except Exception:
        pass

    return ""


def _parse_doc_paths(query_output: str) -> list[str]:
    """从 hss-kb query --verbose 输出中提取文档相对路径列表。

    输出格式示例：
      📄 processed-data/业务领域知识库/xxx/yyy.md
    返回去重后的路径列表（保持原顺序）。
    """
    paths: list[str] = []
    seen: set[str] = set()
    for line in query_output.splitlines():
        line = line.strip()
        if "📄" in line:
            path = line.split("📄")[-1].strip()
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def _fetch_top_docs(
    prompt: str,
    kb_root: str,
    top_n: int = 3,
) -> list[tuple[str, str]]:
    """执行 hss-kb query，读取 Top N 文档内容，返回 [(相对路径, 内容)] 列表。

    文档内容截断至 4000 字符（避免 prompt 过长）。
    任何错误均静默降级，返回空列表。
    """
    if not kb_root:
        return []

    try:
        result = subprocess.run(
            [_hss_kb_bin(), "query", prompt, "--verbose"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        paths = _parse_doc_paths(result.stdout)
    except Exception:
        return []

    # 优先选 processed-data 下的业务文档（过滤 _RAW_INDEX 原始索引）
    processed_paths = [p for p in paths if "processed-data" in p and "_RAW_INDEX" not in p]
    raw_paths = [p for p in paths if p not in processed_paths]
    ordered = processed_paths + raw_paths  # processed 优先，原始索引兜底

    docs: list[tuple[str, str]] = []
    for rel_path in ordered[:top_n]:
        abs_path = os.path.join(kb_root, rel_path)
        try:
            with open(abs_path, encoding="utf-8") as f:
                content = f.read(4000)   # 截断至 4000 字符
            docs.append((rel_path, content))
        except OSError:
            continue
    return docs


def is_available() -> bool:
    """Return True if hss-kb CLI is installed and reachable."""
    return shutil.which("hss-kb") is not None


def query_cloud(
    prompt: str,
    *,
    caller: str = "wechat-work-sender",
    scope: str = "",
    output_format: str = "纯文本",
    timeout: int = 180,
    quiet: bool = True,
) -> HssKBResult:
    """用 hss-kb contract + mc 本地执行知识库问答。

    流程：
      1. hss-kb contract --caller <caller> --intent <prompt> [--scope <scope>]
         → 生成 AI 指令上下文（包含知识库目录索引、检索建议、执行步骤）
      2. 把 contract 输出和用户问题拼成 prompt，传给 mc --code 执行
         → mc 有文件读取能力，可直接读本地知识库文档

    Args:
        prompt:        用户问题。
        caller:        传给 --caller 的标识符（默认 wechat-work-sender）。
        scope:         可选的查询范围（服务名/领域路径），传给 --scope。
        output_format: 期望输出格式，传给 --output（默认"纯文本"）。
        timeout:       最长等待秒数（默认 120）。
        quiet:         暂未使用，保留兼容。

    Returns:
        HssKBResult(answer, raw_output)；成功时 error 为空字符串。

    Raises:
        HssKBUnavailableError: hss-kb 或 mc 未安装。
        HssKBTimeoutError:     命令超时。
        HssKBQueryError:       命令返回非零退出码。
    """
    if not is_available():
        raise HssKBUnavailableError(
            f"hss-kb CLI 未安装，请运行: {INSTALL_HINT}"
        )
    claude = _claude_bin()
    if not (shutil.which("claude") or any(
        os.path.exists(os.path.expanduser(p)) for p in _CLAUDE_CANDIDATES
    )):
        raise HssKBUnavailableError(
            "claude CLI 未找到，请确认 Claude Code CLI 已安装并在 PATH 中"
        )

    # ── Step 1：hss-kb query 取 Top 文档路径，Python 直接读取内容 ──
    kb_root = _resolve_kb_root()
    doc_contents = _fetch_top_docs(prompt, kb_root, top_n=3)

    # ── Step 2：组装完整 prompt，直接注入文档内容，无需 claude 再读文件 ──
    docs_section = ""
    if doc_contents:
        parts = [
            "【知识库文档内容（已预读，直接基于以下内容回答，无需再读文件）】\n"
        ]
        for path, content in doc_contents:
            parts.append(f"--- 来源：{path} ---\n{content}\n")
        docs_section = "\n".join(parts)

    full_prompt = (
        f"{docs_section}\n\n"
        "---\n\n"
        f"【用户问题】{prompt}\n\n"
        "请根据上方知识库文档内容回答用户问题。\n"
        "要求：只输出最终回答正文，语言简洁、条理清晰；"
        "必须在回答末尾标注来源文件路径；"
        "如文档中没有相关信息，明确说明\"未找到\"，不要编造。"
    )

    # 用 claude CLI 执行（--dangerously-skip-permissions，不再需要 --add-dir 读文件）
    # 文档内容已注入 prompt，无需工具调用，--output-format text 确保纯文本输出
    claude_cmd = [
        _claude_bin(),
        "--dangerously-skip-permissions",
        "--print", "--no-session-persistence",
        "--output-format", "text",
        full_prompt,
    ]

    claude_timeout = timeout - 20  # 减去 query(~10s) + 读文件(~5s) 耗时
    try:
        mc_result = subprocess.run(
            claude_cmd,
            capture_output=True,
            text=True,
            timeout=claude_timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HssKBUnavailableError("claude CLI 未找到，请确认已安装") from exc
    except subprocess.TimeoutExpired as exc:
        raise HssKBTimeoutError(f"知识库问答超时（{claude_timeout}s）") from exc

    raw = (mc_result.stdout or "").strip()
    if mc_result.returncode != 0:
        err = (mc_result.stderr or raw or "").strip()
        raise HssKBQueryError(
            f"claude 返回错误（exitcode={mc_result.returncode}）: {err[:200]}"
        )

    return HssKBResult(answer=raw, raw_output=raw)
