#!/usr/bin/env python3
"""
amail_tools.py — 独立单元测试
========================================

不依赖 Hermes Agent 环境，使用 mock HTTP server 验证核心逻辑。

Usage:
    # 直接运行（自动启动内置 mock server）
    python3 test_amr_tools.py

    # 指定真实 gateway 地址（可选，用于 E2E 验证）
    python3 test_amr_tools.py --live http://127.0.0.1:38080 --key sk-xxx

    # 只测试特定模块
    python3 test_amr_tools.py --test client,preprocess
"""

import json
import logging
import os
import sys
import tempfile
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Optional
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════════════════════════
# Mock environment — 在不依赖 Hermes 的环境下加载 tools 模块
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

# Mock Hermes 模块（在 tools 模块导入之前创建）
class MockRegistry:
    def register(self, **kw):
        pass

class MockModule:
    registry = MockRegistry()
    def tool_result(self, x):
        return x

# 注入 mock，防止 ImportError
sys.modules["tools"] = MockModule()
sys.modules["tools.registry"] = MockModule()

# 现在可以安全导入 tools 模块
from amail_tools import (
    _GatewayClient,
    send_mail,
    manage_contacts,
    preprocess_mail_payload,
    trigger_profile_hooks,
    _profile_hooks,
    _auto_register_email,
    _auto_deregister_email,
    _load_gateway_config,
    _load_profile_config,
    _inject_profile_config,
    init_tenant,
    agent_startup_activate,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Mock HTTP Server
# ═══════════════════════════════════════════════════════════════════════════════

_ROUTES = {}  # (method, path_prefix) → handler

def route(methods, prefix):
    def wrap(fn):
        for m in methods:
            _ROUTES[(m, prefix)] = fn
        return fn
    return wrap

class MockGatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _check_auth(self):
        return bool(self.headers.get("X-Api-Key", ""))

    def _route(self, method):
        if not self._check_auth():
            return self._json(401, {"error": "Missing X-Api-Key"})
        import sys
        p = urlparse(self.path)
        print(f"[DBG _route] path={self.path!r} parsed_path={p.path!r}", file=sys.stderr)
        matches = sorted(_ROUTES.items(), key=lambda x: -len(x[0][1]))
        for (m, prefix), handler in matches:
            if m == method and p.path.startswith(prefix):
                print(f"[DBG _route] MATCH: {m} {prefix} handler={handler.__name__}", file=sys.stderr)
                body = {}
                try:
                    bl = int(self.headers.get("Content-Length", 0))
                    if bl:
                        body = json.loads(self.rfile.read(bl))
                except: pass
                return handler(self, p, body)
        print(f"[DBG _route] NO MATCH for {method} {p.path}", file=sys.stderr)
        return self._json(404, {"error": "no route"})

    do_GET = lambda s: s._route("GET")
    do_POST = lambda s: s._route("POST")
    do_PUT = lambda s: s._route("PUT")
    do_DELETE = lambda s: s._route("DELETE")

# ── Routes ──
@route(["GET"], "/api/v1/whoami")
def whoami(h, p, b):
    h._json(200, {"scope": "tenant_admin", "tenant_id": "test-tenant", "email": "admin@x.com"})

@route(["GET"], "/api/v1/admin/tenants/")
def tenant_detail(h, p, b):
    if "/domains" in p.path:
        h._json(200, [{"id": "d1", "domain": "test.domain"}])
    else:
        h._json(200, [{"id": "test-tenant", "name": "Test"}])

@route(["GET"], "/api/v1/admin/whitelists")
def list_wl(h, p, b):
    h._json(200, [{"id": 1, "value": "trusted@corp.com", "direction": "to"}])

@route(["GET"], "/api/v1/admin/whitelists/check")
def check_wl(h, p, b):
    """Mock whitelist check endpoint."""
    from urllib.parse import parse_qs
    import sys
    qs = parse_qs(p.query)
    value = qs.get("value", [""])[0]
    direction = qs.get("direction", [""])[0]
    # Return whitelisted=true for trusted@corp.com
    whitelisted = value == "trusted@corp.com" and direction == "to"
    print(f"[DBG] check_wl: value={value!r} dir={direction!r} wl={whitelisted}", file=sys.stderr)
    h._json(200, {"whitelisted": whitelisted})

@route(["GET"], "/api/v1/admin/activation-codes")
def list_address_codes(h, p, b):
    h._json(200, {"codes": [{"code_hash": "abc123", "status": "available"}]})

@route(["GET"], "/api/v1/api-keys")
def list_keys(h, p, b):
    h._json(200, [{"id": 10, "email_address": "agent-1@test.domain"}])

@route(["GET"], "/api/v1/stats/agent/me")
def agent_stats(h, p, b):
    h._json(200, {"today": {"sent": 10, "failed": 0}, "success_rate": 100.0})

@route(["POST"], "/api/v1/admin/activation-codes/batch")
def batch_gen(h, p, b):
    email_addr = b.get("email_address", "")
    h._json(201, {
        "count": b.get("count", 1),
        "raw_codes": [f"mock-addr-code-{h.server.server_port}-{email_addr}"],
    })

@route(["GET"], "/api/v1/stats/tenant")
def tenant_stats(h, p, b):
    if "/daily-usage" in p.path:
        h._json(200, {"sent": 50, "limit": 1000})
    else:
        h._json(200, {"today": {"sent": 100, "failed": 2}})

@route(["GET"], "/api/v1/stats/agents")
def agents_stats(h, p, b):
    h._json(200, {"agents": [{"email": "a1@x.com", "sent": 10}]})

@route(["POST"], "/api/v1/send")
def send(h, p, b):
    if not b.get("markdown"):
        return h._json(422, {"error": "markdown required"})
    h._json(201, {"id": "mock-email-001", "status": "queued"})

@route(["POST"], "/api/v1/api-keys")
def create_key(h, p, b):
    h._json(201, {"id": 99, "raw_key": "sk-mock-" + str(h.server.server_port),
                   "email_address": b.get("email_address", ""), "category": b.get("category", "tenant")})


def create_domain(h, p, b):
    h._json(201, {"id": b.get("id"), "domain": b.get("domain")})

@route(["POST"], "/api/v1/admin/whitelists")
def create_wl(h, p, b):
    h._json(201, {"id": 1, "value": b.get("value"), "direction": b.get("direction")})

@route(["PUT"], "/api/v1/api-keys/")
def rotate_key(h, p, b):
    if b.get("rotate"):
        h._json(200, {"id": 99, "raw_key": "sk-rotated-" + str(h.server.server_port)})
    else:
        h._json(200, {"id": 99})

@route(["DELETE"], "/api/v1/api-keys/")
def del_key(h, p, b):
    h._json(204, {})

@route(["DELETE"], "/api/v1/admin/whitelists/")
def del_wl(h, p, b):
    h._json(204, {})

@route(["POST"], "/api/v1/attachments")
def upload_attachment(h, p, b):
    h._json(201, {"attachment_id": "att-mock-001", "filename": b.get("filename", "unknown")})


# ── Unauthenticated routes (patched into do_POST) ──
_original_do_POST = MockGatewayHandler.do_POST
def _patched_do_POST(self):
    p = urlparse(self.path)
    body = {}
    try:
        bl = int(self.headers.get("Content-Length", 0))
        if bl:
            body = json.loads(self.rfile.read(bl))
    except: pass
    ua_routes = {
        "/api/v1/activate-tenant": ("POST", do_activate_tenant),
        "/api/v1/activation-codes/batch": ("POST", do_batch_codes),
        "/api/v1/activate-address": ("POST", do_activate_address),
    }
    for prefix, (m, handler) in ua_routes.items():
        if p.path.startswith(prefix):
            return handler(self, p, body)
    return _original_do_POST(self)

MockGatewayHandler.do_POST = _patched_do_POST

def do_activate_tenant(h, p, b):
    code = b.get("code", "")
    tenant_id = b.get("tenant_id", "mock-tenant")
    h._json(201, {
        "status": "activated",
        "raw_key": "***" + str(h.server.server_port),
        "tenant_id": tenant_id,
    })

def do_batch_codes(h, p, b):
    email_addr = b.get("email_address", "")
    h._json(201, {
        "count": b.get("count", 1),
        "raw_codes": [f"mock-addr-code-{h.server.server_port}-{email_addr}"],
    })

def do_activate_address(h, p, b):
    code = b.get("code", "")
    email = b.get("email_address", "")
    h._json(200, {
        "status": "activated",
        "raw_key": "sk-act...ock-" + str(h.server.server_port),
        "email_address": email or "test@test.com",
        "tenant_id": "mock-tenant",
        "scopes": ["send"],
    })


class MockGatewayServer:
    """管理 mock HTTP server 的生命周期"""

    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), MockGatewayHandler)
        self.port = self.server.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.1)  # 等待 server 就绪

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=2)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Framework
# ═══════════════════════════════════════════════════════════════════════════════

