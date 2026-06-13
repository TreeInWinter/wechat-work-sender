# Payment Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mock-verifiable payment backend and connect the macOS client so donation/support status is based on server-verified orders instead of local user clicks.

**Architecture:** Create a new FastAPI service in `/Users/baijinshan/IdeaProjects/sidekick-pay-server` with SQLite-backed orders and entitlements, using a mock provider for local verification and provider stubs for WeChat/Alipay. Add a `payment_client.py` module and pure payment policy helpers in the existing client, then replace the donation panel with dynamic QR order polling and add a payment service configuration page.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy, Pydantic, pytest, CustomTkinter, Pillow, qrcode.

---

## File Map

- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/requirements.txt`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/main.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/config.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/db.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/models.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/schemas.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/base.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/mock.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/wechat.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/alipay.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/services/payment_service.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/tests/test_payment_flow.py`
- Create: `/Users/baijinshan/IdeaProjects/wechat-work-sender/payment_client.py`
- Create: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_payment_client.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/config.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/gui_panel.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_gui_panel_ui.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/requirements.txt`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/AGENTS.md`

## Task 1: Backend Scaffold And Health

**Files:**
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/requirements.txt`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/main.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/config.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/db.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/models.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/tests/test_payment_flow.py`

- [ ] **Step 1: Create backend directories and dependency file**

```text
fastapi
uvicorn
sqlalchemy
pydantic
pytest
httpx
```

- [ ] **Step 2: Write failing health test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_healthz():
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["ok"] is True
```

- [ ] **Step 3: Implement FastAPI app and DB bootstrap**

```python
from fastapi import FastAPI

app = FastAPI(title="SideKick Pay Server")


@app.get("/healthz")
def healthz():
    return {"ok": True}
```

- [ ] **Step 4: Verify**

Run: `cd /Users/baijinshan/IdeaProjects/sidekick-pay-server && python3 -m pytest -q`

Expected: health test passes.

## Task 2: Backend Order State Machine

**Files:**
- Modify: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/models.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/schemas.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/services/payment_service.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/base.py`
- Create: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/providers/mock.py`
- Modify: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/app/main.py`
- Modify: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/tests/test_payment_flow.py`

- [ ] **Step 1: Write backend API tests**

```python
def test_mock_order_paid_at_least_ten_grants_supporter(client):
    order = client.post("/api/v1/orders", json={
        "install_id": "install-1",
        "provider": "mock",
        "amount_cents": 1000,
    }).json()
    paid = client.post(f"/api/v1/mock/orders/{order['order_id']}/pay", json={
        "paid_amount_cents": 1000,
    }).json()
    assert paid["status"] == "paid"
    assert paid["tier"] == "supporter"
    assert paid["support_until"]


def test_mock_order_under_ten_is_paid_but_free(client):
    order = client.post("/api/v1/orders", json={
        "install_id": "install-2",
        "provider": "mock",
        "amount_cents": 500,
    }).json()
    paid = client.post(f"/api/v1/mock/orders/{order['order_id']}/pay", json={
        "paid_amount_cents": 500,
    }).json()
    assert paid["status"] == "paid"
    assert paid["tier"] == "free"
    assert paid["support_until"] is None
