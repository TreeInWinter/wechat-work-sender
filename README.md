# IM 快捷发送面板 (macOS)

macOS 辅助工具，通过 Accessibility API 自动化多款 IM 客户端，提供话术快捷发送、聊天内容读取和 AI 回复生成。**不修改客户端进程，不走网络接口**，纯系统级 API。

---

## 支持的 IM 客户端

| 客户端 | 发送 | 读取聊天记录 | 备注 |
|--------|------|------------|------|
| 企业微信 | ✅ | ✅ | 主力支持 |
| 大象（美团内部） | ✅ | ✅ | WebView 渲染 |
| 微信（个人版） | ✅ | ❌ | Qt 渲染，坐标点击 |

---

## 主要功能

### 话术面板
- 分组管理常用话术，一键发送
- 支持变量模板：`{{客户名}}`、`{{订单号}}`，`{{日期}}`/`{{时间}}`/`{{星期}}` 自动填充
- 支持图文连续发送（按顺序发送文字与图片；企业微信 regular chat 不支持单条图文混排消息）
- 搜索过滤 + 键盘快捷键（`⌘F` 聚焦搜索，`⌘↩` 发送自定义消息，`⌘1`–`⌘9` 快速发送）

### AI 回复助手
- 读取当前聊天窗口最近消息，调用 `mc --code` 生成候选回复
- 候选回复在面板展示，支持编辑、复制、清空、重新生成后再发送
- 支持接入本地 Obsidian 知识库（`--add-dir`），让 AI 参考领域文档生成更有依据的回复

### 知识库捕获（新）
- AI 视图新增「💾 存入知识库」按钮，将优质回复存入 Obsidian vault
- 点击后 AI 自动提炼结构化字段（标题、适用场景、标签），弹出可编辑弹窗确认
- 保存为带 YAML frontmatter 的 `.md` 文件，自动记录来源客户端，可在 Obsidian 中按标签检索
- 形成「AI 参考知识库生成回复 → 好回复存回知识库」双向闭环

---

## 前置要求

- macOS 10.15+
- Python 3.10+（带 Tk 支持，推荐 Miniconda `3.13`）
- 在「系统设置 → 隐私与安全性 → 辅助功能」中授权终端 / IDE

---

## 安装

```bash
uv venv
uv pip install -r requirements.txt
```

---

## 使用

```bash
# 启动 GUI 面板
.venv/bin/python gui_panel.py

# 或使用启动脚本
./start.sh
```

**知识库配置**：启动后点击 AI 助手视图右上角 ⚙，选择本地 Obsidian vault 文件夹并启用知识库。

---

## 打包（Apple Silicon .dmg）

```bash
./build.sh
```

输出 `dist/wechat-sender.dmg`。安装与 Gatekeeper 说明见 [`docs/install-guide.md`](docs/install-guide.md)。

---

## 项目结构

```
gui_panel.py      # CustomTkinter GUI（话术面板 + AI 助手 + 知识库）
sender.py         # 企业微信 AX API 核心（发送 / 读取 / 截图）
ai_reply.py       # AI 回复生成 + KB 条目提炼
kb_writer.py      # KB 条目写入 Obsidian vault
config.py         # 应用配置读写（config.json）
phrases.json      # 话术数据
im_clients/       # IM 适配器（企业微信 / 微信 / 大象）
tools/            # 调试工具（AX 树探测、OCR）
docs/             # 技术文档 / 设计文档 / 安装指南
```

---

## 安全提醒

- 本工具仅供学习和内部提效，请勿用于骚扰或违规群发
- 企业微信等客户端可能检测异常发送行为，请控制频率
