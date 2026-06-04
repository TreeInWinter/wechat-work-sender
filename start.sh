#!/bin/bash
# 一键启动企业微信快捷发送面板
set -e

cd "$(dirname "$0")"

if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x "/opt/homebrew/Caskroom/miniconda/base/bin/python3.13" ]; then
    PYTHON_BIN="/opt/homebrew/Caskroom/miniconda/base/bin/python3.13"
  elif command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN="python3.13"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 ${PYTHON_BIN}。请先安装 Python 3.10+，或用 PYTHON_BIN 指定 Python 路径。"
  echo "例如：PYTHON_BIN=/opt/homebrew/Caskroom/miniconda/base/bin/python3.13 ./start.sh"
  exit 1
fi

check_version_cmd='import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
version_text="$("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])')"
if ! "$PYTHON_BIN" -c "$check_version_cmd"; then
  echo "${PYTHON_BIN} 是 Python ${version_text}，但本项目要求 Python 3.10+。"
  exit 1
fi

if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
  echo "${PYTHON_BIN} 缺少 Tk 支持，无法运行 CustomTkinter。"
  echo "请改用带 Tk 的 Python，例如：PYTHON_BIN=/opt/homebrew/Caskroom/miniconda/base/bin/python3.13 ./start.sh"
  exit 1
fi

if [ -x ".venv/bin/python" ]; then
  current_version="$(.venv/bin/python -c 'import sys; print(sys.version.split()[0])')"
  if ! .venv/bin/python -c "$check_version_cmd"; then
    printf '当前 .venv 使用 Python %s，但本项目要求 Python 3.10+。\n' "$current_version"
    echo "请删除旧虚拟环境后重试：rm -rf .venv && ./start.sh"
    exit 1
  fi
  if ! .venv/bin/python -c "import tkinter" >/dev/null 2>&1; then
    echo "当前 .venv 的 Python 缺少 Tk 支持，无法运行 CustomTkinter。"
    echo "请删除旧虚拟环境后重试：rm -rf .venv && ./start.sh"
    exit 1
  fi
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，正在用 ${PYTHON_BIN} 创建 Python ${version_text} 虚拟环境..."
  "$PYTHON_BIN" -m venv .venv
fi

if ! .venv/bin/python -c "import customtkinter" >/dev/null 2>&1; then
  echo "正在安装依赖..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements.txt --python .venv/bin/python
  else
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi

exec .venv/bin/python gui_panel.py
