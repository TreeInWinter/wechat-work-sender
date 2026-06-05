# 微信聊天内容 OCR 读取 — 设计文档

**日期**：2026-06-05  
**分支**：feature/multi-im-adapters  
**背景**：微信 macOS 版使用 Qt 渲染，AX API 树只有 6 个节点，无法读取消息历史。改用 macOS Vision 框架 OCR 截图识别。

---

## 目标

让 `WechatAdapter.read_chat_messages()` 返回结构化消息列表：

```python
[
    {"sender": "张三", "content": "明天几点开会？", "time": "上午 10:30"},
    {"sender": "我",   "content": "下午两点",       "time": None},
]
```

接口与企业微信/大象 adapter 一致，GUI 无需改动。

---

## 约束

- 不依赖外部 OCR 服务，使用系统自带 macOS Vision 框架（`import Vision`，已验证可用）
- 不修改 `sender.py` / `gui_panel.py`
- 新增文件：`im_clients/wechat_ocr.py`（单一职责，便于测试和替换）
- 单测用 mock 隔离 Vision 调用，无需真机

---

## 架构

```
WechatAdapter.read_chat_messages()
  └─► wechat_ocr.read_chat_messages(window_bounds)
        ├─ _capture_chat_area(window_bounds)   # 截图 → NSImage
        ├─ _run_vision_ocr(ns_image)            # Vision OCR → observations
        └─ _parse_observations(observations, img_width)  # 解析 → List[dict]
```

---

## 模块设计：`im_clients/wechat_ocr.py`

### 函数：`read_chat_messages(window_bounds, max_messages=20)`

**入参**：`window_bounds = (x, y, w, h)`，微信主窗口坐标（屏幕坐标系）  
**出参**：`List[{"sender": str, "content": str, "time": str | None}]`

```
window_bounds
  → crop: y += TOP_SKIP(50px), h -= TOP_SKIP + BOTTOM_SKIP(100px)
  → _capture_chat_area → NSImage（纯聊天区截图，无标题栏、无输入框）
  → _run_vision_ocr → List[VNObservation]
  → _parse_observations → List[dict]
  → 返回最后 max_messages 条
```

---

### 函数：`_capture_chat_area(bounds)`

使用 `CGWindowListCreateImage`（Quartz）截取屏幕指定矩形区域：

```python
from Quartz import CGWindowListCreateImage, CGRectMake, kCGWindowListOptionAll, kCGNullWindowID

rect = CGRectMake(x, y + TOP_SKIP, w, h - TOP_SKIP - BOTTOM_SKIP)
cg_image = CGWindowListCreateImage(rect, kCGWindowListOptionAll, kCGNullWindowID, 0)
```

转换为 `NSImage` 供 Vision 使用。

**裁剪参数**（常量，真机验证后可调）：
- `TOP_SKIP = 50`：跳过标题栏/导航栏
- `BOTTOM_SKIP = 100`：跳过聊天输入框

---

### 函数：`_run_vision_ocr(ns_image)`

使用 Vision `VNRecognizeTextRequest`：

```python
import Vision

handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(png_data, None)
request = Vision.VNRecognizeTextRequest.alloc().init()
request.setRecognitionLevel_(1)          # 1 = accurate
request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
request.setUsesLanguageCorrection_(True)
handler.performRequests_error_([request], None)
```

返回 `List[VNRecognizedTextObservation]`，每条包含：
- `.topCandidates_(1)[0].string()`：识别文字
- `.boundingBox()`：归一化坐标（原点在**左下角**，需翻转 y）

---

### 函数：`_parse_observations(observations, img_width)`

**核心逻辑**：

**Step 1：坐标归一化**

Vision boundingBox 原点在左下角，转换为左上角坐标系：
```
y_top = 1.0 - (obs.boundingBox().origin.y + obs.boundingBox().size.height)
x_center = obs.boundingBox().origin.x + obs.boundingBox().size.width / 2
```

**Step 2：按 y 排序**（从上到下 = 时间顺序）

**Step 3：识别时间戳**

正则匹配 `(上午|下午|昨天|星期\w)\s*\d{1,2}:\d{2}` 或 `\d{1,2}:\d{2}`，且 `x_center` 在 `[0.3, 0.7]` 之间（居中）→ 标记为时间分隔符，记录 `current_time`。

**Step 4：群聊发送方识别**

条件：
- `x_center < 0.3`（靠左）
- 文本长度 < 30 字符（短昵称）
- 下方紧邻（y 差 < 0.06）另一条左侧消息

满足以上条件 → 标记为 `pending_sender`，下一条左侧消息采用该昵称。

**Step 5：气泡归属判断**

```
x_center > 0.5  →  sender = "我"
x_center < 0.5  →  sender = pending_sender or "对方"（单聊兜底）
```

**Step 6：合并同一消息的多行文本**

y 差 < `LINE_MERGE_THRESHOLD = 0.04` 且归属相同 → 合并为同一条消息，内容用 `\n` 拼接。

---

## 改动：`im_clients/wechat.py`

```python
# capabilities 中修改：
can_read_chat=True,  # 改为 True，OCR 实现

# read_chat_messages 方法：
def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
    from .wechat_ocr import read_chat_messages as ocr_read
    bounds = self._get_window_bounds()
    if bounds is None:
        return []
    return ocr_read(bounds, max_messages=max_messages)

# 新增辅助方法（抽取自 _click_input_area，两个方法共用）：
def _get_window_bounds(self) -> tuple | None:
    """
    返回微信主窗口 (x, y, w, h)，未运行或无窗口返回 None。
    复用 _click_input_area 中已有的 kAXPositionAttribute + kAXSizeAttribute 逻辑，
    抽取为共享私有方法，_click_input_area 改为调用此方法。
    """
    ...
```

---

## 测试设计

### `tests/test_wechat_ocr.py`

mock `_run_vision_ocr` 返回固定 observations，测试 `_parse_observations` 逻辑：

| 测试用例 | 验证点 |
|---------|--------|
| 单聊：左右各一条消息 | sender 正确区分"我"/"对方" |
| 时间戳居中 | 被识别为时间分隔符，不作为消息 |
| 群聊：昵称 + 消息 | 昵称正确关联到下一条消息 |
| 多行消息合并 | y 相近的 observations 合并为一条 |
| 空 observations | 返回 `[]` |

`_capture_chat_area` 和 `_run_vision_ocr` 用 mock 隔离，不需要真机。

---

## 已知局限

1. **OCR 误识别**：手写体、特殊字体、表情包文字可能识别失败，容忍偶发错误。
2. **发送方昵称精度**：单聊无法获取对方真实昵称，固定返回 `"对方"`；群聊依赖昵称在消息气泡上方出现，若微信版本改变布局需重新调整阈值。
3. **截图权限**：需要 macOS 屏幕录制权限（`com.apple.screencapture`），首次运行会弹系统授权对话框。
4. **遮挡问题**：若微信窗口被其他窗口遮挡，截图内容不完整。`activate()` 前调用可缓解。
5. **常量调优**：`TOP_SKIP`、`BOTTOM_SKIP`、`LINE_MERGE_THRESHOLD` 在不同分辨率/缩放比例下可能需微调。

---

## 不在本次范围内

- 大象 adapter 的 OCR 读取（单独需求）
- 消息类型识别（图片消息、语音消息）
- 实时消息监听（当前为手动触发读取）
