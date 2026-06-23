"""
amail_tools.py -- amail Hermes Agent 集成模块

三进程共用文件（Gateway / Agent / CLI），通过 try/except 隔离进程特定逻辑。

Provides:
  - _GatewayClient         : HTTP client for amail API
  - send_mail()            : Agent tool -- send email via gateway
  - manage_contacts()      : Agent tool -- manage address whitelist
  - preprocess_mail_payload() : Gateway preprocessor -- download attachments
  - register_profile_hook()   : Profile lifecycle hook registry
  - trigger_profile_hooks()   : Hook dispatcher (called by profiles.py)

Toolset: amail
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime
import socket
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

_TOOLSET = "amail"
_GATEWAY_CONFIG_KEY = "amail"


# ═══════════════════════════════════════════════════════════════
# _GatewayClient -- HTTP client for amail API
# ═══════════════════════════════════════════════════════════════

class _GatewayClient:
    """Thin HTTP wrapper around amail gateway REST API.
    No process-level side effects. Safe to instantiate anywhere."""

    def __init__(self, gateway_url: str, api_key: str, timeout: int = 30):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """"Make an HTTP request to the gateway API. Returns parsed JSON or error dict."""
        url = f"{self.gateway_url}{path}"
        req_headers = {"Accept": "application/json"}
        if self.api_key:
            req_headers["X-Api-Key"] = self.api_key
        if headers:
            req_headers.update(headers)

        data = None
        if raw_body is not None:
            data = raw_body
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        try:
            req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                status = resp.status
                try:
                    parsed = json.loads(resp_body)
                    # Handle JSON arrays -- wrap into {"data": [...]}
                    if isinstance(parsed, list):
                        return {"status": status, "data": parsed}
                    # Don't let response body overwrite HTTP status
                    parsed.pop("status", None)
                    return {"status": status, **parsed}
                except json.JSONDecodeError:
                    return {"status": status, "body": resp_body}
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                err_body.pop("status", None)
            except Exception:
                err_body = {"error": str(e)}
            return {"status": e.code, "error": str(e), **err_body}
        except Exception as e:
            return {"status": 0, "error": str(e)}

    # ── Send API ────────────────────────────────────────────────

    def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/send"""
        payload: Dict[str, Any] = {
            "to": to,
            "markdown": body,
        }
        if sender:
            payload["sender"] = sender
        if subject:
            payload["subject"] = subject
        if cc:
            payload["cc"] = cc
        if attachments:
            payload["attachments"] = attachments
        if in_reply_to or references:
            payload["headers"] = {}
            if in_reply_to:
                payload["headers"]["In-Reply-To"] = in_reply_to
            if references:
                payload["headers"]["References"] = references
        return self._request("POST", "/api/v1/send", body=payload)

    # ── Attachment API ──────────────────────────────────────────

    def upload_attachment(self, file_path: str) -> dict:
        """POST /api/v1/upload -- upload a file as an attachment."""
        path = Path(file_path)
        if not path.is_file():
            return {"status": 400, "error": f"File not found: {file_path}"}
        content = path.read_bytes()
        # Use multipart-like approach via raw bytes with content-type header
        boundary = "----HermesBoundary"
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self._request(
            "POST",
            "/api/v1/upload",
            raw_body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def download_attachment(self, attachment_id: str) -> Optional[bytes]:
        """GET /api/v1/attachments/{id} -- download attachment bytes."""
        url = f"{self.gateway_url}/api/v1/attachments/{attachment_id}"
        req = urllib.request.Request(
            url,
            headers={"X-Api-Key": self.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except Exception as e:
            logger.error("download_attachment(%s) failed: %s", attachment_id, e)
            return None

    # ── Whitelist API ───────────────────────────────────────────

    def check_whitelist(self, domain_addr: str, value: str, direction: str = "to") -> bool:
        """Check if a value is whitelisted for the given direction.

        Args:
            domain_addr: Domain to check against
            value: Email address or pattern to check
            direction: "to" (outbound send, default), "from" (inbound receive)
        """
        result = self._request(
            "GET",
            f"/api/v1/admin/whitelists/check?domain_addr={domain_addr}&value={value}&direction={direction}",
        )
        return result.get("status") == 200 and result.get("whitelisted", False)

    def add_whitelist(
        self, system_id: str, domain_addr: str, direction: str,
        value: str, description: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            "/api/v1/admin/whitelists",
            body={
                "system_id": system_id,
                "domain_addr": domain_addr,
                "direction": direction,
                "value": value,
                "description": description,
            },
        )

    def delete_whitelist(self, entry_id: int) -> dict:
        """DELETE /api/v1/admin/whitelists/:id"""
        return self._request("DELETE", f"/api/v1/admin/whitelists/{entry_id}")

    # ── Agent State API (per-agent KV store) ─────────────────────

    def agent_state_get(self, key: str) -> Optional[str]:
        """GET /api/v1/admin/agent-state/:key - returns value string or None."""
        result = self._request("GET", f"/api/v1/admin/agent-state/{key}")
        if result.get("status") == 200:
            return result.get("value")
        return None

    def agent_state_put(self, key: str, value: str) -> dict:
        """PUT /api/v1/admin/agent-state/:key - upsert a value."""
        return self._request("PUT", f"/api/v1/admin/agent-state/{key}", body={"value": value})

    def agent_state_delete(self, key: str) -> dict:
        """DELETE /api/v1/admin/agent-state/:key."""
        return self._request("DELETE", f"/api/v1/admin/agent-state/{key}")

    # ── Semantic endpoints ──────────────────────────────

    def put_contact(self, address: str, profile: str) -> dict:
        """PUT /api/v1/admin/contacts/:address — atomic write + name index + merge."""
        return self._request("PUT", f"/api/v1/admin/contacts/{address}",
                             body={"profile": profile})

    def get_contact(self, address: str) -> Optional[dict]:
        """GET /api/v1/admin/contacts/:address — returns {address, profile} or None."""
        result = self._request("GET", f"/api/v1/admin/contacts/{address}")
        if result.get("status") == 200:
            return {"address": result.get("address"), "profile": result.get("profile")}
        return None

    def get_contacts_by_name(self, name: str) -> list:
        """GET /api/v1/admin/contacts?name=... — returns [{"address":...,"profile":...}]."""
        result = self._request("GET", f"/api/v1/admin/contacts?name={name}")
        if result.get("status") == 200:
            return result.get("results", [])
        return []

    def put_thread_summary(self, message_id: str, summary: str) -> dict:
        """PUT /api/v1/admin/thread-summary/:message_id — resolve thread_id + write."""
        return self._request("PUT", f"/api/v1/admin/thread-summary/{message_id}",
                             body={"summary": summary})

    def get_thread_summary(self, message_id: str) -> Optional[str]:
        """GET /api/v1/admin/thread-summary/:message_id — resolve + read, returns summary str or None."""
        result = self._request("GET", f"/api/v1/admin/thread-summary/{message_id}")
        if result.get("status") == 200:
            return result.get("summary")
        return None

    # ── Domain / API Key management ─────────────────────────────

    def register_email(
        self,
        system_id: str,
        mx_domain: str,
        email: str,
        webhook_url: str,
        webhook_secret: str,
        manager_address: str = "",
        generate_code: bool = False,
    ) -> dict:
        """POST /api/v1/admin/systems/:sid/addresses — register an agent address.
        When generate_code=True, also creates an activation code in one call."""
        params = "?generate_code=true" if generate_code else ""
        result = self._request(
            "POST",
            f"/api/v1/admin/systems/{system_id}/addresses{params}",
            body={
                "id": f"addr-{email.replace('@', '-at-')}-{int(time.time())}",
                "email": email,
                "webhook_url": webhook_url,
                "webhook_secret": webhook_secret,
                "manager_address": manager_address,
            },
        )
        return result

    # ── Address Activation Code API ─────────────────────────────

    def list_address_codes(
        self,
        system_id: str,
        claimed: bool = False,
        limit: int = 10,
    ) -> dict:
        """GET /api/v1/admin/activation-codes?code_type=address -- List address codes.

        Requires system_admin scope.

        Returns ``{"status": 200, "codes": [...], "count": N}``
        """
        params = (
            f"code_type=address"
            f"&system_id={system_id}"
            f"&claimed={str(claimed).lower()}"
            f"&limit={limit}"
        )
        return self._request("GET", f"/api/v1/admin/activation-codes?{params}")

    def generate_address_codes(
        self,
        system_id: str,
        domain: str,
        count: int = 1,
        email_address: Optional[str] = None,
        expires_in_mins: int = 10080,
    ) -> dict:
        """POST /api/v1/admin/activation-codes/batch -- Generate address activation codes.

        Requires system_admin scope.

        Returns ``{"status": 200, "raw_codes": ["addr-xxxx-..."]}``
        """
        body: Dict[str, Any] = {
            "code_type": "address",
            "system_id": system_id,
            "domain": domain,
            "count": count,
            "expires_in_mins": expires_in_mins,
        }
        if email_address:
            body["email_address"] = email_address
        return self._request(
            "POST", "/api/v1/admin/activation-codes/batch", body=body
        )

    # ── System Activation ─────────────────────────────────────────

    def activate_system(self, code: str, **kwargs) -> dict:
        """POST /api/v1/activate-system -- Activate a system using a product code.

        No authentication required -- the activation code IS the credential.
        Extra kwargs (system_id, system_name, domain) are passed through
        as optional fields -- the server auto-generates any missing values.

        Args:
            code: The product activation code (e.g. "prod-xxxx-xxxx-...")

        Returns ``{"status": 200, "raw_key": "sk-...", "system_id": "...", ...}``
        """
        body = {"code": code}
        # Pass through any optional overrides
        for k in ("system_id", "system_name", "domain"):
            v = kwargs.get(k)
            if v:
                body[k] = v
        result = self._request("POST", "/api/v1/activate-system", body=body)
        raw_key = result.get("raw_key", "")
        if not raw_key:
            return {"success": False, "error": f"activation failed: {result}"}
        return {
            "success": True,
            "raw_key": raw_key,
            "system_id": result.get("system_id", ""),
            "system_name": result.get("system_name", ""),
            "domain": result.get("domain", ""),
        }

    # ── Address Activation (Agent side) ─────────────────────────

    def activate_address(self, code: str, email_address: str = "", scopes: Optional[list] = None) -> dict:
        """POST /api/v1/activate-address -- Agent activates an address code to get raw_key.

        No authentication required -- the address activation code IS the credential.

        Args:
            code: The address activation code (e.g. "addr-xxxx-xxxx-...")
            email_address: The email address to bind to the API key (required)
            scopes: Optional scope list (defaults to ["send"])

        Returns ``{"status": 200, "raw_key": "sk-...", "api_key_id": N, ...}``
        """
        body = {"code": code, "email_address": email_address, "scopes": scopes or ["send"]}
        result = self._request("POST", "/api/v1/activate-address", body=body)
        raw_key = result.get("raw_key", "")
        if not raw_key:
            return {"success": False, "error": f"activation failed: {result}"}
        return {
            "success": True,
            "raw_key": raw_key,
            "api_key_id": result.get("api_key_id", 0),
            "email_address": result.get("email_address", ""),
        }


# ═══════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════

def _gateway_config_path() -> Path:
    """Return the path to the standalone amail gateway config file.
    
    Always uses ~/.hermes/amail_gateway.json — gateway config is global,
    not per-profile."""
    return Path.home() / ".hermes" / "amail_gateway.json"


def _load_gateway_config() -> Optional[dict]:
    """load amail gateway connection config

    Reads from (in priority order):
    1. Environment variables (AMAIL_URL + AMAIL_ADMIN_KEY/AMAIL_PRODUCT_CODE)
    2. ~/.hermes/amail_gateway.json (standalone, no config.yaml pollution [gateway config])
    3. ~/.hermes/config.yaml platforms.amail (legacy fallback)
    """
    # Try environment variables first
    gateway_url = os.environ.get("AMAIL_GATEWAY_URL", "")
    admin_key = os.environ.get("AMAIL_ADMIN_KEY", "")
    product_code = os.environ.get("AMAIL_PRODUCT_CODE", "")
    sys_id = os.environ.get("AMAIL_SYS_ID", "")
    system_id = sys_id or os.environ.get("AMAIL_TENANT_ID", "")
    mx_domain = os.environ.get("AMAIL_MX_DOMAIN", "amail.token.tm")
    domain = mx_domain or os.environ.get("AMAIL_DOMAIN", "")
    # Legacy: map AMAIL_BRIDGE_URL → webhook_host at the config level
    raw_webhook = os.environ.get("AMAIL_WEBHOOK_HOST", "") or os.environ.get("AMAIL_BRIDGE_URL", "")
    if raw_webhook:
        # Strip protocol and /path to get host:port
        raw_webhook = raw_webhook.replace("http://", "").replace("https://", "").split("/")[0]
    if gateway_url and (admin_key or product_code):
        return {
            "gateway_url": gateway_url,
            "admin_key": admin_key,
            "product_code": product_code,
            "system_id": system_id,
            "domain": domain,
            "manager_address": os.environ.get("AMAIL_MANAGER_ADDRESS", ""),
            "webhook_host": raw_webhook,
            "sys_id": sys_id,
            "mx_domain": mx_domain,
        }

    # Try standalone amail_gateway.json
    gateway_path = _gateway_config_path()
    if gateway_path.exists():
        try:
            with open(gateway_path) as f:
                cfg = json.load(f)
            if cfg.get("gateway_url") and (cfg.get("admin_key") or cfg.get("product_code")):
                return cfg
        except Exception:
            pass

    # Legacy fallback: config.yaml platforms.amail
    try:
        from gateway.config import load_config
        cfg = load_config()
        gateway_cfg = cfg.get("platforms", {}).get(_GATEWAY_CONFIG_KEY, {})
        if gateway_cfg.get("gateway_url") and (gateway_cfg.get("admin_key") or gateway_cfg.get("product_code")):
            result = dict(gateway_cfg)
            result.setdefault("system_id", gateway_cfg.get("sys_id", ""))
            result.setdefault("domain", gateway_cfg.get("mx_domain", ""))
            return result
    except Exception:
        pass

    return None


def _load_profile_config() -> Optional[dict]:
    """Load per-profile gateway config from profile directory."""
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        return None

    # Try amail.json first (primary), then amail_gateway.json (legacy)
    for fname in ("amail.json", "amail_gateway.json"):
        config_path = Path(profile_dir) / fname
        if config_path.is_file():
            try:
                return json.loads(config_path.read_text())
            except Exception:
                pass

    return None


def _inject_profile_config(profile_dir: str, config: dict) -> None:
    """Write per-profile gateway config to profile directory."""
    config_path = Path(profile_dir) / "amail.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2))


# ═══════════════════════════════════════════════════════════════
# Unified Setup -- auto-detect admin_key vs activation_code path
# ═══════════════════════════════════════════════════════════════

def setup(
    gateway_url: str,
    system_id: str,
    admin_key: str = "",
    product_code: str = "",
    system_name: str = "",
    domain: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
    webhook_base_url: str = "",
    webhook_secret: str = "",
) -> dict:
    """Unified integration entry point.

    Provide gateway_url + system_id + ONE of (admin_key, product_code).
    The function auto-detects the path and saves config.

    Args:
        gateway_url:         amail gateway server URL (required)
        system_id:         System identifier (auto-generated by server from product code)
        admin_key:         Existing system_admin API key
        product_code:      Product activation code (one-time; creates system if new)
        system_name:       Human-readable name (only used with product_code path)
        domain:            Default mail domain (optional)
        save_raw_snapshots: Persist raw email snapshots to disk (default: False)
        webhook_base_url:  Default webhook URL for inbound routing (optional)
        webhook_secret:    HMAC secret for webhook verification (optional)

    Returns:
        {\"success\": True, \"system_id\": \"...\", \"path\": \"admin_key\"|\"activation\", ...}
        {\"success\": False, \"error\": \"...\"}
    """
    if not gateway_url:
        return {"success": False, "error": "gateway_url is required"}

    # Auto-detect webhook callback host (parameter > env var > auto-detect)
    if not webhook_host:
        webhook_host = os.environ.get("AMAIL_WEBHOOK_HOST", "")
    if not webhook_host:
        webhook_host = _detect_webhook_host(gateway_url)

    # ── Path A: admin_key provided (already-activated system) ──
    if admin_key:
        if not system_id:
            return {"success": False, "error": "system_id is required for admin_key path"}
        # Save directly to Hermes config
        _save_gateway_config(
            gateway_url=gateway_url,
            admin_key=admin_key,
            system_id=system_id,
            domain=domain or "admin.local",
            save_raw_snapshots=save_raw_snapshots,
            manager_address=manager_address,
            webhook_host=webhook_host,
        )
        return {
            "success": True,
            "system_id": system_id,
            "path": "admin_key",
            "note": "Admin key saved. Agent keys can now be created via POST /api/v1/api-keys.",
        }

    # ── Path B: product_code provided (new system activation) ──
    if product_code:
        result = init_system(
            product_code=product_code,
            system_id=system_id,
            system_name=system_name,
            domain=domain,
            gateway_url=gateway_url,
            save_raw_snapshots=save_raw_snapshots,
            manager_address=manager_address,
            webhook_host=webhook_host,
        )
        if result.get("success"):
            result["path"] = "activation"
        return result

    return {"success": False, "error": "Either admin_key or product_code is required"}


def verify_integration(gateway_url: str = "", admin_key: str = "") -> dict:
    """Diagnostic: verify all integration points are correctly configured.

    Checks gateway connectivity, admin_key validity, webhook route existence,
    preprocessor registration, and profile hooks. Returns a dict with
    per-check pass/fail status and suggestions for remediation.

    Args:
        gateway_url: Gateway server URL (auto-detected from config if empty)
        admin_key: Admin API key (auto-detected from config if empty)
    """
    results = {"checks": [], "all_pass": True}

    def add(name: str, ok: bool, detail: str, fix: str = ""):
        results["checks"].append({"check": name, "pass": ok, "detail": detail, "fix": fix})
        if not ok:
            results["all_pass"] = False

    # Resolve config
    config = _load_gateway_config()
    gateway_url = gateway_url or (config.get("gateway_url", "") if config else "")
    admin_key = admin_key or (config.get("admin_key", "") if config else "")

    # 1. Gateway connectivity
    if not gateway_url:
        add("gateway_connectivity", False, "No gateway_url configured", "Run integrate.sh or set AMAIL_GATEWAY_URL env var")
    else:
        try:
            req = urllib.request.Request(f"{gateway_url.rstrip('/')}/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                add("gateway_connectivity", r.status == 200,
                    f"HTTP {r.status}", "Start amail-gateway service")
        except Exception as e:
            add("gateway_connectivity", False, str(e), "Start amail-gateway service")

    # 2. Admin key validity
    if not admin_key:
        add("admin_key", False, "No admin_key configured", "Run integrate.sh with admin_key")
    else:
        try:
            req = urllib.request.Request(f"{gateway_url.rstrip('/')}/api/v1/whoami",
                headers={"X-Api-Key": admin_key})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                scope = data.get("scope", "")
                add("admin_key", "platform" in scope or "system" in scope,
                    f"scope={scope}", "Use a key with platform or system scope")
        except Exception as e:
            add("admin_key", False, str(e), "Check admin_key is correct and gateway is running")

    # Also read gateway config for optional system_name
    cfg_path = Path.home() / ".hermes" / "amail_gateway.json"
    if cfg_path.exists():
        try:
            local_cfg = json.loads(cfg_path.read_text())
            sn = local_cfg.get("system_name", "")
            if sn:
                add("system_name", True, f"shared domain identifier: {sn}")
        except Exception:
            pass

    # 3. Webhook route (check default + named profile subscriptions)
    has_amail = False
    routes_checked = []
    # Default profile
    subs_default = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "webhook_subscriptions.json"
    routes_checked.append(str(subs_default))
    if subs_default.exists():
        try:
            if "amail-inbound" in json.loads(subs_default.read_text()):
                has_amail = True
        except Exception:
            pass
    # Named profiles
    if not has_amail:
        profiles_root = Path.home() / ".hermes" / "profiles"
        if profiles_root.is_dir():
            for d in sorted(profiles_root.iterdir()):
                if not d.is_dir():
                    continue
                subs_prof = d / "webhook_subscriptions.json"
                routes_checked.append(str(subs_prof))
                if subs_prof.exists():
                    try:
                        if "amail-inbound" in json.loads(subs_prof.read_text()):
                            has_amail = True
                            break
                    except Exception:
                        pass
    if has_amail:
        # Verify the route has preprocess = "amail_gateway" configured
        preprocess_ok = False
        for subs_path in routes_checked:
            p = Path(subs_path)
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    if "subscriptions" in data:
                        routes = data["subscriptions"].get("routes", {})
                    else:
                        routes = data
                    route = routes.get("amail-inbound", {})
                    if route.get("preprocess") == "amail_gateway":
                        preprocess_ok = True
                        break
                except Exception:
                    pass
        if preprocess_ok:
            add("webhook_route", True, "amail-inbound route found (preprocessor configured)")
        else:
            add("webhook_route", False, "amail-inbound route missing preprocess=\"amail_gateway\"",
                "Run integrate.sh (Step 5) to reconfigure the webhook route")
    else:
        add("webhook_route", False,
            f"amail-inbound route missing (checked: {', '.join(routes_checked)})",
            "Create profile to auto-register, or add route to webhook_subscriptions.json")

    # 4. Hermes webhook.py patch (PREPROCESS_REGISTRY)
    herm_dir = Path(os.environ.get("HERMES_DIR", str(Path.home() / ".hermes" / "hermes-agent")))
    webhook_py = herm_dir / "gateway" / "platforms" / "webhook.py"
    if webhook_py.exists():
        try:
            wh_content = webhook_py.read_text()
            wh_patched = "PREPROCESS_REGISTRY" in wh_content
            add("webhook_patch", wh_patched,
                "webhook.py has preprocessor support" if wh_patched else "webhook.py NOT patched",
                "Run integrate.sh (Step 5) or apply patches/webhook.py.patch")
        except Exception:
            add("webhook_patch", False, "Cannot read webhook.py", "Check HERMES_DIR path")
    else:
        add("webhook_patch", False, f"webhook.py not found at {webhook_py}",
            "Set HERMES_DIR to Hermes source root")

    # 5. Hermes profiles.py patch (trigger_profile_hooks)
    for profiles_path in [
        herm_dir / "hermes_cli" / "profiles.py",
        herm_dir / "cli" / "profiles.py",
    ]:
        if profiles_path.exists():
            try:
                pf_content = profiles_path.read_text()
                pf_patched = "trigger_profile_hooks" in pf_content
                add("profiles_patch", pf_patched,
                    "profiles.py has amail hooks" if pf_patched else "profiles.py NOT patched",
                    "Run integrate.sh (Step 6) or apply patches/profiles.py.patch")
            except Exception:
                add("profiles_patch", False, "Cannot read profiles.py")
            break
    else:
        add("profiles_patch", False, "profiles.py not found",
            "Set HERMES_DIR or check Hermes installation")

    # 6. Profile hooks installed in module
    hooks_ok = (
        _auto_register_email in _profile_hooks.get("profile_created", [])
        and _auto_deregister_email in _profile_hooks.get("profile_deleted", [])
    )
    add("profile_hooks", hooks_ok,
        "create/delete hooks registered" if hooks_ok else "hooks not registered",
        "Check register_profile_hook calls at bottom of amail_tools.py")

    return results


def _save_gateway_config(
    gateway_url: str,
    admin_key: str,
    system_id: str,
    domain: str = "",
    system_name: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
) -> None:
    """Save amail gateway connection config to standalone JSON file.

    Writes to ~/.hermes/amail_gateway.json — does NOT pollute config.yaml.
    Webhook config is gateway-managed, not stored here."""
    cfg = {
        "gateway_url": gateway_url,
        "admin_key": admin_key,
        "system_id": system_id,
        "system_name": system_name,
        "save_raw_snapshots": save_raw_snapshots,
    }
    if domain:
        cfg["domain"] = domain
    if manager_address:
        cfg["manager_address"] = manager_address
    if webhook_host:
        cfg["webhook_host"] = webhook_host

    gateway_path = _gateway_config_path()
    gateway_path.parent.mkdir(parents=True, exist_ok=True)
    with open(gateway_path, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Webhook config (gateway-managed, per-profile) ──────────────

def _port_is_available(port: int, host: str = "0.0.0.0") -> bool:
    """Check if a TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.bind((host, port))
            return True
    except OSError:
        return False


def _read_webhook_port(cfg_path: Path) -> int:
    """Read webhook port from a profile config file. Returns 0 if not found."""
    if not cfg_path.exists():
        return 0
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        wh = cfg.get("platforms", {}).get("webhook", {})
        if wh.get("enabled"):
            return int(wh.get("extra", {}).get("port", 0))
    except Exception:
        pass
    return 0


def _next_available_webhook_port(base_port: int = 8644) -> int:
    """Find the next available webhook port.
    
    Scans all existing profile configs for the max port, then probes
    actual port availability. Increments until an unused port is found.
    """
    # Scan existing profiles for max configured port
    max_port = base_port - 1
    default_cfg = Path.home() / ".hermes" / "config.yaml"
    max_port = max(max_port, _read_webhook_port(default_cfg))
    profiles_dir = Path.home() / ".hermes" / "profiles"
    if profiles_dir.is_dir():
        for d in profiles_dir.iterdir():
            if d.is_dir():
                max_port = max(max_port, _read_webhook_port(d / "config.yaml"))
    
    # Start after max configured port, probe actual availability
    candidate = max(max_port + 1, base_port)
    for _ in range(100):  # safety limit
        if _port_is_available(candidate):
            return candidate
        candidate += 1
    return candidate  # fallback — likely all ports exhausted


def _ensure_profile_webhook(profile_dir: str) -> Optional[dict]:
    """Ensure the profile has webhook configured. Auto-generates if missing.
    
    Returns {enabled, host, port, secret} or None on fatal error.
    """
    cfg_path = Path(profile_dir) / "config.yaml"
    
    # Already configured? Return existing
    if cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            wh = cfg.get("platforms", {}).get("webhook", {})
            if wh.get("enabled"):
                extra = wh.get("extra", {})
                return {
                    "enabled": True,
                    "host": extra.get("host", "0.0.0.0"),
                    "port": int(extra.get("port", 8644)),
                    "secret": extra.get("secret", ""),
                }
        except Exception as e:
            logger.warning("[amail_gateway] Failed to read webhook config: %s", e)
    
    # Auto-generate
    port = _next_available_webhook_port()
    secret = secrets.token_hex(32)
    
    try:
        import yaml
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if cfg_path.exists():
            existing = yaml.safe_load(cfg_path.read_text()) or {}
        
        # Deep-merge with existing config
        platforms = dict(existing.get("platforms", {}))
        platforms["webhook"] = {
            "enabled": True,
            "extra": {"host": "0.0.0.0", "port": port, "secret": secret},
        }
        merged = {**existing, "platforms": platforms}
        cfg_path.write_text(yaml.dump(merged, default_flow_style=False))
        logger.info("[amail_gateway] Auto-configured webhook for %s (port=%d)", profile_dir, port)
    except Exception as e:
        logger.error("[amail_gateway] Failed to write webhook config for %s: %s", profile_dir, e)
        return None
    
    return {"enabled": True, "host": "0.0.0.0", "port": port, "secret": secret}

def _load_webhook_config() -> Optional[dict]:
    """Load Hermes webhook platform config from environment or config file.
    
    Returns {"enabled": bool, "host": str, "port": int, "secret": str}
    or None if webhook platform is not configured.
    """
    # Check environment (set by hermes gateway setup or manual .env)
    webhook_enabled = os.environ.get("WEBHOOK_ENABLED", "").lower() in {"true", "1", "yes"}
    webhook_port = os.environ.get("WEBHOOK_PORT", "8644")
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")

    # Also check config.yaml for webhook platform settings
    try:
        from gateway.config import load_config
        cfg = load_config()
        wh = cfg.get("platforms", {}).get("webhook", {})
        if wh.get("enabled"):
            webhook_enabled = True
        extra = wh.get("extra", {})
        if extra.get("port") and not os.environ.get("WEBHOOK_PORT"):
            webhook_port = str(extra["port"])
        if extra.get("secret") and not webhook_secret:
            webhook_secret = extra["secret"]
    except Exception:
        pass

    if not webhook_enabled:
        return None

    try:
        port = int(webhook_port)
    except (ValueError, TypeError):
        port = 8644

    # Determine host for constructing webhook URLs
    host = os.environ.get("WEBHOOK_HOST", "127.0.0.1")

    return {"enabled": True, "host": host, "port": port, "secret": webhook_secret}


# ── Webhook host auto-detection ──────────────────────────────

def _detect_webhook_host(gateway_url: str) -> str:
    """determine the reachable host for gateway → Hermes webhook callbacks

    Compares ``gateway_url``'s host against local interfaces to choose the
    correct callback address:

    - Same machine (loopback or own IP) → ``127.0.0.1``
    - Same LAN (private IP, different host) → our LAN IP
    - Remote (public IP) → our external IP or LAN fallback

    Returns the best host string.  Failing everything, returns ``127.0.0.1``.
    """
    from urllib.parse import urlparse
    try:
        gateway_host = urlparse(gateway_url).hostname or ""
    except Exception:
        gateway_host = ""

    if not gateway_host:
        return "127.0.0.1"

    # ── Detect our primary LAN IP ────────────────────────────
    lan_ip = ""
    # Best-effort: let the kernel pick the route to an external address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass

    # Fallback: scan interfaces
    if not lan_ip:
        try:
            import subprocess as _sp
            out = _sp.check_output(
                ["ip", "-4", "-brief", "addr", "show", "scope", "global"],
                text=True, timeout=3,
            )
            for line in out.splitlines():
                parts = line.strip().split()
                # ip -brief output: "eth0  UP  192.168.1.2/24 ..."
                for p in parts:
                    if "/" in p and p[0].isdigit():
                        ip = p.split("/")[0]
                        if not ip.startswith("127."):
                            lan_ip = ip
                            break
                if lan_ip:
                    break
        except Exception:
            pass

    # ── Classify gateway host ──────────────────────────────────
    import ipaddress as _ipaddr

    def _is_loopback(host: str) -> bool:
        return host in ("127.0.0.1", "localhost", "::1", "ip6-localhost")

    def _is_private(host: str) -> bool:
        try:
            return _ipaddr.ip_address(host).is_private
        except ValueError:
            return False

    if _is_loopback(gateway_host):
        return "127.0.0.1"

    if lan_ip and gateway_host == lan_ip:
        return lan_ip  # same machine via LAN — works for Docker containers too

    if _is_private(gateway_host):
        # Same LAN — gateway can reach us via our LAN IP
        if lan_ip:
            return lan_ip
        return "127.0.0.1"  # fallback

    # ── Hostname (not IP): try DNS resolution (with timeout) ──
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
        with ThreadPoolExecutor(max_workers=1) as _dns:
            resolved = _dns.submit(socket.gethostbyname, gateway_host).result(timeout=5)
        if _is_loopback(resolved):
            return "127.0.0.1"
        if lan_ip and resolved == lan_ip:
            return lan_ip
        if _is_private(resolved):
            return lan_ip if lan_ip else "127.0.0.1"
    except Exception:
        pass  # can't resolve, continue to public detection

    # ── Public IP: try external detection ───────────────────
    try:
        import urllib.request as _ur
        req = _ur.Request("https://ifconfig.me", headers={"User-Agent": "curl/7.0"})
        with _ur.urlopen(req, timeout=5) as resp:
            external_ip = resp.read().decode().strip()
            if external_ip and not _is_private(external_ip):
                logger.info(
                    "[amail_gateway] Detected external IP %s for webhook callback "
                    "(gateway at %s is public)", external_ip, gateway_host
                )
                return external_ip
    except Exception:
        pass

    if lan_ip:
        logger.warning(
            "[amail_gateway] Gateway at %s is public but cannot detect external IP. "
            "Using LAN IP %s — gateway must be able to reach this address. "
            "Set AMAIL_WEBHOOK_HOST to override.", gateway_host, lan_ip
        )
        return lan_ip

    return "127.0.0.1"


def list_personas() -> dict:
    """List available personas for the current profile.
    
    Returns {name: prompt, ...} from the profile's agent.personalities
    in {profile_dir}/config.yaml. Empty dict if none configured.
    """
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if profile_dir:
        try:
            import yaml
            profile_cfg_path = Path(profile_dir) / "config.yaml"
            if profile_cfg_path.exists():
                with open(profile_cfg_path) as f:
                    cfg = yaml.safe_load(f) or {}
                return cfg.get("agent", {}).get("personalities", {}) or {}
        except Exception:
            pass
    return {}



def _ensure_webhook_route(
    route_name: str,
    secret: str,
    profile_dir: str = "",
    skills: Optional[List[str]] = None,
    deliver: str = "log",
    persona: str = "",
) -> bool:
    """Idempotently create/update a webhook route in webhook_subscriptions.json.
    
    Writes to ``{profile_dir}/webhook_subscriptions.json`` so each profile's
    gateway sees its own routes. Falls back to ``HERMES_HOME`` (or ~/.hermes)
    when ``profile_dir`` is empty.

    Returns True if the route was newly created, False if it already existed.
    """
    # Validate persona if specified
    if persona:
        personas = list_personas()
        if persona not in personas:
            logger.warning(
                "[amail_gateway] Persona '%s' not found in agent.personalities. "
                "Available: %s. Route will be created without persona.",
                persona, ", ".join(personas.keys()) or "(none)"
            )
            persona = ""  # clear invalid persona

    if profile_dir:
        hermhome = profile_dir
    else:
        hermhome = os.environ.get("HERMES_HOME",
            str(Path.home() / ".hermes"))
    subs_path = Path(hermhome) / "webhook_subscriptions.json"
    subs = {}
    if subs_path.exists():
        try:
            subs = json.loads(subs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass

    existed = route_name in subs

    route_entry = {
        "description": f"amail inbound email route ({route_name})",
        "events": [],
        "secret": secret,
        "preprocess": "amail_gateway",    # triggers preprocess_mail_payload
        "prompt": "",
        "skills": skills or ["amail"],
        "deliver": deliver,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if persona:
        route_entry["persona"] = persona
    subs[route_name] = route_entry

    subs_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = subs_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(subs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(subs_path)
    logger.info("[amail_gateway] %s webhook route: %s %s",
                "Updated" if existed else "Created", route_name, subs_path)
    return not existed


# ═══════════════════════════════════════════════════════════════
# System Initialization
# ═══════════════════════════════════════════════════════════════

def init_system(
    product_code: str,
    system_id: str,
    system_name: str,
    domain: str = "",
    gateway_url: str = "",
    save_raw_snapshots: bool = False,
    manager_address: str = "",
    webhook_host: str = "",
) -> dict:
    """Initialize a system using a product activation code.

    This is the first-step setup for a new system that has NOT been activated yet.
    It takes a pre-generated product activation code, activates it on the server,
    creates the system + default domain + quotas, and returns a system_admin API key.

    Webhook config is NOT set at domain level -- each agent address registers its
    own webhook via _auto_register_email() when profiles are created.

    The returned admin_key is saved to the global Hermes config automatically.

    Args:
        product_code: Pre-generated product activation code (e.g. "prod-xxxx-xxxx")
        system_id: System identifier (ignored for product_code path; server auto-generates)
        system_name: Human-readable system name
        domain: Default mail domain (optional -- uses product-level default if omitted)
        gateway_url: amail gateway server URL (required if not in config/env)

    Returns:
        {"success": True, "system_id": "...", "admin_key": "sk-...", ...}
        {"success": False, "error": "..."}
    """
    # Resolve gateway_url from config/env if not provided
    if not gateway_url:
        cfg = _load_gateway_config()
        gateway_url = cfg.get("gateway_url", "") if cfg else ""
    if not gateway_url:
        return {"success": False, "error": "gateway_url is required (pass it or set AMAIL_GATEWAY_URL / config)"}

    if not product_code:
        return {"success": False, "error": "product_code is required for system initialization"}

    # Backend auto-generates system_id/system_name/domain from product code
    client = _GatewayClient(gateway_url, "")
    result = client.activate_system(
        code=product_code,
        system_name=system_name or None,
        domain=domain or None,
    )

    status = result.get("status", 0)
    if not result.get("success"):
        return {"success": False, "error": result.get("error", f"Activation failed (HTTP {status})"), "status": status}

    # Backend returns "raw_key" (not "admin_key") from /api/v1/activate-system
    admin_key = result.get("raw_key", "")
    created_system_id = result.get("system_id", system_id)
    created_domain = result.get("domain", domain)

    if not admin_key:
        return {"success": False, "error": "No admin_key returned from server", "status": status}

    # Save admin_key to standalone gateway config
    _save_gateway_config(
        gateway_url=gateway_url,
        admin_key=admin_key,
        system_id=created_system_id,
        domain=created_domain,
        system_name=system_name or result.get("system_name", ""),
        save_raw_snapshots=save_raw_snapshots,
        manager_address=manager_address,
        webhook_host=webhook_host,
    )
    logger.info("[amail] Gateway config saved to %s", _gateway_config_path())

    return {
        "success": True,
        "system_id": created_system_id,
        "admin_key": admin_key,
        "gateway_url": gateway_url,
        "domain": created_domain,
        "system_name": system_name or result.get("system_name", ""),
    }


# ═══════════════════════════════════════════════════════════════
# Agent Tools
# ═══════════════════════════════════════════════════════════════

async def send_mail(
    to: Union[str, List[str]],
    subject: str,
    body: str,
    cc: Optional[Union[str, List[str]]] = None,
    attachments: Optional[List[str]] = None,
    message_id: Optional[str] = None,
) -> dict:
    """Send an email via your amail address.

    Attachments (file paths) are automatically uploaded before sending.
    For replies, pass the original email's message_id -- the tool will
    automatically resolve In-Reply-To, References headers, and the
    sender persona (from the stored inbound message metadata).
    """
    # Normalize array args to comma/space-separated strings
    if isinstance(to, list):
        to = ", ".join(to)
    if isinstance(cc, list):
        cc = ", ".join(cc)

    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "amail not configured for this profile"}

    # Auto-activate if profile has activation_code but no api_key yet
    if config.get("activation_code") and not config.get("api_key"):
        profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
        if profile_dir:
            _auto_activate_profile(profile_dir, config)
            config = _load_profile_config()
            if not config:
                return {"success": False, "error": "amail config lost after activation"}

    if not config.get("api_key"):
        return {"success": False, "error": "amail api_key not available (activation may have failed)"}

    # ── Guard: email must be configured ──────────────────────
    base_email = config.get("email", "")
    if not base_email:
        return {"success": False, "error": "amail email not configured for this profile — cannot send"}

    client = _GatewayClient(config["gateway_url"], config["api_key"])

    # ── Resolve message metadata once (avoids duplicate HTTP round-trip) ──
    msg_meta = _load_message_meta(message_id) if message_id else None

    # ── Resolve sender: persona from inbound metadata > current persona > base email ──
    sender = base_email
    if msg_meta:
        stored_persona = msg_meta.get("my_amail_addr", "")
        if stored_persona and "@" in stored_persona:
            sender = stored_persona
            logger.info("[amail] Reply detected — using persona sender: %s", sender)
    elif not message_id:
        # New email: auto-detect current persona from profile directory
        persona = _current_persona_name()
        if persona:
            local, domain = base_email.split("@", 1)
            sender = f"{local}.{persona}@{domain}"
            logger.info("[amail] New email from persona '%s' — sender: %s", persona, sender)

    # Parse recipients
    to_list = [a.strip() for a in to.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else None

    # Resolve threading headers from message_id
    in_reply_to = None
    references = None
    if message_id:
        in_reply_to = message_id
        if msg_meta:
            # Build References: original references + original message_id
            refs = msg_meta.get("references", [])
            if isinstance(refs, str):
                refs = [r.strip() for r in refs.split() if r.strip()]
            all_refs = refs + [message_id]
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for r in all_refs:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)
            references = " ".join(deduped)
        else:
            # No metadata -- just use message_id as the reference chain start
            references = message_id

    # Resolve and validate attachments
    resolved_paths, resolve_errors = _resolve_attachments(attachments) if attachments else ([], [])
    if resolve_errors:
        return {"success": False, "error": "Attachment resolution failed", "details": resolve_errors}

    # Size checks + upload
    upload_errors = []
    attachment_ids = []
    for path in resolved_paths:
        size_err = _check_attachment_size(path)
        if size_err:
            upload_errors.append(size_err)
            continue
        resp = client.upload_attachment(path)
        if resp.get("status") == 201:
            attachment_ids.append({"id": resp.get("attachment_id", resp.get("id", ""))})
        else:
            upload_errors.append(f"Upload failed for {Path(path).name}: {resp.get('error', 'HTTP ' + str(resp.get('status', '?')))}")

    if upload_errors and not attachment_ids:
        return {"success": False, "error": "All attachments failed", "details": upload_errors}

    result = client.send_mail(
        to=",".join(to_list),
        subject=subject,
        body=body,
        cc=",".join(cc_list) if cc_list else None,
        attachments=attachment_ids if attachment_ids else None,
        in_reply_to=in_reply_to,
        references=references,
        sender=sender,
    )

    # Store outbound message metadata for future replies
    out_msg_id = result.get("message_id", "")
    if out_msg_id:
        _store_message_meta(out_msg_id, references=references)

    # Optionally save outbound email snapshot
    if out_msg_id and config.get("save_raw_snapshots"):
        _save_outbound_snapshot(out_msg_id, sender, sender, to, subject, body,
                                cc_list or [], attachment_ids or [],
                                in_reply_to or "", references or "")

    # Auto-bootstrap thread summary for new (non-reply) emails
    thread_bootstrapped = False
    if out_msg_id and not message_id:
        try:
            initial_summary = f"Subject: {subject}\nStatus: awaiting response"
            await set_email_summary(out_msg_id, initial_summary)
            thread_bootstrapped = True
            logger.info("[amail] Thread summary bootstrapped for new email: %s", out_msg_id)
        except Exception as e:
            logger.warning("[amail] Failed to bootstrap thread summary: %s", e)

    # Flatten status into success/error
    status = result.pop("status", 0)
    if 200 <= status < 300:
        out = {"success": True, **result}
        if thread_bootstrapped:
            out["thread_bootstrapped"] = True
        if upload_errors:
            failed_names = [Path(e.split(":")[0] if ":" not in e else "").name or e for e in upload_errors]
            out["note"] = f"Sent, but {len(upload_errors)} attachment(s) had issues: {'; '.join(upload_errors[:3])}"
        return out
    else:
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Send failed: {error}"}


async def manage_contacts(
    action: str,
    address: Optional[str] = None,
    direction: str = "all",
    **kwargs,
) -> dict:
    """Manage your amail address book (whitelist).

    Args:
        action: "check", "add", or "remove"
        address: email address to add/remove (required for add/remove)
        direction: "from" (default, inbound receive) or "to" (outbound send) or "all"
    """
    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "amail not configured for this profile"}

    client = _GatewayClient(config["gateway_url"], config["api_key"])
    # Agent whitelist is per-amail, not per-domain.
    # domain_addr = amail address (agent-1@mail.project.com)
    amail = config.get("email", "")
    system_id = config.get("system_id", "")

    if action == "check":
        if not address:
            return {"success": False, "error": "address is required for check"}
        # Query whitelist entries to extract direction from the record
        list_result = client._request("GET", f"/api/v1/admin/whitelists?domain_addr={amail}")
        entries = list_result.get("data", []) if isinstance(list_result, dict) else []
        for entry in entries:
            if entry.get("value") == address:
                return {
                    "success": True,
                    "in_contacts": True,
                    "direction": entry.get("direction", "all"),
                    "address": address,
                }
        return {"success": True, "in_contacts": False, "address": address}

    elif action == "add":
        if not address:
            return {"success": False, "error": "address is required for add"}
        # Agent cannot directly add to whitelist.
        # Instead, send a request email to the manager for approval.
        # The manager replies with "add X to my contacts" which is processed
        # by webhook.rs handle_manager_commands.
        manager_addr = config.get("manager_address", "")
        if not manager_addr:
            return {"success": False, "error": "No manager_address configured — cannot send approval request"}
        client_mgr = _GatewayClient(config["gateway_url"], config["api_key"])
        description = kwargs.get("description", "") if kwargs else ""
        desc_line = f"\ndescription: {description}" if description else ""
        result = client_mgr.send_mail(
            to=manager_addr,
            subject=f"[Amail] Contact request: {address}",
            body=f"Please add {address} to {amail}'s contacts with direction={direction}.{desc_line}\n\n"
                 f"To approve, reply to this email with:\nadd {address} to my contacts with direction={direction}",
        )
        status = result.get("status", 0)
        if 200 <= status < 300:
            return {"success": True, "note": f"Approval request sent to manager ({manager_addr})"}
        error = result.get("error", f"HTTP {status}")
        return {"success": False, "error": f"Failed to send approval request: {error}"}

    elif action == "remove":
        if not address:
            return {"success": False, "error": "address is required for remove"}
        result = client._request("DELETE",
            f"/api/v1/admin/whitelists?domain_addr={amail}&value={address}")
        status = result.pop("status", 0)
        if status == 204:
            return {"success": True}
        if status == 404:
            return {"success": False, "error": f"{address} not found in whitelist"}
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Failed to remove {address}: {error}"}

    elif action == "update":
        if not address:
            return {"success": False, "error": "address is required for update"}
        new_direction = kwargs.get("direction", direction)
        if not new_direction:
            return {"success": False, "error": "direction is required for update"}
        # Find the entry ID for this address
        list_result = client._request("GET", f"/api/v1/admin/whitelists?domain_addr={amail}")
        entries = list_result.get("data", []) if isinstance(list_result, dict) else []
        entry_id = None
        for entry in entries:
            if entry.get("value") == address:
                entry_id = entry.get("id")
                break
        if not entry_id:
            return {"success": False, "error": f"{address} not found in whitelist"}
        result = client._request("PUT", f"/api/v1/admin/whitelists/{entry_id}",
                                 body={"direction": new_direction})
        status = result.pop("status", 0)
        if 200 <= status < 300:
            return {"success": True, "note": f"direction updated to {new_direction}"}
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Failed to update {address}: {error}"}


    else:
        return {"success": False, "error": f"Unknown action: {action}"}



# ── Contact profile (for context awareness) ──────────────────────

async def contact_profile(address: str = "", name: str = "") -> dict:
    """Look up a contact profile by address or name.

    At least one of address or name must be provided.
    - address: exact lookup via GET /api/v1/admin/contacts/:address
    - name: server-side search via GET /api/v1/admin/contacts?name=
    """
    if not address and not name:
        return {"address": "", "profile": None, "error": "address or name required"}

    config = _load_profile_config()
    if not config:
        return {"address": address, "profile": None}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    # Search by address (exact match) — semantic endpoint
    if address:
        contact = client.get_contact(address)
        if contact:
            return {"address": address, "profile": contact.get("profile")}
        return {"address": address, "profile": None}

    # Search by name (server-side)
    results = client.get_contacts_by_name(name.strip())
    if not results:
        return {"address": "", "profile": None, "searched_name": name}
    if len(results) == 1:
        return {"address": results[0]["address"], "profile": results[0]["profile"]}
    return {"ambiguous": True, "candidates": [r["address"] for r in results]}



async def set_contact_profile(address: str, profile: str) -> dict:
    """Store or update a contact profile. The gateway handles JSON merge,
    name extraction, and name index maintenance atomically.
    """
    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "amail not configured for this profile"}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    result = client.put_contact(address, profile)
    if result.get("status") == 200:
        return {"success": True}
    error = result.get("error", f"HTTP {result.get('status')}")
    return {"success": False, "error": f"Failed to store profile: {error}"}


def _parse_recipients(to: str, cc: str) -> list:
    """Parse to+cc into deduplicated list (fallback for payloads without pre-parsed recipients)."""
    seen = set()
    result = []
    for field in (to, cc):
        if not field:
            continue
        for addr in field.split(","):
            addr = addr.strip().lower()
            if addr and addr not in seen:
                seen.add(addr)
                result.append(addr)
    return result


# ═══════════════════════════════════════════════════════════════
# Gateway Preprocessor — inbound mail payload transformation
# ═══════════════════════════════════════════════════════════════

def preprocess_mail_payload(payload: dict, headers: dict) -> dict:
    """Preprocess amail webhook payload before prompt rendering.

    Rust backend already handles text cleaning. Python side handles:
    - Persona extraction from 'to' address (persona.profile@domain format)
    - Persona validation against configured personalities
    - direct_message / mentioned (persona-aware matching)
    - attachment download
    """
    result = dict(payload)
    body = result.get("body", "")

    # Agent identity (for direct_message / mentioned)
    config = _load_profile_config()
    agent_email = config.get("email", "") if config else ""
    system_name = config.get("system_name", "") if config else ""

    if not agent_email:
        logger.warning("[amail_gateway] No email configured for this profile — inbound preprocessing skipped")
        # Still return a recognizable payload so the gateway continues
        result["_preprocess_error"] = "amail email not configured"
        return result

    # ── Extract display names from headers before stripping ──
    import re as _re
    _name_re = _re.compile(r'^(.+?)\s*<')
    _email_re = _re.compile(r'<([^>]+)>')

    def _parse_header_addrs(header_val: str):
        results = []
        for part in header_val.split(','):
            part = part.strip()
            if not part:
                continue
            m = _email_re.search(part)
            if m:
                email = m.group(1).strip().lower()
                nm = _name_re.match(part)
                name = nm.group(1).strip() if nm else email.split('@')[0]
            elif '@' in part:
                email = part.strip().lower()
                name = email.split('@')[0]
            else:
                continue
            results.append((name, email))
        return results

    def _to_list(v):
        if isinstance(v, list):
            return [s.strip() for s in v if s and s.strip()]
        if isinstance(v, str):
            return [s.strip() for s in v.split(',') if s.strip()]
        return []

    def _base_email(email: str) -> str:
        """Strip persona prefix: support.alice@agent.com -> alice@agent.com"""
        persona, profile, sys_name = parse_amail_persona(email, system_name)
        domain = email.split('@', 1)[1] if '@' in email else ''
        if sys_name:
            return f"{profile}.{sys_name}@{domain}"
        return f"{profile}@{domain}"

    to_raw = _to_list(result.get("to", []))
    cc_raw = _to_list(result.get("cc", []))

    # Extract display names from MIME headers
    raw_headers = result.get("headers", {}) or {}
    to_named = _parse_header_addrs(raw_headers.get("to", ""))
    cc_named = _parse_header_addrs(raw_headers.get("cc", ""))

    def _fmt(n, e): return f"{n} <{e}>" if n else e

    if to_named:
        to_display = [_fmt(n, e) for n, e in to_named]
    else:
        to_display = to_raw
    if cc_named:
        cc_display = [_fmt(n, e) for n, e in cc_named]
    else:
        cc_display = cc_raw
    result["recipients"] = {"to": to_display, "cc": cc_display}

    # Bare emails for matching
    to_bare = [e for _, e in to_named] if to_named else [a.lower() for a in to_raw]
    cc_bare = [e for _, e in cc_named] if cc_named else [a.lower() for a in cc_raw]

    # Set sender field with display name (SKILL.md defines "sender", not "from")
    from_named = _parse_header_addrs(raw_headers.get("from", ""))
    if from_named:
        result["sender"] = _fmt(from_named[0][0], from_named[0][1])

    # ── Persona extraction from 'to' address ──
    # Find the recipient that belongs to our agent domain
    agent_domain = agent_email.split('@', 1)[1] if agent_email and '@' in agent_email else ''
    my_to_addr = ''
    for addr in to_bare:
        if agent_domain and addr.endswith('@' + agent_domain):
            my_to_addr = addr
            break

    persona, profile, _sys_name = parse_amail_persona(my_to_addr, system_name) if my_to_addr else ('', '', '')
    if persona:
        # Validate persona against configured personalities
        configured = list_personas()
        if persona in configured:
            result["my_amail_addr"] = my_to_addr
        else:
            logger.warning("[amail_gateway] Persona '%s' not found in agent.personalities — falling back to base address", persona)
    if not result.get("my_amail_addr"):
        result["my_amail_addr"] = my_to_addr or agent_email

    # ── Persona-aware direct_message / mentioned ──
    if agent_email:
        agent_email_lower = agent_email.lower()
        agent_base = _base_email(agent_email_lower)
        all_bare = to_bare + cc_bare
        all_base = [_base_email(a) for a in all_bare]

        # DM: only one to-recipient, and it's us (persona-aware)
        result["direct_message"] = (
            len(to_bare) == 1
            and not cc_bare
            and all_base[0] == agent_base
        )

        # mentioned: match profile name and display name
        agent_local = agent_email.split('@')[0]
        agent_display = ''
        for n, e in to_named + cc_named:
            if _base_email(e) == agent_base and n:
                agent_display = n
                break
        match_targets = [agent_local, profile] if profile else [agent_local]
        if agent_display:
            match_targets.append(agent_display)
        body_lower = (body or "").lower()
        result["mentioned"] = any(
            f'@{t.lower()}' in body_lower or t.lower() in body_lower.split()
            for t in match_targets if t
        ) if agent_email else False
    else:
        result["direct_message"] = False
        result["mentioned"] = False

    attachments = result.get("attachments")

    if attachments and isinstance(attachments, list) and len(attachments) > 0:
        config = _load_gateway_config()
        if not config:
            logger.warning("[amail_gateway] Cannot download attachments: no gateway config")
            return result

        client = _GatewayClient(config["gateway_url"], config["admin_key"])
        local_paths = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_id = att.get("attachment_id", att.get("id", ""))
            fname = att.get("filename", att.get("name", "unnamed_attachment"))
            if not att_id:
                continue

            content = client.download_attachment(att_id)
            if content is None:
                continue

            # Save to cache directory
            cache_dir = Path.home() / ".hermes" / "cache" / "attachments"
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_path = cache_dir / fname
            # Avoid overwriting -- append counter if needed
            if local_path.exists():
                stem, suffix = local_path.stem, local_path.suffix
                counter = 1
                while local_path.exists():
                    local_path = cache_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            local_path.write_bytes(content)
            local_paths.append(str(local_path))

            # Convert binary documents to markdown (DOCX, XLSX, PDF, HTML)
            ext = Path(fname).suffix.lower()
            if ext in (".docx", ".xlsx", ".html", ".htm"):
                try:
                    from markitdown import MarkItDown
                    md_text = MarkItDown().convert(str(local_path)).text_content
                    if md_text.strip():
                        md_path = cache_dir / f"{Path(fname).stem}.md"
                        md_path.write_text(md_text)
                        local_paths.append(str(md_path))
                except Exception:
                    pass  # keep original, agent falls through to PDF skill

        result["attachments"] = local_paths

    # ── Strip backend-only fields not in SKILL.md to avoid LLM confusion ──
    for field in ("mail_id", "to", "cc", "headers", "created_at", "forwarder", "forward_at"):
        result.pop(field, None)

    # ── Store message metadata + optional raw snapshot ──────────
    mid = result.get("message_id", "")
    refs = result.get("references", [])
    my_addr = result.get("my_amail_addr", "")
    if mid and my_addr:
        store_inbound_message(mid, refs, my_addr, preprocessed_payload=result)
        # Lightweight log entry
        _from = headers.get("from", raw_headers.get("from", ""))
        _subj = headers.get("subject", raw_headers.get("subject", ""))
        _log_amail("inbound", str(_from), my_addr, str(_subj))

    return result


# ═══════════════════════════════════════════════════════════════
# Webhook Preprocessor Registration (Gateway process only)
# ═══════════════════════════════════════════════════════════════

try:
    from gateway.platforms.webhook import register_preprocessor

    register_preprocessor("amail_gateway", preprocess_mail_payload)
    logger.info("amail preprocessor registered with webhook gateway")
except ImportError:
    # Agent process / CLI process — webhook module unavailable, expected
    pass
except Exception as e:
    logger.warning("amail preprocessor registration failed: %s — inbound mail will NOT be preprocessed", e)


# ═══════════════════════════════════════════════════════════════
# Profile Hook System
# ═══════════════════════════════════════════════════════════════

_profile_hooks: Dict[str, List[Callable]] = {
    "profile_created": [],
    "profile_deleted": [],
}


def register_profile_hook(event: str, callback: Callable) -> None:
    """Register a callback for profile lifecycle events."""
    if event not in _profile_hooks:
        _profile_hooks[event] = []
    _profile_hooks[event].append(callback)


def trigger_profile_hooks(event: str, profile_name: str, profile_dir: str) -> None:
    """Called by profiles.py to fire all registered hooks for an event.

    Gracefully handles missing config -- if no gateway is configured, hooks are
    simply skipped.
    """
    config = _load_gateway_config()
    if not config:
        logger.debug("[amail_gateway] No gateway config -- skipping hooks for %s", event)
        return

    for cb in _profile_hooks.get(event, []):
        try:
            cb(profile_name, profile_dir, config)
        except Exception as e:
            logger.warning("[amail_gateway] hook %s for '%s' failed: %s", event, profile_name, e)


# ── Hook: auto-register email on profile creation ──────────────

def parse_amail_persona(email: str, system_name: str = "") -> tuple:
    """Parse persona, profile, and system_name from an amail address.
    
    Returns (persona, profile_name, sys_name).
    
    Shared domain (three-part: persona.profile.sys_name@domain):
      'support.ql-biopharm.myco@amail.token.tm'  → ('support', 'ql-biopharm', 'myco')
      'ql-biopharm.myco@amail.token.tm'           → ('', 'ql-biopharm', 'myco')
      'myco@amail.token.tm'                       → ('', 'default', 'myco')  ← short form
    
    Non-shared domain (two-part: persona.profile@domain):
      'support.alice@agent.com'  → ('support', 'alice', '')
      'alice@agent.com'          → ('', 'alice', '')
    """
    local = email.split('@')[0] if '@' in email else email
    parts = local.split('.')
    
    # If system_name is known and local part matches → short form (default agent)
    if system_name and len(parts) == 1 and parts[0] == system_name:
        return ('', 'default', system_name)
    
    # Three-part: persona.profile.sys_name@domain
    if system_name and len(parts) >= 2 and parts[-1] == system_name:
        sys_name = parts[-1]
        profile_parts = parts[:-1]
        if len(profile_parts) >= 2:
            return ('.'.join(profile_parts[:-1]), profile_parts[-1], sys_name)
        return ('', profile_parts[0], sys_name)
    
    # Traditional: persona.profile@domain
    if len(parts) >= 2:
        return ('.'.join(parts[:-1]), parts[-1], '')
    return ('', parts[0], '')


def _auto_register_email(name: str, profile_dir: str, config: dict) -> None:
    """When a new Profile is created, register its email with amail:
    1. Create domain entry for {name}@{domain}
    2. Create activation code for the agent
    3. Ensure amail-inbound webhook route on the gateway
    4. Inject config into profile directory
    
    The registered address is the agent's identity. Persona switching is
    handled at inbound time by parse_amail_persona() -- the amail skill
    extracts persona from the 'to' address (persona.profile@domain format).
    """
    gateway_url = config.get("gateway_url", "")
    admin_key = config.get("admin_key", "")
    domain = config.get("domain", "")
    system_id = config.get("system_id", "")

    if not gateway_url or not admin_key:
        logger.warning("[amail_gateway] Cannot auto-register: gateway_url or admin_key not configured")
        return
    if not domain:
        logger.warning("[amail_gateway] Cannot auto-register: domain not configured")
        return
    if not system_id:
        logger.warning("[amail_gateway] Cannot auto-register: system_id not configured")
        return

    client = _GatewayClient(gateway_url, admin_key)
    system_name = config.get("system_name", "") or ""
    if system_name:
        if name == "default":
            email = f"{system_name}@{domain}"
            alias_email = f"default.{system_name}@{domain}"
        else:
            email = f"{name}.{system_name}@{domain}"
            alias_email = ""
    else:
        email = f"{name}@{domain}"
        alias_email = ""
    manager_address = config.get("manager_address", "")

    # Auto-configure or read profile webhook config
    wh_config = _ensure_profile_webhook(profile_dir)
    if not wh_config:
        logger.warning("[amail_gateway] Failed to configure webhook for %s — inbound mail disabled", profile_dir)
        webhook_url = ""
        webhook_secret = ""
    else:
        webhook_secret = wh_config["secret"]
        wh_port = wh_config["port"]

        webhook_host = config.get("webhook_host", "")
        if not webhook_host:
            # integrate.sh set webhook_host="" → gateway is local
            webhook_url = f"http://127.0.0.1:{wh_port}/webhooks/amail-inbound"
        else:
            # Remote gateway → call bridge API to get webhook_url
            # Protocol: IP:port → http, domain:port → https
            if re.match(r'^\d+\.\d+\.\d+\.\d+:', webhook_host):
                bridge_base = f"http://{webhook_host}"
            else:
                bridge_base = f"https://{webhook_host}"

            try:
                import json as _json
                data = _json.dumps(
                    {"email": email, "host": "127.0.0.1", "port": wh_port}
                ).encode()
                req = urllib.request.Request(
                    f"{bridge_base}/api/v1/routes",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    resp_data = _json.loads(r.read().decode())
                webhook_url = resp_data.get("webhook_url", "")
                logger.info("[amail_gateway] Bridge returned webhook_url=%s", webhook_url)
            except Exception as e:
                logger.error("[amail_gateway] Bridge unreachable: %s", e)
                return

        # Ensure amail-inbound route exists (idempotent)
        _ensure_webhook_route("amail-inbound", webhook_secret, profile_dir=profile_dir)

    # Register the email + generate activation code in one call
    result = client.register_email(
        system_id=system_id,
        mx_domain=config["domain"],
        email=email,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        manager_address=manager_address,
        generate_code=True,
    )
    logger.info("[amail_gateway] Registered email %s: %s", email, result)

    if result.get("status") not in ("created", 200, 201):
        logger.error("[amail_gateway] Failed to register email %s: %s — skipping activation code generation", email, result)
        return

    # Allow agent to send email to its own manager (for contact approval requests)
    if manager_address:
        client.add_whitelist(
            system_id=system_id,
            domain_addr=email,
            direction="all",
            value=manager_address,
            description="Agent ↔ Manager (auto-created)",
        )

    # Register alias for default profile (sys_name@domain + default.sys_name@domain)
    if alias_email:
        alias_result = client.register_email(
            system_id=system_id,
            mx_domain=config["domain"],
            email=alias_email,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            manager_address=manager_address,
            generate_code=False,
        )
        logger.info("[amail_gateway] Registered alias %s → %s: %s", alias_email, email, alias_result)
        logger.info("[amail_gateway] Whitelisted manager %s for agent %s", manager_address, email)

    # Extract activation code from combined response
    activation_code = ""
    if isinstance(result, dict):
        raw = result.get("activation_code", "")
        if raw:
            activation_code = raw

    if not activation_code:
        logger.warning("[amail_gateway] No activation code in register response for %s", email)
        return

    _inject_profile_config(profile_dir, {
        "email": email,
        "activation_code": activation_code,
        "gateway_url": gateway_url,
            "domain": config["domain"],
            "system_id": system_id,
            "manager_address": manager_address,
            "save_raw_snapshots": config.get("save_raw_snapshots", False),
            "webhook_host": config.get("webhook_host", ""),
            "_wh_port": wh_port if wh_config else 0,
        })


# ═══════════════════════════════════════════════════════════════
# Hook: auto-activate profile on agent startup
def _auto_activate_profile(profile_dir: str, config: dict) -> None:
    """Activate a pending profile (has activation_code, no api_key yet).

    Called by the agent startup process when it detects an activation code
    in the profile config. This ensures the raw_key is only visible to
    the agent process itself.
    """
    config_path = Path(profile_dir) / "amail.json"
    if not config_path.is_file():
        return
    try:
        with open(config_path) as f:
            prof = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    activation_code = prof.get("activation_code", "")
    if not activation_code:
        return  # Already activated or no code

    if prof.get("api_key"):
        # Already has a key -- clean up stale activation_code
        prof.pop("activation_code", None)
        with open(config_path, "w") as f:
            json.dump(prof, f, indent=2)
        return

    client = _GatewayClient(config.get("gateway_url", prof.get("gateway_url", "")),
                          "", timeout=5)
    result = client.activate_address(activation_code, email_address=prof.get("email", ""))
    if result.get("success") and result.get("raw_key"):
        prof["api_key"] = result["raw_key"]
        prof.pop("activation_code", None)
        prof.pop("last_activation_attempt", None)
        with open(config_path, "w") as f:
            json.dump(prof, f, indent=2)
        logger.info("[amail_gateway] Activated profile, api_key saved to %s", config_path)

        # ── Port refresh: re-register bridge route if webhook port changed ──
        webhook_host = config.get("webhook_host", "")
        if webhook_host:
            wh_config = _ensure_profile_webhook(profile_dir)
            if wh_config:
                current_port = wh_config["port"]
                last_port = prof.get("_wh_port", 0)
                if current_port != last_port:
                    if re.match(r'^\d+\.\d+\.\d+\.\d+:', webhook_host):
                        bridge_base = f"http://{webhook_host}"
                    else:
                        bridge_base = f"https://{webhook_host}"
                    try:
                        import json as _json
                        data = _json.dumps(
                            {"email": prof["email"], "host": "127.0.0.1", "port": current_port}
                        ).encode()
                        req = urllib.request.Request(
                            f"{bridge_base}/api/v1/routes",
                            data=data,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=5) as r:
                            pass
                        prof["_wh_port"] = current_port
                        with open(config_path, "w") as f:
                            json.dump(prof, f, indent=2)
                        logger.info("[amail_gateway] Bridge route updated: port %s -> %s",
                                    last_port, current_port)
                    except Exception as e:
                        logger.warning("[amail_gateway] Bridge route refresh failed: %s", e)
    else:
        # Rate-limit retries: skip if recently attempted (avoids spamming gateway
        # with a permanently invalid activation code)
        import time as _time
        now_ts = _time.time()
        last = prof.get("last_activation_attempt", 0)
        if last and (now_ts - last) < 300:
            logger.debug("[amail_gateway] Skipping activation retry for %s (last attempt %ds ago)",
                         config_path, int(now_ts - last))
        else:
            prof["last_activation_attempt"] = now_ts
            with open(config_path, "w") as f:
                json.dump(prof, f, indent=2)
            logger.warning("[amail_gateway] Failed to activate profile %s: %s",
                           config_path, result.get("error", result))


# ── Public: agent startup activation ───────────────────────────

def agent_startup_activate() -> dict:
    """Check and activate a pending amail profile on agent startup.

    Call this at the beginning of an agent session to ensure the profile
    has a valid API key. If the profile has an activation_code but no
    api_key yet, it will be activated now.

    Returns:
        {"success": True, "activated": True/False} or {"success": False, "error": "..."}
    """
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        return {"success": False, "error": "HERMES_PROFILE_DIR not set"}

    # Check if profile config exists
    config_path = None
    for fname in ("amail.json", "amail_gateway.json"):
        p = Path(profile_dir) / fname
        if p.is_file():
            config_path = p
            break
    if not config_path:
        return {"success": False, "error": f"No amail config found in {profile_dir}"}

    try:
        prof = json.loads(config_path.read_text())
    except Exception as e:
        return {"success": False, "error": f"Failed to read config: {e}"}

    if prof.get("api_key"):
        return {"success": True, "activated": False, "note": "Already activated"}

    if not prof.get("activation_code"):
        return {"success": False, "error": "No activation_code found in profile config"}

    # Activate using gateway_url from the profile's own amail.json
    _auto_activate_profile(profile_dir, prof)

    # Reload to verify
    try:
        prof = json.loads(config_path.read_text())
        if prof.get("api_key"):
            return {"success": True, "activated": True, "email": prof.get("email", "")}
        else:
            return {"success": False, "error": "Activation did not produce an api_key"}
    except Exception as e:
        return {"success": False, "error": f"Failed to verify activation: {e}"}


# ── Hook: auto-deregister email on profile deletion ────────────

def _auto_deregister_email(name: str, profile_dir: str, config: dict) -> None:
    """When a Profile is deleted, clean up its API key in amail."""
    gateway_url = config.get("gateway_url", "")
    admin_key = config.get("admin_key", "")
    domain = config.get("domain", "")
    if not gateway_url or not admin_key:
        return

    # Read the profile's config to get the email address
    config_path = None
    for fname in ("amail.json", "amail_gateway.json"):
        p = Path(profile_dir) / fname
        if p.is_file():
            config_path = p
            break
    if not config_path:
        return

    try:
        profile_config = json.loads(config_path.read_text())
    except Exception:
        return

    profile_email = profile_config.get("email", "")
    if not profile_email:
        return

    # Find and delete the API key by email address
    client = _GatewayClient(gateway_url, admin_key)
    list_result = client._request("GET", "/api/v1/api-keys")
    entries = list_result.get("entries", list_result.get("data", []))
    if isinstance(entries, list):
        for entry in entries:
            if entry.get("email_address") == profile_email:
                api_key_id = entry.get("id")
                if api_key_id:
                    client._request("DELETE", f"/api/v1/api-keys/{api_key_id}")
                    logger.info("[amail_gateway] Deleted API key for %s (id=%s)", profile_email, api_key_id)
                break

    # Remove the profile config file
    config_path.unlink(missing_ok=True)


# Register the hooks explicitly (not via decorator to avoid ordering issues)
register_profile_hook("profile_created", _auto_register_email)
register_profile_hook("profile_deleted", _auto_deregister_email)


# ═══════════════════════════════════════════════════════════════
# Tool Registration (top-level -- auto-discovered by Hermes registry)
# Wrapped in try/except so setup() and preprocessor can be imported
# without the Hermes runtime (CLI / integration scripts).
# ═══════════════════════════════════════════════════════════════

try:
    from tools.registry import registry, tool_result  # noqa: E402
    _HERMES_REGISTRY_AVAILABLE = True
except ImportError:
    _HERMES_REGISTRY_AVAILABLE = False
    class _DummyRegistry:
        def register(self, **kw): pass
    registry = _DummyRegistry()  # type: ignore
    def tool_result(x): return x  # noqa: E743


async def _handle_send_mail(args, **_kw):
    return tool_result(await send_mail(
        to=args.get("to", ""),
        subject=args.get("subject", ""),
        body=args.get("body", ""),
        cc=args.get("cc"),
        attachments=args.get("attachments"),
        message_id=args.get("message_id"),
    ))


async def _handle_manage_contacts(args, **_kw):
    return tool_result(await manage_contacts(
        action=args.get("action", "check"),
        address=args.get("address"),
        direction=args.get("direction", "all"),
    ))


registry.register(
    name="send_mail",
    toolset=_TOOLSET,
    schema={
        "name": "send_mail",
        "description": (
            "Send an email via your amail address. "
            "Attachments are automatically uploaded from local file paths. "
            "For replies: pass the original inbound message_id -- the tool "
            "automatically resolves In-Reply-To, References headers, and sender persona."
            "For new emails: omit message_id; the tool will auto-create a new message_id."
            "After sending, you may call set_email_summary to refine the thread summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": (
                        "Comma-separated recipient email addresses. "
                        "When replying: include the inbound 'sender' "
                        "plus other 'recipients.to' addresses (excluding your own)."
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": (
                        "Email subject line. "
                        "When replying: prefix the inbound subject with 'Re: '."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or markdown).",
                },
                "cc": {
                    "type": "string",
                    "description": (
                        "Optional comma-separated CC recipients. "
                        "When replying: use 'recipients.cc' from the inbound payload."
                    ),
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of file paths to attach. "
                        "Accepts absolute paths, CWD-relative paths, or bare filenames. "
                        "Bare filenames are resolved by searching the workspace directory tree."
                    ),
                },
                "message_id": {
                    "type": "string",
                    "description": (
                        "For replies: pass the 'message_id' field from the inbound email payload. "
                        "The tool will automatically resolve threading headers "
                        "and the sender persona from stored message metadata. "
                        "Omit for new outbound emails."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    handler=_handle_send_mail,
)

registry.register(
    name="manage_contacts",
    toolset=_TOOLSET,
    schema={
        "name": "manage_contacts",
        "description": (
            "Manage your amail address book (contacts). "
            "Use 'check' to verify a contact, 'add' to allow a new sender, "
            "'remove' to revoke access."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["check", "add", "remove", "update"],
                    "description": "Action: check if a contact exists, add a new one (sends approval request), remove a contact, or update direction on existing contact.",
                },
                "address": {
                    "type": "string",
                    "description": "Email address to check, add, or remove (required for all actions).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["from", "to", "all"],
                    "description": "Direction: 'from' (inbound, allow receiving), 'to' (outbound, allow sending), or 'all'.",
                },
            },
            "required": ["action", "address"],
        },
    },
    handler=_handle_manage_contacts,
)

# register contact_profile tool
async def _handle_contact_profile(args, **_kw):
    return tool_result(await contact_profile(
        address=args.get("address", ""),
        name=args.get("name", ""),
    ))

registry.register(
    name="contact_profile",
    toolset=_TOOLSET,
    schema={
        "name": "contact_profile",
        "description": (
            "Look up a contact by address or name. "
            "At least one required. Address is exact match; name searches for a "
            "matching 'name' field in stored profiles. "
            "Returns {address, profile} where the 'profile' value is a JSON string with keys: "
            "name (display name), title (job title), location (city/timezone), "
            "relationship (how they relate to you), focus (recurring topics/priorities), "
            "close_contacts (frequent CCs, semicolon-separated), "
            "style (communication preference). "
            "Returns '{}' if no profile stored."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Email address for exact lookup.",
                },
                "name": {
                    "type": "string",
                    "description": "Contact name for search (case-insensitive substring match on the 'name' field in contact profiles).",
                },
            },
        },
    },
    handler=_handle_contact_profile,
)

# register set_contact_profile tool
async def _handle_set_contact_profile(args, **_kw):
    return tool_result(await set_contact_profile(
        address=args.get("address", ""),
        profile=args.get("profile", ""),
    ))

registry.register(
    name="set_contact_profile",
    toolset=_TOOLSET,
    schema={
        "name": "set_contact_profile",
        "description": (
            "Update the profile for an existing contact. "
            "Only updates contacts that already exist in your address book."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Email address of the contact to update.",
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "JSON-formatted string of profile fields to update. "
                        "Valid keys: name, title, location, relationship, focus, "
                        "close_contacts, style. "
                        "Prefix '+' to append, '-' to remove, no prefix to overwrite. "
                        "Unprefixed values inherit the prefix of the preceding value. "
                        "All values are strings; separate multiple values with semicolons. "
                        "Max 5 values per key. "
                        "Example: {\"location\": \"Beijing\", \"focus\": \"-Q3 planning; +Q4 planning\"}"
                    ),
                },
            },
            "required": ["address", "profile"],
        },
    },
    handler=_handle_set_contact_profile,
)