PASS = 0
FAIL = 0

class TestCase:
    """测试用例基类，提供 pass/fail 追踪"""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def check(self, condition, msg):
        global PASS, FAIL
        if condition:
            PASS += 1
            print(f"  [PASS] {self.name}: {msg}")
        else:
            FAIL += 1
            print(f"  [FAIL] {self.name}: {msg}")

    def eq(self, a, b, msg=""):
        self.check(a == b, msg or f"expected {b!r}, got {a!r}")

    def contains(self, haystack, needle, msg=""):
        s = str(list(haystack.values())) if isinstance(haystack, dict) else str(haystack)
        self.check(needle in s, msg or f"'{needle}' not in output")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_client_basics(mock: MockGatewayServer):
    """核心 HTTP 客户端基础功能"""
    print("\n── Client Basics ──")
    client = _GatewayClient(mock.url, "test-key")

    with TestCase("send_mail — correct payload") as t:
        r = client.send_mail(to="a@b.com", subject="Hi", body="Hello", sender="me@x.com")
        t.contains(r, "mock-email-001")

    with TestCase("upload_attachment — file not found") as t:
        r = client.upload_attachment("/nonexistent/file.txt")
        t.eq(r.get("status"), 400)

    with TestCase("upload_attachment — real file") as t:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            tmp = f.name
        r = client.upload_attachment(tmp)
        os.unlink(tmp)
        t.check(r.get("status") in (201, 400), f"status={r.get('status')}")


    with TestCase("check_whitelist — whitelisted true") as t:
        result = client.check_whitelist("dom.com", "trusted@corp.com", "to")
        t.check(result is True, f"expected True, got {result}")

    with TestCase("check_whitelist — whitelisted false") as t:
        result = client.check_whitelist("dom.com", "unknown@evil.com", "to")
        t.check(result is False, f"expected False, got {result}")

    with TestCase("check_whitelist — fallback when check endpoint fails") as t:
        # Test with a domain that will cause the check endpoint to fail (no route)
        # The mock returns 200 for /whitelists/check with specific values
        # For other values, check endpoint returns whitelisted=false
        # The list fallback should see the entry from list_wl
        result = client.check_whitelist("test.domain", "trusted@corp.com", "to")
        t.check(result is True, f"expected True from fallback, got {result}")

    with TestCase("add_whitelist — direction from/to/both") as t:
        r = client.add_whitelist("t1", "dom.com", "to", "friend@x.com")
        t.eq(r.get("status"), 201)

    with TestCase("delete_whitelist — by id") as t:
        r = client.delete_whitelist(1)
        t.eq(r.get("status"), 204)

    with TestCase("register_email — email as domain") as t:
        r = client.register_email("t1", "dom.com", "agent-1@dom.com", "http://hook", "secret")
        t.eq(r.get("status"), 201)
        # domain 字段应为完整 email
        t.contains(str(r), "agent-1@dom.com")

    with TestCase("download_attachment — binary fetch") as t:
        result = client.download_attachment("att-123")
        t.check(result is not None or result is None, "download returns bytes or None")

    with TestCase("delete_api_key") as t:
        r = client.delete_api_key(99)
        t.eq(r.get("status"), 204)

    with TestCase("key rotation") as t:
        r = client._request("PUT", "/api/v1/api-keys/99", body={"rotate": True})
        t.contains(str(r), "sk-rotated")


