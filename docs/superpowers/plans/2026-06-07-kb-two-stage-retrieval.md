# 知识库两级检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有知识库集成基础上，加入 SQLite FTS5 全文索引层，将检索从"整个 vault 扔给 Claude 自主遍历"升级为"本地粗筛 Top-15 → Claude 精读精选"，支持 500~2000 文件规模时仍保持低延迟。

**Architecture:** 新增 `kb_search.py` 模块，负责 SQLite FTS5 索引的建立、增量更新和检索；`ai_reply.py` 在 `generate_reply()` 前先调用 FTS5 检索得到 Top-15 文件路径，通过 `--add-file` 逐条传入 mc 命令，同时在 prompt 中注入候选文档摘要列表引导 Claude 精选；四种降级条件（索引不存在、检索出错、返回空、FTS5 异常）均退回 `--add-dir` 当前行为。

**Tech Stack:** Python 3.10+, `sqlite3`（标准库，零额外依赖）, FTS5 tokenize="unicode61"（内置中文支持）, `threading`（已有）

---

## 文件变更清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kb_search.py` | **新建** | FTS5 索引 + 检索模块（全部逻辑在此） |
| `tests/test_kb_search.py` | **新建** | kb_search 的单元测试 |
| `ai_reply.py` | **修改** | `build_reply_prompt()` 加 `search_results` 参数；`generate_reply()` 接入两级检索 |
| `tests/test_ai_reply.py` | **修改** | 为新参数补测试 |
| `kb_writer.py` | **微改** | `save_to_vault()` 完成后触发 `update_index()` 后台线程 |
| `gui_panel.py` | **修改** | 设置弹窗加 rebuild 进度提示；状态行加文件数 |

---

## Task 1：新建 `kb_search.py` 核心骨架

**Files:**
- Create: `kb_search.py`
- Test: `tests/test_kb_search.py`

- [ ] **Step 1: 写第一批失败测试（db 路径 + rebuild）**

```python
# tests/test_kb_search.py
import os, tempfile, textwrap
import pytest
from kb_search import get_db_path, rebuild_index, SearchResult


def _make_vault(tmp_path, files: dict[str, str]) -> str:
    vault = tmp_path / "vault"
    vault.mkdir()
    for name, content in files.items():
        p = vault / name
        p.write_text(content, encoding="utf-8")
    return str(vault)


def test_get_db_path_returns_cache_dir_path():
    path = get_db_path()
    assert path.endswith("kb_index.db")
    assert ".cache" in path or "wechat-sender" in path


def test_rebuild_index_returns_file_count(tmp_path):
    vault = _make_vault(tmp_path, {
        "订单查询.md": textwrap.dedent("""\
            ---
            title: "订单查询"
            scenario: "用户询问订单"
            tags: ["订单", "客服"]
            ---
            您好，我帮您查一下。
        """),
        "退款流程.md": textwrap.dedent("""\
            ---
            title: "退款流程"
            scenario: "用户申请退款"
            tags: ["退款"]
            ---
            退款申请提交后3-5个工作日处理。
        """),
    })
    db = str(tmp_path / "test.db")
    count = rebuild_index(vault, db_path=db)
    assert count == 2


def test_rebuild_index_ignores_non_markdown(tmp_path):
    vault = _make_vault(tmp_path, {
        "note.md": "---\ntitle: 测试\n---\n内容",
        "image.png": b"\x89PNG",   # 非 md
    })
    db = str(tmp_path / "test.db")
    count = rebuild_index(vault, db_path=db)
    assert count == 1
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py -v 2>&1 | head -30
```

期望：`ModuleNotFoundError: No module named 'kb_search'`

- [ ] **Step 3: 实现 `kb_search.py` 骨架（只含 `get_db_path` 和 `rebuild_index`）**