# ═══════════════════════════════════════════════════════════════
# Message Metadata — stored in gateway agent_state (internal), keyed msg:{message_id}
#    value: {"references": [...], "thread_id": "..."}
# ═══════════════════════════════════════════════════════════════

# Local-only helpers for raw email snapshots (not gateway data)
def _sanitize_message_id(message_id: str) -> str:
    mid = message_id.strip().lstrip("<").rstrip(">")
    for ch in "/\\:*?\"<>|@ ":
        mid = mid.replace(ch, "_")
    return mid


# ── Attachment path resolution ─────────────────────────────────────

ATTACH_MAX_SIZE_MB = 10
ATTACH_MAX_SEARCH_DEPTH = 5    # max directory depth from workspace root
ATTACH_MAX_SEARCH_MATCHES = 50  # stop early if too many candidates
ATTACH_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".hermes", "target", ".pytest_cache", ".mypy_cache",
    ".tox", ".eggs", "dist", "build", "__pypackages__",
}


def _resolve_attachments(raw_paths: list) -> tuple:
    """Resolve a list of attachment references to verified absolute paths.

    Resolution order for each item:
      1. Absolute path — verify it exists.
      2. CWD-relative — resolve, verify it exists.
      3. Bare filename — walk workspace looking for a unique match.
      4. No match / ambiguous → returned as error for the caller to surface.

    Returns (resolved: list[str], errors: list[str]).
    """
    import glob as _glob

    resolved: list[str] = []
    errors: list[str] = []

    cwd = Path.cwd()
    workspace_roots = _workspace_roots()

    for raw in raw_paths:
        raw = raw.strip()
        if not raw:
            continue

        p = Path(raw)

        # 1. Absolute path
        if p.is_absolute():
            if p.is_file():
                resolved.append(str(p))
            else:
                errors.append(f"Attachment not found: {raw}")
            continue

        # 2. CWD-relative
        cwd_candidate = (cwd / p).resolve()
        if cwd_candidate.is_file():
            resolved.append(str(cwd_candidate))
            continue

        # 3. Bare filename — search workspace trees
        name = p.name
        if not name:
            errors.append(f"Invalid attachment path: {raw}")
            continue

        matches: list[Path] = []
        for root in workspace_roots:
            if not root.is_dir():
                continue
            for candidate in root.rglob(name):
                # Depth guard — skip files nested too deep
                depth = len(candidate.relative_to(root).parts)
                if depth > ATTACH_MAX_SEARCH_DEPTH:
                    continue
                if _is_skipped_dir(candidate):
                    continue
                if candidate.name != name:
                    continue
                matches.append(candidate)
                # Early exit — avoid scanning the entire filesystem
                if len(matches) >= ATTACH_MAX_SEARCH_MATCHES:
                    break
            if len(matches) >= ATTACH_MAX_SEARCH_MATCHES:
                break

        # Deduplicate by resolved path
        unique = list(dict.fromkeys(str(m.resolve()) for m in matches))

        if len(unique) == 0:
            errors.append(
                f"Attachment '{name}' not found in workspace. "
                f"Provide an absolute or CWD-relative path."
            )
        elif len(unique) == 1:
            resolved.append(unique[0])
        else:
            # Multiple matches — need disambiguation
            candidates = "\n    ".join(unique[:5])
            errors.append(
                f"Ambiguous attachment '{name}' — found {len(unique)} files:\n"
                f"    {candidates}\n"
                f"  Use a more specific path."
            )

    return resolved, errors


