#!/usr/bin/env python3
"""
向企业微信发送消息 Demo (macOS)

原理：
1. AppleScript 激活企业微信窗口
2. NSPasteboard 写入要发送的文本到系统剪贴板
3. CGEvent 模拟 Cmd+V 粘贴
4. CGEvent 模拟 Enter 发送

使用前提：
- 企业微信桌面端已打开且已进入某个聊天窗口
- 终端/Python 已在「系统设置 → 隐私与安全性 → 辅助功能」中获得授权
"""

import os
import sys
import time
import subprocess
import html
import base64
import tempfile
from collections import deque

# macOS 原生框架
from AppKit import (
    NSPasteboard, NSStringPboardType, NSPasteboardTypeString,
    NSWorkspace, NSApplicationActivateIgnoringOtherApps,
    NSImage, NSBitmapImageRep,
)
from Foundation import NSData
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXRoleAttribute,
    kAXChildrenAttribute,
    kAXFocusedAttribute,
    kAXWindowsAttribute,
    kAXValueAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
    kCGEventKeyDown,
    kCGEventKeyUp,
    CGEventCreateMouseEvent,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGMouseButtonLeft,
    CGPointMake,
)


class NoChatWindowError(Exception):
    """企业微信未选中聊天窗口时抛出"""
    pass


# ============================================================
# 模块一：窗口识别与激活
# ============================================================

WX_APP_NAME = "企业微信"


def _get_wechat_app():
    """从 NSWorkspace 找到企业微信的 NSRunningApplication 对象"""
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    return next((a for a in apps if a.localizedName() == WX_APP_NAME), None)


def is_wx_running() -> bool:
    """检查企业微信是否正在运行"""
    return _get_wechat_app() is not None


def activate_wx() -> bool:
    """激活企业微信窗口，用 PyObjC 直接调用，无 subprocess 开销"""
    app = _get_wechat_app()
    if app is None:
        print("[错误] 企业微信未运行")
        return False
    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    time.sleep(0.1)  # 等待窗口完成激活
    return True


_ax_app_cache = None  # 缓存 AXUIElement，避免重复查 PID


def _get_ax_app():
    global _ax_app_cache
    if _ax_app_cache is None:
        app = _get_wechat_app()
        if app is None:
            return None
        _ax_app_cache = AXUIElementCreateApplication(app.processIdentifier())
    return _ax_app_cache


def _find_text_area(root):
    """BFS 查找最浅的 AXTextArea（聊天输入框比消息历史区更浅，BFS 优先命中）"""
    queue = deque([(root, 0)])
    while queue:
        element, depth = queue.popleft()
        if depth > 10:
            continue
        try:
            _, role = AXUIElementCopyAttributeValue(element, kAXRoleAttribute, None)
            if role == "AXTextArea":
                return element
            _, children = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, None)
            if children:
                for child in children:
                    queue.append((child, depth + 1))
        except Exception:
            pass
    return None


def focus_chat_input() -> bool:
    """在 AX 树中找到聊天输入框并主动聚焦。找到返回 True，否则返回 False。"""
    ax = _get_ax_app()
    if ax is None:
        return False
    try:
        _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
        if not windows:
            return False
        text_area = _find_text_area(windows[0])
        if text_area is None:
            return False
        AXUIElementSetAttributeValue(text_area, kAXFocusedAttribute, True)
        return True
    except Exception:
        return False


def _find_msg_table(root):
    """BFS 找右侧消息历史的 AXTable（depth=6，路径含两层 AXSplitGroup）"""
    queue = deque([(root, 0)])
    while queue:
        el, d = queue.popleft()
        if d > 8:
            continue
        try:
            role = get_ax_attr(el, kAXRoleAttribute)
            if role == "AXTable" and d == 6:
                return el
            children = get_ax_attr(el, kAXChildrenAttribute) or []
            for c in children:
                queue.append((c, d + 1))
        except Exception:
            pass
    return None


def get_ax_attr(element, attribute):
    _, value = AXUIElementCopyAttributeValue(element, attribute, None)
    return value


def read_chat_messages(max_messages: int = 20) -> list[dict]:
    """
    读取当前聊天窗口的消息记录。

    返回列表，每项为：
        {"content": str, "time": str | None}
    按时间顺序排列，最多返回 max_messages 条。
    """
    ax = _get_ax_app()
    if ax is None:
        return []
    try:
        windows = get_ax_attr(ax, kAXWindowsAttribute)
        if not windows:
            return []
        table = _find_msg_table(windows[0])
        if table is None:
            return []

        messages = []
        rows = get_ax_attr(table, kAXChildrenAttribute) or []
        for row in rows:
            cells = get_ax_attr(row, kAXChildrenAttribute) or []
            if not cells:
                continue
            content, time_str = _extract_msg_fields(cells[0])
            if content:
                messages.append({"content": content, "time": time_str})

        return messages[-max_messages:]
    except Exception:
        return []


