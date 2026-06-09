#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# ── 参数 ────────────────────────────────────────────────────────────
# 默认产出 arm64 包；传 --universal2 产出 Intel + Apple Silicon 通用包。
TARGET_ARCH="${TARGET_ARCH:-arm64}"
for arg in "$@"; do
  case "$arg" in
    --universal2) TARGET_ARCH="universal2" ;;
    --arm64)      TARGET_ARCH="arm64" ;;
    *) echo "未知参数：$arg（可用：--universal2 / --arm64）"; exit 1 ;;
  esac
done
export TARGET_ARCH

if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先执行：uv venv && uv pip install -r requirements.txt"
  exit 1
fi

# ── universal2 预检 ─────────────────────────────────────────────────
# universal2 要求解释器本身与所有原生 wheel 均为双架构，否则 PyInstaller 会
# 在收集阶段才报错（且信息晦涩）。这里提前用 lipo 验证解释器，快速失败并给指引。
if [ "$TARGET_ARCH" = "universal2" ]; then
  echo "目标架构：universal2，预检解释器架构…"
  ARCHS="$(lipo -archs ".venv/bin/python" 2>/dev/null || echo "")"
  if ! { echo "$ARCHS" | grep -q "x86_64" && echo "$ARCHS" | grep -q "arm64"; }; then
    cat <<'EOF'
❌ 当前 .venv 的解释器不是 universal2（缺 x86_64 或 arm64）。
   Miniconda / uv 的 macOS Python 多为单架构（arm64），无法产出 universal2。

   解决：用 python.org 的 universal2 安装器重建 venv，再装 universal2 wheel：
     1) 安装 https://www.python.org/downloads/macos/ 的 “macOS 64-bit universal2 installer”
     2) /usr/local/bin/python3 -m venv .venv-universal2
     3) source .venv-universal2/bin/activate
     4) pip install -r requirements.txt   # Pillow/pyobjc 均有 universal2 wheel
     5) 把本脚本里的 .venv 指向该 venv，或在该 venv 下运行 PyInstaller
   详见 docs/install-guide.md「universal2 通用包」。
EOF
    exit 1
  fi
  echo "  解释器架构 OK：$ARCHS"
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
rm -rf "dist/dmg-root/企业微信快捷发送.app"
cp -R "dist/企业微信快捷发送.app" "dist/dmg-root/"
ln -s /Applications "dist/dmg-root/Applications" 2>/dev/null || true

rm -f "dist/wechat-sender.dmg"
hdiutil create \
  -volname "企业微信快捷发送" \
  -srcfolder "dist/dmg-root" \
  -ov \
  -format UDZO \
  "dist/wechat-sender.dmg"

echo "打包完成（$TARGET_ARCH）：dist/wechat-sender.dmg"
