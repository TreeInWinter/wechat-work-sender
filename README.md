# 向企业微信发送消息 Demo (macOS)

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
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
```

## 使用方法
```bash
# 基本用法：向当前激活的企业微信聊天窗口发送消息
python sender.py "你好，这是自动发送的消息"

# 带 GUI 的话术面板模式
python gui_panel.py
```

## 安全提醒
- 本 Demo 仅供学习和内部提效，请勿用于骚扰或违规群发
- 企业微信可能检测异常发送行为，请控制频率
