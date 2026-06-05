# 微信 OCR 读取聊天消息实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `WechatAdapter.read_chat_messages()` 实现基于 macOS Vision OCR 的聊天消息读取，返回 `[{"sender", "content", "time"}]`。

**Architecture:** 新增 `im_clients/wechat_ocr.py` 封装截图 + OCR + 解析逻辑；在 `wechat.py` 中抽取 `_get_window_bounds()`（`_click_input_area` 复用），`read_chat_messages()` 改为调用 `wechat_ocr.read_chat_messages()`，`can_read_chat` 改为 `True`。

**Tech Stack:** macOS Vision 框架（`import Vision`，PyObjC），Quartz `CGWindowListCreateImage`，unittest + unittest.mock

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `im_clients/wechat_ocr.py` | OCR 截图 + 解析，单一职责 |
| 新建 | `tests/test_wechat_ocr.py` | 纯解析逻辑测试（无真机），OCR mock 测试 |
| 修改 | `im_clients/wechat.py` | 抽取 `_get_window_bounds`，接入 OCR，`can_read_chat=True` |
| 修改 | `tests/test_im_clients.py` | 更新 `can_read_chat` 断言，替换 `read_chat` 测试 |

---

## Task 1：实现解析核心 `_parse_observations`（TDD，纯函数，无真机）

**Files:**
- Create: `im_clients/wechat_ocr.py`（只写常量 + 纯解析函数，不含截图/OCR 代码）
- Create: `tests/test_wechat_ocr.py`

---

- [ ] **Step 1: 写失败测试**

