# im_clients/wechat.py
from __future__ import annotations

import os
import tempfile
import time

import sender  # 复用企业微信已验证的图片合成逻辑（render_blocks_to_image）
from .ax_helpers import (
    activate_app,
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

_WX_PROBE = _get_probe("wechat")


class WechatAdapter(IMClientAdapter):
    """
    微信（个人版）IM 适配器。

    微信 macOS 版使用 Qt 渲染 UI，AX API 无法穿透其内部元素（AX 树只有 6 个节点）。
    因此改用坐标点击定位输入框：激活窗口后点击窗口底部中央（距底 50px）。

    发送：坐标点击输入框 → 剪贴板 Cmd+V → AppleScript Enter（key code 36）
    读取聊天：Qt 渲染层不暴露 AX 消息列表，can_read_chat=False。
    """

    client_id = "wechat"
    display_name = "微信"
    app_names = ("微信", "WeChat")
    bundle_ids = ("com.tencent.xinWeChat", "com.tencent.xinwechat")
    capabilities = TakeoverCapabilities(
        can_activate=True,
        can_window_bounds=True,
        can_send=True,
        can_read_chat=True,   # OCR 实现：截图 + Vision 识别
        verified=True,  # 真机验证：坐标点击 + Cmd+V + AppleScript Enter 可靠
    )

    # AppleScript tell process 用的进程名（真机验证：微信）
    _PROCESS_NAME = "WeChat"

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

    def _get_window_bounds(self) -> tuple | None:
        """
        返回微信主窗口 (x, y, w, h)，未运行或无窗口返回 None。

        从 _click_input_area 中抽取，两个方法共用，避免重复 AX 调用。
        """
        ax = get_ax_element(self._get_app_name() or self.app_names[0])
        if ax is None:
            return None
        try:
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXValueGetValue,
                kAXWindowsAttribute,
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueCGPointType,
                kAXValueCGSizeType,
            )
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                return None
            win = get_largest_window(windows)  # 取主窗口，避免输入法弹框干扰
            if win is None:
                return None
            _, pos_ref = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
            _, size_ref = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
            _, pt = AXValueGetValue(pos_ref, kAXValueCGPointType, None)
            _, sz = AXValueGetValue(size_ref, kAXValueCGSizeType, None)
            return (pt.x, pt.y, sz.width, sz.height)
        except Exception:
            return None

    def _click_input_area(self) -> bool:
        """
        通过坐标点击定位微信输入框。

        微信 Qt 版 AX 树不暴露输入框元素，改用窗口坐标：
        点击窗口底部中央（距底 50px），即输入框所在区域。
        返回 True 表示点击执行（不保证焦点已获取）。
        """
        bounds = self._get_window_bounds()
        if bounds is None:
            return False
        try:
            from Quartz import (
                CGEventCreateMouseEvent,
                CGEventPost,
                CGPointMake,
                kCGEventLeftMouseDown,
                kCGEventLeftMouseUp,
                kCGHIDEventTap,
                kCGMouseButtonLeft,
            )
            x, y, w, h = bounds
            click_x = x + w / 2
            click_y = y + h - _WX_PROBE.click_bottom_offset  # 输入框在窗口底部中央，距底约 50px
            p = CGPointMake(click_x, click_y)
            CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(
                None, kCGEventLeftMouseDown, p, kCGMouseButtonLeft))
            time.sleep(0.05)
            CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(
                None, kCGEventLeftMouseUp, p, kCGMouseButtonLeft))
            time.sleep(0.2)
            return True
        except Exception:
            return False

    def send_blocks(self, blocks: list) -> bool:
        """
        发送 blocks 到当前微信聊天窗口。

        纯文字：坐标点击输入框 → set_clipboard_text → Cmd+V → AppleScript Enter
        含图片：render_blocks_to_image 合成 PNG → set_clipboard_png → Cmd+V → Enter
        图文混排：合成单张图片发送（保证只出现一条消息）
        """
        app_name = self._get_app_name()
        if app_name is None:
            return False

        if not activate_app(app_name):
            return False

        if not self._click_input_area():
            raise UnsupportedClientAction("微信未找到聊天窗口，请先在微信中选中一个聊天")

        has_image = any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

        if has_image:
            return self._send_as_image(blocks, app_name)
        else:
            return self._send_text_blocks(blocks, app_name)

    def _send_text_blocks(self, blocks: list, app_name: str) -> bool:
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

    def _send_as_image(self, blocks: list, app_name: str) -> bool:
        """图文混排：合成 PNG 发送（保证单条消息）。"""
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            output_path = sender.render_blocks_to_image(blocks, output_path=tmp)
            set_clipboard_png(output_path)
            paste_and_send(app_name=self._PROCESS_NAME)
            return True
        except Exception as e:
            raise UnsupportedClientAction(f"微信图片合成失败: {e}") from e
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """
        截取微信聊天区域截图，通过 Vision OCR 识别消息内容。

        返回格式: [{"sender": str, "content": str, "time": str | None}]
        微信未运行或无窗口时返回 []。

        窗口发现走 wechat_ocr.find_main_window()（CGWindowList，只需屏幕录制权限），
        不依赖 AX/辅助功能——微信 Qt 渲染 AX 不透过，且独立运行时常无辅助功能权限。
        """
        from . import wechat_ocr
        return wechat_ocr.read_chat_messages(max_messages=max_messages)
