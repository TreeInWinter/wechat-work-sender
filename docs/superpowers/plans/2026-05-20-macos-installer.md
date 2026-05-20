# macOS 安装包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为企业微信快捷发送面板生成可分发的 macOS Apple Silicon `.dmg` 安装包。

**Architecture:** 用 PyInstaller 将 Python 应用打包成 `.app` bundle，用 hdiutil 生成 `.dmg`。代码层面迁移 `DATA_FILE` 到 `~/Library/Application Support/`，新增首次启动数据初始化逻辑。

**Tech Stack:** Python 3.13, PyInstaller, pyinstaller-hooks-contrib, hdiutil (系统自带)

---

## 文件结构

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `gui_panel.py` | Modify | 迁移 DATA_FILE 路径，新增 ensure_data_file() |
| `phrases_default.json` | Create | bundle 内置默认话术（首次启动用）|
| `build.spec` | Create | PyInstaller 配置，含 hiddenimports 和 Info.plist |
| `build.sh` | Create | 一键打包脚本 |
| `docs/install-guide.md` | Create | 用户安装说明 |

---

## Task 1：迁移 DATA_FILE 路径

**Files:**
- Modify: `gui_panel.py`（顶部常量区 + `__init__`）

- [ ] **Step 1: 读取当前 DATA_FILE 定义**

```bash
grep -n "SCRIPT_DIR\|DATA_FILE\|phrases.json" gui_panel.py
```

Expected: 找到类似 `SCRIPT_DIR = os.path.dirname(...)` 和 `DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")`

- [ ] **Step 2: 替换 DATA_FILE 相关代码**

找到 `gui_panel.py` 中的常量区，将以下旧代码：

```python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "phrases.json")
```

替换为：

```python
import sys
import shutil

# PyInstaller 运行时 sys.frozen=True，sys._MEIPASS 是解压目录
# 普通 python 运行时回退到脚本目录
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用户数据目录（可读写，app 升级后数据不丢失）
APP_SUPPORT = os.path.expanduser(
    "~/Library/Application Support/企业微信快捷发送"
)
os.makedirs(APP_SUPPORT, exist_ok=True)
DATA_FILE = os.path.join(APP_SUPPORT, "phrases.json")
```

注意：`sys` 和 `shutil` 是否已 import，若已有则不重复。

- [ ] **Step 3: 新增 ensure_data_file() 函数**

在 `load_phrases()` 函数之前插入：

```python
def ensure_data_file():
    """首次启动时将 bundle 内的默认话术复制到用户数据目录"""
    if os.path.exists(DATA_FILE):
        return
    bundled = os.path.join(BUNDLE_DIR, "phrases_default.json")
    if os.path.exists(bundled):
        shutil.copy(bundled, DATA_FILE)
    else:
        save_phrases(DEFAULT_PHRASES)
```

- [ ] **Step 4: 在 `__init__` 最前面调用 ensure_data_file()**

找到 `DaxiangSenderApp.__init__` 方法，在第一行插入：

```python
def __init__(self):
    ensure_data_file()   # ← 新增，必须在任何 UI 初始化之前
    self.root = ctk.CTk()
    ...
```

- [ ] **Step 5: 验证语法**