def _extract_msg_fields(cell) -> tuple[str | None, str | None]:
    """从消息 Cell 中提取内容和时间"""
    content = None
    time_str = None
    children = get_ax_attr(cell, kAXChildrenAttribute) or []
    for child in children:
        role = get_ax_attr(child, kAXRoleAttribute)
        val  = get_ax_attr(child, kAXValueAttribute)
        if role == "AXTextArea" and val and content is None:
            raw = str(val)
            # 部分消息 AX 树会将内容重复两次，去重
            half = len(raw) // 2
            content = raw[:half] if half and raw[:half] == raw[half:] else raw
        elif role == "AXStaticText" and val:
            time_str = str(val)
    return content, time_str


# ============================================================
# 模块二：剪贴板操作
# ============================================================

def set_clipboard(text: str):
    """将文本写入系统剪贴板"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def set_clipboard_html(html_content: str, plain_text: str = ""):
    """将 HTML 和纯文本 fallback 一起写入系统剪贴板。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    data = html_content.encode("utf-8")
    pb.setData_forType_(NSData.dataWithBytes_length_(data, len(data)), "public.html")
    if plain_text:
        pb.setString_forType_(plain_text, NSPasteboardTypeString)


def get_clipboard() -> str:
    """读取系统剪贴板内容"""
    pb = NSPasteboard.generalPasteboard()
    return pb.stringForType_(NSPasteboardTypeString) or ""


# ============================================================
# 模块三：模拟按键
# ============================================================

# macOS 虚拟键码
KEY_V = 0x09        # V 键
KEY_RETURN = 0x24   # Enter/Return 键
KEY_A = 0x00        # A 键


def press_key(keycode: int, flags: int = 0):
    """
    模拟按下并释放一个按键。
    keycode: macOS 虚拟键码
    flags: 修饰键标记 (如 kCGEventFlagMaskCommand)
    """
    # Key Down
    event_down = CGEventCreateKeyboardEvent(None, keycode, True)
    if flags:
        CGEventSetFlags(event_down, flags)
    CGEventPost(kCGHIDEventTap, event_down)

    time.sleep(0.05)

    # Key Up
    event_up = CGEventCreateKeyboardEvent(None, keycode, False)
    if flags:
        CGEventSetFlags(event_up, flags)
    CGEventPost(kCGHIDEventTap, event_up)

    time.sleep(0.05)


def paste():
    """模拟 Cmd+V 粘贴"""
    press_key(KEY_V, kCGEventFlagMaskCommand)


def press_enter():
    """用 AppleScript 发送 Return 键，对 Electron 类应用（如企业微信）更可靠"""
    script = '''
    tell application "System Events"
        tell process "企业微信"
            key code 36
        end tell
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def press_shift_enter():
    """用 AppleScript 发送 Shift+Return，在输入框内换行（不发送消息）"""
    script = '''
    tell application "System Events"
        keystroke return using {shift down}
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _mouse_click(x: float, y: float):
    """在屏幕坐标 (x, y) 处模拟鼠标左键单击。"""
    pos = CGPointMake(x, y)
    down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, pos, kCGMouseButtonLeft)
    up   = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp,   pos, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.05)
    CGEventPost(kCGHIDEventTap, up)
    time.sleep(0.05)


