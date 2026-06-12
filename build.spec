# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

datas = [("phrases.json", "."), ("assets/donation-wechat.jpg", "assets")]
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
    name="秒回SideKick",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
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
    name="秒回SideKick",
)

app = BUNDLE(
    coll,
    name="秒回SideKick.app",
    icon=None,
    bundle_identifier="com.baijinshan.wechat-work-sender",
    info_plist={
        "NSAppleEventsUsageDescription": "用于通过系统事件向企业微信粘贴并发送内容。",
        "NSAccessibilityUsageDescription": "用于识别企业微信窗口、聚焦聊天输入框并发送快捷话术。",
        "LSMinimumSystemVersion": "10.15",
    },
)
