#!/bin/bash
set -e

APP_NAME="企业微信快捷发送"
DMG_FILENAME="wechat-sender"
DIST_DIR="dist"
VENV=".venv/bin"

if [ ! -d ".venv" ]; then
    echo "❌ .venv 不存在，请先运行：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

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