def click_send_button() -> bool:
    """在企业微信聊天输入区找到发送按钮并点击。
    优先用 AX AXPress；失败则用鼠标点击按钮中心。
    """
    from ApplicationServices import (
        AXUIElementCopyAttributeValue, kAXWindowsAttribute,
        kAXRoleAttribute, kAXChildrenAttribute,
        kAXPositionAttribute, kAXSizeAttribute,
        AXUIElementPerformAction, AXUIElementCopyActionNames,
        AXValueGetValue, kAXValueCGPointType, kAXValueCGSizeType,
        kAXPressAction,
    )
    from collections import deque

    ax = _get_ax_app()
    if ax is None:
        return False
    try:
        _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
        if not windows:
            return False

        win = windows[0]
        # 获取窗口底部坐标
        _, wpos_ref = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
        _, wsz_ref  = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
        _, wpt = AXValueGetValue(wpos_ref, kAXValueCGPointType, None)
        _, wsz = AXValueGetValue(wsz_ref,  kAXValueCGSizeType,  None)
        win_bottom = wpt.y + wsz.height

        # BFS 找最靠近窗口底部右侧的 AXButton（即发送按钮）
        queue = deque([(win, 0)])
        best = None   # (y_distance_to_bottom, x_right, element, cx, cy)
        while queue:
            el, d = queue.popleft()
            if d > 12:
                continue
            try:
                _, role = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
                if role == "AXButton":
                    _, pr = AXUIElementCopyAttributeValue(el, kAXPositionAttribute, None)
                    _, sr = AXUIElementCopyAttributeValue(el, kAXSizeAttribute, None)
                    if pr and sr:
                        _, pt = AXValueGetValue(pr, kAXValueCGPointType, None)
                        _, sz = AXValueGetValue(sr, kAXValueCGSizeType,  None)
                        if pt and sz and sz.width >= 50:   # 排除小图标按钮
                            dist = win_bottom - (pt.y + sz.height)
                            cx = pt.x + sz.width / 2
                            cy = pt.y + sz.height / 2
                            if best is None or dist < best[0] or (dist == best[0] and cx > best[1]):
                                best = (dist, cx, el, cx, cy)
                _, ch = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
                if ch:
                    for c in ch:
                        queue.append((c, d + 1))
            except Exception:
                pass

        if best is None:
            return False

        _, _, btn, cx, cy = best
        # 先尝试 AX Press
        try:
            _, actions = AXUIElementCopyActionNames(btn)
            if actions and kAXPressAction in actions:
                AXUIElementPerformAction(btn, kAXPressAction)
                return True
        except Exception:
            pass

        # AX Press 不可用时，用鼠标点击
        _mouse_click(cx, cy)
        return True

    except Exception:
        return False