def _workspace_roots() -> list[Path]:
    """Return the directories to search for bare-filename attachments."""
    roots: list[Path] = [Path.cwd()]

    # Profile directory (agent's working sandbox)
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if profile_dir:
        roots.append(Path(profile_dir))

    # Home — broad but last-resort; walk depth limited in practice
    home = Path.home()
    if home.is_dir():
        roots.append(home)

    return roots


def _is_skipped_dir(path: Path) -> bool:
    """True if any ancestor of *path* is a directory that should be skipped."""
    for parent in path.parents:
        if parent.name in ATTACH_SKIP_DIRS:
            return True
    return False


def _check_attachment_size(path: str) -> Optional[str]:
    """Return an error message if the file exceeds the size limit, else None."""
    try:
        size_mb = Path(path).stat().st_size / (1024 * 1024)
        if size_mb > ATTACH_MAX_SIZE_MB:
            return (
                f"Attachment '{Path(path).name}' is {size_mb:.1f} MB — "
                f"max allowed is {ATTACH_MAX_SIZE_MB} MB"
            )
    except OSError:
        pass
    return None


# ── Raw email snapshots ────────────────────────────────────────────

def _save_outbound_snapshot(out_msg_id: str, my_addr: str, sender: str,
                             to: str, subject: str, body: str,
                             cc_list: list, attachment_ids: list,
                             in_reply_to: str, references: str) -> None:
    """Save a JSON snapshot of an outbound email to raw_email/.

    my_addr determines the snapshot subdirectory (persona or base address).
    """
    safe_mid = _sanitize_message_id(out_msg_id)
    safe_addr = _sanitize_message_id(my_addr)
    now = datetime.now()
    yyyymm = now.strftime("%Y%m")
    snapshot_dir = _raw_email_dir() / safe_addr / yyyymm
    snapshot_path = snapshot_dir / f"out-{safe_mid}.json"
    payload = {
        "message_id": out_msg_id,
        "direction": "outbound",
        "sender": sender,
        "to": to,
        "cc": ", ".join(cc_list) if cc_list else "",
        "subject": subject,
        "body": body,
        "attachments": attachment_ids,
        "in_reply_to": in_reply_to,
        "references": references,
        "sent_at": now.isoformat(),
    }
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        tmp = snapshot_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(snapshot_path)
    except Exception:
        logger.warning("Failed to save outbound email snapshot for %s", safe_mid)