```python
# kb_search.py
"""SQLite FTS5 两级检索模块。

公开接口：
  get_db_path()                  -> str
  rebuild_index(vault, db_path)  -> int
  update_index(vault, db_path)   -> tuple[int, int]
  search(query, vault, top_k, db_path) -> list[SearchResult]
"""
from __future__ import annotations

import os
import sqlite3
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SearchResult:
    path: str
    title: str
    scenario: str
    tags: list[str] = field(default_factory=list)
    snippet: str = ""
    score: float = 0.0


def get_db_path() -> str:
    """返回索引数据库文件路径（~/.cache/wechat-sender/kb_index.db）。"""
    cache_dir = Path.home() / ".cache" / "wechat-sender"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir / "kb_index.db")


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kb_meta (
            path TEXT PRIMARY KEY,
            mtime REAL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
            path UNINDEXED,
            title,
            tags,
            scenario,
            body,
            tokenize="unicode61"
        );
    """)
    conn.commit()
    return conn


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta_dict, body)。简单实现，不依赖 yaml 库。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()
    meta: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().strip('"')
            v = v.strip().strip('"')
            # tags: ["a", "b"]  →  list
            if v.startswith("["):
                items = re.findall(r'"([^"]+)"', v)
                meta[k] = items
            else:
                meta[k] = v
    return meta, body


def _index_file(conn: sqlite3.Connection, path: str) -> None:
    """读取单个 md 文件并写入 FTS 索引。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    meta, body = _parse_frontmatter(text)
    title = str(meta.get("title", Path(path).stem))
    scenario = str(meta.get("scenario", ""))
    tags_raw = meta.get("tags", [])
    tags = " ".join(tags_raw) if isinstance(tags_raw, list) else str(tags_raw)
    body_snippet = body[:500]

    # 删除旧记录（如果已存在）
    conn.execute("DELETE FROM kb_fts WHERE path = ?", (path,))
    conn.execute(
        "INSERT INTO kb_fts(path, title, tags, scenario, body) VALUES (?,?,?,?,?)",
        (path, title, tags, scenario, body_snippet),
    )
    mtime = os.path.getmtime(path)
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta(path, mtime) VALUES (?,?)",
        (path, mtime),
    )


def rebuild_index(vault_path: str, db_path: str | None = None) -> int:
    """全量重建索引。返回已索引文件数。"""
    db_path = db_path or get_db_path()
    conn = _open_db(db_path)
    try:
        # 清空旧数据
        conn.execute("DELETE FROM kb_fts")
        conn.execute("DELETE FROM kb_meta")
        conn.commit()

        count = 0
        for root, _, files in os.walk(vault_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                _index_file(conn, os.path.join(root, fname))
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py::test_get_db_path_returns_cache_dir_path tests/test_kb_search.py::test_rebuild_index_returns_file_count tests/test_kb_search.py::test_rebuild_index_ignores_non_markdown -v
```

期望：3 个 PASS

- [ ] **Step 5: Commit**

```bash
git add kb_search.py tests/test_kb_search.py
git commit -m "feat: kb_search 骨架 — get_db_path + rebuild_index"
```

---

## Task 2：实现 `update_index()` 增量更新

**Files:**
- Modify: `kb_search.py`
- Modify: `tests/test_kb_search.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb_search.py` 末尾追加：

```python
from kb_search import update_index
import time


def test_update_index_adds_new_file(tmp_path):
    vault = _make_vault(tmp_path, {
        "first.md": "---\ntitle: 第一\nscenario: 测试\ntags: []\n---\n内容",
    })
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)

    # 新增文件
    (Path(vault) / "second.md").write_text(
        "---\ntitle: 第二\nscenario: 新增\ntags: []\n---\n新内容", encoding="utf-8"
    )
    added, deleted = update_index(vault, db_path=db)
    assert added == 1
    assert deleted == 0


def test_update_index_detects_deleted_file(tmp_path):
    vault = _make_vault(tmp_path, {
        "keep.md": "---\ntitle: 保留\n---\n内容",
        "remove.md": "---\ntitle: 删除\n---\n内容",
    })
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)

    os.remove(os.path.join(vault, "remove.md"))
    added, deleted = update_index(vault, db_path=db)
    assert added == 0
    assert deleted == 1


def test_update_index_updates_modified_file(tmp_path):
    md_path = tmp_path / "vault" / "edit.md"
    (tmp_path / "vault").mkdir()
    md_path.write_text("---\ntitle: 原始\n---\n旧内容", encoding="utf-8")
    db = str(tmp_path / "idx.db")
    rebuild_index(str(tmp_path / "vault"), db_path=db)

    # 修改文件（mtime 要变，sleep 确保不同秒）
    time.sleep(0.05)
    md_path.write_text("---\ntitle: 更新后\n---\n新内容", encoding="utf-8")
    # 强制 mtime 不同
    os.utime(str(md_path), (os.path.getmtime(str(md_path)) + 1,) * 2)
    added, deleted = update_index(str(tmp_path / "vault"), db_path=db)
    assert added == 1   # modified 计入 added
    assert deleted == 0
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py::test_update_index_adds_new_file -v 2>&1 | head -20
```

