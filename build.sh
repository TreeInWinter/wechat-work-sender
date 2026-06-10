#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先执行：uv venv && uv pip install -r requirements.txt"
  exit 1
fi

install_pkg() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install "$@"
  else
    ".venv/bin/python" -m pip install "$@"
  fi
}

".venv/bin/python" -m pip show pyinstaller >/dev/null 2>&1 || {
  echo "正在安装 PyInstaller..."
  install_pkg pyinstaller
}

".venv/bin/python" -m pip show Pillow >/dev/null 2>&1 || {
  echo "正在安装 Pillow..."
  install_pkg Pillow
}

rm -rf build dist
".venv/bin/python" -m PyInstaller build.spec --noconfirm

mkdir -p dist/dmg-root
rm -rf "dist/dmg-root/秒回SideKick.app"
cp -R "dist/秒回SideKick.app" "dist/dmg-root/"
ln -s /Applications "dist/dmg-root/Applications" 2>/dev/null || true

rm -f "dist/miaohui-sidekick.dmg"
hdiutil create \
  -volname "秒回SideKick" \
  -srcfolder "dist/dmg-root" \
  -ov \
  -format UDZO \
  "dist/miaohui-sidekick.dmg"

echo "打包完成：dist/miaohui-sidekick.dmg"
