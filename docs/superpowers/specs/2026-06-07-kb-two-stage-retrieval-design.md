# 知识库两级检索优化设计

**日期**：2026-06-07  
**状态**：待实施  
**背景**：当前知识库检索使用 `--add-dir <vault_path>` 将整个 vault 目录暴露给 Claude，随着文件数增长（目标规模 500~2000 个），Claude 需要先列举整个目录再自主决定读哪些文件，效率低且延迟高。本设计引入两级检索架构来解决这一问题。

---

## 1. 整体架构

### 当前流程

```
聊天消息 → build_reply_prompt() → mc --add-dir <vault> → Claude 自主遍历 → 回复
```

### 新流程（两级检索）

```
聊天消息
  ↓
[第一级] kb_search.py：FTS5 粗筛
  → 提取查询关键词（最后 3 条消息）
  → SQLite FTS5 检索 → Top-15 命中文件
  → 读取每个文件的摘要（frontmatter + 前 100 字）
  ↓
[第二级] ai_reply.py：把 Top-15 摘要列表注入 prompt
  → Claude 从中精选 3~5 个文件，再精读全文
  → 生成最终回复
  ↓
回复展示
```

**关键变化**：
- 新增 `kb_search.py` 模块，负责索引维护和两级检索
- `ai_reply.py` 的 `build_reply_prompt()` 增加 `search_results` 参数接收预检索结果
- 不再使用 `--add-dir`，改为只把 Top-15 文件路径通过 `--add-file` 传给 Claude
- `generate_reply()` 在调用前先执行 FTS5 检索，检索为空或出错时降级为 `--add-dir`

---

## 2. `kb_search.py` 模块

### 索引结构（SQLite FTS5）

```sql
CREATE VIRTUAL TABLE kb_fts USING fts5(
    path UNINDEXED,  -- 文件绝对路径（不参与搜索，用于取回）
    title,       -- YAML frontmatter: title
    tags,        -- YAML frontmatter: tags（join 成空格分隔字符串）
    scenario,    -- YAML frontmatter: scenario（适用场景）
    body,        -- 正文前 500 字
    tokenize="unicode61"  -- 支持中文
);

CREATE TABLE kb_meta (
    path TEXT PRIMARY KEY,
    mtime REAL   -- 文件修改时间，用于增量更新检测
);
```

**索引文件位置**：`~/.cache/wechat-sender/kb_index.db`  
（不放在 vault 里，避免 Obsidian 索引到它）

### 公开接口

```python
@dataclass
class SearchResult:
    path: str        # 文件绝对路径
    title: str
    scenario: str
    tags: list[str]
    snippet: str     # FTS5 snippet()，高亮命中词
    score: float     # BM25 得分

def rebuild_index(vault_path: str) -> int:
    """全量重建索引，返回已索引文件数"""

def update_index(vault_path: str) -> tuple[int, int]:
    """增量更新：扫描 mtime 变化，返回 (新增/更新数, 删除数)"""

def search(query: str, vault_path: str, top_k: int = 15) -> list[SearchResult]:
    """FTS5 检索，返回 Top-K 结果；出错时返回空列表"""
```

---

## 3. Prompt 注入与 Claude 精选

### `build_reply_prompt()` 变化

新增 `search_results: list[SearchResult] = None` 参数。当传入非空结果时，在 prompt 中插入候选文档段落：

```
以下是从知识库中预检索到的候选文档（按相关度排序），
请从中选择 3~5 个你认为最相关的文件精读后再生成回复。
如果这些文档都不相关，可以不参考。

【候选文档】
1. 订单查询处理.md
   场景：用户询问订单处理进度
   标签：订单 客服 SOP
   摘要：您好，我帮您查一下...

2. 退款流程说明.md
   ...
```

### `generate_reply()` 新流程

```python
def generate_reply(messages, config=None):
    search_results = []
    use_add_dir = False

    if config.kb_enabled and config.kb_vault_path:
        # 后台异步增量更新索引（不等结果）
        threading.Thread(target=update_index, args=(config.kb_vault_path,)).start()
        # 同步检索 Top-15
        query = _extract_query(messages)  # 取最后 3 条消息拼成查询串
        search_results = search(query, config.kb_vault_path, top_k=15)
        if not search_results:
            use_add_dir = True  # 检索为空，降级

    prompt = build_reply_prompt(messages, search_results=search_results)

    cmd = ["mc", "--code", "-p", "--no-session-persistence"]
    if config.kb_enabled and config.kb_vault_path:
        if use_add_dir:
            cmd += ["--add-dir", config.kb_vault_path]
        else:
            for r in search_results:
                cmd += ["--add-file", r.path]
    else:
        cmd += ["--tools", ""]
    ...
```

---

## 4. 索引触发时机

| 时机 | 动作 | 方式 |
|------|------|------|
| 首次启用知识库 | `rebuild_index()` | 阻塞 + GUI 进度提示 |
| 修改 vault 路径 | `rebuild_index()` | 阻塞 + GUI 进度提示 |
| 每次生成回复前 | `update_index()` | 后台线程，不阻塞生成 |
| 存入知识库后 | `update_index()` | 后台线程，不阻塞 |

---

## 5. GUI 变化

**设置弹窗**：保存 vault 路径时，显示「正在建立索引…」，`rebuild_index()` 完成后自动关闭。

**知识库状态行**：增加索引文件数显示：
```
📗 知识库已启用 · 日常工作杂记  (342 条)
```

**错误处理**：所有 FTS5 错误静默降级，不影响生成回复流程。

---

## 6. 降级逻辑

| 情况 | 降级行为 | 原因 |
|------|----------|------|
| 索引不存在（首次启用未完成） | `--add-dir <vault>` | 文件数少，当前行为可接受 |
| 索引存在但 `update_index()` 未完成 | 使用旧索引（不降级） | 增量更新，旧索引仍有效 |
| FTS5 检索出错 | `--add-dir <vault>` + log warning | 数据库损坏等异常 |
| FTS5 返回空结果 | `--add-dir <vault>` | 查询词与 vault 差异大，让 Claude 自主遍历更好 |

---

## 7. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `kb_search.py` | **新增** | FTS5 索引 + 检索模块 |
| `ai_reply.py` | **修改** | `generate_reply()` 接入两级检索；`build_reply_prompt()` 增加 `search_results` 参数 |
| `gui_panel.py` | **修改** | 设置弹窗加进度提示；状态行加文件数显示 |
| `config.py` | **不变** | 现有 `kb_enabled` / `kb_vault_path` 字段已够用 |
| `kb_writer.py` | **微改** | `save_to_vault()` 完成后触发 `update_index()` |

---

## 8. 验证方法

1. **单元测试**：`tests/test_kb_search.py`
   - `rebuild_index()` 正确索引 markdown 文件
   - `update_index()` 只处理 mtime 变化的文件
   - `search()` 能按关键词、标签、场景命中正确文件
   - `search()` 在数据库不存在时返回空列表（不抛异常）

2. **端到端测试**：
   - 启用知识库 → 点击「读取并生成」→ 确认 prompt 中出现候选文档列表
   - vault 路径为空 → 确认降级到 `--add-dir` 或 `--tools ""`
   - 删除 `kb_index.db` → 确认降级到 `--add-dir`

3. **性能验证**：
   - 用 500 个 markdown 文件测试 `search()` 延迟 < 100ms