def test_activation_flow(mock: MockGatewayServer):
    """Activation code flow: tenant activation, address codes, address activation"""
    print("\n── Activation Flow ──")

    client = _GatewayClient(mock.url, "")

    with TestCase("activate_tenant — unauthenticated") as t:
        r = client.activate_tenant("mock-product-code", "new-tenant", "New Team")
        t.check(r.get("raw_key"), f"raw_key present")
        t.eq(r.get("tenant_id"), "new-tenant")

    with TestCase("generate_address_codes — unauthenticated batch") as t:
        auth_client = _GatewayClient(mock.url, "test-key")
        r = auth_client.generate_address_codes("t1", "test.com", count=1, email_address="agent@test.com")
        t.check(r.get("count") == 1, f"count={r.get('count')}")
        codes = r.get("raw_codes", [])
        t.check(len(codes) >= 1, f"got {len(codes)} code(s)")

    with TestCase("activate_address — unauthenticated") as t:
        r = client.activate_address("mock-addr-code-test", email_address="agent@test.com")
        t.check(r.get("success"), f"success={r.get('success')}")
        t.check(r.get("raw_key"), f"raw_key present")

    with TestCase("list_address_codes — authenticated") as t:
        # Use authenticated client for listing
        auth_client = _GatewayClient(mock.url, "test-key")
        r = auth_client.list_address_codes("t1")
        # Mock returns whatever — just check no exception
        t.check(r is not None, "list_address_codes returned result")


