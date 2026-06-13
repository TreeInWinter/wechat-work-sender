from __future__ import annotations

import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import payment_client


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_default_payment_config_has_mock_server():
    cfg = payment_client.default_payment_config()

    assert cfg[payment_client.PAYMENT_SERVER_URL_KEY] == "http://127.0.0.1:8787"
    assert cfg[payment_client.PAYMENT_PROVIDER_KEY] == "mock"
    assert cfg[payment_client.PAYMENT_DEFAULT_AMOUNT_CENTS_KEY] == 1000


def test_ensure_payment_config_generates_stable_install_id_update():
    cfg, updates = payment_client.ensure_payment_config({})

    assert cfg[payment_client.PAYMENT_INSTALL_ID_KEY].startswith("sidekick-")
    assert updates[payment_client.PAYMENT_INSTALL_ID_KEY] == cfg[payment_client.PAYMENT_INSTALL_ID_KEY]


def test_payment_client_posts_create_order_json():
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse({"order_id": "order-1", "status": "pending"})

    client = payment_client.PaymentClient("http://pay.local", timeout=3)
    with patch("payment_client.urlrequest.urlopen", fake_urlopen):
        res = client.create_order("install-1", "mock", 1000)

    assert captured["url"] == "http://pay.local/api/v1/orders"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "install_id": "install-1",
        "provider": "mock",
        "amount_cents": 1000,
    }
    assert captured["timeout"] == 3
    assert res["order_id"] == "order-1"


def test_payment_client_posts_sync_order():
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        return _FakeResponse({"order_id": "order-1", "status": "paid"})

    client = payment_client.PaymentClient("http://pay.local")
    with patch("payment_client.urlrequest.urlopen", fake_urlopen):
        res = client.sync_order("order-1")

    assert captured["url"] == "http://pay.local/api/v1/orders/order-1/sync"
    assert captured["method"] == "POST"
    assert captured["body"] is None
    assert res["status"] == "paid"


def test_payment_client_gets_provider_readiness():
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _FakeResponse({"providers": [{"provider": "mock", "configured": True, "missing": []}]})

    client = payment_client.PaymentClient("http://pay.local")
    with patch("payment_client.urlrequest.urlopen", fake_urlopen):
        res = client.providers()

    assert captured["url"] == "http://pay.local/api/v1/providers"
    assert captured["method"] == "GET"
    assert res["providers"][0]["provider"] == "mock"


def test_payment_client_raises_structured_server_error():
    body = json.dumps({
        "error": "provider_not_configured",
        "message": "wechat provider is not configured",
    }).encode("utf-8")

    def fake_urlopen(_req, timeout):
        raise HTTPError(
            url="http://pay.local/api/v1/orders",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(body),
        )

    client = payment_client.PaymentClient("http://pay.local")
    with patch("payment_client.urlrequest.urlopen", fake_urlopen):
        try:
            client.create_order("install-1", "wechat", 1000)
        except payment_client.PaymentClientError as exc:
            assert exc.code == "provider_not_configured"
            assert exc.message == "wechat provider is not configured"
        else:
            raise AssertionError("expected PaymentClientError")
