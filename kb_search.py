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
import threading
from dataclasses import dataclass, field
from pathlib import Path

# 所有写操作（rebuild / update）共享同一把锁，防止多个 daemon 线程并发写 db
_write_lock = threading.Lock()


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
            tokenize="trigram"
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
                # 支持双引号、单引号、裸值三种格式
                items = re.findall(r'["\']([^"\']+)["\']', v)
                if not items:  # 裸值如 [a, b, c]
                    items = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
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


def _sentinel_path(db_path: str) -> str:
    """重建哨兵文件路径：db 存在但该文件也存在，说明上次重建中途崩溃。"""
    return db_path + ".rebuilding"


def rebuild_index(vault_path: str, db_path: str | None = None) -> int:
    """全量重建索引。返回已索引文件数。
    使用哨兵文件保证原子性：重建开始前写 <db>.rebuilding，成功后删除；
    下次 update_index 检测到哨兵文件会强制重走 rebuild_index。
    使用 _write_lock 避免多线程并发写同一 db。
    """
    if not os.path.isdir(vault_path):
        raise ValueError(f"vault_path 不存在或不是目录: {vault_path}")
    db_path = db_path or get_db_path()
    with _write_lock:
        return _rebuild_index_locked(vault_path, db_path)


def _rebuild_index_locked(vault_path: str, db_path: str) -> int:
    """rebuild_index 的实际实现（调用方已持有 _write_lock）。"""
    sentinel = _sentinel_path(db_path)
    Path(sentinel).touch()       # 写入哨兵：标记重建进行中
    conn = _open_db(db_path)
    try:
        # DROP 旧 FTS 表后重建，确保 tokenizer 设置生效
        conn.executescript("""
            DROP TABLE IF EXISTS kb_fts;
            DROP TABLE IF EXISTS kb_meta;
        """)
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
                tokenize="trigram"
            );
        """)
        conn.commit()

        count = 0
        for root, _, files in os.walk(vault_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                _index_file(conn, os.path.join(root, fname))
                count += 1
        conn.commit()
        Path(sentinel).unlink(missing_ok=True)  # 删除哨兵：重建成功
        return count
    finally:
        conn.close()
        # 异常时哨兵保留，下次 update_index 检测到后会触发重建


def update_index(vault_path: str, db_path: str | None = None) -> tuple[int, int]:
    """增量更新索引。返回 (新增/更新数, 删除数)。使用 _write_lock 防止并发写冲突。"""
    db_path = db_path or get_db_path()
    if not os.path.isdir(vault_path):
        raise ValueError(f"vault_path 不存在或不是目录: {vault_path}")

    with _write_lock:
        # db 不存在，或上次 rebuild 中途崩溃（哨兵文件存在），走全量重建
        if not os.path.exists(db_path) or os.path.exists(_sentinel_path(db_path)):
            count = _rebuild_index_locked(vault_path, db_path)
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


def _like_search(
    conn: sqlite3.Connection,
    term: str,
    top_k: int,
) -> list[tuple]:
    """用 LIKE 实现子串匹配，供短查询（< 3 字）兜底。
    注意：FTS5 虚拟表不支持无 MATCH 的普通 WHERE 过滤，
    结果的 vault_prefix 过滤在调用方 Python 侧完成。
    """
    pat = f"%{term}%"
    return conn.execute(
        """
        SELECT path, title, scenario, tags,
               SUBSTR(body, 1, 120) AS snip,
               1.0 AS score
        FROM kb_fts
        WHERE title LIKE ? OR tags LIKE ? OR scenario LIKE ? OR body LIKE ?
        LIMIT ?
        """,
        (pat, pat, pat, pat, top_k),
    ).fetchall()


def search(
    query: str,
    vault_path: str,
    top_k: int = 15,
    db_path: str | None = None,
) -> list[SearchResult]:
    """FTS5 trigram 检索，返回 Top-K 结果。
    - 只返回 vault_path 下的文件（防止多 vault 互相干扰）
    - 3 字以上词：FTS5 MATCH + path 前缀过滤
    - 不足 3 字：LIKE 兜底（同样带 path 前缀过滤）
    - db 不存在或出错时返回空列表。
    """
    db_path = db_path or get_db_path()
    if not os.path.exists(db_path):
        return []

    # 清理特殊字符（trigram 模式下引号会造成语法错误）
    safe_query = query.replace('"', " ").replace("'", " ").strip()
    if not safe_query:
        return []

    vault_prefix = vault_path.rstrip("/") + "/"

    try:
        conn = _open_db(db_path)
        try:
            rows: list[tuple] = []
            # trigram 要求每个 term 至少 3 字符；提取满足条件的词
            terms = safe_query.split()
            fts_terms = [t for t in terms if len(t) >= 3]

            if fts_terms:
                # 每个词用双引号包裹，防止 ()+-*^: 等 FTS5 特殊字符触发语法错误
                fts_query = " ".join(f'"{t}"' for t in fts_terms)
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
                        (fts_query, top_k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                # vault 过滤在 Python 侧完成（FTS5 虚拟表不支持无 MATCH 的 WHERE path LIKE）
                rows = [r for r in rows if r[0].startswith(vault_prefix)]

            # 对长度不足 3 的词补充 LIKE 搜索（结果同样在 Python 侧按 vault 过滤）
            short_terms = [t for t in terms if 0 < len(t) < 3]
            existing_paths = {r[0] for r in rows}
            for st in short_terms:
                for row in _like_search(conn, st, top_k):
                    if row[0].startswith(vault_prefix) and row[0] not in existing_paths:
                        rows.append(row)
                        existing_paths.add(row[0])

        finally:
            conn.close()
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
    return results[:top_k]
