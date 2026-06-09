# updater.py
"""轻量自动更新检查（通知式）。

App 以未签名 ad-hoc 方式分发（`build.spec` 中 codesign_identity=None），
因此**不做静默自替换**——在未签名场景下自替换会触发 Gatekeeper 拦截、易损坏
应用。本模块只负责「检查远端 appcast → 判断是否有新版」这一纯逻辑，由 GUI
在发现新版时弹窗提示用户前往下载页手动安装。

appcast.json 结构（托管在仓库 / Release，见 `appcast.json`）：

    {
      "version": "1.4.0.0",                  # 必填，最新版本号
      "download_url": "https://.../wechat-sender.dmg",  # 必填，DMG 直链
      "notes": "本次更新内容……",            # 可选，更新说明
      "page_url": "https://.../releases/...", # 可选，Release 页面（优先打开）
      "min_os": "10.15",                      # 可选，最低系统要求（仅展示）
      "pub_date": "2026-06-10"                # 可选，发布日期
    }

所有网络/解析错误都被 `check_for_update()` 收敛进返回值，绝不抛出，避免拖累
GUI 启动流程。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认 appcast 地址（仓库 raw）。可用环境变量 WWS_APPCAST_URL 或 config 的
# appcast_url 字段覆盖（见 check_for_update 的调用方）。
DEFAULT_APPCAST_URL = (
    "https://raw.githubusercontent.com/"
    "TreeInWinter/wechat-work-sender/master/appcast.json"
)

DEFAULT_TIMEOUT = 6  # 秒，启动时后台检查，宁可快速失败也不卡用户


def get_appcast_url() -> str:
    """优先读环境变量 WWS_APPCAST_URL，否则用默认仓库地址。"""
    return os.environ.get("WWS_APPCAST_URL", "").strip() or DEFAULT_APPCAST_URL


def get_current_version() -> str:
    """读取当前应用版本号（单一事实来源为 VERSION 文件）。

    优先级：环境变量 WWS_VERSION（便于测试/覆盖）→ 打包后的 VERSION（_MEIPASS）
    → 源码目录 VERSION → 兜底 "0.0.0.0"。
    """
    env = os.environ.get("WWS_VERSION", "").strip()
    if env:
        return env
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "VERSION"))
    candidates.append(os.path.join(SCRIPT_DIR, "VERSION"))
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return text
        except OSError:
            continue
    return "0.0.0.0"


def parse_version(s: str) -> tuple[int, ...]:
    """把 "v1.4.0.0" / "1.4.0" 解析为可比较的整数元组。

    去掉前导 'v'，按 '.' 分段，逐段取前缀数字（如 "1rc2" → 1），无法解析的段记 0。
    空串返回 (0,)。
    """
    s = (s or "").strip().lstrip("vV")
    if not s:
        return (0,)
    parts = []
    for seg in s.split("."):
        seg = seg.strip()
        num = ""
        for ch in seg:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, current: str) -> bool:
    """remote 版本是否严格高于 current（按段补零对齐比较）。"""
    rv = parse_version(remote)
    cv = parse_version(current)
    width = max(len(rv), len(cv))
    rv += (0,) * (width - len(rv))
    cv += (0,) * (width - len(cv))
    return rv > cv


class UpdaterError(Exception):
    """网络或解析失败。check_for_update 会捕获它，不向外抛。"""


@dataclass
class Appcast:
    version: str
    download_url: str
    notes: str = ""
    page_url: str = ""
    min_os: str = ""
    pub_date: str = ""

    @property
    def open_url(self) -> str:
        """用户「前往下载」时应打开的地址：优先 Release 页面，回退 DMG 直链。"""
        return self.page_url or self.download_url


def parse_appcast(data: dict) -> Appcast:
    """从已解析的 JSON dict 构造 Appcast，校验必填字段。"""
    if not isinstance(data, dict):
        raise UpdaterError("appcast 格式错误：根节点应为对象")
    version = str(data.get("version", "")).strip()
    download_url = str(data.get("download_url", "")).strip()
    if not version:
        raise UpdaterError("appcast 缺少 version 字段")
    if not download_url:
        raise UpdaterError("appcast 缺少 download_url 字段")
    return Appcast(
        version=version,
        download_url=download_url,
        notes=str(data.get("notes", "")).strip(),
        page_url=str(data.get("page_url", "")).strip(),
        min_os=str(data.get("min_os", "")).strip(),
        pub_date=str(data.get("pub_date", "")).strip(),
    )


def fetch_appcast(url: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> Appcast:
    """下载并解析 appcast。失败抛 UpdaterError。"""
    url = url or get_appcast_url()
    req = urllib.request.Request(url, headers={"User-Agent": "wechat-work-sender-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise UpdaterError(f"网络请求失败：{e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise UpdaterError(f"appcast 解析失败：{e}") from e
    return parse_appcast(data)


@dataclass
class UpdateCheckResult:
    has_update: bool
    current_version: str
    appcast: Appcast | None = None
    error: str | None = None


def check_for_update(
    current_version: str | None = None,
    url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> UpdateCheckResult:
    """检查是否有新版。**绝不抛异常**，错误收敛进 result.error。

    适合在后台线程调用，回主线程后据 result 决定是否弹窗。
    """
    current = current_version or get_current_version()
    try:
        appcast = fetch_appcast(url, timeout=timeout)
    except UpdaterError as e:
        return UpdateCheckResult(False, current, None, str(e))
    except Exception as e:  # 兜底：任何意外都不应拖垮 GUI
        return UpdateCheckResult(False, current, None, f"检查更新异常：{e}")
    has = is_newer(appcast.version, current)
    return UpdateCheckResult(has, current, appcast, None)