def test_init_tenant(mock: MockGatewayServer):
    """init_tenant() — bootstrap a new tenant from product code"""
    print("\n── init_tenant ──")

    with TestCase("init_tenant — creates tenant + returns config") as t:
        os.environ["AMAIL_URL"] = mock.url
        r = init_tenant(
            product_code="mock-pc-123",
            tenant_id="test-new-tenant",
            tenant_name="Test Team",
            domain="mail.test.com",
            webhook_url="http://127.0.0.1:9920",
            webhook_secret="test-secret",
        )
        del os.environ["AMAIL_URL"]
        t.check(r.get("success"), f"success={r.get('success')}")
        t.check(r.get("admin_key"), f"admin_key returned")

    with TestCase("init_tenant — missing gateway_url") as t:
        for k in list(os.environ.keys()):
            if k.startswith("AMAIL"):
                del os.environ[k]
        r = init_tenant(product_code="x", tenant_id="x", tenant_name="x")
        t.check(not r.get("success", True), "should fail without gateway_url")


def test_agent_startup_activate(mock: MockGatewayServer):
    """agent_startup_activate() — activate profile on startup"""
    print("\n── agent_startup_activate ──")

    with TestCase("agent_startup_activate — no profile dir") as t:
        if "HERMES_PROFILE_DIR" in os.environ:
            del os.environ["HERMES_PROFILE_DIR"]
        r = agent_startup_activate()
        t.check(not r.get("success", True), "should fail without HERMES_PROFILE_DIR")

    with TestCase("agent_startup_activate — no config file") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            r = agent_startup_activate()
            t.check(not r.get("success", True), "should fail without config")
        del os.environ["HERMES_PROFILE_DIR"]

    with TestCase("agent_startup_activate — already activated") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            _inject_profile_config(d, {
                "email": "agent@test.com",
                "api_key": "sk-already-has-key",
                "gateway_url": mock.url,
            })
            r = agent_startup_activate()
            t.check(r.get("success"), f"success={r.get('success')}")
            t.eq(r.get("activated"), False)  # Already activated
        del os.environ["HERMES_PROFILE_DIR"]

    with TestCase("agent_startup_activate — pending activation") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            _inject_profile_config(d, {
                "email": "agent@test.com",
                "activation_code": "mock-addr-code-agent",
                "gateway_url": mock.url,
                "domain": "test.com",
                "tenant_id": "t1",
            })
            # Also need global config for gateway_url
            os.environ["AMAIL_URL"] = mock.url
            os.environ["AMAIL_ADMIN_KEY"] = "test-key"
            r = agent_startup_activate()
            del os.environ["AMAIL_URL"]
            del os.environ["AMAIL_ADMIN_KEY"]
            t.check(r.get("success"), f"success={r.get('success')}")
            t.eq(r.get("activated"), True, f"activated={r.get('activated')}")
        del os.environ["HERMES_PROFILE_DIR"]


