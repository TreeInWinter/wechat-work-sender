# IM 快捷发送面板 (macOS)

macOS 辅助工具，通过 Accessibility API 自动化多款 IM 客户端，提供话术快捷发送、聊天内容读取和 AI 回复生成。**不修改客户端进程，不走网络接口**，纯系统级 API。

---

## 支持的 IM 客户端

| 客户端 | 发送 | 读取聊天记录 | 备注 |
|--------|------|------------|------|
| 企业微信 | ✅ | ✅ | 主力支持 |
| 大象（美团内部） | ✅ | ✅ | WebView 渲染 |
| 微信（个人版） | ✅ | ✅ | Qt 渲染：坐标点击发送 + Vision OCR 截图读取 |

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
- **一键改写（对话式微调）**：对当前草稿一键「更正式 / 更简短 / 换个说法」，或输入自定义要求（如「加上歉意、更口语化」）反复链式微调，直到满意再发送
- 支持接入本地 Obsidian 知识库（`--add-dir`），让 AI 参考领域文档生成更有依据的回复

### 知识库捕获（新）
- AI 视图新增「💾 存入知识库」按钮，将优质回复存入 Obsidian vault
- 点击后 AI 自动提炼结构化字段（标题、适用场景、标签），弹出可编辑弹窗确认
- 保存为带 YAML frontmatter 的 `.md` 文件，自动记录来源客户端，可在 Obsidian 中按标签检索
- 形成「AI 参考知识库生成回复 → 好回复存回知识库」双向闭环

### 稳健性自检（新）
- 状态栏 🩺 按钮：一键检查各 IM 的 AX 结构是否仍符合预期
- 客户端版本更新可能改变 AX 树深度，导致发送/读取静默失效；自检提前发现并提示
- 启动时被动检查辅助功能权限/窗口可达性，问题在状态栏非阻塞提示
- 所有 AX depth 参数收敛到 `im_clients/probes.py`，客户端更新后只需改一处

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

## 打包（.dmg）

```bash
./build.sh             # 默认 arm64（Apple Silicon）
./build.sh --universal2  # Intel + Apple Silicon 通用包（需 universal2 解释器）
```

输出 `dist/wechat-sender.dmg`。`--universal2` 会先用 `lipo` 预检解释器架构，
Miniconda/uv 的 macOS Python 多为单架构 arm64，需改用 python.org universal2 安装器
重建 venv——详见 [`docs/install-guide.md`](docs/install-guide.md)「universal2 通用包」。
安装与 Gatekeeper 说明同见该文档。

### 自动更新

App 启动后会后台检查 `appcast.json`（默认仓库 raw 地址，可经 `WWS_APPCAST_URL`
覆盖），发现新版时弹窗提示前往下载页手动安装；状态栏 **⬆** 按钮可手动检查。
未签名 ad-hoc 分发不做静默自替换。发布新版时更新仓库根的 `appcast.json`
（`version` / `download_url` / `notes`）即可。可在 `config.json` 设
`update_check_enabled: false` 关闭启动检查。

---

## 项目结构

```
gui_panel.py      # CustomTkinter GUI（话术面板 + AI 助手 + 知识库）
sender.py         # 企业微信 AX API 核心（发送 / 读取 / 截图）
ai_reply.py       # AI 回复生成 + KB 条目提炼
kb_writer.py      # KB 条目写入 Obsidian vault
config.py         # 应用配置读写（config.json）
updater.py        # 自动更新检查（通知式，读 appcast.json）
appcast.json      # 更新清单（最新版本 / 下载地址 / 更新说明）
phrases.json      # 话术数据
im_clients/       # IM 适配器（企业微信 / 微信 / 大象）
tools/            # 调试工具（AX 树探测、OCR）
docs/             # 技术文档 / 设计文档 / 安装指南
```

---

## 安全提醒

- 本工具仅供学习和内部提效，请勿用于骚扰或违规群发
- 企业微信等客户端可能检测异常发送行为，请控制频率
