# im_clients/probes.py
"""
AX 结构探针：把散落在各 adapter / sender.py 里的「AX depth 魔法数」收敛到一处，
作为单一事实来源，并提供启动自检——当 IM 客户端更新导致 AX 树结构变化、
我们硬编码的 depth 失效时，提前发现并告警，而不是等用户报「发不出/读不到」。

## 为什么需要

发送/读取依赖在 AX 树固定 depth 上找到输入框 / 消息节点：
  - 企业微信：输入框 AXTextArea（从 window 算 depth≤10），消息 AXTable（depth=6）
  - 大象：输入框 AXTextArea（从 app 算 depth≤26，有占位符），消息 AXStaticText（从 window 算 depth=22）
  - 微信：Qt 不透 AX，坐标点击发送 + OCR 读取，不走 AX

客户端版本更新后 AX 树可能整体加深/变浅，硬编码 depth 命中不到 → 功能静默失效。
自检在这种情况发生时给出明确信号。

## 用法

    from im_clients import probes
    results = probes.run_self_check(discovered_clients)
    for r in results:
        if r.status == probes.STATUS_DEGRADED:
            warn(r.detail)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# AX 符号在模块级导入，便于自检逻辑被单测 patch（非 macOS 环境下占位为 None）
try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        kAXChildrenAttribute,
        kAXRoleAttribute,
        kAXWindowsAttribute,
    )
except Exception:  # pragma: no cover - 仅非 macOS 占位
    AXUIElementCopyAttributeValue = None  # type: ignore[assignment]
    kAXChildrenAttribute = kAXRoleAttribute = kAXWindowsAttribute = None  # type: ignore[assignment]


# ── 探针数据结构 ────────────────────────────────────────────────

@dataclass(frozen=True)
class ElementProbe:
    """
    描述在 AX 树中查找某个元素的期望。

    role:             期望的 AXRole（如 "AXTextArea" / "AXTable" / "AXStaticText"）
    root:             BFS 起点，"app"=应用根元素，"window"=主窗口
    max_depth:        BFS 深度上限（从 root 算）
    exact_depth:      若设定，自检要求该 role 恰好出现在此 depth（消息节点用）；
                      None 表示只要在 max_depth 内找到最浅的即可（输入框用）
    allow_with_value: True 时接受有值的元素（如大象输入框的占位符）
    """
    role: str
    root: str = "window"          # "app" | "window"
    max_depth: int = 10
    exact_depth: int | None = None
    allow_with_value: bool = False


@dataclass(frozen=True)
class AXProbe:
    """单个 IM 客户端的 AX 结构探针。"""
    client_id: str
    uses_ax: bool = True
    input: ElementProbe | None = None       # 输入框查找规则
    message: ElementProbe | None = None     # 消息容器查找规则
    click_bottom_offset: int | None = None  # 非 AX（Qt）客户端的底部点击偏移（px）


# ── 各客户端探针配置（魔法数单一事实来源）──────────────────────

PROBES: dict[str, AXProbe] = {
    # 企业微信：sender.py 的 _find_text_area / _find_msg_table 从此读取常量
    "wechat_work": AXProbe(
        client_id="wechat_work",
        uses_ax=True,
        input=ElementProbe(role="AXTextArea", root="window", max_depth=10),
        message=ElementProbe(role="AXTable", root="window", max_depth=8, exact_depth=6),
    ),
    # 大象：daxiang.py 从此读取常量（输入框从 app 根算，消息从 window 算）
    "daxiang": AXProbe(
        client_id="daxiang",
        uses_ax=True,
        input=ElementProbe(role="AXTextArea", root="app", max_depth=26, allow_with_value=True),
        message=ElementProbe(role="AXStaticText", root="window", max_depth=22, exact_depth=22),
    ),
    # 微信：Qt 渲染，不走 AX（坐标点击 + OCR）
    "wechat": AXProbe(
        client_id="wechat",
        uses_ax=False,
        click_bottom_offset=50,
    ),
}


def get_probe(client_id: str) -> AXProbe | None:
    return PROBES.get(client_id)


# ── 自检结果 ────────────────────────────────────────────────────

STATUS_OK = "ok"                  # 结构符合预期
STATUS_DEGRADED = "degraded"      # 结构异常，客户端可能已更新 → 需重新探测
STATUS_NOT_RUNNING = "not_running"  # 客户端未运行，跳过
STATUS_NO_WINDOW = "no_window"    # 运行但找不到窗口（未打开/最小化？）
STATUS_NO_PERMISSION = "no_permission"  # 辅助功能权限未授予
STATUS_SKIPPED = "skipped"        # 无探针配置或无需检查

# kAXErrorAPIDisabled：辅助功能 API 未授权（进程未在「辅助功能」白名单）
_AX_ERROR_API_DISABLED = -25211


@dataclass(frozen=True)
class ProbeResult:
    client_id: str
    display_name: str
    status: str
    detail: str

    @property
    def is_problem(self) -> bool:
        """是否属于需要提醒用户的问题（区别于「未运行」这类正常状态）。"""
        return self.status in (STATUS_DEGRADED, STATUS_NO_WINDOW, STATUS_NO_PERMISSION)


# ── 纯逻辑：结果分类（便于单测，不触碰 AX）──────────────────────

def classify_input(probe_input: ElementProbe | None, found_depth: int | None) -> tuple[str, str]:
    """
    根据输入框查找结果分类。found_depth=None 表示未找到。
    返回 (status, detail_片段)。
    """
    if probe_input is None:
        return STATUS_OK, "无输入框探针"
    if found_depth is None:
        return (
            STATUS_DEGRADED,
            f"未找到输入框（{probe_input.role}，{probe_input.root} 根 depth≤{probe_input.max_depth}），"
            f"客户端 AX 结构可能已变化",
        )
    return STATUS_OK, f"输入框 {probe_input.role} @depth={found_depth}（上限 {probe_input.max_depth}）"


def classify_message(probe_msg: ElementProbe | None, msg_found: bool) -> tuple[str, str]:
    """根据消息容器查找结果分类。返回 (status, detail_片段)。"""
    if probe_msg is None:
        return STATUS_OK, ""
    if not msg_found:
        loc = (
            f"depth={probe_msg.exact_depth}"
            if probe_msg.exact_depth is not None
            else f"depth≤{probe_msg.max_depth}"
        )
        return (
            STATUS_DEGRADED,
            f"未在预期位置找到消息节点（{probe_msg.role}，{loc}），读取可能已失效",
        )
    return STATUS_OK, f"消息节点 {probe_msg.role} 命中"


def combine(input_cls: tuple[str, str], msg_cls: tuple[str, str]) -> tuple[str, str]:
    """合并输入框 + 消息的分类结果：任一 degraded 则整体 degraded。"""
    in_status, in_detail = input_cls
    msg_status, msg_detail = msg_cls
    details = [d for d in (in_detail, msg_detail) if d]
    status = STATUS_DEGRADED if STATUS_DEGRADED in (in_status, msg_status) else STATUS_OK
    return status, "；".join(details)


# ── AX 树 BFS（自检用，只读不改）────────────────────────────────

def _bfs_shallowest_depth(root, role: str, max_depth: int) -> int | None:
    """BFS 找最浅的指定 role 的 depth（从 root 算 depth=0），未找到返回 None。"""
    queue = deque([(root, 0)])
    while queue:
        el, d = queue.popleft()
        if d > max_depth:
            continue
        try:
            _, r = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            if r == role:
                return d
            _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
            if children:
                for c in children:
                    queue.append((c, d + 1))
        except Exception:
            pass
    return None


def _bfs_role_exists_at_depth(root, role: str, depth: int, max_depth: int) -> bool:
    """BFS 检查指定 role 是否出现在精确 depth（从 root 算），用于消息节点。"""
    queue = deque([(root, 0)])
    while queue:
        el, d = queue.popleft()
        if d > max_depth:
            continue
        try:
            _, r = AXUIElementCopyAttributeValue(el, kAXRoleAttribute, None)
            if r == role and d == depth:
                return True
            if d < max_depth:
                _, children = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute, None)
                if children:
                    for c in children:
                        queue.append((c, d + 1))
        except Exception:
            pass
    return False


# ── 单客户端自检 ────────────────────────────────────────────────

def run_probe(adapter, probe: AXProbe | None = None, *, activate: bool = True) -> ProbeResult:
    """
    对单个客户端运行结构自检（只读，不发送任何消息）。

    AX 客户端：激活 → 取 AX 树 → BFS 验证输入框/消息节点是否在预期位置。
    非 AX 客户端（微信）：检查 CGWindowList 能否发现窗口。

    activate=False 时跳过激活（被动检查，AX 路径可能因窗口未渲染而 no_window）。
    """
    from .ax_helpers import activate_app, get_ax_element, get_largest_window, is_app_running

    probe = probe or get_probe(adapter.client_id)
    display = getattr(adapter, "display_name", adapter.client_id)

    if probe is None:
        return ProbeResult(adapter.client_id, display, STATUS_SKIPPED, "无探针配置")

    # 找到正在运行的 app 名
    running_name = None
    for name in getattr(adapter, "app_names", ()):
        if is_app_running(name):
            running_name = name
            break
    if running_name is None:
        return ProbeResult(adapter.client_id, display, STATUS_NOT_RUNNING, "未运行")

    # 非 AX 客户端（微信）：只验证窗口可达
    if not probe.uses_ax:
        try:
            from .wechat_ocr import find_main_window
            wid, _ = find_main_window()
        except Exception:
            wid = None
        if wid is None:
            return ProbeResult(
                adapter.client_id, display, STATUS_NO_WINDOW,
                "未发现窗口（请确认窗口已打开且未最小化）",
            )
        return ProbeResult(adapter.client_id, display, STATUS_OK, "窗口可达（OCR 路径）")

    # AX 客户端
    if activate:
        activate_app(running_name)
    ax = get_ax_element(running_name)
    if ax is None:
        return ProbeResult(
            adapter.client_id, display, STATUS_DEGRADED,
            "无法获取 AX 元素（请检查辅助功能权限）",
        )

    try:
        err, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
    except Exception:
        err, windows = None, None
    if err == _AX_ERROR_API_DISABLED:
        return ProbeResult(
            adapter.client_id, display, STATUS_NO_PERMISSION,
            "辅助功能权限未授予（系统设置 → 隐私与安全性 → 辅助功能）",
        )
    if not windows:
        return ProbeResult(
            adapter.client_id, display, STATUS_NO_WINDOW,
            "AX 未返回窗口（窗口未打开或需先激活）",
        )
    main_win = get_largest_window(windows) or windows[0]

    def _root_for(ep: ElementProbe):
        return ax if ep.root == "app" else main_win

    # 输入框查找
    input_depth = None
    if probe.input is not None:
        input_depth = _bfs_shallowest_depth(
            _root_for(probe.input), probe.input.role, probe.input.max_depth
        )
    input_cls = classify_input(probe.input, input_depth)

    # 消息节点查找
    msg_found = True
    if probe.message is not None:
        mp = probe.message
        root = _root_for(mp)
        if mp.exact_depth is not None:
            msg_found = _bfs_role_exists_at_depth(root, mp.role, mp.exact_depth, mp.max_depth)
        else:
            msg_found = _bfs_shallowest_depth(root, mp.role, mp.max_depth) is not None
    msg_cls = classify_message(probe.message, msg_found)

    status, detail = combine(input_cls, msg_cls)
    return ProbeResult(adapter.client_id, display, status, detail)


def run_self_check(discovered_clients, *, activate: bool = True) -> list[ProbeResult]:
    """
    对所有已发现的客户端运行自检，返回结果列表。

    discovered_clients: discover_clients() 的返回（含 .adapter）。
    activate: 是否允许激活客户端窗口（深度 AX 检查需要；被动检查传 False）。
    """
    results: list[ProbeResult] = []
    for client in discovered_clients:
        adapter = getattr(client, "adapter", None)
        if adapter is None:
            continue
        try:
            results.append(run_probe(adapter, activate=activate))
        except Exception as exc:
            results.append(ProbeResult(
                getattr(adapter, "client_id", "?"),
                getattr(adapter, "display_name", "?"),
                STATUS_DEGRADED,
                f"自检异常: {exc}",
            ))
    return results
