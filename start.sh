#!/bin/bash
# 一键启动企业微信快捷发送面板
cd "$(dirname "$0")"
source .venv/bin/activate
python3 gui_panel.py
