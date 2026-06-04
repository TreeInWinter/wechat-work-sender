from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable, Iterable


class UnsupportedClientAction(Exception):
    """Raised when a client adapter does not support the requested action yet."""


@dataclass(frozen=True)
class ApplicationInfo:
    name: str
    bundle_id: str | None = None
    path: str | None = None
    running: bool = False
    pid: int | None = None


@dataclass(frozen=True)
class TakeoverCapabilities:
    can_activate: bool = True
    can_window_bounds: bool = True
    can_send: bool = False
    can_read_chat: bool = False
    verified: bool = False


@dataclass(frozen=True)
class DiscoveredClient:
    client_id: str
    display_name: str
    installed: bool
    running: bool
    adapter: "IMClientAdapter"
    matched_app: ApplicationInfo | None

    @property
    def capabilities(self) -> TakeoverCapabilities:
        return self.adapter.capabilities

    @property
    def status_text(self) -> str:
        if not self.installed:
            return "未安装"
        if not self.running:
            return "未运行"
        if not self.capabilities.verified:
            return "待验证"
        return "已连接"

    @property
    def menu_label(self) -> str:
        return f"{self.display_name} · {self.status_text}"


RuntimeAppProvider = Callable[[], object | None]
WindowBoundsProvider = Callable[[], tuple[int, int, int, int] | None]


class IMClientAdapter:
    client_id = ""
    display_name = ""
    app_names: tuple[str, ...] = ()
    bundle_ids: tuple[str, ...] = ()
    capabilities = TakeoverCapabilities()

    def __init__(self):
        self._runtime_app_provider: RuntimeAppProvider | None = None
        self._window_bounds_provider: WindowBoundsProvider | None = None

    def matches(self, app: ApplicationInfo) -> bool:
        return app.name in self.app_names or (
            app.bundle_id is not None and app.bundle_id in self.bundle_ids
        )

    def discover(self, apps: Iterable[ApplicationInfo]) -> DiscoveredClient:
        matched = None
        for app in apps:
            if self.matches(app):
                if matched is None or app.running:
                    matched = app
                if app.running:
                    break
        installed = matched is not None
        running = bool(matched and matched.running)
        return DiscoveredClient(
            client_id=self.client_id,
            display_name=self.display_name,
            installed=installed,
            running=running,
            adapter=self,
            matched_app=matched,
        )

    def set_runtime_app_provider(self, provider: RuntimeAppProvider):
        self._runtime_app_provider = provider

    def set_window_bounds_provider(self, provider: WindowBoundsProvider):
        self._window_bounds_provider = provider

    def is_running(self) -> bool:
        return self._get_runtime_app() is not None

    def activate(self) -> bool:
        app = self._get_runtime_app()
        if app is None:
            return False
        try:
            from AppKit import NSApplicationActivateIgnoringOtherApps

            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            time.sleep(0.1)
            return True
        except Exception:
            return False

    def window_bounds(self) -> tuple[int, int, int, int] | None:
        if self._window_bounds_provider is not None:
            return self._window_bounds_provider()
        return self._get_ax_window_bounds()

    def read_chat_messages(self, max_messages: int = 20) -> list[dict]:
        raise UnsupportedClientAction(f"{self.display_name} 的聊天读取能力尚未验证")

    def send_blocks(self, blocks: list) -> bool:
        raise UnsupportedClientAction(f"{self.display_name} 的发送能力尚未验证")

    def send_text(self, text: str) -> bool:
        return self.send_blocks([{"type": "text", "content": text}])

    def _get_runtime_app(self):
        if self._runtime_app_provider is not None:
            return self._runtime_app_provider()
        try:
            from AppKit import NSWorkspace

            apps = NSWorkspace.sharedWorkspace().runningApplications()
            for app in apps:
                name = str(app.localizedName() or "")
                bundle_id = str(app.bundleIdentifier() or "")
                if name in self.app_names or bundle_id in self.bundle_ids:
                    return app
        except Exception:
            return None
        return None

    def _get_ax_window_bounds(self) -> tuple[int, int, int, int] | None:
        app = self._get_runtime_app()
        if app is None:
            return None
        try:
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
                AXValueGetValue,
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueCGPointType,
                kAXValueCGSizeType,
                kAXWindowsAttribute,
            )

            ax = AXUIElementCreateApplication(app.processIdentifier())
            _, windows = AXUIElementCopyAttributeValue(ax, kAXWindowsAttribute, None)
            if not windows:
                return None
            win = windows[0]
            _, pos_ref = AXUIElementCopyAttributeValue(win, kAXPositionAttribute, None)
            _, size_ref = AXUIElementCopyAttributeValue(win, kAXSizeAttribute, None)
            _, pt = AXValueGetValue(pos_ref, kAXValueCGPointType, None)
            _, sz = AXValueGetValue(size_ref, kAXValueCGSizeType, None)
            return (int(pt.x), int(pt.y), int(sz.width), int(sz.height))
        except Exception:
            return None


def scan_installed_applications(paths: tuple[str, ...] | None = None) -> list[ApplicationInfo]:
    roots = paths or ("/Applications", os.path.expanduser("~/Applications"))
    apps = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for entry in entries:
            if entry.endswith(".app"):
                apps.append(
                    ApplicationInfo(
                        name=entry[:-4],
                        path=os.path.join(root, entry),
                    )
                )
    return apps


def scan_running_applications() -> list[ApplicationInfo]:
    try:
        from AppKit import NSWorkspace

        apps = []
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            apps.append(
                ApplicationInfo(
                    name=str(app.localizedName() or ""),
                    bundle_id=str(app.bundleIdentifier() or "") or None,
                    running=True,
                    pid=app.processIdentifier(),
                )
            )
        return apps
    except Exception:
        return []

