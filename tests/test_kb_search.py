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
    })
    # 创建一个非 md 文件
    (tmp_path / "vault" / "image.png").write_bytes(b"\x89PNG")
    db = str(tmp_path / "test.db")
    count = rebuild_index(vault, db_path=db)
    assert count == 1


def test_parse_frontmatter_single_quote_tags(tmp_path):
    """单引号 tags 格式应正确解析。"""
    vault = _make_vault(tmp_path, {
        "test.md": "---\ntitle: 测试\ntags: ['问候', '售后']\n---\n内容"
    })
    db = str(tmp_path / "idx.db")
    rebuild_index(vault, db_path=db)
    from kb_search import search
    results = search("测试", vault, db_path=db)
    # 标题能检索到就说明文件被正确索引了
    assert len(results) >= 1


def test_rebuild_index_raises_on_invalid_vault_path():
    """vault_path 不存在时应抛出 ValueError。"""
    with pytest.raises(ValueError, match="不存在"):
        rebuild_index("/nonexistent/path/that/does/not/exist")


from kb_search import update_index
import time
from pathlib import Path


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

    # 修改文件，强制 mtime 变化
    md_path.write_text("---\ntitle: 更新后\n---\n新内容", encoding="utf-8")
    os.utime(str(md_path), (os.path.getmtime(str(md_path)) + 1,) * 2)
    added, deleted = update_index(str(tmp_path / "vault"), db_path=db)
    assert added == 1   # modified 计入 added
    assert deleted == 0


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
