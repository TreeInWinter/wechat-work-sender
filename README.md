# 向企业微信发送消息 (macOS)

## 原理
1. 通过 macOS Accessibility API 识别企业微信窗口
2. 通过 AppleScript 激活窗口并聚焦输入框
3. 通过 NSPasteboard 写入剪贴板内容
4. 通过 CGEvent 模拟 Cmd+V 粘贴 + Enter 发送

## 前置要求
- macOS 10.15+
- Python 3.9+
- 需要在「系统设置 → 隐私与安全性 → 辅助功能」中授权终端/IDE

## 安装依赖
```bash
uv venv
uv pip install -r requirements.txt
```

## 使用方法
```bash
# 基本用法：向当前激活的企业微信聊天窗口发送消息
python sender.py "你好，这是自动发送的消息"

# 带 GUI 的话术面板模式
python gui_panel.py
```

## 个人版基础体验
- 搜索：在面板顶部搜索当前分组话术，`Esc` 可清空。
- 快捷键：`⌘F` 聚焦搜索，`⌘↩` 发送自定义消息，`⌘1` 到 `⌘9` 发送当前可见话术。
- 变量模板：话术中可写 `{{客户名}}`、`{{订单号}}` 等占位符；`{{日期}}`、`{{时间}}`、`{{星期}}` 会自动替换。
- 发送预览：点击发送后先预览内容并填写变量，确认后才发送。
- 权限引导：面板右上角 `权限` 可查看授权状态并打开系统设置。

## 打包
```bash
./build.sh
```

输出 `dist/wechat-sender.dmg`。安装与 Gatekeeper 说明见 `docs/install-guide.md`。

## 安全提醒
- 本 Demo 仅供学习和内部提效，请勿用于骚扰或违规群发
- 企业微信可能检测异常发送行为，请控制频率
