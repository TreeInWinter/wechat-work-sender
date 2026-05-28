# macOS 安装与权限引导

## 开发环境运行

```bash
uv venv
uv pip install -r requirements.txt
.venv/bin/python gui_panel.py
```

## 打包安装包

```bash
./build.sh
```

输出文件：

```text
dist/wechat-sender.dmg
```

打开 DMG 后，将 `企业微信快捷发送.app` 拖入 `Applications`。

## 必需权限

打开 `系统设置 → 隐私与安全性 → 辅助功能`，勾选当前运行入口：

- 开发运行：Terminal、PyCharm、Cursor 或实际启动 Python 的 App。
- 安装包运行：`企业微信快捷发送.app`。

如果已经勾选但仍提示无权限，关闭本工具后重新打开。

## 首次打开被 Gatekeeper 拦截

如果 macOS 提示无法打开：

1. 在 Finder 中右键 `企业微信快捷发送.app`。
2. 选择 `打开`。
3. 在确认弹窗中再次选择 `打开`。

本工具只通过 macOS Accessibility API 操作企业微信窗口，不修改企业微信进程，也不调用企业微信网络接口。