```bash
.venv/bin/python -m py_compile gui_panel.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: 验证开发模式下数据目录正常创建**

```bash
.venv/bin/python -c "
import gui_panel
print('APP_SUPPORT:', gui_panel.APP_SUPPORT)
print('DATA_FILE:', gui_panel.DATA_FILE)
import os
print('目录存在:', os.path.isdir(gui_panel.APP_SUPPORT))
"
```

Expected:
```
APP_SUPPORT: /Users/.../Library/Application Support/企业微信快捷发送
DATA_FILE: /Users/.../Library/Application Support/企业微信快捷发送/phrases.json
目录存在: True
```

- [ ] **Step 7: 提交**

```bash
git add gui_panel.py
git commit -m "feat: 迁移 DATA_FILE 到 ~/Library/Application Support/"
```

---

## Task 2：创建 phrases_default.json

**Files:**
- Create: `phrases_default.json`

- [ ] **Step 1: 创建文件**

```json
{
  "问候语": [
    "您好，我是您的专属客服，请问有什么可以帮您？",
    "您好，感谢您的耐心等待，现在为您处理。",
    "早上好！有什么需要帮助的吗？",
    "好的"
  ],
  "常用回复": [
    "好的，我这边帮您查一下，请稍等。",
    "已收到您的反馈，我们会尽快处理。",
    "非常抱歉给您带来不便，我们马上为您解决。",
    "感谢您的理解与支持！"
  ],
  "结束语": [
    "还有其他问题吗？如果没有的话，祝您生活愉快！",
    "问题已解决，如有其他需要随时联系我们。",
    "感谢咨询，再见！"
  ]
}
```

保存路径：`phrases_default.json`（项目根目录，与 `gui_panel.py` 同级）

- [ ] **Step 2: 验证 JSON 合法**

```bash
.venv/bin/python -c "import json; json.load(open('phrases_default.json')); print('JSON OK')"
```

Expected: `JSON OK`

- [ ] **Step 3: 提交**

```bash
git add phrases_default.json
git commit -m "feat: 新增 bundle 内置默认话术模板"
```

---

## Task 3：创建 build.spec

**Files:**
- Create: `build.spec`

- [ ] **Step 1: 安装打包依赖**

```bash
.venv/bin/pip install pyinstaller pyinstaller-hooks-contrib
```

Expected: 安装成功，无报错

- [ ] **Step 2: 验证 PyInstaller 可用**

```bash
.venv/bin/pyinstaller --version
```

Expected: 打印版本号，如 `6.x.x`

- [ ] **Step 3: 创建 build.spec**

```python
# build.spec
from PyInstaller.utils.hooks import collect_data_files, collect_all

# 收集 customtkinter 所有资源（主题图片、JSON 配置等，漏掉启动崩溃）
ctk_datas, ctk_binaries, ctk_hidden = collect_all('customtkinter')

# 收集 tkinter / Tcl-Tk 动态库（漏掉窗口无法打开）
tk_datas, tk_binaries, tk_hidden = collect_all('tkinter')

block_cipher = None

