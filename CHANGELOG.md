# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0.0] - 2026-06-07

### Added

- **知识库两级检索**：新增 `kb_search.py` 模块，基于 SQLite FTS5 trigram 全文索引，AI 生成回复时先本地粗筛 Top-15 候选文档（`--add-file`），空结果自动降级为全目录上下文（`--add-dir`），支持 500–2000 文件规模下低延迟检索
- **中文子串搜索**：FTS5 使用 trigram tokenizer，支持连续汉字子串匹配；2 字短词通过 LIKE 兜底，覆盖常见中文 2 字词组
- **增量索引更新**：`update_index()` 基于文件 mtime 做增量扫描，存入知识库后后台自动触发；`rebuild_index()` 带崩溃哨兵文件，进程中断后下次自动全量重建
- **多 vault 隔离**：`search()` 按 vault 路径前缀过滤，多知识库配置互不干扰
- **并发写保护**：模块级 `threading.Lock` 防止多个后台线程并发写同一 SQLite db

### Changed

- **知识库设置弹窗 UX**：
  - 弹窗改为居中叠放在主窗口上，消除初始位置闪烁（`withdraw` → 定位 → `deiconify`）
  - 新增「重建索引」按钮，原地显示进度（重建中按钮禁用 + 完成/失败状态提示），不关闭设置窗口
  - 状态行显示当前 vault 已索引文件数
  - 保存时自动判断是否需要重建：路径变更或 vault 从未被索引时触发
- **`build_reply_prompt()`** 支持 `search_results` 参数，将候选文档列表注入提示词，引导 AI 精选后精读
- **`kb_writer.save_to_vault()`** 存入后异步触发增量索引更新

### Fixed

- SQLite 连接泄漏：`_vault_is_indexed` / `_update_kb_row` 改用 `try/finally`，异常时不漏句柄
- `_start_rebuild_ui` 异常静默吞噬：重建失败时弹窗显示红色错误信息，不再假装成功
- FTS5 查询词未加引号：`()+-*^:` 等特殊字符会触发 `OperationalError` 静默返回空，改为每词包裹双引号
- 后台 daemon 线程无异常捕获：vault 被删或 db 锁定时 stack trace 漏到 stderr，补 `try/except` 静默处理
- 测试：`test_kb_enabled_uses_add_dir_and_no_tools_flag` 未隔离全局 db，补 mock；两个 patch 目标从 `subprocess.run` 改为 `ai_reply.subprocess.run`
- `AIEmptyResponseError` 调试命令改用实际构建的 cmd，不再显示错误的 `config.args`