```

- [ ] **Step 2: Implement models and service**

```python
class Order(Base):
    __tablename__ = "orders"
    order_id = Column(String, primary_key=True)
    install_id = Column(String, index=True, nullable=False)
    provider = Column(String, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")
    paid_amount_cents = Column(Integer, nullable=True)
    support_until = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Implement mock routes**

```python
@app.post("/api/v1/orders", response_model=OrderResponse)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    return service.create_order(db, payload)


@app.post("/api/v1/mock/orders/{order_id}/pay", response_model=OrderResponse)
def mock_pay(order_id: str, payload: MockPayRequest, db: Session = Depends(get_db)):
    return service.mark_paid(db, order_id, payload.paid_amount_cents)
```

- [ ] **Step 4: Verify**

Run: `cd /Users/baijinshan/IdeaProjects/sidekick-pay-server && python3 -m pytest -q`

Expected: all backend tests pass.

## Task 3: Client Payment API Layer And Policy

**Files:**
- Create: `/Users/baijinshan/IdeaProjects/wechat-work-sender/payment_client.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/config.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/gui_panel.py`
- Create: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_payment_client.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_gui_panel_ui.py`

- [ ] **Step 1: Write client tests**

```python
def test_default_payment_config_has_mock_server():
    cfg = payment_client.default_payment_config()
    assert cfg["payment_provider"] == "mock"
    assert cfg["payment_default_amount_cents"] == 1000


def test_unexpired_entitlement_suppresses_prompt():
    updates, should_prompt = gui_panel.next_donation_prompt_state(
        {
            gui_panel.DONATION_SEND_COUNT_KEY: 9,
            gui_panel.PAYMENT_ENTITLEMENT_CACHE_KEY: {
                "tier": "supporter",
                "support_until": "2026-07-13T00:00:00+08:00",
            },
        },
        now=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )
    assert should_prompt is False
```

- [ ] **Step 2: Implement `PaymentClient`**

```python
class PaymentClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        return self._request("GET", "/healthz")

    def create_order(self, install_id: str, provider: str, amount_cents: int) -> dict:
        return self._request("POST", "/api/v1/orders", {
            "install_id": install_id,
            "provider": provider,
            "amount_cents": amount_cents,
        })
```

- [ ] **Step 3: Implement entitlement-aware prompt policy**

```python
PAYMENT_ENTITLEMENT_CACHE_KEY = "payment_entitlement_cache"


def payment_entitlement_active(cache, now=None) -> bool:
    ...
```

- [ ] **Step 4: Verify**

Run: `cd /Users/baijinshan/IdeaProjects/wechat-work-sender && .venv/bin/python -m pytest tests/test_payment_client.py tests/test_gui_panel_ui.py::DonationPromptTests -q`

Expected: all selected client tests pass.

## Task 4: Payment Configuration Mock Page

**Files:**
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/gui_panel.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/config.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/requirements.txt`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_gui_panel_ui.py`

- [ ] **Step 1: Add menu entry and UI helpers**

```python
.add_command("支付服务设置…", self._show_payment_settings)
```

- [ ] **Step 2: Build the settings panel**

The panel contains service URL, provider segmented control, amount entry, status label, QR preview, and buttons for `测试连接`, `生成测试二维码`, `模拟支付成功`, `保存`.

- [ ] **Step 3: Add qrcode dependency**

Append to `requirements.txt`:

```text
qrcode
```

- [ ] **Step 4: Verify**

Run: `cd /Users/baijinshan/IdeaProjects/wechat-work-sender && .venv/bin/python -m py_compile gui_panel.py payment_client.py config.py`

Expected: compile succeeds.

## Task 5: Donation Panel Dynamic QR Integration

**Files:**
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/gui_panel.py`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/tests/test_gui_panel_ui.py`

- [ ] **Step 1: Replace manual self-report buttons**

Remove the two manual registration buttons from `_show_donation_panel` and add dynamic order controls.

- [ ] **Step 2: Poll order status**

```python
def _poll_payment_order(order_id: str):
    order = client.get_order(order_id)
    if order["status"] == "paid":
        self._save_payment_entitlement(order)
```

- [ ] **Step 3: Verify**

Run: `cd /Users/baijinshan/IdeaProjects/wechat-work-sender && .venv/bin/python -m pytest tests/test_gui_panel_ui.py::DonationPromptTests tests/test_payment_client.py -q`

Expected: policy and API tests pass.

## Task 6: End-To-End Mock Integration

**Files:**
- Modify: `/Users/baijinshan/IdeaProjects/sidekick-pay-server/README.md`
- Modify: `/Users/baijinshan/IdeaProjects/wechat-work-sender/AGENTS.md`

- [ ] **Step 1: Start backend**

Run:

```bash
cd /Users/baijinshan/IdeaProjects/sidekick-pay-server
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

- [ ] **Step 2: Run integration script**

Use `PaymentClient` from the existing client to call health, create mock order, simulate pay, and query entitlement.

- [ ] **Step 3: Run verification**

Run backend tests, client selected tests, client compile, and a lightweight smoke script that instantiates payment policy without opening a real macOS payment provider.

Expected: all verification commands pass and backend/client mock flow returns `tier=supporter`.

## Self-Review Notes

- Spec coverage: tasks cover backend project, mock provider, provider boundaries, client config page, dynamic donation panel, entitlement-based prompt policy, and end-to-end mock integration.
- Placeholder scan: no task relies on unknown fields; concrete file paths and commands are listed.
- Type consistency: server fields use `install_id`, `provider`, `amount_cents`, `order_id`, `status`, `paid_amount_cents`, `tier`, `support_until`; client config uses the same field names.