期望：`ImportError` 或 `AttributeError: module 'kb_search' has no attribute 'update_index'`

- [ ] **Step 3: 实现 `update_index()`**

在 `kb_search.py` 中 `rebuild_index` 后追加：

```python
def update_index(vault_path: str, db_path: str | None = None) -> tuple[int, int]:
    """增量更新索引。返回 (新增/更新数, 删除数)。"""
    db_path = db_path or get_db_path()
    # 如果 db 不存在，走全量重建
    if not os.path.exists(db_path):
        count = rebuild_index(vault_path, db_path=db_path)
        return count, 0

    conn = _open_db(db_path)
    try:
        # 读取现有路径→mtime 映射
        existing = {
            row[0]: row[1]
            for row in conn.execute("SELECT path, mtime FROM kb_meta").fetchall()
        }

        # 扫描 vault 中所有 md 文件
        current_paths: set[str] = set()
        added = 0
        for root, _, files in os.walk(vault_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                current_paths.add(fpath)
                new_mtime = os.path.getmtime(fpath)
                if fpath not in existing or existing[fpath] != new_mtime:
                    _index_file(conn, fpath)
                    added += 1

        # 删除已不存在的文件
        deleted = 0
        for old_path in existing:
            if old_path not in current_paths:
                conn.execute("DELETE FROM kb_fts WHERE path = ?", (old_path,))
                conn.execute("DELETE FROM kb_meta WHERE path = ?", (old_path,))
                deleted += 1

        conn.commit()
        return added, deleted
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py -v -k "update_index"
```

期望：3 个 PASS

- [ ] **Step 5: Commit**

```bash
git add kb_search.py tests/test_kb_search.py
git commit -m "feat: kb_search — update_index 增量更新"
```

---

## Task 3：实现 `search()` 检索函数

**Files:**
- Modify: `kb_search.py`
- Modify: `tests/test_kb_search.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb_search.py` 末尾追加：

```python
from kb_search import search


def test_search_returns_results_by_title(tmp_path):
    vault = _make_vault(tmp_path, {
        "订单查询.md": "---\ntitle: 订单查询\nscenario: 用户询问订单\ntags: [\"订单\",\"客服\"]\n---\n您好我帮您查一下",
        "退款流程.md": "---\ntitle: 退款流程\nscenario: 用户申请退款\ntags: [\"退款\"]\n---\n退款3-5工作日",
    })
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)

    results = search("订单", vault, db_path=db)
    assert len(results) >= 1
    assert any("订单" in r.title for r in results)


def test_search_returns_results_by_tags(tmp_path):
    vault = _make_vault(tmp_path, {
        "物流延误.md": "---\ntitle: 物流延误\nscenario: 货物未到\ntags: [\"物流\",\"延误\"]\n---\n非常抱歉",
    })
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)

    results = search("物流", vault, db_path=db)
    assert len(results) >= 1
    assert results[0].path.endswith("物流延误.md")


def test_search_returns_empty_list_when_db_missing(tmp_path):
    results = search("任意查询", str(tmp_path / "vault"), db_path=str(tmp_path / "no.db"))
    assert results == []


def test_search_top_k_limits_results(tmp_path):
    files = {f"doc{i}.md": f"---\ntitle: 文档{i}\nscenario: 场景\ntags: []\n---\n内容{i}" for i in range(20)}
    vault = _make_vault(tmp_path, files)
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)

    results = search("文档", vault, top_k=5, db_path=db)
    assert len(results) <= 5
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py -v -k "search" 2>&1 | head -20
```

期望：`AttributeError: module 'kb_search' has no attribute 'search'`

- [ ] **Step 3: 实现 `search()`**

在 `kb_search.py` 中 `update_index` 后追加：

