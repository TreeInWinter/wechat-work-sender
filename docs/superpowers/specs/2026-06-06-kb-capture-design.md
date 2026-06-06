# KB Capture：聊天回复 → Obsidian 知识库 设计文档

**日期**：2026-06-06
**分支**：`feature/knowledge-base-optimization`
**范围**：在 AI 回复生成流程中，为用户提供将候选回复结构化存入本地 Obsidian vault 的能力，形成"KB 增强生成 → 人工确认 → 好答案回流 KB"的双向闭环。

---

## 背景与目标

当前知识库集成（`--add-dir` 模式）已实现"KB → AI 回复"单向流动。用户反馈的两个核心痛点：

1. **重复回答同类问题**——没有复用机制
2. **好答案随聊天消失**——有价值的回复没有被沉淀

目标：在 AI 视图增加「存入知识库」入口，将高质量候选回复以结构化方式写入 Obsidian vault，使其在下次 AI 生成时能被检索到，形成正向积累。

---

## 设计决策

### 触发方式：手动按钮，不自动存

用户主动决定哪条回复值得保存，避免 vault 被低质回复污染。按钮与「确认发送」并列、互相独立——存档不等于发送。

### 内容结构：AI 提炼 + 可编辑弹窗（方案 B+C）

点击后先触发一次 AI 提炼调用（~5s），输出标题、场景、标签的 JSON 预填弹窗；用户可以在弹窗中修改任意字段后再保存。AI 提炼失败/超时时弹窗照常出现，字段留空供用户手填，不阻断操作。

### 来源标识：自动写入，只读

保存时从当前激活的 IM adapter（`display_name`）读取来源（企业微信 / 微信 / 大象），写入 YAML `source` 字段，弹窗中只读展示，不允许用户修改。

---

## 文件改动清单

### 1. 新增 `kb_writer.py`

单一职责：将 `KBEntry` 序列化为带 YAML frontmatter 的 `.md` 文件，写入 vault。

**数据模型**：
```python
@dataclass
class KBEntry:
    title: str
    scenario: str       # 适用场景
    tags: list[str]
    reply: str
    source: str         # IM 来源（企业微信 / 微信 / 大象）
    date: str           # YYYY-MM-DD
```

**对外接口**：
```python
def save_to_vault(entry: KBEntry, vault_path: str) -> str:
    """
    将 entry 写入 <vault_path>/IM回复记录/ 目录。
    文件名：YYYY-MM-DD-<title>.md
    同名冲突时自动追加时间戳后缀，不覆盖。
    返回最终写入的文件路径。
    """
```

**输出文件格式**（YAML frontmatter + Markdown body）：
```markdown
---
title: 订单查询 - 24小时反馈流程
date: 2026-06-06
tags: [订单, 客服, SOP]
source: 企业微信
---

## 适用场景
用户询问订单处理进度或等待时限

## 标准回复
您好，关于这个问题，我们的标准处理流程是先核实订单信息，然后在24小时内反馈处理结果。
```

存储路径：`<vault_path>/IM回复记录/`（目录不存在时自动创建）。

---

### 2. 修改 `ai_reply.py`

**新增 `extract_kb_entry()` 函数**：

```python
def extract_kb_entry(
    messages: list[dict],
    reply: str,
    config: AIReplyConfig | None = None,
) -> dict | None:
    """
    根据聊天记录和候选回复，提炼结构化 KB 条目字段。
    返回 {"title": ..., "scenario": ..., "tags": [...]}。
    解析失败或超时时返回 None（调用方降级为空字段）。
    """
```

提炼 prompt 要求模型只输出 JSON，不输出任何其他内容，便于解析。

提炼命令与 generate_reply 共用 `AIReplyConfig`；KB 模式下不传 `--add-dir`（提炼任务不需要读 vault）。

---

### 3. 修改 `gui_panel.py`

**AI 视图新增「💾 存入知识库」按钮**：
- 位置：「✅ 确认发送」右侧
- 候选回复文本框为空时 disabled
- 点击后在后台线程调用 `extract_kb_entry()`，按钮文案变为旋转动效（复用现有 `_ai_generate_async` 的动效模式）

**新增 `_show_kb_save_dialog(entry_dict, source_name)` 方法**：
- 弹出 `CTkToplevel`（临时关闭 topmost，参照现有弹窗惯例）
- 五个字段：
  | 字段 | 类型 | 初始值 |
  |------|------|--------|
  | 标题 | 可编辑 `CTkEntry` | AI 提炼结果或空 |
  | 适用场景 | 可编辑 `CTkTextbox`（两行） | AI 提炼结果或空 |
  | 标签 | 可编辑 `CTkEntry`（逗号分隔） | AI 提炼结果或空 |
  | 回复内容 | 可编辑 `CTkTextbox` | 候选回复原文 |
  | 来源 | 只读 `CTkLabel` | 当前 adapter.display_name |
- 保存前校验：标题不能为空
- 点「保存到 Vault」→ 调用 `kb_writer.save_to_vault()`
- 成功后状态栏短暂显示「✅ 已存入知识库：<文件名>」

---

## 数据流

```
用户点击「💾 存入知识库」
  ↓
后台线程：extract_kb_entry(messages, reply, config)
  ├─ 成功 → dict {"title", "scenario", "tags"}
  └─ 失败/超时 → None（降级为空字段）
  ↓
主线程：_show_kb_save_dialog(entry_dict, adapter.display_name)
  ↓
用户编辑 / 确认
  ↓
kb_writer.save_to_vault(KBEntry(...), vault_path)
  ↓
状态栏显示「✅ 已存入知识库：<文件名>」
```

---

## 边界情况

| 情况 | 处理方式 |
|------|---------|
| AI 提炼超时（>10s） | 弹窗照常弹出，字段留空，用户手填 |
| AI 输出不是合法 JSON | 同上，降级为空字段 |
| Vault 路径未配置 | 点击按钮时弹 warning："请先在 ⚙ 设置中配置知识库路径" |
| 标题为空就点保存 | 弹窗内校验，提示"标题不能为空" |
| 同名文件已存在 | 文件名追加 `-<HHmmss>` 时间戳后缀，不覆盖 |
| 候选回复为空 | 按钮 disabled，不可点击 |
| Vault 目录不存在 | `save_to_vault` 自动创建 `IM回复记录/` 目录 |

---

## 验证方式

1. 候选回复为空时，「💾 存入知识库」按钮呈 disabled 状态
2. 有候选回复时点击按钮，按钮出现旋转动效（~5s）
3. 弹窗出现，字段已由 AI 预填
4. 修改标题后点"保存到 Vault"，在 vault 的 `IM回复记录/` 目录下出现对应 `.md` 文件
5. 文件内容包含正确的 YAML frontmatter（含 `source` 字段）
6. vault 未配置时点击按钮，显示友好提示
7. 标题留空点保存，弹窗内报错提示
8. 连续保存同标题两次，第二个文件自动加时间戳后缀
