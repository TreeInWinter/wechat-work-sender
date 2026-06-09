# im_clients/daxiang.py
from __future__ import annotations

import os
import re
import tempfile
import time

import sender  # 复用企业微信已验证的图片合成逻辑（render_blocks_to_image）
from .ax_helpers import (
    activate_app,
    focus_input,
    get_ax_element,
    get_clipboard_text,
    get_largest_window,
    is_app_running,
    paste_and_send,
    set_clipboard_png,
    set_clipboard_text,
)
from .base import IMClientAdapter, TakeoverCapabilities, UnsupportedClientAction
from .probes import get_probe as _get_probe

_DX_PROBE = _get_probe("daxiang")


class DaxiangAdapter(IMClientAdapter):
    """
    大象（美团内部 IM）适配器。

    真机探测结论（2026-06-05）：
      - bundle ID: cn.neixin.pc（非 com.sankuai.daxiang）
      - AX 树：WebView 渲染，AXWebArea 在 depth=5，聊天输入框 AXTextArea 在 depth=23
        （从 app root 算为 depth=24），有占位符文本 '说点什么...'
      - 发送：AX 找到输入框（max_depth=26，allow_with_value=True）→ Cmd+V → Enter
      - 读取：消息以 AXStaticText 散布在 depth=22-25，无 AXTable 结构
    """

    client_id = "daxiang"
    display_name = "大象"
    app_names = ("大象", "Daxiang", "DaXiang")
    bundle_ids = ("cn.neixin.pc", "com.sankuai.daxiang", "com.meituan.daxiang")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,
        verified=True,   # 真机验证：focus_input depth=26 + Cmd+V + AppleScript Enter 可靠
    )

    # AppleScript tell process 用的进程名（真机验证：大象）
    _PROCESS_NAME = "大象"

    # 大象输入框在 AX 树深处（depth=23 from window = depth=24 from app root）
    # depth 常量收敛到 im_clients/probes.py
    _INPUT_MAX_DEPTH = _DX_PROBE.input.max_depth          # 26
    _INPUT_ALLOW_WITH_VALUE = _DX_PROBE.input.allow_with_value  # True（占位符）

    def is_running(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return True
        return False

    def activate(self) -> bool:
        for name in self.app_names:
            if is_app_running(name):
                return activate_app(name)
        return False

    def _get_app_name(self) -> str | None:
        """返回当前正在运行的 app_name（用于 AX 查找）。"""
        for name in self.app_names:
            if is_app_running(name):
                return name
        return None

    def send_blocks(self, blocks: list) -> bool:
        """
        发送 blocks 到当前大象聊天窗口。

        纯文字：set_clipboard_text + paste_and_send
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png + paste_and_send
        图文混排：合成单张图片发送（保证只出现一条消息）

        注意：大象输入框在 AX 树 depth=24（从 app root 算），有占位符文本，
        需要 max_depth=26 且 allow_with_value=True。
        """
        app_name = self._get_app_name()
        if app_name is None:
            return False

        if not activate_app(app_name):
            return False

        ax = get_ax_element(app_name)
        if ax is None:
            return False

        try:
            if not focus_input(
                ax,
                max_depth=self._INPUT_MAX_DEPTH,
                allow_with_value=self._INPUT_ALLOW_WITH_VALUE,
            ):
                raise UnsupportedClientAction("大象未找到聊天输入框，请先选中一个聊天")
        except UnsupportedClientAction:
            raise
        except Exception as e:
            raise UnsupportedClientAction("大象 AX 访问失败，请检查辅助功能权限") from e

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks)
        else:
            return self._send_text_blocks(blocks)

    def _send_text_blocks(self, blocks: list) -> bool:
        """纯文字 blocks：拼接后写剪贴板，paste_and_send。"""
        text = "\n".join(
            b.get("content", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
        if not text:
            return False
        original = get_clipboard_text()
        try:
            set_clipboard_text(text)
            paste_and_send(app_name=self._PROCESS_NAME)
        finally:
            set_clipboard_text(original)
        return True

    def _send_as_image(self, blocks: list) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=self._PROCESS_NAME)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"大象图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # depth=22（from window）是当前聊天的消息区域
    # depth=23 是侧边栏联系人列表，不包含在读取范围内（收敛到 probes.py）
    _MSG_DEPTH = _DX_PROBE.message.exact_depth   # 22

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """
        读取当前大象聊天窗口的消息记录。

        大象 AX 树结构（真机探测 2026-06-05）：
          - depth=22（from window）= 当前打开的聊天消息，顺序排列
          - 前 6 个节点是 UI 过滤器（未读/稍后/@我/单聊/群聊/图标），跳过
          - 然后按序：时间戳 → 发送者名 → 消息内容（可多行）→ 时间戳 → ...
          - depth=23 是侧边栏联系人列表，排除在外
        """
        from collections import deque
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            kAXChildrenAttribute,
            kAXRoleAttribute,
            kAXValueAttribute,
            kAXWindowsAttribute,
        )

        app_name = self._get_app_name()
        if app_name is None:
            return []

        # kAXWindowsAttribute 在未激活时返回空，需要先激活再等 AX 树渲染
        activate_app(app_name)
        ax = get_ax_element(app_name)
        if ax is None:
            return []

        try:
            # 重试等待：AX 树在激活后需要 200-500ms 才完全展开
            windows = None
            for _ in range(5):
                _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
                if windows and len(windows) >= 1:
                    break
                time.sleep(0.15)

            if not windows:
                return []

            # 取面积最大的窗口（主窗口），避免输入法弹框干扰
            main_win = get_largest_window(windows)
            if main_win is None:
                return []

            # BFS 收集 depth=22 的 AXStaticText，保留顺序。
            # 排除 AXList 父节点下的节点（侧边栏会话列表，不是当前聊天内容）。
            texts: list[str] = []
            queue: deque = deque([(main_win, 0, False)])  # (el, depth, under_axlist)
            while queue:
                el, d, under_list = queue.popleft()
                if d > self._MSG_DEPTH:
                    continue
                _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
                _, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
                is_list = role == "AXList"
                cur_under_list = under_list or is_list
                if role == "AXStaticText" and val and d == self._MSG_DEPTH and not cur_under_list:
                    texts.append(str(val))
                if d < self._MSG_DEPTH:
                    _, ch = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
                    if ch:
                        for c in ch:
                            queue.append((c, d + 1, cur_under_list))

            return _parse_daxiang_messages(texts, max_messages)
        except Exception:
            return []


