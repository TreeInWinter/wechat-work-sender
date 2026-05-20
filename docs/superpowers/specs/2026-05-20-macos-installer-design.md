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
- **pyinstaller-hooks-contrib**：PyInstaller 官方 hook 库，包含 pyobjc 的自动处理规则，**必须安装**
- **hdiutil**：macOS 系统自带，无需额外安装，将 `.app` 打包成 `.dmg`

### 打包目标

```
dist/
├── 企业微信快捷发送.app   ← PyInstaller 输出
└── wechat-sender.dmg      ← hdiutil 输出（文件名 ASCII，避免路径问题）
```

> DMG 卷标（挂载后显示的名字）仍用中文「企业微信快捷发送」，文件名用 ASCII。

---

## 代码变更（必须在打包前完成）

### 1. DATA_FILE 路径迁移

`.app` 内部只读，`phrases.json` 必须迁移到用户可写目录。

**修改位置：** `gui_panel.py`（`sender.py` 中 `DATA_FILE` 不存在，无需改）

```python
# 旧代码（只读 bundle 内，打包后写入报 Permission denied）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")

# 新代码
APP_SUPPORT = os.path.expanduser(
    "~/Library/Application Support/企业微信快捷发送"
)
os.makedirs(APP_SUPPORT, exist_ok=True)
DATA_FILE = os.path.join(APP_SUPPORT, "phrases.json")
```

### 2. bundle_dir 检测（规范写法）

```python
import sys

# PyInstaller 运行时 sys.frozen = True，sys._MEIPASS 是解压目录
# 普通运行时回退到脚本目录
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
```

### 3. 首次启动时复制默认话术

```python
import shutil

DEFAULT_PHRASES_BUNDLED = os.path.join(BUNDLE_DIR, "phrases_default.json")

def ensure_data_file():
    """首次启动时将 bundle 内的默认话术复制到用户数据目录"""
    if not os.path.exists(DATA_FILE):
        if os.path.exists(DEFAULT_PHRASES_BUNDLED):
            shutil.copy(DEFAULT_PHRASES_BUNDLED, DATA_FILE)
        else:
            save_phrases(DEFAULT_PHRASES)  # 回退到代码内硬编码的默认值
```

在 `DaxiangSenderApp.__init__` 最前面调用 `ensure_data_file()`。

---

## 打包配置

### build.spec（PyInstaller 配置文件）

```python
from PyInstaller.utils.hooks import collect_data_files, collect_all
import sys

# ── 收集 customtkinter 所有资源（主题图片、JSON 配置等）
ctk_datas, ctk_binaries, ctk_hidden = collect_all('customtkinter')

# ── 收集 tkinter / Tcl-Tk 动态库（漏掉会导致窗口无法打开）
tk_datas, tk_binaries, tk_hidden = collect_all('tkinter')

block_cipher = None

a = Analysis(
    ['gui_panel.py'],
    pathex=[],
    binaries=ctk_binaries + tk_binaries,
    datas=[
        ('phrases_default.json', '.'),  # 内置默认话术模板
    ] + ctk_datas + tk_datas,
    hiddenimports=[
        # pyobjc（pyinstaller-hooks-contrib 会自动处理大部分，此处补充常见漏项）
        'AppKit', 'Foundation', 'Quartz',
        'ApplicationServices',
        'objc', '_objc',
        'AppKit._AppKit',
        'Foundation._Foundation',
        'Quartz._Quartz',
        'ApplicationServices._ApplicationServices',
        # tkinter
        '_tkinter',
        'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.simpledialog',
    ] + ctk_hidden + tk_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='企业微信快捷发送',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,         # 不显示终端窗口
    disable_windowed_traceback=False,
    target_arch='arm64',   # Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='企业微信快捷发送',
)

app = BUNDLE(
    coll,
    name='企业微信快捷发送.app',
    icon=None,             # 无 icon.icns 时用系统默认
    bundle_identifier='com.internal.wechat-sender',
    info_plist={
        'NSAccessibilityUsageDescription':
            '本应用需要辅助功能权限以自动化企业微信发送消息',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleDisplayName': '企业微信快捷发送',
        'CFBundleShortVersionString': '1.0.0',
    },
)
```

