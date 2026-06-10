"""拖拽跟随：监听全局鼠标事件，在目标 IM 窗口被拖动时让面板高频同步移动。

100ms AX 轮询天然有半帧到一帧的拖影；要做到原生级丝滑，拖动期间不查 AX，
直接用「mouseDown 时记录的鼠标-窗口偏移 + 每个 dragged 事件的鼠标位置」预测
目标窗口位置（与系统拖动同速率，60-120Hz）。本模块只负责"感知"——预测位置
经 on_drag_move 回调交给 GUI 侧存储，实际移动由 Tk 的 8ms 高频泵用
geometry() 执行（必须经 _tkinter 进 Tcl，原因见 DragFollowController 文档）。
mouseUp 后由调用方做一次 AX 真值校正（macOS 屏幕边缘吸附会让真实窗口与
预测位置出现偏差）。

坐标约定：全部使用 AX 全局坐标（主屏左上角原点，y 向下）；
NSEvent.mouseLocation 的 AppKit 坐标（左下角原点）在读取时即翻转。

纯逻辑（DragSession / in_drag_band）无 AppKit 依赖，有单测；
AppKit/Quartz 导入全部延迟到 DragFollowController 运行时。
"""

# 窗口顶部多高的区域视为「可拖拽标题栏」。企业微信（Electron）自定义拖拽区
# 约为顶部 60px，放宽到 80px；误判的代价只是面板短暂跟移，mouseUp 校正会拉回。
DRAG_BAND = 80


def in_drag_band(mouse: tuple, bounds: tuple, band: int = DRAG_BAND) -> bool:
    """鼠标是否落在窗口顶部的拖拽带内（AX 坐标）。"""
    mx, my = mouse
    wx, wy, ww, wh = bounds
    return wx <= mx <= wx + ww and wy <= my <= wy + min(band, wh)


class DragSession:
    """一次拖拽会话：mouseDown 时记偏移，之后由鼠标位置直接推算窗口位置。"""

    def __init__(self, mouse: tuple, bounds: tuple):
        mx, my = mouse
        wx, wy, ww, wh = bounds
        self._dx = wx - mx
        self._dy = wy - my
        self._size = (ww, wh)

    def target_bounds_for(self, mouse: tuple) -> tuple:
        mx, my = mouse
        return (int(mx + self._dx), int(my + self._dy),
                self._size[0], self._size[1])


def primary_screen_height() -> float:
    from AppKit import NSScreen
    return NSScreen.screens()[0].frame().size.height


def owner_at_point(x: float, y: float) -> str | None:
    """返回包含该点的最前 layer-0 窗口的 ownerName（CGWindowList 前→后有序）。

    用于 mouseDown 时确认点击的确实是目标 IM 的窗口，排除「别的窗口恰好叠在
    目标窗口拖拽带上」的误跟随。只读 owner/bounds，不需要屏幕录制权限。
    面板自身在 NSFloatingWindowLevel（layer=3），会被 layer!=0 过滤跳过。
    """
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    infos = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
    for info in infos:
        if info.get("kCGWindowLayer", 0) != 0:
            continue
        b = info.get("kCGWindowBounds") or {}
        bx, by = b.get("X", 0), b.get("Y", 0)
        bw, bh = b.get("Width", 0), b.get("Height", 0)
        if bx <= x <= bx + bw and by <= y <= by + bh:
            return info.get("kCGWindowOwnerName")
    return None


class DragFollowController:
    """全局鼠标监听 + 拖拽会话状态机。

    回调约定：
    - get_target_bounds() -> (x, y, w, h) | None   目标窗口 AX 坐标
    - get_owner_names() -> tuple[str, ...]          目标 app 的 CGWindowList ownerName 候选
    - on_drag_move(bounds)                          拖动中，bounds 为预测的目标窗口位置
    - on_drag_end()                                 松手，调用方应做 AX 真值校正

    ⚠️ 两条铁律（各踩过一次坑，违反即 PyEval_RestoreThread fatal）：

    1. handler 回调（on_drag_move/on_drag_end）里只能做纯 Python 计算/赋值，
       不能调 Tk（root.after/geometry 等）——handler 发生在 Tcl_DoOneEvent
       泵 Cocoa 事件的过程中，Tcl 已释放 GIL，PyObjC 经 PyGILState 临时拿回，
       此时重入 _tkinter 会破坏其 tcl_tstate 配对。
    2. 面板（Tk 窗口）只能经 root.geometry() 移动，**任何上下文**都不能用
       PyObjC NSWindow.setFrameOrigin_ 动它：PyObjC 释放 GIL 时不设 _tkinter
       的 tcl_tstate，窗口移动同步触发 TkMacOSX windowDidMove → CTk 的
       <Configure> 回调 → ENTER_PYTHON 拿到 NULL 线程状态 → fatal。
       geometry() 经 _tkinter 进 Tcl，tcl_tstate 配对正确，安全。

    AX 读取 / CGWindowList / NSEvent.mouseLocation 等只读、不碰 Tk 的
    PyObjC 调用在 handler 里已验证安全。
    """

    def __init__(self, get_target_bounds, get_owner_names,
                 on_drag_move, on_drag_end, band: int = DRAG_BAND):
        self._get_target_bounds = get_target_bounds
        self._get_owner_names = get_owner_names
        self._on_drag_move = on_drag_move
        self._on_drag_end = on_drag_end
        self._band = band
        self._session = None
        self._monitor = None
        self._primary_h = 0.0  # 会话期间缓存，mouseDown 时刷新

    @property
    def dragging(self) -> bool:
        return self._session is not None

    def start(self) -> bool:
        """安装全局监听。失败（极少见）返回 False，调用方回退纯轮询。"""
        try:
            from AppKit import (
                NSEvent,
                NSEventMaskLeftMouseDown,
                NSEventMaskLeftMouseDragged,
                NSEventMaskLeftMouseUp,
            )
            mask = (NSEventMaskLeftMouseDown
                    | NSEventMaskLeftMouseDragged
                    | NSEventMaskLeftMouseUp)
            self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, self._handle)
            return self._monitor is not None
        except Exception:
            self._monitor = None
            return False

    def stop(self):
        if self._monitor is not None:
            try:
                from AppKit import NSEvent
                NSEvent.removeMonitor_(self._monitor)
            except Exception:
                pass
            self._monitor = None
        self._session = None

    # ── 内部 ──

    def _mouse_ax_point(self) -> tuple:
        from AppKit import NSEvent
        loc = NSEvent.mouseLocation()
        return (loc.x, self._primary_h - loc.y)

    def _handle(self, event):
        # handler 在 Cocoa 运行循环里回调，任何异常都不能外泄
        try:
            et = event.type()
            if et == 1:        # NSEventTypeLeftMouseDown
                self._maybe_begin()
            elif et == 6:      # NSEventTypeLeftMouseDragged
                if self._session is not None:
                    self._on_drag_move(
                        self._session.target_bounds_for(self._mouse_ax_point()))
            elif et == 2:      # NSEventTypeLeftMouseUp
                if self._session is not None:
                    self._session = None
                    self._on_drag_end()
        except Exception:
            self._session = None

    def _maybe_begin(self):
        self._primary_h = primary_screen_height()
        mouse = self._mouse_ax_point()
        bounds = self._get_target_bounds()
        if not bounds or not in_drag_band(mouse, bounds, self._band):
            return
        # 确认点中的是目标 app 的窗口（而非叠在上面的其他窗口）
        owner = owner_at_point(*mouse)
        if owner is not None and owner not in self._get_owner_names():
            return
        self._session = DragSession(mouse, bounds)