def _current_persona_name() -> Optional[str]:
    """Return the current persona name from the active Hermes profile directory.

    Returns None for the default (base) profile; otherwise the profile dir name
    (e.g. "alice" for ~/.hermes/profiles/alice).
    """
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        return None
    p = Path(profile_dir).resolve()
    home_hermes = (Path.home() / ".hermes").resolve()
    if p == home_hermes:
        return None
    # Must be a subdirectory of ~/.hermes/profiles/ — extract the persona name
    profiles_dir = home_hermes / "profiles"
    try:
        p.relative_to(profiles_dir)
    except ValueError:
        return None
    name = p.name
    return name if name else None


def _raw_email_dir() -> Path:
    profile_dir = os.environ.get("HERMES_PROFILE_DIR", "")
    if not profile_dir:
        profile_dir = Path.home() / ".hermes"
    return Path(profile_dir) / "raw_email"



def _log_amail(direction: str, from_addr: str, to_addr: str, subject: str) -> None:
    """Append a lightweight email processing log entry (not dependent on save_raw_snapshots).
    
    Log is written to ~/.hermes/amail.log for integration test verification.
    """
    import json as _json
    log_path = Path.home() / ".hermes" / "amail.log"
    entry = _json.dumps({
        "ts": datetime.now().isoformat(),
        "dir": direction,
        "from": from_addr,
        "to": to_addr,
        "subj": subject,
    }, ensure_ascii=False)
    try:
        with open(log_path, "a") as f:
            f.write(entry + "\n")
    except Exception:
        logger.debug("Failed to write amail log: %s", log_path)