```python
# tests/test_wechat_ocr.py
import unittest


def _obs(text, x_center, y_top, width=0.3, height=0.03):
    """构造 _parse_observations 所需的 obs dict（等价于 _obs_to_dict 的输出）。"""
    return {
        "text": text,
        "x": x_center - width / 2,
        "y_top": y_top,
        "width": width,
        "height": height,
        "x_center": x_center,
    }


class ParseObservationsTests(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        from im_clients.wechat_ocr import _parse_observations
        self.assertEqual(_parse_observations([]), [])

    def test_single_chat_left_right(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("你好", 0.25, 0.1),    # 左侧 → 对方
            _obs("你好呀", 0.75, 0.2),  # 右侧 → 我
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "你好")
        self.assertEqual(result[1]["sender"], "我")
        self.assertEqual(result[1]["content"], "你好呀")

    def test_time_separator_becomes_time_field_not_message(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("上午 10:30", 0.5, 0.05),  # 居中时间戳
            _obs("你好", 0.25, 0.15),
        ]
        result = _parse_observations(obs)
        # 时间戳不作为消息，只有 1 条消息
        self.assertEqual(len(result), 1)
        # 时间戳挂到下一条消息的 time 字段
        self.assertEqual(result[0]["time"], "上午 10:30")
        # 消息内容不包含时间戳文字
        self.assertNotIn("10:30", result[0]["content"])
        self.assertEqual(result[0]["sender"], "对方")

    def test_group_chat_sender_name_linked_to_next_message(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("张三", 0.2, 0.10),    # 昵称（短文本，靠左）
            _obs("明天几点", 0.3, 0.13),  # 消息，左侧，y 接近
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sender"], "张三")
        self.assertEqual(result[0]["content"], "明天几点")

    def test_short_left_text_is_message_when_next_is_right_side(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("好的", 0.25, 0.10),   # 短左侧文本，但下一条是右侧 → 应作为消息
            _obs("收到", 0.75, 0.20),
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "好的")

    def test_multiline_same_side_merged(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("第一行", 0.25, 0.10),
            _obs("第二行", 0.25, 0.12),  # y 差 0.02 < 0.04，同侧 → 合并
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "第一行\n第二行")

    def test_multiline_different_side_not_merged(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("对方消息", 0.25, 0.10),
            _obs("我的回复", 0.75, 0.12),  # 虽然 y 很近但侧不同 → 不合并
        ]
        result = _parse_observations(obs)
        self.assertEqual(len(result), 2)

    def test_time_field_carried_to_subsequent_messages(self):
        from im_clients.wechat_ocr import _parse_observations
        obs = [
            _obs("下午 3:00", 0.5, 0.05),
            _obs("消息A", 0.25, 0.10),
            _obs("消息B", 0.75, 0.20),
        ]
        result = _parse_observations(obs)
        self.assertEqual(result[0]["time"], "下午 3:00")
        self.assertEqual(result[1]["time"], "下午 3:00")


class ObsToDictTests(unittest.TestCase):

    def test_converts_vision_observation_to_dict(self):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import _obs_to_dict

        obs = MagicMock()
        candidate = MagicMock()
        candidate.string.return_value = "你好"
        obs.topCandidates_.return_value = [candidate]

        box = MagicMock()
        box.origin.x = 0.1
        box.origin.y = 0.3   # Vision 左下原点
        box.size.width = 0.2
        box.size.height = 0.05
        obs.boundingBox.return_value = box

        result = _obs_to_dict(obs)

        self.assertEqual(result["text"], "你好")
        self.assertAlmostEqual(result["x_center"], 0.2)         # 0.1 + 0.2/2
        self.assertAlmostEqual(result["y_top"], 0.65)           # 1 - (0.3 + 0.05)
        self.assertAlmostEqual(result["width"], 0.2)
        self.assertAlmostEqual(result["height"], 0.05)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认全部失败**

```bash
.venv/bin/python -m pytest tests/test_wechat_ocr.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'im_clients.wechat_ocr'`

---

- [ ] **Step 3: 创建 `im_clients/wechat_ocr.py`（只含解析逻辑，不含截图/OCR）**

```python
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
    """判断 obs 是否为群聊昵称行（短文本靠左，下方紧跟左侧消息）。"""
    if next_obs is None:
        return False
    return (
        obs["x_center"] < _NAME_MAX_X
        and len(obs["text"].strip()) <= _NAME_MAX_LEN
        and next_obs["x_center"] < _RIGHT_THRESHOLD
        and 0 < next_obs["y_top"] - obs["y_top"] < _NAME_NEXT_Y
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
                y_top = n["y_top"]
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
```

- [ ] **Step 4: 运行测试，确认全部通过**

```bash
.venv/bin/python -m pytest tests/test_wechat_ocr.py -v
```

Expected: 全部 PASS（10 个测试）

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile im_clients/wechat_ocr.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add im_clients/wechat_ocr.py tests/test_wechat_ocr.py
git commit -m "feat: add wechat_ocr - Vision OCR parsing core (TDD)

- _parse_observations: 按 x 坐标判断发送方（我/对方/群聊昵称）
- _is_sender_name: 群聊昵称前瞻判断
- _obs_to_dict: Vision observation → dict（坐标翻转）
- 时间戳识别（居中短文本，正则匹配）
- 多行消息合并（y 差 < 0.04，同侧）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2：补充截图/OCR 测试，验证 `_capture_chat_area` + `_run_vision_ocr` + `read_chat_messages`

**Files:**
- Modify: `tests/test_wechat_ocr.py`（新增 3 个 mock 测试类）

> `_capture_chat_area` 和 `_run_vision_ocr` 的实现已在 Task 1 写入 `wechat_ocr.py`，此 Task 只补充测试。

---

- [ ] **Step 1: 在 `tests/test_wechat_ocr.py` 末尾追加以下测试类**

```python
# 追加到 tests/test_wechat_ocr.py 末尾


class CaptureAndOcrIntegrationTests(unittest.TestCase):
    """验证 read_chat_messages 的整体流程（mock 截图和 OCR）。"""

    @patch("im_clients.wechat_ocr._capture_chat_area", return_value=None)
    def test_returns_empty_when_capture_fails(self, _capture):
        from im_clients.wechat_ocr import read_chat_messages
        result = read_chat_messages((0, 0, 800, 600))
        self.assertEqual(result, [])

    @patch("im_clients.wechat_ocr._capture_chat_area")
    @patch("im_clients.wechat_ocr._run_vision_ocr")
    @patch("im_clients.wechat_ocr._obs_to_dict")
    def test_returns_parsed_messages_from_ocr(self, mock_to_dict, mock_ocr, mock_capture):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import read_chat_messages

        mock_capture.return_value = MagicMock()  # 假装截图成功

        # mock OCR 返回 1 个 observation（MagicMock 的 topCandidates_ 是 truthy）
        fake_obs = MagicMock()
        mock_ocr.return_value = [fake_obs]

        # mock _obs_to_dict 返回一个左侧消息
        mock_to_dict.return_value = _obs("你好世界", 0.25, 0.1)

        result = read_chat_messages((0, 0, 800, 600))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sender"], "对方")
        self.assertEqual(result[0]["content"], "你好世界")

    @patch("im_clients.wechat_ocr._capture_chat_area")
    @patch("im_clients.wechat_ocr._run_vision_ocr")
    @patch("im_clients.wechat_ocr._obs_to_dict")
    def test_respects_max_messages_limit(self, mock_to_dict, mock_ocr, mock_capture):
        from unittest.mock import MagicMock
        from im_clients.wechat_ocr import read_chat_messages

        mock_capture.return_value = MagicMock()

        # 构造 5 条消息的 observations
        fake_obs_list = [MagicMock() for _ in range(5)]
        mock_ocr.return_value = fake_obs_list
        mock_to_dict.side_effect = [
            _obs(f"消息{i}", 0.25, i * 0.1) for i in range(5)
        ]

        result = read_chat_messages((0, 0, 800, 600), max_messages=3)

        self.assertEqual(len(result), 3)  # 只返回最后 3 条
```

- [ ] **Step 2: 运行全部 wechat_ocr 测试**

```bash
.venv/bin/python -m pytest tests/test_wechat_ocr.py -v
```

Expected: 全部 PASS（12 个测试）

- [ ] **Step 3: Commit**

```bash
git add tests/test_wechat_ocr.py
git commit -m "test: add mock tests for read_chat_messages, _run_vision_ocr integration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3：重构 `wechat.py` + 接入 OCR + 更新测试

**Files:**
- Modify: `im_clients/wechat.py`
- Modify: `tests/test_im_clients.py`

---

- [ ] **Step 1: 在 `tests/test_im_clients.py` 中先写 2 个新测试，1 个改现有断言**

找到并修改 `IMClientDiscoveryTests.test_discovers_supported_clients_from_installed_apps`，将第 26 行：

```python
# 原：微信 Qt 版 AX 不暴露消息历史，can_read_chat=False
self.assertFalse(by_id["wechat"].capabilities.can_read_chat)
```

改为：

```python
# 微信 OCR 实现后 can_read_chat=True
self.assertTrue(by_id["wechat"].capabilities.can_read_chat)
```

找到 `WechatAdapterSendTests` 类，将 `test_read_chat_always_returns_empty` 整体替换为以下两个测试：

```python
    @patch("im_clients.wechat_ocr.read_chat_messages", return_value=[])
    def test_read_chat_returns_empty_when_ocr_returns_empty(self, mock_ocr):
        from im_clients.wechat import WechatAdapter
        adapter = WechatAdapter()
        adapter._get_window_bounds = lambda: None  # 无窗口
        result = adapter.read_chat_messages()
        self.assertEqual(result, [])

    @patch("im_clients.wechat_ocr.read_chat_messages")
    def test_read_chat_delegates_to_ocr_with_window_bounds(self, mock_ocr):
        from im_clients.wechat import WechatAdapter
        mock_ocr.return_value = [{"sender": "对方", "content": "你好", "time": None}]
        adapter = WechatAdapter()
        adapter._get_window_bounds = lambda: (100, 200, 800, 600)  # mock 窗口位置
        result = adapter.read_chat_messages(max_messages=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "你好")
        mock_ocr.assert_called_once_with((100, 200, 800, 600), max_messages=5)
```

- [ ] **Step 2: 运行测试，确认新测试失败、旧测试通过**

```bash
.venv/bin/python -m pytest tests/test_im_clients.py -v 2>&1 | tail -20
```

Expected: `test_read_chat_delegates_to_ocr_with_window_bounds` FAIL，其他 PASS

---

- [ ] **Step 3: 修改 `im_clients/wechat.py`**

**3a. 在 class 顶部，将 `can_read_chat=False` 改为 `True`：**

```python
# 原：
can_read_chat=False,  # Qt 渲染，AX 无法读取消息历史
# 改为：
can_read_chat=True,   # OCR 实现：截图 + Vision 识别
```

**3b. 在 `_click_input_area` 之前新增 `_get_window_bounds` 方法（抽取 _click_input_area 里的坐标逻辑）：**

```python
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
            win = windows[0]
            _, pos_ref = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
            _, size_ref = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
            _, pt = AXValueGetValue(pos_ref, kAXValueCGPointType, None)
            _, sz = AXValueGetValue(size_ref, kAXValueCGSizeType, None)
            return (pt.x, pt.y, sz.width, sz.height)
        except Exception:
            return None
```

**3c. 将 `_click_input_area` 重构为使用 `_get_window_bounds`（删除重复的 AX 代码）：**

```python
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
            click_y = y + h - 50  # 输入框在窗口底部中央，距底约 50px
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
```

**3d. 将 `read_chat_messages` 方法整体替换为：**

```python
    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        """
        截取微信聊天区域截图，通过 Vision OCR 识别消息内容。

        返回格式: [{"sender": str, "content": str, "time": str | None}]
        微信未运行或无窗口时返回 []。
        """
        from . import wechat_ocr
        bounds = self._get_window_bounds()
        if bounds is None:
            return []
        return wechat_ocr.read_chat_messages(bounds, max_messages=max_messages)
```

- [ ] **Step 4: 运行全部测试，确认全部通过**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 全部 PASS（包括新增的 2 个 read_chat 测试）

- [ ] **Step 5: 语法检查**

```bash
.venv/bin/python -m py_compile im_clients/wechat.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add im_clients/wechat.py tests/test_im_clients.py
git commit -m "feat: WechatAdapter.read_chat_messages - 接入 Vision OCR

- 抽取 _get_window_bounds()，_click_input_area 复用
- read_chat_messages() 委托 wechat_ocr.read_chat_messages()
- can_read_chat=True
- 更新测试：移除 always_returns_empty，新增 OCR 委托测试

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4：最终验收

**Files:**
- 无新增文件

---

- [ ] **Step 1: 运行全部测试套件**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: 全部 PASS，无 FAIL / ERROR

- [ ] **Step 2: 确认 sender.py / gui_panel.py 未改动**

```bash
git diff master -- sender.py gui_panel.py
```

Expected: 无输出

- [ ] **Step 3: 查看 diff 摘要**

```bash
git diff master --stat
```

Expected 新增/修改文件：
```
 im_clients/wechat.py       | (修改：_get_window_bounds，read_chat_messages，can_read_chat)
 im_clients/wechat_ocr.py   | (新增)
 tests/test_wechat_ocr.py   | (新增)
 tests/test_im_clients.py   | (修改：can_read_chat 断言，read_chat 测试)
 CLAUDE.md                  | (修改：文档更新)
 docs/superpowers/specs/...  | (新增：设计文档)
 docs/superpowers/plans/...  | (新增：本文件)
```

- [ ] **Step 4: 真机测试（需要微信运行并选中聊天）**

```bash
.venv/bin/python -c "
from im_clients.wechat import WechatAdapter
adapter = WechatAdapter()
print('running:', adapter.is_running())
msgs = adapter.read_chat_messages(max_messages=5)
for m in msgs:
    print(m)
"
```

Expected: 打印最近 5 条消息，格式 `{'sender': '对方', 'content': '...', 'time': '...'}`

如果消息为空或识别效果差，调整 `wechat_ocr.py` 中的常量：
- `_TOP_SKIP` / `_BOTTOM_SKIP`：真机截图后确认实际标题栏/输入框高度
- `_LINE_MERGE_Y`：如多行消息被拆分，适当增大（0.05~0.06）
- `_NAME_NEXT_Y`：如群聊昵称未被识别，适当增大（0.08）

- [ ] **Step 5: 最终 Commit（如有常量微调）**

```bash
git add -A
git commit -m "fix: wechat_ocr - 真机验证后微调 OCR 解析常量（如有调整）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## OCR 效果调试参考

| 现象 | 原因 | 调整 |
|------|------|------|
| 截图全黑 | 屏幕录制权限未授权 | 系统偏好 → 安全性 → 屏幕录制，勾选 Terminal/Python |
| 消息区域截到输入框 | `_BOTTOM_SKIP` 太小 | 加大到 120~150 |
| 标题栏被识别为消息 | `_TOP_SKIP` 太小 | 加大到 80~100 |
| 多行消息被拆开 | `_LINE_MERGE_Y` 太小 | 调大到 0.05~0.06 |
| 群聊昵称变成消息 | `_NAME_NEXT_Y` 太小 | 调大到 0.08~0.10 |
| 时间标签变成消息 | `_TIME_RE` 未匹配到格式 | 打印识别到的文本，补充正则 |