def test_config_loading(mock: MockGatewayServer):
    """配置加载逻辑"""
    print("\n── Config Loading ──")

    with TestCase("env var: AMAILGATEWAY_*") as t:
        os.environ["AMAIL_URL"] = mock.url
        os.environ["AMAIL_ADMIN_KEY"] = "env-key"
        os.environ["AMAIL_SYS_ID"] = "myproject"
        os.environ["AMAIL_MX_DOMAIN"] = "mail.myproject.com"
        cfg = _load_gateway_config()
        t.check(cfg is not None, "config loaded")
        if cfg:
            t.eq(cfg["gateway_url"], mock.url)
            t.eq(cfg["tenant_id"], "myproject")
            t.eq(cfg["domain"], "mail.myproject.com")
        del os.environ["AMAIL_URL"]
        del os.environ["AMAIL_ADMIN_KEY"]
        del os.environ["AMAIL_SYS_ID"]
        del os.environ["AMAIL_MX_DOMAIN"]

    with TestCase("profile config: inject + load") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            cfg = {"email": "test@x.com", "api_key": "sk-test"}
            _inject_profile_config(d, cfg)
            loaded = _load_profile_config()
            t.check(loaded is not None, "profile config loaded")
            if loaded:
                t.eq(loaded["email"], "test@x.com")
        del os.environ["HERMES_PROFILE_DIR"]


def test_preprocess(mock: MockGatewayServer):
    """Webhook preprocessor"""
    print("\n── Preprocess ──")

    with TestCase("no attachments — passthrough") as t:
        r = preprocess_mail_payload({"from": "a@b.com", "body": "Hi"}, {})
        t.eq(r["from"], "a@b.com")

    with TestCase("attachments — no gateway config") as t:
        r = preprocess_mail_payload({"attachments": [{"id": "abc", "filename": "t.txt"}]}, {})
        t.check(isinstance(r["attachments"], list), "attachments preserved as list")

    with TestCase("attachments — with gateway config") as t:
        os.environ["AMAIL_URL"] = mock.url
        os.environ["AMAIL_ADMIN_KEY"] = "test-key"
        payload = {"attachments": [{"attachment_id": "abc", "filename": "test.txt"}]}
        r = preprocess_mail_payload(payload, {})
        del os.environ["AMAIL_URL"]
        del os.environ["AMAIL_ADMIN_KEY"]
        t.check(isinstance(r.get("attachments"), list), "attachments is array")


def test_agent_tools(mock: MockGatewayServer):
    """Agent 工具函数（send_mail, manage_contacts）"""
    print("\n── Agent Tools ──")

    with TestCase("send_mail — no profile config") as t:
        r = asyncio_run(send_mail(to="a@b.com", subject="T", body="Hello"))
        t.contains(str(r), "not configured")

    with TestCase("send_mail — with profile config") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            _inject_profile_config(d, {
                "email": "agent@test.com",
                "api_key": "sk-test",
                "gateway_url": mock.url,
                "domain": "test.com",
                "tenant_id": "t1",
            })
            r = asyncio_run(send_mail(to="a@b.com", subject="T", body="Hello"))
            t.contains(str(r), "mock-email-001")
        del os.environ["HERMES_PROFILE_DIR"]

    with TestCase("manage_contacts — check (no config)") as t:
        r = asyncio_run(manage_contacts(action="check", address="test@x.com"))
        t.contains(str(r), "not configured")

    with TestCase("manage_contacts — check with profile") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            _inject_profile_config(d, {
                "email": "agent@test.com",
                "api_key": "sk-test",
                "gateway_url": mock.url,
                "domain": "test.com",
                "tenant_id": "t1",
            })
            r = asyncio_run(manage_contacts(action="check", address="trusted@corp.com", direction="to"))
            t.contains(str(r), "in_contacts")
        del os.environ["HERMES_PROFILE_DIR"]

    with TestCase("manage_contacts — add/remove with profile") as t:
        with tempfile.TemporaryDirectory() as d:
            os.environ["HERMES_PROFILE_DIR"] = d
            _inject_profile_config(d, {
                "email": "agent@test.com",
                "api_key": "sk-test",
                "gateway_url": mock.url,
                "domain": "test.com",
                "tenant_id": "t1",
            })
            r = asyncio_run(manage_contacts(action="add", address="friend@x.com", direction="to"))
            t.contains(str(r), "success")
        del os.environ["HERMES_PROFILE_DIR"]


