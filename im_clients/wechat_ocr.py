# im_clients/wechat_ocr.py
"""
微信聊天区域 OCR 读取。

使用 macOS Vision 框架对聊天窗口截图识别文字，
通过 x 坐标判断消息发送方（左侧=对方/昵称，右侧=我）。
"""
from __future__ import annotations

import re

# ── 截图裁剪常量（像素，屏幕坐标）─────────────────────────────
_TOP_SKIP = 50       # 跳过标题栏/导航栏
_BOTTOM_SKIP = 100   # 跳过输入框区域

# ── 解析阈值（归一化坐标 0.0-1.0）─────────────────────────────
_RIGHT_THRESHOLD = 0.5   # x_center > 0.5 → 右侧 → 我
_NAME_MAX_X = 0.3        # 群聊昵称 x_center 上限
_NAME_MAX_LEN = 30       # 群聊昵称最多字符数
_LINE_MERGE_Y = 0.04     # y 差小于此值视为同一消息的多行
_NAME_NEXT_Y = 0.06      # 昵称与其消息的最大 y 距离
_TIME_X_MIN = 0.3        # 时间戳 x_center 范围
_TIME_X_MAX = 0.7

_TIME_RE = re.compile(
    r'(?:上午|下午|昨天|星期[一二三四五六日]|\d{4}[/-]\d{1,2}[/-]\d{1,2})?\s*\d{1,2}:\d{2}'
)


# ── 顶层接口 ───────────────────────────────────────────────────

def read_chat_messages(window_bounds: tuple, max_messages: int = 20) -> list[dict]:
    """
    截取微信聊天区域截图，OCR 识别，返回结构化消息列表。

    window_bounds: (x, y, w, h) 屏幕坐标（macOS 左上角原点）
    返回: [{"sender": str, "content": str, "time": str | None}, ...]
    """
    ns_image = _capture_chat_area(window_bounds)
    if ns_image is None:
        return []
    raw_obs = _run_vision_ocr(ns_image)
    obs_dicts = [_obs_to_dict(obs) for obs in raw_obs if obs.topCandidates_(1)]
    messages = _parse_observations(obs_dicts)
    return messages[-max_messages:]


# ── 截图 ────────────────────────────────────────────────────────

def _capture_chat_area(window_bounds: tuple):
    """截取微信聊天区域（去除标题栏和输入框），返回 NSImage，失败返回 None。"""
    from AppKit import NSBitmapImageRep, NSImage
    from Quartz import (
        CGWindowListCreateImage,
        CGRectMake,
        kCGWindowListOptionAll,
        kCGNullWindowID,
        kCGWindowImageDefault,
    )
    x, y, w, h = window_bounds
    crop_y = y + _TOP_SKIP
    crop_h = h - _TOP_SKIP - _BOTTOM_SKIP
    if crop_h <= 0:
        return None
    rect = CGRectMake(x, crop_y, w, crop_h)
    cg_image = CGWindowListCreateImage(
        rect, kCGWindowListOptionAll, kCGNullWindowID, kCGWindowImageDefault
    )
    if cg_image is None:
        return None
    bitmap = NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
    ns_img = NSImage.alloc().init()
    ns_img.addRepresentation_(bitmap)
    return ns_img


# ── Vision OCR ─────────────────────────────────────────────────

def _run_vision_ocr(ns_image) -> list:
    """对 NSImage 运行 Vision OCR，返回 VNRecognizedTextObservation 列表。"""
    import Vision
    from AppKit import NSBitmapImageRep

    tiff = ns_image.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff)
    png_data = bitmap.representationUsingType_properties_(4, None)  # NSPNGFileType
    if png_data is None:
        return []
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(png_data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(1)  # VNRequestTextRecognitionLevelAccurate
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
    request.setUsesLanguageCorrection_(True)
    handler.performRequests_error_([request], None)
    return list(request.results() or [])


# ── 解析 ────────────────────────────────────────────────────────

def _obs_to_dict(obs) -> dict:
    """将 VNRecognizedTextObservation 转为可测试的 dict。"""
    box = obs.boundingBox()
    x = box.origin.x
    y_bottom = box.origin.y
    w = box.size.width
    h = box.size.height
    return {
        "text": obs.topCandidates_(1)[0].string(),
        "x": x,
        "y_top": 1.0 - (y_bottom + h),  # Vision 坐标左下原点，翻转为左上
        "width": w,
        "height": h,
        "x_center": x + w / 2,
    }


def _is_sender_name(obs: dict, next_obs: dict | None) -> bool:
    """判断 obs 是否为群聊昵称行（短文本靠左，下方紧跟左侧消息且 x_center 更大）。"""
    if next_obs is None:
        return False
    return (
        obs["x_center"] < _NAME_MAX_X
        and len(obs["text"].strip()) <= _NAME_MAX_LEN
        and next_obs["x_center"] < _RIGHT_THRESHOLD
        and 0 < next_obs["y_top"] - obs["y_top"] < _NAME_NEXT_Y
        and next_obs["x_center"] > obs["x_center"]  # 消息泡在昵称右侧（缩进更大）
    )


def _parse_observations(obs_list: list[dict]) -> list[dict]:
    """
    将 OCR observation dicts 解析为结构化消息列表。

    obs dict 格式（由 _obs_to_dict 产生）：
      {"text": str, "x": float, "y_top": float,
       "width": float, "height": float, "x_center": float}
    """
    if not obs_list:
        return []

    sorted_obs = sorted(obs_list, key=lambda o: o["y_top"])
    messages: list[dict] = []
    current_time: str | None = None
    i = 0

    while i < len(sorted_obs):
        obs = sorted_obs[i]
        text = obs["text"].strip()
        if not text:
            i += 1
            continue

        x_center = obs["x_center"]
        y_top = obs["y_top"]

        # 1. 时间戳（居中，匹配时间格式）→ 记录 current_time，不作为消息
        if _TIME_X_MIN < x_center < _TIME_X_MAX and _TIME_RE.search(text):
            current_time = text
            i += 1
            continue

        # 2. 群聊昵称（向前看：短文本靠左，下一条是左侧消息且 y 接近）
        next_obs = sorted_obs[i + 1] if i + 1 < len(sorted_obs) else None
        if _is_sender_name(obs, next_obs):
            sender = text
            i += 1  # 跳过昵称行，下一条是消息正文
            if i >= len(sorted_obs):  # 昵称在末尾，无正文可读
                break
            obs = sorted_obs[i]
            text = obs["text"].strip()
            x_center = obs["x_center"]
            y_top = obs["y_top"]
        else:
            sender = "我" if x_center > _RIGHT_THRESHOLD else "对方"

        # 3. 合并同一消息的多行（y 差 < 阈值，同侧，非时间戳）
        content_parts = [text]
        cur_is_me = x_center > _RIGHT_THRESHOLD
        while i + 1 < len(sorted_obs):
            n = sorted_obs[i + 1]
            n_text = n["text"].strip()
            n_is_me = n["x_center"] > _RIGHT_THRESHOLD
            n_is_time = _TIME_X_MIN < n["x_center"] < _TIME_X_MAX and _TIME_RE.search(n_text)
            if (
                n_text
                and n_is_me == cur_is_me
                and n["y_top"] - y_top < _LINE_MERGE_Y
                and not n_is_time
            ):
                content_parts.append(n_text)
                y_top = n["y_top"]  # 滑动窗口：比较相邻行间距，允许消息跨多行累积
                i += 1
            else:
                break

        messages.append({
            "sender": sender,
            "content": "\n".join(content_parts),
            "time": current_time,
        })
        i += 1

    return messages