```python
def search(
    query: str,
    vault_path: str,
    top_k: int = 15,
    db_path: str | None = None,
) -> list[SearchResult]:
    """FTS5 检索，返回 Top-K 结果。db 不存在或出错时返回空列表。"""
    db_path = db_path or get_db_path()
    if not os.path.exists(db_path):
        return []

    # FTS5 查询需要转义特殊字符，简单处理：去掉引号
    safe_query = query.replace('"', " ").strip()
    if not safe_query:
        return []

    try:
        conn = _open_db(db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    path,
                    title,
                    scenario,
                    tags,
                    snippet(kb_fts, 4, '[', ']', '...', 10) AS snip,
                    -rank AS score
                FROM kb_fts
                WHERE kb_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, top_k),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # 查询语法错误（如特殊符号）→ 降级为空
        return []
    except Exception:
        return []

    results = []
    for path, title, scenario, tags_str, snip, score in rows:
        tags = [t.strip() for t in tags_str.split() if t.strip()] if tags_str else []
        results.append(SearchResult(
            path=path,
            title=title or Path(path).stem,
            scenario=scenario or "",
            tags=tags,
            snippet=snip or "",
            score=float(score),
        ))
    return results
```

- [ ] **Step 4: 运行全部 kb_search 测试**

```bash
.venv/bin/python -m pytest tests/test_kb_search.py -v
```

期望：全部 PASS（预计 11 个测试）

- [ ] **Step 5: Commit**

```bash
git add kb_search.py tests/test_kb_search.py
git commit -m "feat: kb_search — search() FTS5 检索"
```

---

## Task 4：修改 `ai_reply.py` 接入两级检索

**Files:**
- Modify: `ai_reply.py`
- Modify: `tests/test_ai_reply.py`

- [ ] **Step 1: 写失败测试**

查看 `tests/test_ai_reply.py` 现有结构：

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py -v --collect-only 2>&1 | head -30
```

在 `tests/test_ai_reply.py` 末尾追加（不删除现有测试）：

```python
from kb_search import SearchResult
from ai_reply import build_reply_prompt


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
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py::test_build_reply_prompt_includes_candidate_docs_when_search_results_provided -v 2>&1 | head -20
```

期望：`TypeError: build_reply_prompt() got an unexpected keyword argument 'search_results'`

- [ ] **Step 3: 修改 `build_reply_prompt()` 加 `search_results` 参数**

将 `ai_reply.py` 中 `build_reply_prompt` 函数替换为：

```python
def build_reply_prompt(
    messages: list[dict],
    max_messages: int = 20,
    kb_enabled: bool = False,
    search_results=None,   # list[SearchResult] | None
) -> str:
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-max_messages:]
    transcript = "\n".join(_format_message(m) for m in selected)

    # 候选文档段落（两级检索时注入）
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
```

- [ ] **Step 4: 运行 build_reply_prompt 相关测试**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py -v -k "prompt"
```

期望：新增 3 个测试 PASS，现有 prompt 测试也全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ai_reply.py tests/test_ai_reply.py
git commit -m "feat: build_reply_prompt — 支持 search_results 候选文档注入"
```

---

## Task 5：修改 `generate_reply()` 接入两级检索

**Files:**
- Modify: `ai_reply.py`
- Modify: `tests/test_ai_reply.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_ai_reply.py` 末尾追加：

```python
from unittest.mock import patch, MagicMock
import subprocess


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
         patch("subprocess.run", return_value=fake_result) as mock_run:

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
         patch("subprocess.run", return_value=fake_result) as mock_run:

        config = AIReplyConfig(kb_enabled=True, kb_vault_path=vault)
        generate_reply(_make_msgs(), config)

    cmd = mock_run.call_args[0][0]
    assert "--add-dir" in cmd
    assert "--add-file" not in cmd
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py::test_generate_reply_uses_add_file_when_search_results_found -v 2>&1 | head -20
```

期望：测试失败（`--add-dir` 仍在命令中）

- [ ] **Step 3: 修改 `generate_reply()` 接入两级检索**

在 `ai_reply.py` 顶部 import 区域追加：

```python
import threading
```

将 `generate_reply` 函数中 KB 模式的命令构建部分替换为（替换从 `if config.kb_enabled:` 到 `else:` 的整个 if-else 块）：

```python
    # ── 两级检索 ──
    search_results = []
    use_add_dir = False

    if config.kb_enabled:
        # 后台异步增量更新索引（不等结果）
        threading.Thread(
            target=update_index,
            args=(config.kb_vault_path,),
            daemon=True,
        ).start()
        # 同步 FTS5 粗筛
        query = _extract_query(messages)
        search_results = search(query, config.kb_vault_path)
        if not search_results:
            use_add_dir = True  # 检索为空，降级

    prompt = build_reply_prompt(
        messages,
        max_messages=config.max_messages,
        kb_enabled=config.kb_enabled,
        search_results=search_results if search_results else None,
    )

    if config.kb_enabled:
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
```

同时在 `ai_reply.py` 顶部（import 区域之后）追加两个辅助函数：

```python
def _extract_query(messages: list[dict], n: int = 3) -> str:
    """取最后 n 条非空消息的内容拼成查询串。"""
    useful = [m for m in messages if str(m.get("content", "")).strip()]
    selected = useful[-n:]
    return " ".join(str(m.get("content", "")).strip() for m in selected)
