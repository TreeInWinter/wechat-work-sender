# 即时通讯接管对象选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a target selector so the macOS panel can discover installed IM clients and route takeover actions through isolated per-client adapters.

**Architecture:** Create an `im_clients` package with a small adapter protocol, a registry, and one module per supported client. Keep Enterprise WeChat as the only fully verified adapter, while WeChat and Daxiang are discoverable but conservative until their AX trees are verified.

**Tech Stack:** Python 3.10+, CustomTkinter, PyObjC AppKit/ApplicationServices, existing sender clipboard and AX helpers.

---

### Task 1: Client Discovery Model

**Files:**
- Create: `im_clients/base.py`
- Create: `im_clients/registry.py`
- Create: `im_clients/wechat_work.py`
- Create: `im_clients/wechat.py`
- Create: `im_clients/daxiang.py`
- Test: `tests/test_im_clients.py`

- [ ] **Step 1: Write failing tests for discovery and default selection**

Cover installed/running state, adapter capability flags, and default target preference.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_im_clients`

- [ ] **Step 3: Implement minimal adapter data model and registry**

Define adapter metadata and scanner injection points so tests do not require macOS apps to exist.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_im_clients`

### Task 2: Enterprise WeChat Adapter Wrapper

**Files:**
- Modify: `sender.py`
- Modify: `im_clients/wechat_work.py`
- Test: `tests/test_im_clients.py`

- [ ] **Step 1: Write failing tests proving Enterprise WeChat adapter delegates to existing sender behavior**

Use mocks to verify send, read, running status, and window bounds route through the adapter.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_im_clients`

- [ ] **Step 3: Implement wrapper methods without changing existing sender semantics**

Add adapter methods for `is_running`, `activate`, `window_bounds`, `send_blocks`, and `read_chat_messages`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_im_clients`

### Task 3: GUI Target Selector

**Files:**
- Modify: `gui_panel.py`
- Modify: `tests/test_gui_send.py`

- [ ] **Step 1: Write failing GUI-level tests for current target routing**

Verify send/read/status helpers use `self.current_client` instead of fixed `is_wx_running` / `read_chat_messages` imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_gui_send`

- [ ] **Step 3: Add selector state and route operations through selected adapter**

Add a compact target menu in the status area, refresh labels, and keep Enterprise WeChat as default.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_gui_send`

### Task 4: Verification

**Files:**
- Modify as needed from prior tasks.

- [ ] **Step 1: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_im_clients tests.test_gui_send tests.test_ai_reply`

- [ ] **Step 2: Run syntax check**

Run: `.venv/bin/python -m py_compile gui_panel.py sender.py ai_reply.py im_clients/*.py`

- [ ] **Step 3: Review diff**

Run: `git diff --stat` and inspect changed files for accidental unrelated edits.

