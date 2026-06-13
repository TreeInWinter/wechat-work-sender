#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON=".venv/bin/python"
APP_NAME="秒回SideKick"
DMG_NAME="miaohui-sidekick.dmg"

require_file() {
  if [ ! -e "$1" ]; then
    echo "缺少必需文件：$1"
    exit 1
  fi
}

install_pkg() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYTHON" "$@"
  else
    "$PYTHON" -m pip install "$@"
  fi
}

if [ ! -x "$PYTHON" ]; then
  if command -v uv >/dev/null 2>&1; then
    echo "未找到 .venv，正在使用 uv 创建虚拟环境..."
    uv venv
  else
    echo "未找到 .venv，且未安装 uv。请先执行：uv venv && uv pip install -r requirements.txt"
    exit 1
  fi
fi

require_file "requirements.txt"
require_file "build.spec"
require_file "phrases.json"
require_file "assets/donation-wechat.jpg"

echo "正在同步 Python 依赖..."
install_pkg -r requirements.txt

echo "正在检查入口模块语法..."
"$PYTHON" -m py_compile gui_panel.py sender.py config.py

rm -rf build dist
"$PYTHON" -m PyInstaller build.spec --noconfirm

mkdir -p dist/dmg-root
rm -rf "dist/dmg-root/${APP_NAME}.app"
cp -R "dist/${APP_NAME}.app" "dist/dmg-root/"
ln -s /Applications "dist/dmg-root/Applications" 2>/dev/null || true

rm -f "dist/${DMG_NAME}"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "dist/dmg-root" \
  -ov \
  -format UDZO \
  "dist/${DMG_NAME}"

echo "打包完成：dist/${DMG_NAME}"