def store_inbound_message(
    message_id: str,
    references: list,
    my_amail_addr: str,
    preprocessed_payload: Optional[dict] = None,
    attachment_sources: Optional[dict] = None,
) -> Optional[str]:
    """Called by the gateway preprocessor when an inbound email arrives.

    Always: stores message metadata to gateway agent_state keyed msg:{mid}.
    Optionally (save_raw_snapshots=true): saves the AGENT-VISIBLE JSON snapshot
    (AFTER preprocessing) to raw_email/{agent_addr}/{yyyymm}/.

    IMPORTANT: preprocessed_payload must be the output of preprocess_mail_payload()
    — the agent-visible format with sender/recipients/my_amail_addr/direct_message fields.
    Do NOT pass the gateway RAW webhook payload.
    """
    if not message_id or not message_id.strip():
        return None
    mid = message_id.strip()
    refs = [r.strip() for r in (references or []) if r.strip()]
    thread_id = refs[0] if refs else mid

    # ── Store message metadata to gateway ─────────────────────────
    msg_value = json.dumps({
        "references": refs,
        "thread_id": thread_id,
        "my_amail_addr": my_amail_addr,
    })
    config = _load_profile_config()
    if config:
        client = _GatewayClient(config["gateway_url"], config["api_key"])
        client.agent_state_put(f"msg:{mid}", msg_value)

    # ── Optionally save agent-visible snapshot ──────────────────
    if not config or not config.get("save_raw_snapshots"):
        return None

    safe_mid = _sanitize_message_id(mid)
    safe_addr = _sanitize_message_id(my_amail_addr)
    now = datetime.now()
    yyyymm = now.strftime("%Y%m")
    snapshot_dir = _raw_email_dir() / safe_addr / yyyymm
    snapshot_path = snapshot_dir / f"in-{safe_mid}.json"
    attch_dir = snapshot_dir / "attch" / safe_mid

    snapshot_saved = False
    if preprocessed_payload:
        # Guard: detect gateway RAW format (has 'mail_id' field — gateway-internal UUID)
        if "mail_id" in preprocessed_payload and "recipients" not in preprocessed_payload:
            logger.warning(
                "store_inbound_message received gateway RAW payload instead of preprocessed agent-visible JSON. "
                "Call preprocess_mail_payload() first. Snapshot may contain wrong format."
            )
        try:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            tmp = snapshot_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(preprocessed_payload, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(snapshot_path)
            snapshot_saved = True
        except Exception:
            logger.warning("Failed to save inbound email snapshot for %s", safe_mid)

    if attachment_sources:
        try:
            attch_dir.mkdir(parents=True, exist_ok=True)
            for filename, src_path in (attachment_sources or {}).items():
                src = Path(src_path)
                if not src.is_file():
                    continue
                safe_name = Path(filename).name
                dst = attch_dir / safe_name
                dst.write_bytes(src.read_bytes())
        except Exception:
            logger.warning("Failed to copy attachments for %s", safe_mid)

    return str(snapshot_path) if snapshot_saved else None


def _load_message_meta(message_id: str) -> Optional[dict]:
    """Load message metadata from gateway agent_state. Returns None if not found."""
    config = _load_profile_config()
    if not config:
        return None
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    value = client.agent_state_get(f"msg:{message_id.strip()}")
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _store_message_meta(message_id: str, references: Optional[str] = None) -> None:
    """Store outbound message metadata to gateway for future replies."""
    if not message_id or not message_id.strip():
        return
    mid = message_id.strip()
    refs = [r.strip() for r in (references or "").split() if r.strip()]
    thread_id = refs[0] if refs else mid
    msg_value = json.dumps({"references": refs, "thread_id": thread_id})
    config = _load_profile_config()
    if config:
        client = _GatewayClient(config["gateway_url"], config["api_key"])
        client.agent_state_put(f"msg:{mid}", msg_value)


# ═══════════════════════════════════════════════════════════════
# email_summary / set_email_summary — via semantic thread-summary endpoints
#    key: thread:{thread_id}, value: summary text
# ═══════════════════════════════════════════════════════════════

async def email_summary(message_id: str) -> dict:
    """Look up the stored summary for the email thread containing this message.

    Uses semantic endpoint GET /admin/thread-summary/:message_id which
    resolves message_id → thread_id internally.
    """
    config = _load_profile_config()
    if not config:
        return {"thread_id": "", "summary": ""}
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    result = client.get_thread_summary(message_id)
    if result:
        # get_thread_summary returns the summary string on success
        return {"thread_id": message_id, "summary": result}
    return {"thread_id": message_id, "summary": ""}


async def set_email_summary(message_id: str, summary: str) -> dict:
    """Store or update the summary for the email thread containing this message.

    Resolves message_id → thread_id, then writes the summary to gateway
    agent_state keyed 'thread:{thread_id}'.
    """
    if not message_id or not message_id.strip():
        return {"success": False, "error_code": "MESSAGE_ID_REQUIRED"}
    if not isinstance(summary, str):
        return {"success": False, "error_code": "SUMMARY_MUST_BE_STRING"}
    if len(summary) > 2000:
        return {"success": False, "error_code": "SUMMARY_TOO_LONG", "max_length": 2000}

    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "amail not configured for this profile"}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    result = client.put_thread_summary(message_id, summary)
    if result.get("status") == 200:
        return {"success": True}
    error = result.get("error", f"HTTP {result.get('status')}")
    return {"success": False, "error": f"Failed to store summary: {error}"}