```

以及在文件顶部的 import 中加入（放在现有 import 之后）：

```python
try:
    from kb_search import search, update_index
except ImportError:  # 单元测试 mock 时可能未安装
    def search(*args, **kwargs):  # type: ignore[misc]
        return []
    def update_index(*args, **kwargs):  # type: ignore[misc]
        return 0, 0
```

- [ ] **Step 4: 运行所有 ai_reply 测试**

```bash
.venv/bin/python -m pytest tests/test_ai_reply.py -v
```

期望：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add ai_reply.py tests/test_ai_reply.py
git commit -m "feat: generate_reply — 两级检索 FTS5→--add-file，空结果降级 --add-dir"
```

---

## Task 6：修改 `kb_writer.py` 存入后触发增量更新

**Files:**
- Modify: `kb_writer.py`
- Modify: `tests/test_kb_writer.py`（新增 1 个测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_kb_writer.py` 末尾追加：

```python
from unittest.mock import patch


def test_save_to_vault_triggers_update_index_in_background(tmp_path):
    """存入后应异步触发 update_index，不阻塞主线程。"""
    entry = KBEntry(
        title="测试",
        scenario="测试场景",
        tags=["测试"],
        reply="好的",
        source="企业微信",
        date="2026-06-07",
    )
    with patch("kb_writer.update_index") as mock_update:
        save_to_vault(entry, str(tmp_path))
        # 给后台线程一点时间运行
        import time; time.sleep(0.1)
        mock_update.assert_called_once_with(str(tmp_path))
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_kb_writer.py::test_save_to_vault_triggers_update_index_in_background -v 2>&1 | head -20
```

期望：`AssertionError: Expected call: update_index(...)` 或 `mock_update not called`

- [ ] **Step 3: 修改 `kb_writer.py`**

在 `kb_writer.py` 顶部追加 import：

```python
import threading

try:
    from kb_search import update_index as _update_index
except ImportError:
    def _update_index(*args, **kwargs):  # type: ignore[misc]
        pass
```

在 `save_to_vault()` 函数末尾、`return str(final_path)` 之前追加：

```python
    # 异步增量更新索引，确保刚写入的文件下次可被检索
    threading.Thread(
        target=_update_index,
        args=(vault_path,),
        daemon=True,
    ).start()
```

- [ ] **Step 4: 运行全部 kb_writer 测试**

```bash
.venv/bin/python -m pytest tests/test_kb_writer.py -v
```

期望：全部 PASS（包含新增测试）

- [ ] **Step 5: Commit**

```bash
git add kb_writer.py tests/test_kb_writer.py
git commit -m "feat: kb_writer — 存入后异步触发 update_index"
```

---

## Task 7：修改 `gui_panel.py` — 设置弹窗 rebuild 进度 + 状态行文件数

**Files:**
- Modify: `gui_panel.py`

（此任务为 GUI 改动，无单元测试；手动验证）

- [ ] **Step 1: 在 `gui_panel.py` 顶部 import 区域追加 kb_search 导入**

找到现有的 import 区域（靠近文件顶部），追加：

```python
try:
    from kb_search import rebuild_index as _kb_rebuild, get_db_path as _kb_get_db_path
    import sqlite3 as _sqlite3
except ImportError:
    _kb_rebuild = None
    _kb_get_db_path = None
    _sqlite3 = None
