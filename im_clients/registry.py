from __future__ import annotations

from .base import (
    ApplicationInfo,
    DiscoveredClient,
    scan_installed_applications,
    scan_running_applications,
)
from .daxiang import DaxiangAdapter
from .wechat import WechatAdapter
from .wechat_work import WechatWorkAdapter


def create_adapters():
    return [
        WechatWorkAdapter(),
        WechatAdapter(),
        DaxiangAdapter(),
    ]


def scan_applications() -> list[ApplicationInfo]:
    by_key: dict[tuple[str, str | None], ApplicationInfo] = {}
    for app in scan_installed_applications() + scan_running_applications():
        key = (app.name, app.bundle_id)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = app
        else:
            by_key[key] = ApplicationInfo(
                name=app.name or previous.name,
                bundle_id=app.bundle_id or previous.bundle_id,
                path=app.path or previous.path,
                running=app.running or previous.running,
                pid=app.pid or previous.pid,
            )
    return list(by_key.values())


def discover_clients(apps: list[ApplicationInfo] | None = None) -> list[DiscoveredClient]:
    source_apps = scan_applications() if apps is None else apps
    return [adapter.discover(source_apps) for adapter in create_adapters()]


def choose_default_client(clients: list[DiscoveredClient]) -> DiscoveredClient:
    if not clients:
        raise ValueError("没有可用的 IM 客户端适配器")
    preferred = next((client for client in clients if client.client_id == "wechat_work"), None)
    if preferred is not None and preferred.installed:
        return preferred
    installed = next((client for client in clients if client.installed), None)
    if installed is not None:
        return installed
    if preferred is not None:
        return preferred
    return clients[0]


def get_client_by_id(client_id: str, clients: list[DiscoveredClient] | None = None) -> DiscoveredClient | None:
    for client in clients or discover_clients():
        if client.client_id == client_id:
            return client
    return None