def type_text(text: str):
    """用 AppleScript keystroke 直接模拟键盘输入，支持中文 Unicode。

    比剪贴板粘贴（Cmd+V）更接近用户手动输入：企业微信会将其保留在
    输入框 buffer 中，后续粘贴图片后 Enter 可将两者作为一条消息发出。
    """
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    script = f'''
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def select_all():
    """模拟 Cmd+A 全选"""
    press_key(KEY_A, kCGEventFlagMaskCommand)


# ============================================================
# 模块四：核心发送逻辑
# ============================================================

def send_message(text: str, auto_activate: bool = True, delay_before_send: float = 0.1) -> bool:
    """
    向企业微信当前聊天窗口发送一条文本消息。

    参数：
        text: 要发送的消息文本
        auto_activate: 是否自动激活企业微信窗口（如果已经是前台则不需要）
        delay_before_send: 粘贴后等待多久再按回车（秒），防止粘贴未完成就发送

    返回：
        是否发送成功（基本判断，无法100%确认消息已送达）
    """
    if not text.strip():
        print("[警告] 消息内容为空，跳过发送")
        return False

    # Step 1: 激活企业微信（内含运行检查）
    if auto_activate:
        if not activate_wx():
            return False

    # Step 2: 找到聊天输入框并聚焦（同时验证是否有聊天窗口）
    if not focus_chat_input():
        raise NoChatWindowError("请先在企业微信中选中聊天窗口")

    # Step 3: 保存原始剪贴板内容
    original_clipboard = get_clipboard()

    # Step 3: 写入消息到剪贴板并粘贴
    set_clipboard(text)
    paste()
    time.sleep(delay_before_send)

    # Step 4: 模拟 Enter 发送
    press_enter()

    # Step 5: 恢复原始剪贴板
    set_clipboard(original_clipboard)

    print(f"[成功] 消息已发送: {text[:50]}{'...' if len(text) > 50 else ''}")
    return True


def send_image(path: str, auto_activate: bool = True) -> bool:
    """向企业微信当前聊天窗口发送一张图片。

    参数：
        path: 图片文件路径（支持 ~ 展开）
        auto_activate: 是否重新激活企业微信窗口。顺序发送时传 False，
                       避免重复激活打断当前输入框焦点。
    """
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise FileNotFoundError(f"图片不存在: {expanded}")

    if not is_wx_running():
        print("[错误] 企业微信未运行")
        return False

    if auto_activate:
        if not activate_wx():
            return False

    if not focus_chat_input():
        raise NoChatWindowError("请先在企业微信中选中聊天窗口")

    image = NSImage.alloc().initWithContentsOfFile_(expanded)
    if image is None:
        raise ValueError(f"无法加载图片: {expanded}")

    original_text = get_clipboard()   # 保存原文字剪贴板

    # 企业微信（Electron/Chromium）需要 public.png 格式，纯 TIFF 不被识别
    # 与 macOS 截图工具写入格式保持一致
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    tiff_data = image.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
    png_data = bitmap.representationUsingType_properties_(4, None)  # 4 = NSPNGFileType
    if png_data:
        pb.setData_forType_(png_data, "public.png")
    else:
        pb.writeObjects_([image])   # 兜底：写 TIFF

    time.sleep(0.1)
    paste()
    time.sleep(0.5)
    press_enter()
    time.sleep(0.2)

    # 恢复文字剪贴板（图片数据无法恢复，只恢复文字内容）
    set_clipboard(original_text)

    print(f"[成功] 图片已发送: {os.path.basename(expanded)}")
    return True


def _blocks_plain_text(blocks: list) -> str:
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            content = block.get("content", "").strip()
            if content:
                parts.append(content)
        elif block.get("type") == "image":
            path = block.get("path", "")
            if path:
                parts.append(f"[图片: {os.path.basename(path)}]")
    return "\n".join(parts)


def _image_data_uri(path: str) -> str:
    expanded = os.path.expanduser(path)
    ext = os.path.splitext(expanded)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    with open(expanded, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_html_blocks(blocks: list) -> str:
    body = []
    for block in blocks:
        if block.get("type") == "text":
            content = block.get("content", "").strip()
            if content:
                escaped = html.escape(content).replace("\n", "<br>")
                body.append(f'<div style="white-space:pre-wrap">{escaped}</div>')
        elif block.get("type") == "image":
            path = block.get("path", "")
            if path:
                uri = _image_data_uri(path)
                body.append(f'<div><img src="{uri}"></div>')
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        f'<body>{"".join(body)}</body></html>'
    )


def _validate_image_blocks(blocks: list):
    for block in blocks:
        if block.get("type") != "image":
            continue
        path = block.get("path", "")
        expanded = os.path.expanduser(path)
        if not os.path.exists(expanded):
            raise FileNotFoundError(f"图片不存在: {expanded}")


def send_blocks_html_once(blocks: list, auto_activate: bool = True) -> bool:
    """实验路径：把 text + img(data URI) 作为 HTML 剪贴板一次性粘贴并发送。

    注意：企业微信是否保留 HTML 中的图片，取决于 Electron/Web 编辑器的粘贴
    处理和客户端协议。本函数只能完成一次性 HTML 粘贴，不能保证最终消息一定
    以原生图文混排形式发出。
    """
    useful_blocks = [
        b for b in blocks
        if b.get("type") == "image" or (b.get("type") == "text" and b.get("content", "").strip())
    ]
    if not useful_blocks:
        return True

    _validate_image_blocks(useful_blocks)

    if auto_activate:
        if not activate_wx():
            return False
    if not focus_chat_input():
        raise NoChatWindowError("请先在企业微信中选中聊天窗口")

    original_text = get_clipboard()
    set_clipboard_html(_build_html_blocks(useful_blocks), _blocks_plain_text(useful_blocks))
    time.sleep(0.1)
    paste()
    time.sleep(0.5)
    press_enter()
    time.sleep(0.2)
    set_clipboard(original_text)
    return True


def _load_ui_font(size: int):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_width(draw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap_text_by_width(draw, text: str, font, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and _text_width(draw, candidate, font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines


def render_blocks_to_image(blocks: list, output_path: str | None = None, max_width: int = 900) -> str:
    """将图文 block 渲染为一张 PNG，用于单条图片消息兜底发送。"""
    from PIL import Image, ImageDraw

    useful_blocks = [
        b for b in blocks
        if b.get("type") == "image" or (b.get("type") == "text" and b.get("content", "").strip())
    ]
    if not useful_blocks:
        raise ValueError("没有可渲染的图文内容")
    _validate_image_blocks(useful_blocks)

    padding = 28
    gap = 18
    text_color = (30, 35, 48)
    bg_color = (255, 255, 255)
    font = _load_ui_font(30)
    line_gap = 9
    content_width = max_width - padding * 2

    probe = Image.new("RGB", (max_width, 100), bg_color)
    draw = ImageDraw.Draw(probe)
    rendered = []
    total_height = padding

    for block in useful_blocks:
        if block.get("type") == "text":
            lines = _wrap_text_by_width(draw, block.get("content", "").strip(), font, content_width)
            line_boxes = [draw.textbbox((0, 0), line or " ", font=font) for line in lines]
            line_heights = [box[3] - box[1] for box in line_boxes]
            height = sum(line_heights) + line_gap * max(0, len(lines) - 1)
            rendered.append(("text", lines, line_heights, height))
            total_height += height + gap
        elif block.get("type") == "image":
            img = Image.open(os.path.expanduser(block.get("path", ""))).convert("RGBA")
            if img.width > content_width:
                ratio = content_width / img.width
                img = img.resize((content_width, max(1, int(img.height * ratio))), Image.LANCZOS)
            rendered.append(("image", img, img.height))
            total_height += img.height + gap

    total_height = max(padding * 2, total_height - gap + padding)
    canvas = Image.new("RGB", (max_width, total_height), bg_color)
    draw = ImageDraw.Draw(canvas)
    y = padding

    for item in rendered:
        if item[0] == "text":
            _, lines, line_heights, _ = item
            for line, line_height in zip(lines, line_heights):
                draw.text((padding, y), line, fill=text_color, font=font)
                y += line_height + line_gap
            y -= line_gap
        else:
            _, img, _ = item
            x = padding + (content_width - img.width) // 2
            canvas.paste(img, (x, y), img)
            y += img.height
        y += gap

    if output_path is None:
        fd, output_path = tempfile.mkstemp(prefix="wechat_mixed_", suffix=".png")
        os.close(fd)
    canvas.save(output_path, "PNG")
    return output_path


def send_blocks_as_image(blocks: list, auto_activate: bool = True) -> bool:
    """可靠路径：把图文混排渲染为一张图片，再作为单条图片消息发送。"""
    output_path = render_blocks_to_image(blocks)
    try:
        return send_image(output_path, auto_activate=auto_activate)
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass


def send_blocks_single(blocks: list, prefer_html: bool = False) -> bool:
    """尽量以单条消息发送图文内容。

    prefer_html=True 会先尝试 HTML 剪贴板实验路径；异常时降级为合成图片。
    默认直接使用合成图片，因为这是当前能保证"单条消息"的路径。
    """
    useful_blocks = [
        b for b in blocks
        if b.get("type") == "image" or (b.get("type") == "text" and b.get("content", "").strip())
    ]
    if not useful_blocks:
        return True

    has_image = any(b.get("type") == "image" for b in useful_blocks)
    if not has_image:
        return send_message(_blocks_plain_text(useful_blocks))

    if prefer_html:
        try:
            return send_blocks_html_once(useful_blocks)
        except Exception as exc:
            print(f"[警告] HTML 图文粘贴失败，降级为合成图片: {exc}")

    return send_blocks_as_image(useful_blocks)


def send_blocks(blocks: list) -> bool:
    """依次发送图文混排的各个 block。

    每个 block 独立发送：
    - text  → send_message()（剪贴板粘贴 + Enter，已验证可靠）
    - image → send_image()（PNG 格式剪贴板 + Enter，已验证可靠）

    第一个 block 正常激活企业微信，后续 block 跳过重复激活。
    """
    if not blocks:
        return True

    first = True
    for block in blocks:
        btype = block.get("type")

        if btype == "text":
            content = block.get("content", "").strip()
            if not content:
                continue
            send_message(content, auto_activate=first)
            first = False
            time.sleep(0.3)

        elif btype == "image":
            path = block.get("path", "")
            if not path:
                continue
            send_image(path, auto_activate=first)
            first = False
            time.sleep(0.3)

    return True


def send_messages_batch(messages: list, interval: float = 1.0):
    """
    批量发送多条消息。

    参数：
        messages: 消息列表
        interval: 每条消息之间的间隔（秒）
    """
    print(f"[信息] 准备批量发送 {len(messages)} 条消息，间隔 {interval} 秒")

    for i, msg in enumerate(messages, 1):
        print(f"[{i}/{len(messages)}] 发送中...")
        success = send_message(msg, auto_activate=(i == 1))
        if not success:
            print(f"[错误] 第 {i} 条消息发送失败，终止批量发送")
            return
        if i < len(messages):
            time.sleep(interval)

    print(f"[完成] 批量发送 {len(messages)} 条消息完毕")


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("用法: python sender.py <消息内容>")
        print("示例: python sender.py '你好，这是自动发送的消息'")
        print("")
        print("批量发送（用 | 分隔）:")
        print("  python sender.py '消息1|消息2|消息3'")
        sys.exit(1)

    text = " ".join(sys.argv[1:])

    # 支持用 | 分隔批量发送
    if "|" in text:
        messages = [m.strip() for m in text.split("|") if m.strip()]
        send_messages_batch(messages)
    else:
        send_message(text)


if __name__ == "__main__":
    main()