# ── Registry: email_summary ─────────────────────────────────────

async def _handle_email_summary(args, **_kw):
    return tool_result(await email_summary(
        message_id=args.get("message_id", ""),
    ))

registry.register(
    name="email_summary",
    toolset=_TOOLSET,
    schema={
        "name": "email_summary",
        "description": (
            "Look up the stored summary for an email thread. "
            "Pass any message_id from the thread -- the tool resolves "
            "the canonical thread_id automatically. "
            "Returns {thread_id, summary}. "
            "The summary is a plain-text snapshot of active topics, decisions, "
            "pending actions, and unresolved questions. Empty string if none stored. "
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Any message_id from the thread whose summary to retrieve.",
                },
            },
            "required": ["message_id"],
        },
    },
    handler=_handle_email_summary,
    emoji="📧",
)

# ── Registry: set_email_summary ─────────────────────────────────

async def _handle_set_email_summary(args, **_kw):
    return tool_result(await set_email_summary(
        message_id=args.get("message_id", ""),
        summary=args.get("summary", ""),
    ))

registry.register(
    name="set_email_summary",
    toolset=_TOOLSET,
    schema={
        "name": "set_email_summary",
        "description": (
            "Store or update the summary for an email thread. "
            "Pass any message_id from the thread -- the tool resolves "
            "the canonical thread_id automatically. "
            "Pass an empty string as summary to clear it. "
            "Call this after processing an inbound email to persist the updated state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Any message_id from the thread (usually the current inbound email's message_id).",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Plain-text summary of all active topics in the thread. "
                        "For each topic: one short sentence on what's being decided "
                        "plus current status or next step (e.g. 'waiting for David'). "
                        "Fully resolved topics: either remove entirely or mark [DONE] "
                        "and drop after one more round. "
                        "Multiple topics: numbered or bullet lines (max 5). "
                        "Single topic: a short paragraph is fine. "
                        "Keep it actionable — future you must understand open items "
                        "within seconds. Do NOT archive the email chain; only distill "
                        "active decisions, pending actions, and unresolved questions. "
                        "Max 2000 characters. Empty string clears the summary."
                    ),
                },
            },
            "required": ["message_id", "summary"],
        },
    },
    handler=_handle_set_email_summary,
    emoji="📝",
)

# ── Auto-activate profile on module import (no-op if not in agent process) ──
agent_startup_activate()
