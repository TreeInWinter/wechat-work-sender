# 本地知识库集成设计文档

**日期**：2026-06-05  
**分支**：`feature/knowledge-base-optimization`  
**范围**：在 AI 回复生成流程中集成本地 Obsidian vault，通过 `--add-dir` 让 `mc --code` 直接读取知识库文件

---

## 背景与目标

当前 AI 回复生成（`ai_reply.py`）直接把聊天记录喂给 `mc --code`，没有任何领域知识支撑，回复质量依赖模型本身的泛化能力。

用户有本地 Obsidian vault，其中存有业务相关笔记、话术模板、FAQ 等。目标是：**在用户自愿启用的前提下，让 `mc --code` 能读取 vault 中的相关文档，生成更有依据的回复**。

---

## 设计决策

### 检索方式：`--add-dir`（方案 B）

放弃"本地关键词搜索 + 手动注入片段"的方案，改为将 vault 目录通过 `--add-dir <path>` 传给 `mc --code`，让模型自主决定读哪些文件。

- 无需维护本地搜索/向量化逻辑
- vault 更新后无需重新索引
- `--tools ""` 限制需同步移除，使 mc 获得文件读取能力
- 未启用时行为完全不变，向后兼容

---

## 文件改动清单

### 1. 新增：`config.py`

统一管理应用配置的读写，存储路径与 `phrases.json` 相同（`~/Library/Application Support/wechat-sender/`）。

```
配置文件路径：~/Library/Application Support/wechat-sender/config.json
```

Schema：
```json
{
  "kb_enabled": false,
  "kb_vault_path": ""
}
```

对外接口：
- `load_config() -> dict`：读取配置，文件不存在时返回默认值
- `save_config(data: dict) -> None`：写入配置

### 2. 修改：`ai_reply.py`

**`AIReplyConfig` 新增字段**：
```python
kb_enabled: bool = False
kb_vault_path: str = ""
```

**`generate_reply` 逻辑变更**：

KB 未启用（现有行为不变）：
```
mc --code -p --tools "" --no-session-persistence <prompt>
```

KB 启用时：
```
mc --code -p --add-dir <vault_path> --no-session-persistence <prompt>
```

注意：KB 启用时去掉 `--tools ""`，使 mc 能读取文件。

**`build_reply_prompt` 变更**：当 `kb_enabled=True` 时，在 prompt 开头追加知识库引导段：
```
你可以访问本地知识库目录中的文档。请先根据聊天内容在知识库中检索相关文档，
结合检索结果和聊天上下文，生成一段可以直接发送的中文回复。
```

### 3. 修改：`gui_panel.py`

**Header 新增 ⚙ 按钮**：
- 位置：`status_frame` 最右侧（`↻` 刷新按钮左边）
- 样式：半透明白色背景，与现有 Header 按钮风格一致
- 点击：调用 `_show_ai_settings()`

**新增 `_show_ai_settings()` 方法**：
- 弹出 `CTkToplevel` 设置窗口（需临时关闭 `topmost` 再恢复，参照现有弹窗惯例）
- 内容：
  - `CTkSwitch`：启用知识库（绑定 `kb_enabled`）
  - 路径显示框（`CTkEntry`，只读）+ "浏览…" 按钮（调用 `filedialog.askdirectory()`）
  - 保存 / 取消按钮
- 保存时：写入 `config.json`，更新内存中的配置

**AI 视图新增知识库状态行**（位于两个主按钮下方）：
- 启用时：绿色背景 + `📗 知识库已启用 · <vault 名>`
- 未启用时：浅灰 + `📂 知识库未启用`
- 点击状态行可直接打开设置弹窗

**`_ai_generate_async` 变更**：
- 生成前从内存配置读取 `kb_enabled` / `kb_vault_path`
- 构造对应的 `AIReplyConfig` 传入 `generate_reply`

---

## 数据流

```
用户点击"读取并生成"
  ↓
读取内存配置（kb_enabled, kb_vault_path）
  ↓
构造 AIReplyConfig（含 KB 参数）
  ↓
kb_enabled=True?
  ├─ Yes → args = ["--code", "-p", "--add-dir", vault_path, "--no-session-persistence"]
  │         prompt 前置知识库引导段
  └─ No  → args = ["--code", "-p", "--tools", "", "--no-session-persistence"]（原行为）
  ↓
subprocess 调用 mc <args> <prompt>
  ↓
mc 自行检索 vault 中相关 .md 文件，结合生成回复
  ↓
回复写入候选回复文本框
```

---

## 边界情况

| 情况 | 处理方式 |
|------|---------|
| vault 路径为空但 KB 已启用 | 保存时校验，路径为空则禁止启用，提示用户先选择路径 |
| 路径不存在 | `generate_reply` 前校验，抛 `AICommandFailedError`，状态栏显示错误信息 |
| mc 读取 vault 超时 | 沿用现有 `AICommandTimeoutError`，超时 60s |
| 用户取消文件夹选择 | 不修改路径，保持原值 |

---

## 验证方式

1. 启动应用，点击 ⚙ 按钮，确认弹窗正常显示
2. 选择一个本地文件夹，保存后状态行变绿
3. 重启应用，确认配置持久化（路径和开关恢复）
4. 在 AI 助手视图点击"读取并生成"，确认命令行中出现 `--add-dir <vault>`
5. 关闭 KB 开关，再次生成，确认命令回退到 `--tools ""`
6. vault 路径填非法路径，确认状态栏显示友好错误