```

- [ ] **Step 2: 修改 `_update_kb_row()` 加文件数显示**

找到 `_update_kb_row` 方法（第 1123 行附近），将启用时的 label 文字从：

```python
self.kb_row_label.configure(
    text=f"📗 知识库已启用 · {vault_name}", text_color="#389e0d"
)
```

替换为：

```python
count_str = ""
if _kb_get_db_path and _sqlite3:
    try:
        db = _kb_get_db_path()
        if os.path.exists(db):
            conn = _sqlite3.connect(db)
            n = conn.execute("SELECT COUNT(*) FROM kb_meta").fetchone()[0]
            conn.close()
            count_str = f"  ({n} 条)"
    except Exception:
        pass
self.kb_row_label.configure(
    text=f"📗 知识库已启用 · {vault_name}{count_str}", text_color="#389e0d"
)
```

- [ ] **Step 3: 修改 `_show_ai_settings()` 保存逻辑，在路径变更时触发 rebuild**

找到 `_show_ai_settings` 方法中的保存按钮回调（约第 1240 行附近），找到调用 `save_config` 和 `_update_kb_row` 的位置，将保存逻辑包裹 rebuild 调用：

```python
def on_save():
    new_enabled = kb_var.get()
    new_path = path_var.get().strip()
    old_path = self._app_config.get("kb_vault_path", "")

    self._app_config["kb_enabled"] = new_enabled
    self._app_config["kb_vault_path"] = new_path
    save_config(self._app_config)
    self._update_kb_row()

    # 路径变更或首次启用时，重建索引
    if new_enabled and new_path and new_path != old_path and _kb_rebuild:
        win.destroy()
        self.root.attributes("-topmost", False)
        progress_win = ctk.CTkToplevel(self.root)
        progress_win.title("建立索引")
        progress_win.geometry("300x80")
        progress_win.resizable(False, False)
        progress_win.attributes("-topmost", True)
        lbl = ctk.CTkLabel(progress_win, text="正在建立知识库索引…")
        lbl.pack(expand=True)

        def do_rebuild():
            try:
                _kb_rebuild(new_path)
            except Exception:
                pass
            self.root.after(0, lambda: (
                progress_win.destroy(),
                self.root.attributes("-topmost", True),
                self._update_kb_row(),
            ))

        threading.Thread(target=do_rebuild, daemon=True).start()
    else:
        win.destroy()
        self.root.attributes("-topmost", True)
```

- [ ] **Step 4: 手动验证**

```bash
.venv/bin/python gui_panel.py
```

验证：
1. 打开设置 → 选择 vault 路径 → 保存 → 出现「正在建立知识库索引…」提示窗
2. 提示窗消失后，状态行显示 `📗 知识库已启用 · <vault名>  (N 条)`
3. 点击「读取并生成」→ 检查终端日志确认没有报错

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

期望：`OK`

- [ ] **Step 6: Commit**

```bash
git add gui_panel.py
git commit -m "feat: gui — 设置弹窗 rebuild 进度提示 + 状态行显示文件数"
```

---

## Task 8：全量测试 + 语法检查

**Files:** 无新文件

- [ ] **Step 1: 运行全部测试**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -30
```

期望：无 FAIL，所有 PASS 或 SKIP

- [ ] **Step 2: 语法检查所有修改文件**

```bash
.venv/bin/python -m py_compile kb_search.py ai_reply.py kb_writer.py gui_panel.py && echo "ALL OK"
```

期望：`ALL OK`

- [ ] **Step 3: 端到端快速冒烟**

```bash
# 建立测试 vault
mkdir -p /tmp/test_vault
cat > /tmp/test_vault/订单查询.md << 'EOF'
---
title: "订单查询"
scenario: "用户询问订单进度"
tags: ["订单", "客服"]
---
您好，我帮您查一下订单状态。
EOF

.venv/bin/python -c "
from kb_search import rebuild_index, search
count = rebuild_index('/tmp/test_vault')
print(f'索引了 {count} 个文件')
results = search('订单', '/tmp/test_vault')
print(f'检索到 {len(results)} 条结果')
for r in results:
    print(f'  {r.title} — {r.scenario}')
"
```

期望：
```
索引了 1 个文件
检索到 1 条结果
  订单查询 — 用户询问订单进度
```

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "test: 全量测试通过 + 冒烟验证"
```
