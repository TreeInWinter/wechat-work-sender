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
        'AppKit', 'Foundation', 'Quartz',
        'ApplicationServices',
        'objc', '_objc',
        'AppKit._AppKit',
        'Foundation._Foundation',
        'Quartz._Quartz',
        'ApplicationServices._ApplicationServices',
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
