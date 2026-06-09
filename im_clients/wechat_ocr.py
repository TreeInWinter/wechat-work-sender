# im_clients/wechat_ocr.py
"""
微信聊天区域 OCR 读取。

使用 macOS Vision 框架对聊天窗口截图识别文字，
通过 x 坐标判断消息发送方（左侧=对方/昵称，右侧=我）。

真机验证关键结论（2026-06-09，macOS 26.5.1）：
1. **必须用 Fast 识别级别**：该 macOS 版本 Accurate（level=1）的中文模型损坏，
   识别结果全是乱码且置信度恒为 0.30/0.50；Fast（level=0）中文正常，置信度 1.00。
2. **必须显式设 revision ≥ 2**：默认 revision 1 仅支持 en-US，中文完全识别不出。
   revision 2 起支持 zh-Hans/zh-Hant，revision 3 支持更多语言，优先用最高可用 revision。
3. **按窗口 ID 定向截图**：CGWindowListCreateImage 用 kCGWindowListOptionAll + 矩形
   会把该屏幕区域内所有叠加窗口一起截进来（如被系统设置遮挡时截到设置面板）。
   改用 kCGWindowListOptionIncludingWindow + 窗口 ID，只截微信窗口本身。
4. **不依赖 AX 拿窗口**：微信 Qt 渲染 AX 不透过，且 AX 需「辅助功能」权限；
   CGWindowList 只需「屏幕录制」权限（OCR 本就需要），用它发现窗口更稳。
5. **过滤左侧会话列表**：微信是「左侧会话列表 + 右侧聊天面板」布局，
   会话列表的名字/时间戳会污染消息解析，需按 x 过滤掉（保留聊天面板）后再解析。
"""
from __future__ import annotations

import logging
import re

# ── 布局过滤阈值（归一化坐标 0.0-1.0，相对整窗）─────────────────
_SIDEBAR_MAX_X = 0.40    # x_center < 此值 → 左侧会话列表，丢弃（聊天面板在右侧）
_TOP_Y = 0.06            # y_top < 此值 → 聊天标题栏，丢弃
_BOTTOM_Y = 0.93         # y_top > 此值 → 底部输入框/工具栏，丢弃
_MIN_CONFIDENCE = 0.3    # OCR 置信度低于此值 → 视为噪声，丢弃

# ── 解析阈值（归一化坐标 0.0-1.0，已映射到聊天面板内）───────────
_RIGHT_THRESHOLD = 0.5   # 面板内 x_center > 0.5 → 右侧 → 我
_NAME_MAX_X = 0.3        # 群聊昵称 x_center 上限
_NAME_MAX_LEN = 30       # 群聊昵称最多字符数
_LINE_MERGE_Y = 0.04     # y 差小于此值视为同一消息的多行
_NAME_NEXT_Y = 0.06      # 昵称与其消息的最大 y 距离
_TIME_X_MIN = 0.3        # 时间戳 x_center 范围
_TIME_X_MAX = 0.7

_TIME_RE = re.compile(
    r'(?:上午|下午|昨天|星期[一二三四五六日]|\d{4}[/-]\d{1,2}[/-]\d{1,2})?\s*\d{1,2}:\d{2}'
)

# 微信窗口所有者名（不同语言环境）
_WECHAT_OWNERS = ("微信", "WeChat")
_MIN_MAIN_WINDOW_WIDTH = 400  # 主窗口宽度下限，过滤输入法/小弹框


# ── 顶层接口 ───────────────────────────────────────────────────

def read_chat_messages(window_bounds: tuple | None = None,
                       max_messages: int = 20) -> list[dict]:
    """
    截取微信聊天区域截图，OCR 识别，返回结构化消息列表。

    window_bounds: 兼容旧签名，已不使用（窗口经 CGWindowList 自动发现）。
    返回: [{"sender": str, "content": str, "time": str | None}, ...]
    微信未运行/无窗口/截图失败时返回 []。
    """
    window_id, _bounds = find_main_window()
    if window_id is None:
        return []
    cg_image = _capture_window(window_id)
    if cg_image is None:
        return []
    raw_obs = _run_vision_ocr(cg_image)
    obs_dicts = [_obs_to_dict(obs) for obs in raw_obs if obs.topCandidates_(1)]
    chat_obs = _filter_chat_area(obs_dicts)
    messages = _parse_observations(chat_obs)
    return messages[-max_messages:]


# ── 窗口发现（CGWindowList，无需 AX/辅助功能权限）───────────────