### build.sh（一键打包脚本）

```bash
#!/bin/bash
set -e

APP_NAME="企业微信快捷发送"
DMG_FILENAME="wechat-sender"          # ASCII 文件名，避免路径问题
DIST_DIR="dist"
VENV=".venv/bin"

echo "==> 安装打包依赖..."
"$VENV/pip" install pyinstaller pyinstaller-hooks-contrib

echo "==> 清理旧构建..."
rm -rf "$DIST_DIR" build __pycache__

echo "==> PyInstaller 打包..."
"$VENV/pyinstaller" build.spec

echo "==> 创建 DMG..."
STAGING="dmg_staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -r "$DIST_DIR/${APP_NAME}.app" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "$DIST_DIR/${DMG_FILENAME}.dmg"

rm -rf "$STAGING"

echo ""
echo "✅ 打包完成：$DIST_DIR/${DMG_FILENAME}.dmg"
echo "   大小：$(du -sh "$DIST_DIR/${DMG_FILENAME}.dmg" | cut -f1)"
```

---

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `build.spec` | PyInstaller 配置，包含资源收集和 Info.plist |
| `build.sh` | 一键打包脚本，输出 `.dmg` |
| `phrases_default.json` | bundle 内置的默认话术模板（内容与 `phrases.json` 相同）|
| `docs/install-guide.md` | 用户安装说明（含 macOS 14+ Gatekeeper 处理步骤）|

---

## 修改文件清单

| 文件 | 变更 | 原因 |
|------|------|------|
| `gui_panel.py` | `DATA_FILE` 路径改为 `~/Library/Application Support/` | bundle 内只读 |
| `gui_panel.py` | 新增 `BUNDLE_DIR` 检测和 `ensure_data_file()` | 首次启动初始化数据 |
| `gui_panel.py` | `__init__` 最前面调用 `ensure_data_file()` | 保证数据目录存在 |

---

## 安装流程（macOS 14+ 用户视角）

1. 下载 `wechat-sender.dmg`
2. 双击打开 DMG，将「企业微信快捷发送.app」拖入 Applications
3. 首次打开时 macOS 弹出警告 → **不要点"移到废纸篓"**  
   → 打开「系统设置 → 隐私与安全性 → 安全性」  
   → 找到「已阻止使用'企业微信快捷发送'」→ 点「仍然打开」
4. 在「系统设置 → 隐私与安全性 → 辅助功能」添加 `企业微信快捷发送.app`
5. 重新打开应用，正常使用

> 步骤 3-4 只需做一次。后续直接双击启动。

---

## 验证方式（冒烟测试）

| 测试项 | 预期结果 |
|--------|---------|
| `build.sh` 执行 | 无报错，输出 `dist/wechat-sender.dmg` |
| 挂载 DMG | 卷标显示「企业微信快捷发送」，含 .app 和 Applications 快捷方式 |
| 首次启动 | `~/Library/Application Support/企业微信快捷发送/phrases.json` 自动创建 |
| 添加话术 | 重启后数据保留（写入 `~/Library/...` 非 bundle 内）|
| 发送消息 | 授权辅助功能后发送成功 |
| 读取聊天 | 弹窗正常显示消息 |
| 升级安装 | 旧 `phrases.json` 不被覆盖 |

---

## 已知限制

- **无代码签名**：无 Apple Developer 账号，macOS 14+ 需按安装说明处理 Gatekeeper
- **辅助功能需重授权**：从终端改为 .app 运行，系统视为新应用，需重新授权
- **仅 arm64**：不支持 Intel Mac
- **pyobjc hidden imports 需验证**：打包后需实际运行冒烟测试，按日志补充漏项
