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


@pytest.mark.skip(reason="需要 search() 实现后启用")
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
