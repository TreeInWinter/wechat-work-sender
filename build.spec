# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_all

# 目标架构：默认 arm64（Apple Silicon）。设 TARGET_ARCH=universal2 可产出
# Intel + Apple Silicon 通用二进制——前提是当前解释器与所有原生 wheel 均为
# universal2（用 python.org universal2 安装器建 venv），否则 PyInstaller 会报错。
# 详见 docs/install-guide.md「universal2 通用包」一节与 build.sh 的预检。
TARGET_ARCH = os.environ.get("TARGET_ARCH", "arm64")

# VERSION 一并打包，供运行时 updater.get_current_version() 读取版本号。
datas = [("phrases.json", "."), ("VERSION", ".")]
binaries = []
hiddenimports = []

for package in ("customtkinter", "tkinter", "PIL"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports


a = Analysis(
    ["gui_panel.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="企业微信快捷发送",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="企业微信快捷发送",
)

app = BUNDLE(
    coll,
    name="企业微信快捷发送.app",
    icon=None,
    bundle_identifier="com.baijinshan.wechat-work-sender",
    info_plist={
        "NSAppleEventsUsageDescription": "用于通过系统事件向企业微信粘贴并发送内容。",
        "NSAccessibilityUsageDescription": "用于识别企业微信窗口、聚焦聊天输入框并发送快捷话术。",
        "LSMinimumSystemVersion": "10.15",
    },
)
