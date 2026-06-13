"""HTTP client and local defaults for SideKick payment verification."""
from __future__ import annotations

import json
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest


DEFAULT_PAYMENT_SERVER_URL = "http://127.0.0.1:8787"
DEFAULT_PAYMENT_PROVIDER = "mock"
DEFAULT_PAYMENT_AMOUNT_CENTS = 1000

PAYMENT_SERVER_URL_KEY = "payment_server_url"
PAYMENT_PROVIDER_KEY = "payment_provider"
PAYMENT_DEFAULT_AMOUNT_CENTS_KEY = "payment_default_amount_cents"
PAYMENT_INSTALL_ID_KEY = "payment_install_id"
PAYMENT_ENTITLEMENT_CACHE_KEY = "payment_entitlement_cache"


class PaymentClientError(RuntimeError):
    def __init__(self, message: str, code: str = "payment_client_error"):
        super().__init__(message)
        self.code = code
        self.message = message


def default_payment_config() -> dict:
    return {
        PAYMENT_SERVER_URL_KEY: DEFAULT_PAYMENT_SERVER_URL,
        PAYMENT_PROVIDER_KEY: DEFAULT_PAYMENT_PROVIDER,
        PAYMENT_DEFAULT_AMOUNT_CENTS_KEY: DEFAULT_PAYMENT_AMOUNT_CENTS,
        PAYMENT_INSTALL_ID_KEY: "",
        PAYMENT_ENTITLEMENT_CACHE_KEY: None,
    }


def ensure_payment_config(config: dict | None) -> tuple[dict, dict]:
    """Return config with payment defaults and updates that should be persisted."""
    base = dict(default_payment_config())
    if isinstance(config, dict):
        base.update(config)
    updates = {}
    if not str(base.get(PAYMENT_INSTALL_ID_KEY) or "").strip():
        base[PAYMENT_INSTALL_ID_KEY] = f"sidekick-{uuid.uuid4()}"
        updates[PAYMENT_INSTALL_ID_KEY] = base[PAYMENT_INSTALL_ID_KEY]
    return base, updates


class PaymentClient:
    def __init__(self, base_url: str = DEFAULT_PAYMENT_SERVER_URL, timeout: float = 5.0):
        self.base_url = (base_url or DEFAULT_PAYMENT_SERVER_URL).rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        return self._request("GET", "/healthz")

    def providers(self) -> dict:
        return self._request("GET", "/api/v1/providers")

    def get_entitlement(self, install_id: str) -> dict:
        return self._request("GET", f"/api/v1/entitlements/{install_id}")

    def create_order(self, install_id: str, provider: str, amount_cents: int) -> dict:
        return self._request(
            "POST",
            "/api/v1/orders",
            {
                "install_id": install_id,
                "provider": provider,
                "amount_cents": int(amount_cents),
            },
        )

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/api/v1/orders/{order_id}")

    def sync_order(self, order_id: str) -> dict:
        return self._request("POST", f"/api/v1/orders/{order_id}/sync")

    def mock_pay(self, order_id: str, paid_amount_cents: int) -> dict:
        return self._request(
            "POST",
            f"/api/v1/mock/orders/{order_id}/pay",
            {"paid_amount_cents": int(paid_amount_cents)},
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urlrequest.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            code = "http_error"
            message = body or str(exc)
            try:
                parsed = json.loads(body)
                code = parsed.get("error") or code
                message = parsed.get("message") or message
            except json.JSONDecodeError:
                pass
            raise PaymentClientError(message, code=code) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise PaymentClientError(str(exc), code="network_error") from exc

        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise PaymentClientError("payment server returned invalid JSON", code="invalid_json") from exc
