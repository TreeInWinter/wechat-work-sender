# Changelog

All notable changes to this project will be documented in this file.

## [1.3.0.0] - 2026-06-09

### Added
- **AX 结构探针 + 启动自检（稳健性）**：新增 `im_clients/probes.py`
  - 把散落在 `sender.py`/`daxiang.py`/`wechat.py` 的 AX depth 魔法数收敛到 `PROBES` 字典（单一事实来源）
  - `run_self_check()` / `run_probe()`：BFS 验证各客户端输入框/消息节点是否仍在预期 depth，
    客户端更新致结构变化时返回 `degraded`，提前发现「发不出/读不到」
  - 状态区分 `ok`/`degraded`/`no_window`/`no_permission`（`kAXErrorAPIDisabled=-25211`）/`not_running`
  - GUI 状态栏新增 🩺 自检按钮（手动全量检查 + 弹窗汇总）
  - 启动后 1.2s 被动自检（不激活、不抢焦点）：仅对权限缺失 / 微信窗口不可达等
    「与激活无关的确定问题」在状态栏提示，避免误报
- 测试：`tests/test_probes.py`（分类逻辑、配置完整性、run_probe 各状态分支）

### Changed
- `sender.py`/`daxiang.py`/`wechat.py` 的 AX depth 常量改为从 `probes.PROBES` 读取，行为不变
- `probes.py` 在模块级导入 AX 符号，便于自检逻辑被单测 patch

## [1.2.0.0] - 2026-06-09

### Added
- **AI 草稿对话式微调**：候选回复区新增「一键改写」栏
  - 三个预设：更正式 / 更简短 / 换个说法（`ai_reply.REFINE_PRESETS`）
  - 自定义修改要求输入框 + 应用按钮（支持回车提交），如「加上歉意、更口语化」
  - 以当前文本框内容为基准改写，支持多轮链式微调（改写结果可继续再改）
  - `ai_reply.refine_reply()` / `build_refine_prompt()`：改写走纯文本模式（不读知识库），低延迟
- 测试：`tests/test_ai_reply.py` 新增 `BuildRefinePromptTests` / `RefineReplyTests`（含空草稿、空要求、超时、命令缺失、不读 KB 等用例）

### Changed
- 抽出 `ai_reply._invoke_ai()` 统一 AI 命令调用与错误处理（generate/refine 共用错误语义）
- 生成中（生成/改写）时改写按钮统一禁用，完成后恢复

## [1.1.0.0] - 2026-06-09

### Fixed
- **微信消息读取真机修复（核心）**：此前 OCR 在真机上中文 0 识别，根因为 Vision 配置：
  - `VNRecognizeTextRequest` 默认 revision=1 **只支持 en-US**，改为显式取最高可用 revision（≥2 才支持 zh-Hans）
  - macOS 26 上 Accurate（level=1）中文模型损坏（全乱码、置信度恒 0.30/0.50），改用 Fast（level=0），置信度回到 1.00
  - 截图从 `kCGWindowListOptionAll`+矩形（会截到遮挡窗口）改为按窗口 ID `kCGWindowListOptionIncludingWindow`，只截微信窗口
  - 新增 `_filter_chat_area`：按 x 过滤左侧会话列表（避免名字/时间戳污染），并把面板内坐标归一化后再解析

### Changed
- 微信窗口发现从 AX（需「辅助功能」权限，独立运行时常报 `kAXErrorAPIDisabled`）改为 `find_main_window()`（CGWindowList，仅需「屏幕录制」权限）
- `wechat.py` 读取链路不再依赖 `_get_window_bounds()`（AX），由 `wechat_ocr` 内部自行发现窗口
- `tools/debug_ocr.py` 同步改用 Fast + revision，调试输出与线上行为一致
- `_obs_to_dict` 增加 `confidence` 字段，低于阈值的 OCR 噪声在 `_filter_chat_area` 中丢弃

### Added
- 微信（个人版）`can_read_chat=True`，README 支持表更新为读取 ✅
- `tests/test_wechat_ocr.py` 新增 `_filter_chat_area` 测试（侧边栏过滤 / 归一化 / 低置信 / 标题输入框过滤）

## [1.0.1.0] - 2026-06-08

### Changed
- 云端知识库问答从远程 CatPaw Agent（`hss-kb ask sync`，需服务端权限）改为本地执行：
  用 `hss-kb query` 预取 Top 3 相关文档，再由 `claude --dangerously-skip-permissions`
  本地推理生成答案，端到端约 24 秒，无需任何服务端权限
- `ai_reply.generate_reply()` 在 cloud 模式下直接返回 `query_cloud` 的答案，
  不再二次调用 mc，减少一次 LLM 调用延迟

### Added
- `hss_kb_client`: 新增 `_resolve_kb_root`（自动读取 kb-router.json 解析知识库路径）、
  `_fetch_top_docs`（预读 Top N 文档内容注入 prompt）、`_claude_bin`（定位 claude CLI）

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