def find_main_window() -> tuple[int | None, tuple | None]:
    """
    通过 CGWindowList 发现微信主窗口。

    返回 (window_id, (x, y, w, h))；未找到返回 (None, None)。
    只需「屏幕录制」权限，不依赖 AX/辅助功能。
    """
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )
    except Exception:
        return None, None
    info = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    if not info:
        return None, None
    best = None  # (area, window_id, bounds)
    for w in info:
        owner = w.get("kCGWindowOwnerName", "") or ""
        if owner not in _WECHAT_OWNERS:
            continue
        if w.get("kCGWindowLayer", 0) != 0:  # 仅普通层窗口，排除菜单/悬浮层
            continue
        b = w.get("kCGWindowBounds", {}) or {}
        width = b.get("Width", 0) or 0
        height = b.get("Height", 0) or 0
        if width < _MIN_MAIN_WINDOW_WIDTH:
            continue
        area = width * height
        if best is None or area > best[0]:
            best = (area, w.get("kCGWindowNumber"),
                    (b.get("X", 0), b.get("Y", 0), width, height))
    if best is None:
        return None, None
    return best[1], best[2]


# ── 截图（按窗口 ID 定向，避免截到遮挡窗口）─────────────────────

def _capture_window(window_id: int):
    """对指定窗口 ID 截图，返回 CGImage，失败返回 None。"""
    try:
        from Quartz import (
            CGWindowListCreateImage,
            CGRectNull,
            kCGWindowListOptionIncludingWindow,
            kCGWindowImageBoundsIgnoreFraming,
            kCGWindowImageBestResolution,  # Retina 全分辨率，OCR 更准
        )
    except Exception:
        return None
    return CGWindowListCreateImage(
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        window_id,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
    )


# ── Vision OCR ─────────────────────────────────────────────────

def _best_revision() -> int:
    """返回支持中文的最高可用 Vision revision（≥2 才支持 zh-Hans），失败回退 2。"""
    try:
        import Vision
        revisions = list(Vision.VNRecognizeTextRequest.supportedRevisions() or [])
        # revision 1 仅 en-US，必须 ≥2
        usable = [r for r in revisions if r >= 2]
        return max(usable) if usable else 2
    except Exception:
        return 2


def _run_vision_ocr(cg_image) -> list:
    """对 CGImage 运行 Vision OCR，返回 VNRecognizedTextObservation 列表。"""
    import Vision

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, None
    )
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRevision_(_best_revision())     # ★ 中文需 revision ≥ 2
    request.setRecognitionLevel_(0)            # ★ Fast：Accurate 在 macOS 26 中文损坏
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    request.setUsesLanguageCorrection_(True)
    request.setMinimumTextHeight_(0.005)       # 识别更小字号
    _, err = handler.performRequests_error_([request], None)
    if err:
        logging.warning("Vision OCR error: %s", err)
    return list(request.results() or [])


# ── 解析 ────────────────────────────────────────────────────────

def _obs_to_dict(obs) -> dict:
    """将 VNRecognizedTextObservation 转为可测试的 dict。"""
    box = obs.boundingBox()
    x = box.origin.x
    y_bottom = box.origin.y
    w = box.size.width
    h = box.size.height
    candidate = obs.topCandidates_(1)[0]
    return {
        "text": candidate.string(),
        "confidence": float(candidate.confidence()),
        "x": x,
        "y_top": 1.0 - (y_bottom + h),  # Vision 坐标左下原点，翻转为左上
        "width": w,
        "height": h,
        "x_center": x + w / 2,
    }


def _filter_chat_area(obs_list: list[dict],
                     sidebar_max_x: float = _SIDEBAR_MAX_X) -> list[dict]:
    """
    过滤掉左侧会话列表 / 标题栏 / 底部输入框 / 低置信噪声，
    并把保留下来的聊天面板内 obs 的 x 坐标归一化到面板宽度 [0, 1]。

    归一化后，下游 _parse_observations 的左右/昵称/时间阈值（都基于 0-1）
    可直接复用，无需关心面板在整窗中的实际位置。
    """
    span = 1.0 - sidebar_max_x
    if span <= 0:
        return []
    result: list[dict] = []
    for o in obs_list:
        if o.get("confidence", 1.0) < _MIN_CONFIDENCE:
            continue
        if o["x_center"] < sidebar_max_x:   # 左侧会话列表
            continue
        if not (_TOP_Y < o["y_top"] < _BOTTOM_Y):  # 标题栏 / 输入框
            continue
        no = dict(o)
        no["x"] = max(0.0, (o["x"] - sidebar_max_x) / span)
        no["x_center"] = max(0.0, min(1.0, (o["x_center"] - sidebar_max_x) / span))
        no["width"] = o["width"] / span
        result.append(no)
    return result


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

    obs dict 格式（由 _obs_to_dict 产生，x 坐标已由 _filter_chat_area 归一化）：
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
