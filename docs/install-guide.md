# macOS 安装与权限引导

## 开发环境运行

```bash
uv venv
uv pip install -r requirements.txt
.venv/bin/python gui_panel.py
```

## 打包安装包

```bash
./build.sh              # 默认 arm64（Apple Silicon）
./build.sh --universal2 # Intel + Apple Silicon 通用包
```

输出文件：

```text
dist/wechat-sender.dmg
```

打开 DMG 后，将 `企业微信快捷发送.app` 拖入 `Applications`。

### universal2 通用包

`--universal2` 产出同时支持 Intel（x86_64）与 Apple Silicon（arm64）的通用二进制。
前提是**当前解释器与所有原生 wheel 均为 universal2 双架构**，否则 PyInstaller 无法
合成通用包。`build.sh` 会先用 `lipo` 预检解释器，单架构时快速失败并提示。

⚠️ Miniconda、Homebrew、`uv` 安装的 macOS Python 多为**单架构 arm64**
（`uv python` 的发行版也是 `macos-aarch64`），无法直接产出 universal2。需改用
python.org 官方 universal2 安装器重建 venv：

```bash
# 1) 安装 https://www.python.org/downloads/macos/ 的
#    “macOS 64-bit universal2 installer”
# 2) 用它创建独立 venv
/usr/local/bin/python3 -m venv .venv-universal2
source .venv-universal2/bin/activate

# 3) 安装依赖（Pillow / pyobjc 均发布 universal2 wheel；customtkinter 为纯 Python）
pip install -r requirements.txt

# 4) 验证解释器为双架构
lipo -archs $(which python)      # 应输出：x86_64 arm64

# 5) 在该 venv 下打包（build.sh 默认用 .venv，可临时软链或在该 venv 内手动跑）
TARGET_ARCH=universal2 python -m PyInstaller build.spec --noconfirm
```

> 说明：本机若只有单架构 arm64 解释器，只能产出 arm64 包；Intel Mac 上运行需要
> universal2 或 x86_64 包。

## 自动更新

App 启动后约 2.5s 在后台检查更新清单 `appcast.json`（默认从仓库 raw 地址拉取，
可用环境变量 `WWS_APPCAST_URL` 覆盖）。发现新版时弹窗显示更新说明，点「是」打开
下载页手动安装。状态栏 **⬆** 按钮可随时手动检查。

- 未签名 ad-hoc 分发不做静默自替换（会触发 Gatekeeper），只通知 + 引导手动安装。
- 发布新版：打包上传新 DMG 后，更新仓库根 `appcast.json` 的 `version` /
  `download_url` / `notes` 即可，老版本下次启动会检测到。
- 关闭启动检查：在 `~/Library/Application Support/WechatWorkSender/config.json`
  设 `"update_check_enabled": false`。

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
