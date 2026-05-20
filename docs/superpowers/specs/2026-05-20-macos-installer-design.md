# macOS 安装包设计文档

**项目：** 企业微信快捷发送面板  
**功能：** macOS Apple Silicon (.dmg) 安装包  
**分支：** feature/macos-installer  
**日期：** 2026-05-20  
**状态：** 待实现

---

## 背景

当前项目只能通过终端 `python gui_panel.py` 运行，需要 Python 环境和依赖安装，无法分发给非开发人员。目标是生成一个可直接分发给团队的 `.dmg` 安装包，用户拖拽即安装，双击即运行。

---

## 技术方案

### 打包工具：PyInstaller + hdiutil

- **PyInstaller**：将 Python 应用和所有依赖打包成独立 `.app` bundle，arm64 原生支持
- **hdiutil**：macOS 系统自带，无需额外安装，将 `.app` 打包成 `.dmg`

### 打包目标

```
dist/
├── 企业微信快捷发送.app      ← PyInstaller 输出
└── 企业微信快捷发送.dmg      ← hdiutil 输出（最终分发物）
```

---

## 代码变更（必须在打包前完成）

### 1. DATA_FILE 路径迁移

`.app` 内部只读，`phrases.json` 必须迁移到用户可写目录。

**修改位置：** `gui_panel.py` 和 `sender.py`（如有引用）

```python
# 旧代码（只读 bundle 内）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")

# 新代码
APP_SUPPORT = os.path.expanduser(
    "~/Library/Application Support/企业微信快捷发送"
)
os.makedirs(APP_SUPPORT, exist_ok=True)
DATA_FILE = os.path.join(APP_SUPPORT, "phrases.json")
```

### 2. 首次启动时复制默认话术

```python
DEFAULT_PHRASES_BUNDLED = os.path.join(
    getattr(sys, "_MEIPASS", os.path.dirname(__file__)),
    "phrases_default.json"
)

def ensure_data_file():
    if not os.path.exists(DATA_FILE):
        if os.path.exists(DEFAULT_PHRASES_BUNDLED):
            shutil.copy(DEFAULT_PHRASES_BUNDLED, DATA_FILE)
        else:
            save_phrases(DEFAULT_PHRASES)
```

`sys._MEIPASS` 是 PyInstaller 运行时解压目录，普通运行时该属性不存在，回退到脚本目录。

---

## 打包配置

### build.spec（PyInstaller 配置文件）

```python
a = Analysis(
    ['gui_panel.py'],
    datas=[('phrases.json', '.')],           # 内置默认话术模板
    hiddenimports=[
        'AppKit', 'Foundation', 'Quartz',
        'ApplicationServices',
        'objc', '_objc',
        'customtkinter',
        'tkinter', 'tkinter.ttk',
        '_tkinter',
    ],
    ...
)

app = BUNDLE(
    exe,
    name='企业微信快捷发送.app',
    icon='assets/icon.icns',                 # 可选，无则用默认图标
    bundle_identifier='com.internal.wechat-sender',
    info_plist={
        'NSAccessibilityUsageDescription':
            '本应用需要辅助功能权限以自动化企业微信发送消息',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
    },
)
```

### DMG 创建脚本（build.sh）

```bash
#!/bin/bash
set -e

APP_NAME="企业微信快捷发送"
DIST_DIR="dist"

# 1. 清理旧构建
rm -rf "$DIST_DIR"

# 2. PyInstaller 打包
pyinstaller build.spec

# 3. 创建临时 DMG 目录
mkdir -p dmg_staging
cp -r "$DIST_DIR/${APP_NAME}.app" dmg_staging/
ln -s /Applications dmg_staging/Applications  # 快捷方式

# 4. hdiutil 生成 DMG
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder dmg_staging \
    -ov -format UDZO \
    "$DIST_DIR/${APP_NAME}.dmg"

# 5. 清理临时目录
rm -rf dmg_staging

echo "✅ 打包完成：$DIST_DIR/${APP_NAME}.dmg"
```

---

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `build.spec` | PyInstaller 配置，声明 hiddenimports、Info.plist、数据文件 |
| `build.sh` | 一键打包脚本，输出 `.dmg` |
| `phrases_default.json` | bundle 内置的默认话术模板（首次启动时复制） |
| `assets/icon.icns` | 应用图标（可选，无则跳过） |
| `docs/install-guide.md` | 用户安装说明（Gatekeeper 处理 + 辅助功能授权） |

---

## 修改文件清单

| 文件 | 变更 | 原因 |
|------|------|------|
| `gui_panel.py` | `DATA_FILE` 路径改为 `~/Library/Application Support/` | bundle 内只读 |
| `gui_panel.py` | 启动时调用 `ensure_data_file()` | 首次启动复制默认话术 |

---

## 安装流程（用户视角）

1. 下载 `企业微信快捷发送.dmg`
2. 打开 DMG，将 `.app` 拖入 Applications
3. 首次打开时 macOS 提示"未知来源"→ **右键 → 打开 → 打开**
4. 在「系统设置 → 隐私与安全性 → 辅助功能」添加 `企业微信快捷发送.app`
5. 重新打开应用，正常使用

> **注意**：步骤 3-4 只需做一次。后续直接双击启动。

---

## 验证方式

1. `build.sh` 执行无报错
2. 生成的 `.app` 可双击启动
3. 首次启动自动创建 `~/Library/Application Support/企业微信快捷发送/phrases.json`
4. 添加/删除话术后数据持久化到 `~/Library/...`
5. 发送消息正常（需先授予辅助功能权限）
6. 读取聊天内容正常
7. 关闭并重启 app，话术数据保留

---

## 已知限制

- **无代码签名**：分发时需告知用户 Gatekeeper 处理步骤
- **辅助功能需重授权**：首次安装后需在系统设置中重新授权
- **不支持 Intel Mac**：仅针对 Apple Silicon (arm64) 构建
