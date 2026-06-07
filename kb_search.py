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