# ── 大象消息解析 ────────────────────────────────────────────────────

# depth=22 前 6 个固定 UI 过滤器
_UI_TABS = {"未读", "稍后", "@我", "单聊", "群聊"}

# 时间格式：10:30 / 09:59 / 06-04 17:53
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$|^\d{2}-\d{2}\s+\d{1,2}:\d{2}$")

# 图标字符（Unicode 私有区 -）
_ICON_RE = re.compile(r"^[-]+$")

# 发送者名称：2-4 个汉字，可选后跟 (Pinyin/英文昵称)
_SENDER_RE = re.compile(r"^[一-鿿]{2,4}(\([A-Za-z\s.]+\))?$")


def _is_junk(text: str) -> bool:
    """过滤 UI 图标和空白。"""
    t = text.strip()
    return not t or bool(_ICON_RE.match(t))


def _parse_daxiang_messages(texts: list[str], max_messages: int) -> list[dict]:
    """
    将 depth=22 的 AXStaticText 序列解析为结构化消息列表。

    大象 AX 树中，每条消息的字段顺序不固定：
      - 时间戳可以先于发送者出现，也可以在发送者之后
      - 时间戳和发送者一起构成"消息头"（header），内容紧随其后
      - 遇到新的时间戳或发送者时，若已有内容则 flush 上一条

    解析状态机：
      IN_HEADER: 正在收集时间/发送者（尚未遇到任何内容行）
      IN_CONTENT: 已遇到至少一行内容，继续追加内容

    遇到 TIME 或 SENDER：
      - 若当前处于 IN_CONTENT 状态 → flush，开启新消息头
      - 若当前处于 IN_HEADER 状态 → 更新头部字段（time/sender），不 flush
    遇到 CONTENT：
      - 追加到 content_parts，进入 IN_CONTENT 状态
    """
    # 跳过开头 UI 元素（未读/稍后/@我/单聊/群聊/图标）
    start = 0
    while start < len(texts) and (texts[start] in _UI_TABS or _is_junk(texts[start])):
        start += 1

    messages: list[dict] = []
    current_time: str | None = None
    current_sender: str | None = None
    content_parts: list[str] = []
    in_content = False  # True: 已有内容行，遇到 T/S 需要 flush

    def flush() -> None:
        body = "\n".join(p for p in content_parts if p.strip())
        if body:
            messages.append({
                "sender": current_sender or "对方",
                "content": body,
                "time": current_time,
            })

    for raw in texts[start:]:
        text = raw.strip()
        if _is_junk(text):
            continue

        is_time = bool(_TIME_RE.match(text))
        is_sender = bool(_SENDER_RE.match(text))

        if is_time or is_sender:
            if in_content:
                # 有内容在手，flush 上一条，开启新消息头
                flush()
                content_parts = []
                current_time = None
                current_sender = None
                in_content = False
            # 更新消息头字段（无论是否刚 flush）
            if is_time:
                current_time = text
            else:
                current_sender = text
        else:
            # 消息正文
            content_parts.append(text)
            in_content = True

    flush()
    return messages[-max_messages:]