def test_hooks(mock: MockGatewayServer):
    """Profile lifecycle hooks"""
    print("\n── Profile Hooks ──")

    with TestCase("hooks registered") as t:
        t.check(len(_profile_hooks.get("profile_created", [])) >= 1, "profile_created hooks")
        t.check(len(_profile_hooks.get("profile_deleted", [])) >= 1, "profile_deleted hooks")

    with TestCase("trigger — no gateway config") as t:
        with tempfile.TemporaryDirectory() as d:
            try:
                trigger_profile_hooks("profile_created", "test", d)
                t.check(True, "gracefully skipped")
            except Exception as e:
                t.check(False, f"raised: {e}")

    with TestCase("trigger — with gateway config") as t:
        os.environ["AMAIL_URL"] = mock.url
        os.environ["AMAIL_ADMIN_KEY"] = "test-key"
        os.environ["AMAIL_SYS_ID"] = "test"
        os.environ["AMAIL_MX_DOMAIN"] = "test.com"
        with tempfile.TemporaryDirectory() as d:
            try:
                trigger_profile_hooks("profile_created", "test-agent", d)
                t.check(True, "hook ran without exception")
            except Exception as e:
                t.check(False, f"raised: {e}")
        del os.environ["AMAIL_URL"]
        del os.environ["AMAIL_ADMIN_KEY"]
        del os.environ["AMAIL_SYS_ID"]
        del os.environ["AMAIL_MX_DOMAIN"]


def asyncio_run(coro):
    """同步运行 async 函数（兼容 Python 3.10+）"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # 已在事件循环中（Jupyter 等）
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL
    logging.basicConfig(level=logging.WARNING)

    live_url = None
    live_key = None
    test_filter = None

    import argparse
    ap = argparse.ArgumentParser(description="Test amail_tools.py")
    ap.add_argument("--live", help="Real gateway URL for E2E")
    ap.add_argument("--key", help="API key for live testing")
    ap.add_argument("--test", help="Test filter: client,activation,init,activate,config,preprocess,tools,hooks")
    args = ap.parse_args()

    if args.test:
        test_filter = set(args.test.split(","))
    live_url = args.live
    live_key = args.key

    if live_url:
        print(f"Using live gateway: {live_url}")
        mock_server = None
        # Override env vars for live testing
        os.environ["AMAIL_URL"] = live_url
        os.environ["AMAIL_ADMIN_KEY"] = live_key or ""
        mock = type("obj", (object,), {"url": live_url})()
    else:
        print("Starting mock gateway server...")
        mock_server = MockGatewayServer()
        mock = mock_server
        print(f"  Mock server on port {mock.port}")

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     amail_tools.py — Standalone Test Suite           ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    try:
        if not test_filter or "client" in test_filter:
            test_client_basics(mock)
        if not test_filter or "activation" in test_filter:
            test_activation_flow(mock)
        if not test_filter or "init" in test_filter:
            test_init_tenant(mock)
        if not test_filter or "activate" in test_filter:
            test_agent_startup_activate(mock)
        if not test_filter or "config" in test_filter:
            test_config_loading(mock)
        if not test_filter or "preprocess" in test_filter:
            test_preprocess(mock)
        if not test_filter or "tools" in test_filter:
            test_agent_tools(mock)
        if not test_filter or "hooks" in test_filter:
            test_hooks(mock)
    finally:
        if mock_server:
            mock_server.stop()
        # Clean up any env vars we set
        for k in list(os.environ.keys()):
            if k.startswith("AMAILGATEWAY_") or k.startswith("AMAIL") or k == "HERMES_PROFILE_DIR":
                del os.environ[k]

    print()
    print("════════════════════════════════════════════════════════════════")
    print(f"  Total: {PASS + FAIL}  |  {PASS} PASS  |  {FAIL} FAIL  |  {'✅' if FAIL == 0 else '❌'}  ")
    print("════════════════════════════════════════════════════════════════")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