a = Analysis(
    ['gui_panel.py'],
    pathex=[],
    binaries=ctk_binaries + tk_binaries,
    datas=[
        ('phrases_default.json', '.'),
    ] + ctk_datas + tk_datas,
    hiddenimports=[
        # pyobjc（pyinstaller-hooks-contrib 自动处理大部分，此处补充常见漏项）
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
    console=False,
    disable_windowed_traceback=False,
    target_arch='arm64',
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
    icon=None,
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

- [ ] **Step 4: 提交**

```bash
git add build.spec
git commit -m "feat: 新增 PyInstaller 打包配置 build.spec"
```

---

## Task 4：创建 build.sh

**Files:**
- Create: `build.sh`

- [ ] **Step 1: 创建脚本**

```bash
#!/bin/bash
set -e

APP_NAME="企业微信快捷发送"
DMG_FILENAME="wechat-sender"
DIST_DIR="dist"
VENV=".venv/bin"

echo "==> 安装打包依赖..."
"$VENV/pip" install pyinstaller pyinstaller-hooks-contrib --quiet

echo "==> 清理旧构建..."
rm -rf "$DIST_DIR" build __pycache__

echo "==> PyInstaller 打包（arm64）..."
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

- [ ] **Step 2: 赋予执行权限**

```bash
chmod +x build.sh
```

- [ ] **Step 3: 提交**

```bash
git add build.sh
git commit -m "feat: 新增一键打包脚本 build.sh"
```

---

## Task 5：创建安装说明文档

**Files:**
- Create: `docs/install-guide.md`

- [ ] **Step 1: 创建文档**

```markdown
# 安装说明

## 系统要求

- macOS 12 Monterey 或更高版本
- Apple Silicon（M1/M2/M3）芯片
- 企业微信桌面版已安装

## 安装步骤

### 第一步：安装应用

1. 下载 `wechat-sender.dmg`
2. 双击打开 DMG 文件
3. 将「企业微信快捷发送」拖入右侧 Applications 文件夹
4. 弹出 DMG（右键 Finder 边栏中的图标 → 推出）

### 第二步：绕过 Gatekeeper（首次必做）

> 因应用未经 Apple 签名，macOS 会阻止直接打开。

**macOS 14 Sonoma / 13 Ventura：**
1. 双击应用，出现警告弹窗，点「完成」（不要点「移到废纸篓」）
2. 打开「系统设置」→「隐私与安全性」→ 滚动到「安全性」区域
3. 找到「已阻止使用"企业微信快捷发送"」→ 点「仍然打开」
4. 在确认弹窗中点「打开」

**macOS 12 Monterey：**
1. 右键（或 Control + 单击）应用图标 → 点「打开」
2. 在弹窗中点「打开」

> 此步骤只需做一次，之后可直接双击启动。

### 第三步：授予辅助功能权限（必做）

应用需要辅助功能权限才能自动化企业微信：

1. 打开「系统设置」→「隐私与安全性」→「辅助功能」
2. 点右下角🔒解锁
3. 点「+」按钮
4. 在 Applications 中找到「企业微信快捷发送」→ 点「打开」
5. 确保开关处于**开启**状态

### 第四步：启动使用

1. 打开企业微信并进入一个聊天窗口
2. 双击启动「企业微信快捷发送」
3. 应用自动贴合到企业微信右侧

## 常见问题

**Q：提示「应用已损坏，无法打开」**  
A：在终端执行：`xattr -cr /Applications/企业微信快捷发送.app`，然后重新打开。

**Q：应用打开后状态栏显示红点**  
A：确认企业微信已打开，点击状态栏右侧 ↻ 刷新。

**Q：点击发送没有反应**  
A：检查辅助功能权限是否已授予（系统设置 → 隐私与安全性 → 辅助功能）。

**Q：升级新版本后话术丢失**  
A：话术保存在 `~/Library/Application Support/企业微信快捷发送/phrases.json`，升级不会覆盖。如丢失，检查该路径下文件是否存在。
```

- [ ] **Step 2: 提交**

```bash
git add docs/install-guide.md
git commit -m "docs: 新增用户安装说明（含 macOS 14 Gatekeeper 处理步骤）"
```

---

## Task 6：执行打包 + 冒烟测试

**Files:**
- 无代码变更，执行验证

- [ ] **Step 1: 执行打包**

```bash
./build.sh 2>&1 | tee build.log
```

Expected 最后几行：
```
✅ 打包完成：dist/wechat-sender.dmg
   大小：XXM
```

若报错，先检查 `build.log` 中的 `ERROR` 行。

- [ ] **Step 2: 验证 DMG 内容**

```bash
hdiutil attach dist/wechat-sender.dmg
ls /Volumes/企业微信快捷发送/
```

Expected:
```
Applications    企业微信快捷发送.app
```

```bash
hdiutil detach /Volumes/企业微信快捷发送
```

- [ ] **Step 3: 冒烟测试（手动）**

将 `/Volumes/企业微信快捷发送/企业微信快捷发送.app` 复制到 `~/Desktop/` 双击运行（**不要**拷到 `/Applications`，避免权限问题影响测试）：

| 测试项 | 预期结果 |
|--------|---------|
| 双击 .app 启动 | 面板出现，无终端窗口 |
| `~/Library/Application Support/企业微信快捷发送/phrases.json` | 自动创建，内容与 `phrases_default.json` 相同 |
| 话术卡片显示 | 默认话术正常展示 |
| 授权辅助功能后发送话术 | 消息发到企业微信 |
| 添加一条话术 | 重启 app 后保留 |

- [ ] **Step 4: 若启动失败，排查 hidden imports**

若 .app 启动时 crash，用以下方式查看错误：

```bash
# 从命令行启动 .app，可以看到 stderr 输出
/path/to/企业微信快捷发送.app/Contents/MacOS/企业微信快捷发送
```

常见错误：`ModuleNotFoundError: No module named 'xxx'`  
解决：在 `build.spec` 的 `hiddenimports` 中补充 `'xxx'`，重新执行 `./build.sh`。

- [ ] **Step 5: 提交 build.log（仅作参考，不强制）**

```bash
# 可选：忽略构建产物
echo "dist/" >> .gitignore
echo "build/" >> .gitignore
echo "build.log" >> .gitignore
git add .gitignore
git commit -m "chore: 忽略构建产物目录"
```

- [ ] **Step 6: 推送分支**

```bash
git push
```
